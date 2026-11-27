# SPDX-License-Identifier: MIT
"""Hub side of the fleet: drain a shared inbox of payload files written by `the-index collect --out`.

One file at a time, in name order. A file is ingested once (its `payload_id` goes into `inbox_receipt`), then
MOVED to done/YYYY-MM/; anything unreadable is MOVED to bad/ and shown as an open `bad_payload` gap on the hub
until a later drain finds nothing bad. Nothing in the inbox is ever deleted."""
import hashlib
import json
import os
from pathlib import Path

from . import db, files_ingest, gaps, identity, ingest

SUFFIXES = (".json", ".jsonl")


def read_header(path):
    """(payload_id, machine, host) from the JSON top level or the JSONL header line. Raises ValueError."""
    with open(path, encoding="utf-8") as fh:
        head = json.load(fh) if path.suffix == ".json" else json.loads(fh.readline())
    if not isinstance(head, dict) or (path.suffix == ".jsonl" and head.get("t") != "header"):
        raise ValueError("not a payload (no header)")
    pid = head.get("payload_id")
    if not isinstance(pid, str) or not pid.strip():
        raise ValueError("no payload_id")
    machine, host = head.get("machine"), head.get("host")
    host = host.strip()[:200] if isinstance(host, str) else None
    return pid.strip(), machine if isinstance(machine, str) and machine else None, host or None


def _move(path, folder):
    """Move into `folder` without overwriting; returns the new path."""
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / path.name, 0
    while target.exists():
        n += 1
        target = folder / f"{path.name}.{n}"
    os.replace(path, target)
    return target


def _receipt(conn, pid, name, fields):
    device, status = fields
    conn.execute("INSERT INTO inbox_receipt (payload_id, device_id, file_name, status) VALUES (?,?,?,?) "
                 "ON CONFLICT(payload_id) DO UPDATE SET device_id = excluded.device_id, "
                 "file_name = excluded.file_name, status = excluded.status", (pid, device, name, status))


def _ingest(conn, path, ident):
    """Ingest one readable file under its resolved device name; returns the device id."""
    _pid, machine, host = ident
    name = host or (f"member-{machine[:8]}" if machine else None)
    if name is None:
        raise ValueError("neither host nor machine")
    name = identity.resolve_device(conn, name, machine)
    if path.suffix == ".json":
        ingest.ingest(conn, json.loads(path.read_text(encoding="utf-8")), name)
    else:
        with open(path, encoding="utf-8") as fh:
            files_ingest.ingest_stream(conn, fh, name)
    identity.resolve_device(conn, name, machine)          # a new device takes the machine hash now
    conn.execute("UPDATE device SET reach_id = ? WHERE name = ?", (conn.ref_id("ref_reach", "inbox"), name))
    return conn.execute("SELECT id FROM device WHERE name = ?", (name,)).fetchone()[0]


def _digest(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:32]
    except OSError:
        return hashlib.sha256(path.name.encode()).hexdigest()[:32]


def _quarantine(conn, path, root, key):
    _receipt(conn, key, path.name, (None, "bad"))
    _move(path, root / "bad")


def process(conn, path, root):
    """Take one file. Returns (status, reason): ingested, duplicate or bad."""
    month = db.now()[:7]
    try:
        ident = read_header(path)
    except (ValueError, OSError) as exc:
        digest = _digest(path)
        _quarantine(conn, path, root, f"bad:{digest}")
        return "bad", f"{type(exc).__name__}: {exc}"[:200]
    seen = conn.execute("SELECT status FROM inbox_receipt WHERE payload_id = ?", (ident[0],)).fetchone()
    if seen and seen[0] == "ingested":
        _move(path, root / "done" / month)
        return "duplicate", None
    try:
        device = _ingest(conn, path, ident)
    except Exception as exc:  # noqa: BLE001 -- a bad file is quarantined, never fatal
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        _quarantine(conn, path, root, ident[0])
        return "bad", f"{type(exc).__name__}: {exc}"[:200]
    _receipt(conn, ident[0], path.name, (device, "ingested"))
    _move(path, root / "done" / month)
    return "ingested", None


def _sync_bad(conn, hub_name, bad):
    """Open one gap per bad file on the hub; close the earlier ones when nothing is bad any more."""
    open_gaps = conn.execute("SELECT 1 FROM gap g JOIN ref_gap_kind k ON k.id = g.gap_kind_id JOIN device d "
                             "ON d.id = g.device_id WHERE k.code = 'bad_payload' AND g.closed_run IS NULL "
                             "AND d.name = ?", (hub_name,)).fetchone()
    if not bad and not open_gaps:
        return
    conn.execute("BEGIN")
    ctx = ingest.start_run(conn, ingest.ensure_device(conn, hub_name), {"collector": "inbox"})
    reported = [{"kind": "bad_payload", "target": name, "reason": reason} for name, reason in bad]
    gaps.sync(conn, ctx, reported, True)
    ingest.finish_run(conn, ctx, {"items": [], "errors": []}, "ok")
    conn.execute("COMMIT")


def drain(conn, inbox_dir, hub_name):
    """Process every payload file in the inbox. Returns {'ingested': n, 'duplicate': n, 'bad': n}."""
    root = Path(inbox_dir).expanduser()
    if not root.is_dir():
        raise ValueError(f"inbox folder not found: {root}")
    counts, bad = {"ingested": 0, "duplicate": 0, "bad": 0}, []
    for path in sorted(p for p in root.iterdir() if p.is_file() and p.suffix in SUFFIXES
                       and not p.name.startswith(".")):
        status, reason = process(conn, path, root)
        counts[status] += 1
        if status == "bad":
            bad.append((path.name, reason))
    _sync_bad(conn, hub_name, bad)
    return counts


def summary(counts):
    return f"inbox: {counts['ingested']} ingested, {counts['duplicate']} duplicate, {counts['bad']} bad"
