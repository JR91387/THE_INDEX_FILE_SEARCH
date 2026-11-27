# SPDX-License-Identifier: MIT
"""Run `filetree` on this machine and stream it into the database, then read titles for changed documents.
The collector never writes; its state file (last-seen dir mtimes) is written here, in a private temp dir."""
import json
import os
import sys
import tempfile

from . import files_ingest, files_source
from .collectors import folders
from .files_proc import HERE, stream

CACHE_MARKERS = ["node_modules", ".git", "__pycache__", ".venv", ".cache", ".tox", ".mypy_cache", ".gradle"]
LINUX_ROOTS = ["/home", "/srv", "/opt"]
DEFAULTS = {"enabled": True, "full_every": 7, "budget_s": 1800, "titles": True, "meta": True, "title_budget": 20000}


def settings(cfg):
    return {**DEFAULTS, **getattr(cfg, "filetree", {})}


def options(conn, cfg, full):
    s = settings(cfg)
    roots = s.get("roots") or cfg.folders.get("roots") or folders.ROOTS.get(sys.platform, LINUX_ROOTS)
    markers = [r[0] for r in conn.execute("SELECT code FROM ref_agent_marker WHERE retired_at IS NULL")]
    return {"roots": roots, "exclude": list(cfg.folders.get("exclude", [])) + list(s.get("exclude", [])),
            "cache_markers": s.get("cache_markers", CACHE_MARKERS), "agent_markers": markers,
            "full": full, "budget_s": s["budget_s"], "title_budget": s["title_budget"]}


FULL_NEXT = "filetree_full_next"


def mark_full(conn, reason):
    """Make the next filetree run a full walk (`watch` lost events); '' clears the mark."""
    conn.execute("INSERT INTO setting (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                 (FULL_NEXT, str(reason)[:200]))


def full_marked(conn):
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (FULL_NEXT,)).fetchone()
    return bool(row and row[0])


def is_full(conn, device_name, every):
    """Full walk when there is no OK run yet, when `watch` marked one, else on every `every`-th OK run."""
    if full_marked(conn):
        return True
    done = conn.execute("SELECT count(*) FROM scan_run r JOIN device d ON d.id = r.device_id "
                        "JOIN ref_collector c ON c.id = r.collector_id JOIN ref_run_status s ON s.id = r.status_id "
                        "WHERE d.name = ? AND c.code = 'filetree' AND s.code = 'ok'", (device_name,)).fetchone()[0]
    return done == 0 or done % max(1, int(every)) == 0


def write_state(conn, device_name, path):
    with open(path, "w", encoding="utf-8") as out:
        out.writelines(f"{key}\t{mtime}\t{ctime}\n" for key, mtime, ctime in conn.execute(
                "SELECT d.path_key, d.mtime_ns, d.ctime_ns FROM dir d JOIN device v ON v.id = d.device_id "
                "WHERE v.name = ? AND d.retired_run IS NULL AND d.mtime_ns IS NOT NULL", (device_name,)))


def run(conn, cfg, full=None):
    """One filetree run + titles. Returns the ingest-style result (status, items, changes, baseline).
    A non-full run uses the OS's own index when there is one; a full run walks, then checks the walk against it."""
    s = settings(cfg)
    full = is_full(conn, cfg.device_name, s["full_every"]) if full is None else full
    opts = options(conn, cfg, full)
    result = None if full else files_source.run_native(conn, cfg, opts)
    with tempfile.TemporaryDirectory(prefix="the-index-") as tmp:
        if result is None:
            result = walk(conn, cfg, (opts, tmp))
            if full:
                files_source.verify(conn, cfg, opts, result)
            if result.get("bulk"):
                conn.execute("VACUUM")   # a first load leaves half-full index pages: ~12 % of the file back, once
            if full and result["status"] == "ok" and full_marked(conn):
                mark_full(conn, "")
        if s["titles"] and result["status"] != "failed":
            result["titles"] = read_titles(conn, (result, s, tmp))
    return result


def walk(conn, cfg, job):
    opts, tmp = job
    state = os.path.join(tmp, "state.tsv")
    write_state(conn, cfg.device_name, state)
    argv = [sys.executable, "-I", str(HERE / "filetree.py"), json.dumps(opts), "--state", state]
    return stream(argv, float(opts["budget_s"]) + 300,
                  lambda lines: files_ingest.ingest_stream(conn, lines, cfg.device_name))


def worklist(conn, device_id, limit, meta=True):
    """Documents whose title was never read or whose size/mtime changed since; with `meta`, also documents whose
    title was read before front matter existed (meta NULL, a read with nothing found stores '{}')."""
    return conn.execute(
        "SELECT f.id, d.path, f.name, f.size_bytes || ':' || coalesce(f.mtime_ns, '') FROM file f "
        "JOIN dir d ON d.id = f.dir_id JOIN ref_title_type t ON t.code = f.ext AND t.retired_at IS NULL "
        "WHERE f.device_id = ? AND f.retired_run IS NULL "
        "AND (f.title_sig IS NULL OR f.title_sig <> f.size_bytes || ':' || coalesce(f.mtime_ns, '') "
        "OR (? AND f.meta IS NULL)) "
        "ORDER BY f.mtime_ns DESC LIMIT ?", (device_id, int(bool(meta)), int(limit))).fetchall()


def read_titles(conn, job):
    """job = (filetree result, settings, temp dir). Returns how many titles were read."""
    result, s, tmp = job
    rows = worklist(conn, result["device_id"], s["title_budget"], s["meta"])
    if not rows:
        return 0
    sig = {row[0]: row[3] for row in rows}
    path = os.path.join(tmp, "worklist.jsonl")
    with open(path, "w", encoding="utf-8") as out:
        out.writelines(json.dumps({"id": fid, "path": os.path.join(dpath, name)}) + "\n" for fid, dpath, name, _ in rows)
    argv = [sys.executable, "-I", str(HERE / "titles.py"), "--worklist", path,
            json.dumps({"budget_s": min(600, float(s["budget_s"])), "max_files": int(s["title_budget"])})]
    return stream(argv, min(600, float(s["budget_s"])) + 120, lambda lines: store_titles(conn, (lines, sig, result), s["meta"]))


def meta_json(rec):
    """Stored form of a record's meta: JSON text, '{}' when the read found nothing."""
    meta = rec.get("meta")
    return json.dumps(meta if isinstance(meta, dict) else {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


UPDATE_TITLE = (
    "UPDATE file SET title_run = CASE WHEN title_sig IS ?5 THEN title_run "      # same file, only meta was missing
    "WHEN coalesce(title, '') <> coalesce(?1, '') THEN ?6 ELSE title_run END, "
    "title = CASE WHEN title_sig IS ?5 THEN title ELSE ?1 END, "
    "title_src = CASE WHEN title_sig IS ?5 THEN title_src ELSE ?2 END, title_sig = ?5, "
    "meta = coalesce(?3, meta) WHERE id = ?4")


def store_titles(conn, job, with_meta=True):
    lines, sig, result = job
    done = 0
    conn.execute("BEGIN")
    try:
        for line in lines:
            rec = json.loads(line) if line.strip() else {}
            if rec.get("id") not in sig:
                continue
            conn.execute(UPDATE_TITLE, (rec.get("title"), rec.get("src"), meta_json(rec) if with_meta else None,
                                        rec["id"], sig[rec["id"]], result["run_id"]))
            done += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return done
