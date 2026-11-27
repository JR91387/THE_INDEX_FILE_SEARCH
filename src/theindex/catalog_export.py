# SPDX-License-Identifier: MIT
"""Catalog export and listing, written from the database (never from disk)."""
import csv
import json
import os
import tempfile
from pathlib import Path

from . import catalog, files_ingest

EFU_HEADER = ["Filename", "Size", "Date Modified", "Date Created", "Attributes"]


def _selected_dirs(conn, device, prefix):
    rows = conn.execute("SELECT d.id, d.path_key, d.path, p.path_key AS parent_key, d.mtime_ns, d.ctime_ns "
                        "FROM dir d JOIN device v ON v.id = d.device_id LEFT JOIN dir p ON p.id = d.parent_id "
                        "WHERE v.name = ? AND d.retired_run IS NULL ORDER BY d.depth, d.path_key", (device,)).fetchall()
    if prefix:
        want = files_ingest.root_key(prefix, True)
        rows = [r for r in rows if files_ingest.under(r["path_key"].casefold(), [want.casefold()])]
    if not rows:
        raise ValueError(f"no catalog rows for device {device}" + (f" under {prefix}" if prefix else ""))
    return rows


def _full(dir_path, name):
    sep = "\\" if "\\" in dir_path else "/"
    return dir_path.rstrip("\\/") + sep + name


def _files(conn, dirs):
    by_dir = {}
    for r in conn.execute("SELECT dir_id, name, size_bytes, mtime_ns, ctime_ns FROM file "
                          "WHERE retired_run IS NULL AND dir_id IN (SELECT value FROM json_each(?)) "
                          "ORDER BY dir_id, name", (json.dumps([d["id"] for d in dirs]),)):
        by_dir.setdefault(r["dir_id"], []).append(r)
    return by_dir


def _efu_rows(dirs, by_dir):
    for d in dirs:
        yield [d["path"], "", ns_cell(d["mtime_ns"]), ns_cell(d["ctime_ns"]), 16]
        for f in by_dir.get(d["id"], ()):
            yield [_full(d["path"], f["name"]), f["size_bytes"], ns_cell(f["mtime_ns"]), ns_cell(f["ctime_ns"]), 32]


def ns_cell(ns):
    value = catalog.ns_to_filetime(ns)
    return "" if value is None else value


def _jsonl_lines(dirs, by_dir):
    keys = {d["path_key"] for d in dirs}
    roots = [d["path"] for d in dirs if d["parent_key"] not in keys]
    ci = any(d["path_key"] != d["path"].replace("\\", "/").rstrip("/") for d in dirs)
    yield json.dumps({"t": "header", "collector": "catalog", "case_insensitive": ci, "full": True, "roots": roots})
    for d in dirs:
        own = by_dir.get(d["id"], ())
        yield json.dumps({"t": "dir", "key": d["path_key"], "path": d["path"], "files": len(own),
                          "size": sum(f["size_bytes"] for f in own),
                          "parent": d["parent_key"] if d["parent_key"] in keys else None,
                          "mtime_ns": d["mtime_ns"], "ctime_ns": d["ctime_ns"]})
        for f in by_dir.get(d["id"], ()):
            yield json.dumps({"t": "file", "dir": d["path_key"], "name": f["name"], "size": f["size_bytes"],
                              "mtime_ns": f["mtime_ns"], "ctime_ns": f["ctime_ns"]})
    yield json.dumps({"t": "trailer", "status": "ok", "errors": []})


def export_catalog(conn, out, selection, fmt="efu"):
    """Write a device's active folders and files to OUT atomically; selection = (device, path prefix or None).
    Returns (folders, files)."""
    dirs = _selected_dirs(conn, *selection)
    by_dir = _files(conn, dirs)
    out = Path(out)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=out.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            if fmt == "efu":
                writer = csv.writer(fh, lineterminator="\r\n")
                writer.writerow(EFU_HEADER)
                writer.writerows(_efu_rows(dirs, by_dir))
            else:
                fh.writelines(line + "\n" for line in _jsonl_lines(dirs, by_dir))
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return len(dirs), sum(len(v) for v in by_dir.values())


def list_catalogs(conn):
    """Offline devices with active folder/file counts and the time of the last import."""
    rows = conn.execute(
        "SELECT v.name, (SELECT count(*) FROM dir d WHERE d.device_id = v.id AND d.retired_run IS NULL) AS folders, "
        "(SELECT count(*) FROM file f WHERE f.device_id = v.id AND f.retired_run IS NULL) AS files, "
        "(SELECT max(coalesce(r.finished_at, r.started_at)) FROM scan_run r JOIN ref_collector c "
        " ON c.id = r.collector_id WHERE r.device_id = v.id AND c.code = 'catalog') AS last_import "
        "FROM device v JOIN ref_reach rr ON rr.id = v.reach_id WHERE rr.code = 'offline' ORDER BY v.name")
    return [dict(r) for r in rows]
