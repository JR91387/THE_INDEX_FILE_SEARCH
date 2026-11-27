# SPDX-License-Identifier: MIT
"""`find` for large result sets. Ranking every match by relevance (bm25) costs ~100 ms at a million files, and
on tens of thousands of hits relevance says little. So when an unfiltered search matches more than RANK_ALL rows,
results come straight from the search index in rowid order (newest first, which the index reads without sorting):
folders (up to half the page), then files whose name matches, then files matching by title or front matter.
Counts come from the index alone. Smaller result sets keep full relevance ranking (query.find)."""

RANK_ALL = 2000
FILE_COLS = ("SELECT 'file' AS type, 1 AS ord, v.device, v.path, v.name, v.title, f.meta, v.ext, v.size_bytes, "
             "v.mtime_ns, (d.agent_files <> '[]') AS is_project, v.offline, 0 AS rank "
             "FROM v_files v JOIN file f ON f.id = v.id JOIN dir d ON d.id = f.dir_id WHERE v.id IN ")
DIR_COLS = ("SELECT 'dir' AS type, 0 AS ord, v.device, v.path, '' AS name, NULL AS title, NULL AS meta, '' AS ext, "
            "v.size_total AS size_bytes, v.mtime_ns, (v.agent_files <> '[]') AS is_project, v.offline, 0 AS rank "
            "FROM v_dirs v WHERE v.id IN ")


def applies(q):
    """Only plain word searches (optionally kind=dir|file) take the fast path."""
    return not (q["device"] or q["ext"] or q["documents_only"] or q["tag"] or q["author"])


def total(conn, q, expr):
    n = 0
    if q["kind"] in ("file", "any"):
        n += conn.execute("SELECT count(*) FROM file_fts WHERE file_fts MATCH ?", (expr,)).fetchone()[0]
    if q["kind"] in ("dir", "any"):
        n += conn.execute("SELECT count(*) FROM dir_fts WHERE dir_fts MATCH ?", (expr,)).fetchone()[0]
    return n


def _ids(conn, table, expr, want):
    """want = count, or (count, ids to leave out)."""
    want, skip = want if isinstance(want, tuple) else (want, frozenset())
    rows = conn.execute(f"SELECT rowid FROM {table} WHERE {table} MATCH ? ORDER BY rowid DESC LIMIT ?",
                        (expr, want + len(skip)))
    return [r[0] for r in rows if r[0] not in skip][:want]


def rows(conn, q, expr):
    """Up to q['limit'] result rows for a large match set, in the order described above."""
    limit, out = q["limit"], []
    if q["kind"] in ("dir", "any"):
        out += _fetch_ordered(conn, DIR_COLS, _ids(conn, "dir_fts", expr, limit if q["kind"] == "dir" else limit // 2))
    if q["kind"] in ("file", "any") and len(out) < limit:
        named = _ids(conn, "file_fts", "{name} : (" + expr + ")", limit - len(out))
        rest = _ids(conn, "file_fts", expr, (limit - len(out) - len(named), frozenset(named)))
        out += _fetch_ordered(conn, FILE_COLS, named + rest)
    if q["kind"] == "any" and len(out) < limit:
        seen = len([r for r in out if r["type"] == "dir"])
        more = _ids(conn, "dir_fts", expr, limit - len(out) + seen)[seen:]
        out += _fetch_ordered(conn, DIR_COLS, more)
    return out[:limit]


def _fetch_ordered(conn, cols, ids):
    """Rows for ids, in the order of ids (the id column is selected alongside and dropped)."""
    if not ids:
        return []
    sql = cols.replace("SELECT ", "SELECT v.id AS _id, ", 1) + "(" + ",".join("?" * len(ids)) + ")"
    by_id = {r["_id"]: r for r in conn.execute(sql, ids)}
    return [by_id[i] for i in ids if i in by_id]


SUB_CAP = 1000


def substring(conn, q, found, expr):
    """When a search found fewer than its limit, files whose name contains every word (each ≥ 3 characters) as a
    substring, like Everything: 'mber' finds 'amber_notes.txt'. Returns (extra rows, how many such files exist,
    counted up to SUB_CAP). `_` and `%` in a word are wildcards to LIKE, so rows are re-checked in Python."""
    words, need = [w.casefold() for w in q["words"]], q["limit"] - len(found)
    if need <= 0 or q["kind"] == "dir" or not applies(q) or min(map(len, words)) < 3:
        return [], 0
    like = " AND ".join(["name LIKE ?"] * len(words))
    args = [f"%{w}%" for w in words]
    ids = [r[0] for r in conn.execute(
        f"SELECT rowid FROM (SELECT rowid FROM file_name_tri WHERE {like} LIMIT ?) EXCEPT "
        "SELECT rowid FROM file_fts WHERE file_fts MATCH ?", [*args, SUB_CAP, expr])]
    ids.sort(reverse=True)
    rows = [r for r in _fetch_ordered(conn, FILE_COLS, ids[:need * 2]) if all(w in r["name"].casefold() for w in words)]
    return rows[:need], len(ids)
