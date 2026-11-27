# SPDX-License-Identifier: MIT
"""`scan`: lock, run each collector (one failure never stops the rest), load files, rebuild search once, pages."""
import fcntl
import json
import sqlite3
import sys
from contextlib import closing, contextmanager
from pathlib import Path

from . import collect, config, db, declare, files, files_run, identity, inbox, ingest, pages, pull

SKIP_BUSY = "previous scan still running"


@contextmanager
def scan_lock(db_path):
    """Exclusive non-blocking lock on '<db>.lock'. Yields True if taken, False if another scan holds it."""
    path = Path(f"{db_path}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _record_busy(cfg, names):
    """Best effort: leave a skipped run row without waiting on the running scan (a short busy timeout)."""
    if not Path(cfg.db_path).exists():
        return
    try:
        with closing(db.connect(cfg.db_path)) as conn:
            conn.execute("PRAGMA busy_timeout = 2000")
            for name in names:
                ingest.record_skip(conn, cfg.device_name, name, SKIP_BUSY)
    except (sqlite3.Error, KeyError):
        pass


def cmd_scan(cfg, args):
    """Run collectors (or ingest a saved payload with --from-json), then write pages (pages_on_scan)."""
    with scan_lock(cfg.db_path) as taken:
        if not taken:
            print(f"skipped: {SKIP_BUSY}")
            _record_busy(cfg, [args.collector] if args.collector else cfg.collectors)
            return 0
        with closing(db.init(cfg.db_path)) as conn:
            rc = _scan(conn, cfg, args)
            _auto_pages(conn, cfg)
            return rc


def _auto_pages(conn, cfg):
    """Pages after every scan. A failure is one stderr line; it never fails the scan."""
    if not cfg.pages_on_scan:
        return
    try:
        pages.write_all(conn, cfg.pages_dir)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"pages: not written ({exc})", file=sys.stderr)


def _load_saved(path):
    saved = json.loads(Path(path).read_text())
    if not isinstance(saved, dict) or not isinstance(saved.get("collector"), str):
        raise ValueError(f"{path}: not a collector payload (expected a JSON object with a 'collector' name)")  # noqa: TRY004
    return saved


def first_folders_scan(conn, device_name):
    """True when no earlier OK `folders` run exists for this device (the first scan measures everything)."""
    return conn.execute(
        "SELECT 1 FROM scan_run r JOIN ref_run_status s ON s.id = r.status_id "
        "JOIN ref_collector c ON c.id = r.collector_id JOIN device d ON d.id = r.device_id "
        "WHERE c.code = 'folders' AND s.code = 'ok' AND d.name = ? LIMIT 1", (device_name,)).fetchone() is None


def _one(conn, cfg, name, fetch):
    """Run (via fetch) and ingest one collector. Any failure is recorded as a failed run for it; the scan goes on."""
    try:
        payload = fetch(name)
        return ingest.ingest(conn, payload, cfg.device_name)
    except Exception as exc:  # noqa: BLE001 (one collector must never abort the others)
        message = f"{type(exc).__name__}: {exc}"[:500]
        return ingest.ingest(conn, {"collector": name, "status": "failed", "items": [], "errors": [message]},
                             cfg.device_name)


def _scan(conn, cfg, args):
    db.write_settings(conn, cfg.settings())
    cfg.device_name = identity.claim_local(conn, cfg.device_name)    # a renamed host keeps its device row
    declare.expire_due(conn)
    saved = _load_saved(args.from_json) if args.from_json else None
    names = [saved["collector"]] if saved else ([args.collector] if args.collector else cfg.collectors)
    if config.in_blackout(cfg.blackout):
        return _skip_all(conn, cfg, names, "blackout window")
    ok, message = config.run_gate(cfg.pre_run_gate)
    if not ok:
        return _skip_all(conn, cfg, names, f"pre_run_gate: {message}")
    measure_all = args.measure_all or first_folders_scan(conn, cfg.device_name)
    fetch = (lambda _name: saved) if saved else (lambda n: collect.run(conn, cfg, n, measure_all))
    say = (lambda _line: None) if getattr(args, "quiet", False) else print
    for name in names:
        if name == "filetree" and not saved and not files_run.settings(cfg)["enabled"]:
            continue
        result = _filetree(conn, cfg, args.measure_all) if name == "filetree" and not saved else _one(conn, cfg, name, fetch)
        say(f"{name}: {result['status']} items={result['items']} changes={result['changes']}"
            + (" (baseline)" if result["baseline"] else ""))
    identity.claim_local(conn, cfg.device_name)                      # a first scan created the device just now
    _drain_inbox(conn, cfg, say)
    warnings = files.load(conn, cfg)          # after collectors, so declared links find their items
    if warnings:
        print(f"files: {len(warnings)} warning(s)" + "".join(f"\n  {w}" for w in warnings))
    db.rebuild_search(conn)                   # once per scan, not once per collector
    return 0                                  # a recorded run is success; the front page shows partials


def _drain_inbox(conn, cfg, say):
    """Hub role with [inbox] dir set: take the members' payloads. A bad folder is one stderr line, never fatal."""
    if not cfg.inbox_dir or cfg.inbox_role != "hub":
        return
    try:
        failed = pull.fetch_all(cfg.pulls, cfg.inbox_dir)
        say(inbox.summary(inbox.drain(conn, cfg.inbox_dir, cfg.device_name)))
        if cfg.pulls:
            pull.record_gaps(conn, cfg.device_name, failed)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"inbox: not drained ({exc})", file=sys.stderr)


def _filetree(conn, cfg, full):
    """The streamed collector: a crash is recorded as a failed run, like any other collector."""
    try:
        return files_run.run(conn, cfg, full=True if full else None)
    except Exception as exc:  # noqa: BLE001 (one collector must never abort the others)
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        return ingest.ingest(conn, {"collector": "filetree", "status": "failed", "items": [],
                                    "errors": [f"{type(exc).__name__}: {exc}"[:500]]}, cfg.device_name)


def _skip_all(conn, cfg, names, reason):
    for name in names:
        ingest.record_skip(conn, cfg.device_name, name, reason)
    print(f"skipped: {reason}")
    return 0
