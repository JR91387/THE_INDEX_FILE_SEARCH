# SPDX-License-Identifier: MIT
"""What `watch` writes: one flush (the changed folders listed by the filetree collector in targeted mode, through
the normal ingest, then titles), and the watch's own `watch` run that opens or closes its gaps."""
import json
import os
import sys
import tempfile

from . import files_ingest, files_run, ingest, scan
from .files_proc import HERE, stream

TITLES_PER_FLUSH = 500
CHILDREN = ("SELECT c.path_key, c.mtime_ns, c.ctime_ns FROM dir p JOIN dir c ON c.parent_id = p.id "
            "WHERE p.device_id = ? AND p.path_key IN ({}) AND c.retired_run IS NULL AND c.mtime_ns IS NOT NULL")


def case_insensitive():
    return sys.platform in ("win32", "darwin")


def device_id(conn, name):
    row = conn.execute("SELECT id FROM device WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def write_child_state(conn, cfg, dirs, path):
    """State file for a targeted run: the known, active children of the listed dirs (they are skipped)."""
    keys = [files_ingest.root_key(d, case_insensitive()) for d in dirs]
    dev = device_id(conn, cfg.device_name)
    with open(path, "w", encoding="utf-8") as out:
        for at in range(0, len(keys) if dev else 0, 500):
            chunk = keys[at:at + 500]
            rows = conn.execute(CHILDREN.format(",".join("?" * len(chunk))), (dev, *chunk))
            out.writelines(f"{key}\t{mtime}\t{ctime}\n" for key, mtime, ctime in rows)


def flush(conn, cfg, dirs):
    """List `dirs` now. None when a scan holds the lock (the caller keeps them queued), else the ingest result."""
    with scan.scan_lock(cfg.db_path) as taken:
        if not taken:
            return None
        with tempfile.TemporaryDirectory(prefix="the-index-watch-") as tmp:
            return _listed(conn, cfg, (sorted(dirs), tmp))


def _listed(conn, cfg, job):
    dirs, tmp = job
    s = files_run.settings(cfg)
    opts = {**files_run.options(conn, cfg, False), "targets_file": os.path.join(tmp, "targets.txt")}
    # roots stay the filetree roots: a target that is one of them keeps parent NULL, any other keeps its parent
    with open(opts["targets_file"], "w", encoding="utf-8", errors="surrogateescape") as out:
        out.writelines(d + "\n" for d in dirs)
    state = os.path.join(tmp, "state.tsv")
    write_child_state(conn, cfg, dirs, state)
    argv = [sys.executable, "-I", str(HERE / "filetree.py"), json.dumps(opts), "--state", state]
    result = stream(argv, float(opts["budget_s"]) + 300,
                    lambda lines: files_ingest.ingest_stream(conn, lines, cfg.device_name))
    if result["status"] != "ok":
        files_run.mark_full(conn, "watch: a folder listing was incomplete")
    if s["titles"] and result["status"] != "failed":
        limited = {**s, "title_budget": min(int(s["title_budget"]), TITLES_PER_FLUSH)}
        result["titles"] = files_run.read_titles(conn, (result, limited, tmp))
    return result


def watch_roots(conn, cfg):
    """[watch] roots, else the filetree roots."""
    return list(cfg.watch.get("roots") or files_run.options(conn, cfg, False)["roots"])


def record(conn, cfg, gaps):
    """A `watch` run reporting the watch's gaps now; gaps it no longer reports close."""
    with scan.scan_lock(cfg.db_path) as taken:
        if not taken:
            return None
        return ingest.ingest(conn, {"collector": "watch", "status": "ok", "items": [], "gaps": gaps,
                                    "errors": []}, cfg.device_name)
