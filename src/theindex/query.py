# SPDX-License-Identifier: MIT
"""The read-only query layer behind the CLI and the MCP server. Every function takes (conn, params_dict) and
returns {"schema_version": 1, "query": {...}, "results": [...], "more": N}. Never writes, never raises on odd words."""
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta

from . import config, query_fast, search
from .query_describe import describe

VERSION = 1
DEFAULT_LIMIT, MAX_LIMIT, MAX_DEPTH = 25, 500, 6
LIMITS = (1, DEFAULT_LIMIT, MAX_LIMIT)   # (min, default, max)
FILE_SQL = ("SELECT 'file' AS type, 1 AS ord, v.device, v.path, v.name, v.title, f.meta, v.ext, v.size_bytes, v.mtime_ns, "
            "(d.agent_files <> '[]') AS is_project, v.offline, bm25(file_fts, 10, 5, 2) AS rank "
            "FROM file_fts JOIN v_files v ON v.id = file_fts.rowid JOIN file f ON f.id = v.id "
            "JOIN dir d ON d.id = f.dir_id WHERE file_fts MATCH ?")
DIR_SQL = ("SELECT 'dir' AS type, 0 AS ord, v.device, v.path, '' AS name, NULL AS title, NULL AS meta, '' AS ext, "
           "v.size_total AS size_bytes, v.mtime_ns, (v.agent_files <> '[]') AS is_project, "
           "v.offline, bm25(dir_fts) AS rank FROM dir_fts JOIN v_dirs v ON v.id = dir_fts.rowid WHERE dir_fts MATCH ?")
TREE_SQL = ("WITH RECURSIVE sub(id, rel) AS (SELECT id, 0 FROM v_dirs WHERE id = ? UNION ALL "
            "SELECT d.id, sub.rel + 1 FROM v_dirs d JOIN sub ON d.parent_id = sub.id WHERE sub.rel < ?) "
            "SELECT t.device, t.path, sub.rel AS depth, t.size_total, t.files_total, t.pct_of_parent, "
            "t.is_cache FROM sub JOIN v_tree t ON t.id = sub.id WHERE sub.rel > 0 AND t.size_total >= ? "
            "ORDER BY t.size_total DESC, t.path")


