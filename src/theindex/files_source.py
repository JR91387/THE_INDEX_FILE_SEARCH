# SPDX-License-Identifier: MIT
"""The OS's own file index (plocate, Spotlight, Everything) as a fast source for the filetree run.
Silent and stable: a missing, stale or failing tool means the walk, never an error. A native run never retires
rows (header `no_retire`); on a full run the walk stays the authority and the native count only checks it."""
import json
import os
import subprocess
import sys

from . import files_ingest
from .files_proc import HERE, stream

SCRIPT = HERE / "sources.py"


def enabled(cfg):
    return getattr(cfg, "sources", {}).get("native", "auto") != "off"


def argv(opts, *flags):
    return [sys.executable, "-I", str(SCRIPT), *flags, json.dumps(opts)]


def with_titles(conn, opts):
    exts = [r[0] for r in conn.execute("SELECT code FROM ref_title_type WHERE retired_at IS NULL")]
    return {**opts, "title_exts": exts}


def probe(opts):
    """True when a native source is usable here. Never raises."""
    try:
        out = subprocess.run(argv(opts, "--probe"), capture_output=True, text=True, timeout=30, check=False).stdout
        return bool(json.loads(out.splitlines()[0]).get("source"))
    except Exception:  # noqa: BLE001 -- no native source beats an error
        return False


def run_native(conn, cfg, opts):
    """Ingest a native listing; returns the result, or None when the caller should walk instead."""
    if not enabled(cfg):
        return None
    opts = with_titles(conn, opts)
    if not probe(opts):
        return None
    try:
        result = stream(argv(opts), float(opts["budget_s"]) + 300,
                        lambda lines: files_ingest.ingest_stream(conn, lines, cfg.device_name))
    except Exception:  # noqa: BLE001 -- fall back to the walk in the same scan
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        return None
    return result if result["status"] == "ok" else None


def read_counts(lines):
    """(source, files per root) from a count-only stream, or None unless it ended ok."""
    source, trailer = None, None
    for line in lines:
        rec = json.loads(line) if line.strip() else {}
        source = rec.get("source", source) if rec.get("t") == "header" else source
        trailer = rec if rec.get("t") == "trailer" else trailer
    if not trailer or trailer.get("status") != "ok":
        return None
    return source, trailer["counts"].get("roots", {})


def walk_count(conn, device_id, root):
    ci = sys.platform in ("win32", "darwin")
    row = conn.execute("SELECT files_total FROM dir WHERE device_id = ? AND path_key = ? AND retired_run IS NULL",
                       (device_id, files_ingest.root_key(root, ci))).fetchone()
    return row[0] if row else None


def verify(conn, cfg, opts, result):
    """After a full walk: compare files per root with the native index; record `index_mismatch` gaps."""
    if not enabled(cfg) or result["status"] != "ok":
        return
    opts = {**with_titles(conn, opts), "count_only": True}
    try:
        counted = probe(opts) and stream(argv(opts), float(opts["budget_s"]) + 300, read_counts)
        if not counted:
            return
        source, by_root = counted
        bad = {}
        for root in (os.path.normpath(r) for r in opts["roots"]):
            walked, native = walk_count(conn, result["device_id"], root), by_root.get(root, 0)
            if walked is not None and abs(walked - native) > max(50, 0.01 * max(walked, native)):
                bad[root] = f"walk counted {walked} files, {source} counted {native}"
        record(conn, result, bad)
    except Exception:  # noqa: BLE001 -- verification is a bonus; it must never fail the scan
        if conn.in_transaction:
            conn.execute("ROLLBACK")


def record(conn, result, bad):
    """Open or refresh a gap per mismatching root; close earlier ones that now agree (even if this run's sync did)."""
    run, device = result["run_id"], result["device_id"]
    kind, collector = conn.ref_id("ref_gap_kind", "index_mismatch"), conn.ref_id("ref_collector", "filetree")
    conn.execute("BEGIN")
    seen = set()
    for target, reason in bad.items():
        row = conn.execute("SELECT id FROM gap WHERE device_id = ? AND gap_kind_id = ? AND target = ? "
                           "AND (closed_run IS NULL OR closed_run = ?)", (device, kind, target, run)).fetchone()
        if row:
            conn.execute("UPDATE gap SET closed_run = NULL, last_seen_run = ?, reason = ? WHERE id = ?",
                         (run, reason, row[0]))
            seen.add(row[0])
        else:
            seen.add(conn.execute(
                "INSERT INTO gap (device_id, collector_id, gap_kind_id, target, reason, first_seen_run, last_seen_run) "
                "VALUES (?,?,?,?,?,?,?)", (device, collector, kind, target, reason, run, run)).lastrowid)
    for (gap_id,) in conn.execute("SELECT id FROM gap WHERE device_id = ? AND gap_kind_id = ? AND closed_run IS NULL",
                                  (device, kind)).fetchall():
        if gap_id not in seen:
            conn.execute("UPDATE gap SET closed_run = ? WHERE id = ?", (run, gap_id))
    conn.execute("COMMIT")
