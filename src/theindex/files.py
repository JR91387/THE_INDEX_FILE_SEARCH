# SPDX-License-Identifier: MIT
"""Loaders for the hand-written purposes and links files (formats in examples/). Lines after a `[device]`
header apply to that device; lines before any header apply to every device. Bad lines are reported, not fatal.
The purpose table is replaced on every load (git keeps the file's history); declared links are retired when
their line disappears."""
from pathlib import Path

from . import ingest, links


def parse(path):
    """-> [(line_no, device or None, [fields])], skipping blanks and # comments."""
    rows, device = [], None
    for number, raw in enumerate(Path(path).read_text().splitlines(), 1):
        line = raw.strip()                       # only whole-line comments: descriptions may contain '#'
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            device = line[1:-1].strip() or None
            continue
        rows.append((number, None if device == "*" else device, [f.strip() for f in line.split("|")]))
    return rows


def device_ids(conn, name):
    """Ids a scope applies to: one named device, or every device."""
    sql, args = ("SELECT id FROM device WHERE name = ?", (name,)) if name else ("SELECT id FROM device", ())
    return [r[0] for r in conn.execute(sql, args)]


def load_purposes(conn, path, warnings):
    conn.execute("DELETE FROM purpose")
    for number, device, f in parse(path):
        try:
            if len(f) < 3 or not f[0] or not f[2]:
                raise ValueError("need: path_glob | criticality | description")
            ids = device_ids(conn, device) if device else [None]
            if device and not ids:
                raise ValueError(f"unknown device {device!r}")
            state = conn.ref_id("ref_expected_state", f[4]) if len(f) > 4 and f[4] else None
            for device_id in ids:
                conn.execute("INSERT INTO purpose (device_id, path_glob, criticality_id, description, used_by, "
                             "expected_state_id, source_line) VALUES (?,?,?,?,?,?,?)",
                             (device_id, f[0], conn.ref_id("ref_criticality", f[1]), f[2],
                              f[3] if len(f) > 3 and f[3] else None, state, number))
        except (ValueError, KeyError) as exc:
            warnings.append(f"purposes line {number}: {exc}")


def matching(conn, device_id, end):
    """'kind:key_glob' -> ids of active items on the device."""
    kind, _, glob = end.partition(":")
    return [r[0] for r in conn.execute(
        "SELECT i.id FROM item i JOIN ref_item_kind k ON k.id = i.kind_id WHERE i.device_id=? AND k.code=? "
        "AND i.key GLOB ? AND i.retired_run IS NULL", (device_id, kind, glob))]


def load_links(conn, ctx, path, warnings):
    kept = set()
    for number, device, f in parse(path):
        try:
            if len(f) != 3 or ":" not in f[0] or ":" not in f[2]:
                raise ValueError("need: from_kind:key | link_type | to_kind:key")
            type_id = conn.ref_id("ref_link_type", f[1])
            for device_id in device_ids(conn, device):
                pairs = [(a, b) for a in matching(conn, device_id, f[0]) for b in matching(conn, device_id, f[2])]
                kept.update(links.upsert(conn, ctx, pair, (type_id, "declared")) for pair in pairs)
        except (ValueError, KeyError) as exc:
            warnings.append(f"links line {number}: {exc}")
    declared = conn.ref_id("ref_link_source", "declared")
    for row in conn.execute("SELECT id FROM item_link WHERE source_id=? AND retired_run IS NULL", (declared,)):
        if row[0] not in kept:
            conn.execute("UPDATE item_link SET retired_run=? WHERE id=?", (ctx["run_id"], row[0]))


def exists(path, warnings):
    if Path(path).exists():
        return True
    warnings.append(f"missing file: {path}")
    return False


def load(conn, cfg):
    """Load whichever files are configured, as one `files` scan run. Returns the list of warnings."""
    if not (cfg.purposes_file or cfg.links_file):
        return None
    warnings = []
    conn.execute("BEGIN")
    try:
        ctx = ingest.start_run(conn, ingest.ensure_device(conn, cfg.device_name), {"collector": "files"})
        if cfg.purposes_file and exists(cfg.purposes_file, warnings):
            load_purposes(conn, cfg.purposes_file, warnings)
        if cfg.links_file and exists(cfg.links_file, warnings):
            load_links(conn, ctx, cfg.links_file, warnings)
        status = "partial" if warnings else "ok"
        ingest.finish_run(conn, ctx, {"errors": warnings}, status)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return warnings