def clamp(params, key, bounds):
    """params[key] as an int within bounds = (min, default, max); anything unusable gives the default."""
    lo, default, hi = bounds
    try:
        value = int(params.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def envelope(query, results, total=None, **extra):
    more = max(0, (len(results) if total is None else total) - len(results))
    return {"schema_version": VERSION, "query": query, "results": results, "more": more, **extra}


def iso(ns):
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / 1e9, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _words(params):
    words = params.get("words") or []
    return words.split() if isinstance(words, str) else [w for x in words for w in str(x).split()]


def _find_query(params):
    kind = params.get("kind") if params.get("kind") in ("dir", "file") else "any"
    ext = str(params.get("ext") or "").strip().lower().lstrip(".")
    return {"words": _words(params), "kind": kind, "ext": "." + ext if ext else None,
            "device": params.get("device") or None, "documents_only": bool(params.get("documents_only")),
            "tag": str(params.get("tag") or "").strip() or None, "author": str(params.get("author") or "").strip() or None,
            "limit": clamp(params, "limit", LIMITS)}


def _meta_filters(q, sql, args):
    """Add the tag (whole tag) and author (part of the name) filters, both case-insensitive, over file.meta JSON."""
    if q["tag"]:
        sql += " AND EXISTS (SELECT 1 FROM json_each(f.meta, '$.tags') WHERE fold(value) = fold(?))"
        args = args + [q["tag"]]
    if q["author"]:
        sql += " AND instr(fold(json_extract(f.meta, '$.author')), fold(?)) > 0"
        args = args + [q["author"]]
    return sql, args


def _fold(value):
    return value.casefold() if isinstance(value, str) else None


def _find_sql(q, expr):
    """The UNION of the file and dir searches for the filters in q, and its arguments."""
    parts, args = [], []
    dev = " AND v.device = ?" if q["device"] else ""
    tail = [q["device"]] if q["device"] else []
    if q["kind"] in ("file", "any"):
        sql, a = FILE_SQL + dev, [expr] + tail
        if q["ext"]:
            sql, a = sql + " AND v.ext = ?", a + [q["ext"]]
        if q["documents_only"]:
            sql += " AND v.is_document"
        sql, a = _meta_filters(q, sql, a)
        parts.append(sql)
        args += a
    if q["kind"] in ("dir", "any") and not (q["ext"] or q["documents_only"] or q["tag"] or q["author"]):
        parts.append(DIR_SQL + dev)
        args += [expr] + tail
    return " UNION ALL ".join(parts) or "SELECT 0 AS rank, 0 AS ord, '' AS path WHERE 0", args   # no part: no rows


def _hit(r):
    name = r["name"] or re.split(r"[\\/]", r["path"].rstrip("/\\"))[-1]
    return {"type": r["type"], "device": r["device"], "path": r["path"], "name": name, "title": r["title"],
            "meta": json.loads(r["meta"]) if r["meta"] else None, "ext": r["ext"], "size_bytes": r["size_bytes"], "mtime": iso(r["mtime_ns"]),
            "is_project": bool(r["is_project"]), "offline": bool(r["offline"])}


def find(conn, params):
    """Words (prefix match, all required) over file names and titles and folder paths, best first."""
    q = _find_query(params)
    conn.create_function("fold", 1, _fold, deterministic=True)
    try:
        expr = search.match_expr(q["words"])
        if query_fast.applies(q):
            total = query_fast.total(conn, q, expr)
            if total > query_fast.RANK_ALL:
                return envelope(q, [_hit(r) for r in query_fast.rows(conn, q, expr)], total)
        sql, args = _find_sql(q, expr)
        if not query_fast.applies(q):
            total = conn.execute(f"SELECT count(*) FROM ({sql})", args).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM ({sql}) ORDER BY rank, ord, path LIMIT ?", args + [q["limit"]]).fetchall()
        extra, more = query_fast.substring(conn, q, rows, expr)
        return envelope(q, [_hit(r) for r in rows + extra], total + more)
    except sqlite3.OperationalError as exc:
        return envelope(q, [], error=f"bad query: {exc}")


def _start(conn, params):
    """The active dir row named by params['path'] (path or path_key, optionally one device), or None."""
    dev = " AND device = ?" if params.get("device") else ""
    args = [str(params.get("path", ""))] * 2 + ([params["device"]] if dev else [])
    return conn.execute("SELECT * FROM v_dirs WHERE (path = ? OR path_key = ?)" + dev + " ORDER BY id LIMIT 1",
                        args).fetchone()


def tree(conn, params):
    """Folders below a path, down to depth, biggest first, with their share of the parent."""
    q = {"path": str(params.get("path", "")), "depth": clamp(params, "depth", (1, 2, MAX_DEPTH)),
         "min_bytes": clamp(params, "min_bytes", (0, 0, 2**62)), "limit": clamp(params, "limit", LIMITS)}
    start = _start(conn, params)
    if start is None:
        return envelope(q, [], error="unknown path")
    rows = conn.execute(TREE_SQL, (start["id"], q["depth"], q["min_bytes"])).fetchall()
    out = [{**dict(r), "is_cache": bool(r["is_cache"])} for r in rows[:q["limit"]]]
    return envelope(q, out, len(rows))


def projects(conn, params):
    """Folders holding AI-agent instruction files, newest first."""
    q = {"limit": clamp(params, "limit", LIMITS)}
    total = conn.execute("SELECT count(*) FROM v_projects").fetchone()[0]
    rows = conn.execute("SELECT * FROM v_projects ORDER BY mtime_ns IS NULL, mtime_ns DESC, path LIMIT ?", (q["limit"],))
    out = [{"device": r["device"], "path": r["path"], "agent_files": json.loads(r["agent_files"]),
            "size_total": r["size_total"], "mtime": iso(r["mtime_ns"])} for r in rows.fetchall()]
    return envelope(q, out, total)


def folder(conn, params):
    """One folder: its facts, up to limit direct files and up to limit subfolders."""
    q = {"path": str(params.get("path", "")), "limit": clamp(params, "limit", LIMITS)}
    d = _start(conn, params)
    if d is None:
        return envelope(q, [], error="unknown path")
    files = conn.execute("SELECT name, ext, size_bytes, title FROM file WHERE dir_id = ? AND retired_run IS NULL "
                         "ORDER BY name LIMIT ?", (d["id"], q["limit"])).fetchall()
    nfiles = conn.execute("SELECT count(*) FROM file WHERE dir_id = ? AND retired_run IS NULL", (d["id"],)).fetchone()[0]
    subs = conn.execute("SELECT path, size_total FROM v_dirs WHERE parent_id = ? ORDER BY size_total DESC, path LIMIT ?",
                        (d["id"], q["limit"])).fetchall()
    nsubs = conn.execute("SELECT count(*) FROM v_dirs WHERE parent_id = ?", (d["id"],)).fetchone()[0]
    row = {"device": d["device"], "path": d["path"], "size_total": d["size_total"], "files_total": d["files_total"],
           "is_cache": bool(d["is_cache"]), "is_project": d["agent_files"] != "[]",
           "agent_files": json.loads(d["agent_files"]), "mtime": iso(d["mtime_ns"]), "offline": bool(d["offline"]),
           "files": [dict(r) for r in files], "subdirs": [dict(r) for r in subs]}
    return {**envelope(q, [row]), "more": (nfiles - len(files)) + (nsubs - len(subs))}


def _cutoff(since):
    """ISO time of a duration ('7d') ago, or the ISO time given. ValueError when neither."""
    try:
        when = datetime.now(UTC) - timedelta(seconds=config.parse_duration(since))
    except ValueError:
        when = datetime.fromisoformat(str(since))
        when = when if when.tzinfo else when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def changes_files(conn, params):
    """Document events (new, retitled, gone) since a time, newest first."""
    try:
        since = _cutoff(params.get("since", "7d"))
    except ValueError:
        raise ValueError(f"bad since: {params.get('since')!r} (use 7d, 12h, 30m or an ISO time)") from None
    q = {"since": since, "limit": clamp(params, "limit", LIMITS)}
    total = conn.execute("SELECT count(*) FROM v_file_events WHERE at > ?", (since,)).fetchone()[0]
    rows = conn.execute("SELECT device, name, title, action, at FROM v_file_events WHERE at > ? "
                        "ORDER BY at DESC, file_id LIMIT ?", (since, q["limit"])).fetchall()
    return envelope(q, [dict(r) for r in rows], total)


COMMANDS = {"find": find, "tree": tree, "projects": projects, "folder": folder, "changes_files": changes_files,
            "describe": describe}
