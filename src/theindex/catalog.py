# SPDX-License-Identifier: MIT
"""Offline catalogs: an Everything file list (EFU) or our own filetree JSON Lines becomes a device whose reach
is `offline`, loaded through files_ingest.ingest_stream. A bad line or row is skipped and counted, never fatal."""
import csv
import json
from pathlib import Path

from . import files_ingest, ingest

FILETIME_UNIX = 116444736000000000        # 100 ns ticks from 1601-01-01 to 1970-01-01
INT64 = 2 ** 63
DIR_BIT = 0x10
NEEDS = {"dir": ("key", "path"), "file": ("dir", "name")}


def filetime_to_ns(value):
    """Windows FILETIME text -> ns since the Unix epoch; empty or 0 = unknown (None); junk raises ValueError."""
    text = (value or "").strip()
    if not text:
        return None
    ticks = int(text)
    if ticks <= 0:
        return None
    ns = (ticks - FILETIME_UNIX) * 100
    if not -INT64 < ns < INT64:
        raise ValueError("date out of range")
    return ns


def ns_to_filetime(ns):
    return None if ns is None else ns // 100 + FILETIME_UNIX


def split_path(raw):
    """(parent path or None, last name). Separators may be '\\' or '/'; a trailing one is dropped."""
    path = raw.strip().rstrip("\\/")
    cut = max(path.rfind("\\"), path.rfind("/"))
    parent = path[:cut].rstrip("\\/") if cut > 0 else None
    return (parent or None), (path[cut + 1:] if cut >= 0 else path)


def _size(text):
    text = (text or "").strip()
    if not text:
        return 0
    if not text.isdigit():
        raise ValueError("size")
    return int(text)


def _efu_row(fields, header):
    """One normalized row: (is_dir, path, size, mtime_ns, ctime_ns); ValueError when malformed."""
    if len(fields) != len(header):
        raise ValueError("field count")
    row = dict(zip(header, fields))
    name = row["filename"].strip()
    if not name:
        raise ValueError("no filename")
    attrs = (row.get("attributes") or "").strip()
    is_dir = name[-1] in "\\/" or (attrs.isdigit() and int(attrs) & DIR_BIT != 0)
    return (is_dir, name.rstrip("\\/"), _size(row.get("size")), filetime_to_ns(row.get("date modified")),
            filetime_to_ns(row.get("date created")))


def read_efu(path):
    """(rows, skipped): the good rows of an EFU file and how many were skipped."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = [h.strip().lower() for h in next(reader, [])]
        if "filename" not in header:
            raise ValueError("not an EFU file: no Filename column")
        rows, skipped = [], 0
        for fields in reader:
            if not fields:
                continue
            try:
                rows.append(_efu_row(fields, header))
            except (ValueError, OverflowError):
                skipped += 1
    return rows, skipped


def _add_chain(dirs, path, ci):
    """Register path and every ancestor (parents get no dates)."""
    while path:
        key = files_ingest.root_key(path, ci)
        if key in dirs:
            return
        parent, _ = split_path(path)
        dirs[key] = {"path": path, "parent": files_ingest.root_key(parent, ci) if parent else None,
                     "mtime_ns": None, "ctime_ns": None}
        path = parent


def build_stream(rows, ci=True):
    """Filetree-shaped JSON lines (header, dirs parents first with their files, ok trailer) from EFU rows."""
    dirs, files = {}, {}
    for is_dir, path, size, mtime, ctime in rows:
        if is_dir:
            _add_chain(dirs, path, ci)
            dirs[files_ingest.root_key(path, ci)].update(mtime_ns=mtime, ctime_ns=ctime)
            continue
        parent, name = split_path(path)
        if not parent:
            continue
        _add_chain(dirs, parent, ci)
        files.setdefault(files_ingest.root_key(parent, ci), {})[name] = (size, mtime, ctime)
    ordered = sorted(dirs.items(), key=lambda kv: (kv[0].count("/"), kv[0]))
    roots = [d["path"] for _, d in ordered if d["parent"] is None]
    yield json.dumps({"t": "header", "collector": "catalog", "case_insensitive": ci, "full": True, "roots": roots})
    for key, d in ordered:
        listed = files.get(key, {})
        yield json.dumps({"t": "dir", "key": key, **d, "size": sum(v[0] for v in listed.values()),
                          "files": len(listed)})
        for name, (size, mtime, ctime) in listed.items():
            yield json.dumps({"t": "file", "dir": key, "name": name, "size": size, "mtime_ns": mtime,
                              "ctime_ns": ctime})
    yield json.dumps({"t": "trailer", "status": "ok", "errors": []})


def _parse(line):
    """The record dict of one stream line (header forced to `catalog`); ValueError when unusable."""
    try:
        rec = json.loads(line)
        if any(k not in rec for k in NEEDS.get(rec["t"], ())):
            raise ValueError("incomplete record")
    except (KeyError, TypeError) as exc:
        raise ValueError("bad record") from exc
    if rec["t"] == "header":
        rec["collector"] = "catalog"
    return rec


def jsonl_lines(path, tally):
    """Lines of our own stream; unparseable or incomplete lines are skipped and counted in tally."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rec = _parse(line)
            except ValueError:
                tally["skipped"] += 1
                continue
            yield json.dumps(rec) if rec["t"] == "header" else line


def ensure_offline_device(conn, name):
    """The device NAME with reach `offline`; a device that real collectors scan is never turned into a catalog."""
    row = conn.execute("SELECT id FROM device WHERE name = ?", (name,)).fetchone()
    if row is None:
        ingest.ensure_device(conn, name)
    elif conn.execute("SELECT 1 FROM scan_run r JOIN ref_collector c ON c.id = r.collector_id "
                      "WHERE r.device_id = ? AND c.code NOT IN ('catalog', 'filetree')", (row[0],)).fetchone():
        raise ValueError(f"device {name} is scanned by collectors; pick another catalog name")
    conn.execute("UPDATE device SET reach_id = ?, status_id = ? WHERE name = ?",
                 (conn.ref_id("ref_reach", "offline"), conn.ref_id("ref_device_status", "active"), name))


def counts(conn, name):
    q = ("SELECT (SELECT count(*) FROM dir d WHERE d.device_id = v.id AND d.retired_run IS NULL), "
         "(SELECT count(*) FROM file f WHERE f.device_id = v.id AND f.retired_run IS NULL) "
         "FROM device v WHERE name = ?")
    return tuple(conn.execute(q, (name,)).fetchone())


def detect_format(path, fmt=None):
    if fmt:
        return fmt
    return "efu" if Path(path).suffix.lower() in (".efu", ".csv") else "jsonl"


def import_catalog(conn, path, name, fmt=None):
    """Load FILE as the catalog NAME. Returns {'folders', 'files', 'skipped', 'status'}."""
    fmt, tally = detect_format(path, fmt), {"skipped": 0}
    if fmt == "efu":
        rows, tally["skipped"] = read_efu(path)
        lines = build_stream(rows)
    else:
        lines = jsonl_lines(path, tally)
    ensure_offline_device(conn, name)
    result = files_ingest.ingest_stream(conn, lines, name)
    folders, nfiles = counts(conn, name)
    return {"folders": folders, "files": nfiles, "skipped": tally["skipped"], "status": result["status"]}
