# SPDX-License-Identifier: MIT
"""Full-text search over the catalog (search_fts), ranked by bm25. Safe for any user input."""
import sqlite3

MAX_LIMIT = 200
FIELDS = ("source", "kind", "device", "key", "active", "purpose", "criticality", "primary_content", "size_bytes",
          "snippet")
# The best hits first, then the folder facts for each (purpose, criticality, content, size) from v_folders.
SQL = ("WITH hit AS (SELECT rowid AS rid, source, ref_id, device, kind, key, bm25(search_fts, 0, 0, 1, 1, 10, 1) AS rank, "
       "snippet(search_fts, -1, '', '', '...', 12) AS snippet FROM search_fts WHERE search_fts MATCH ? "
       "AND (? IS NULL OR kind = ?) AND (? IS NULL OR device = ?) "
       "ORDER BY rank, rid LIMIT ?) "
       "SELECT h.*, 1 AS active, f.purpose, f.criticality, f.primary_content, f.size_bytes FROM hit h "
       "LEFT JOIN v_folders f ON h.source = 'item' AND f.id = h.ref_id ORDER BY h.rank, h.rid")


def match_expr(terms):
    """Each word becomes a quoted prefix token, so - . / : * and quotes are plain text, never FTS syntax."""
    words = [w for t in terms for w in str(t).split()]
    if not words:
        raise ValueError("search needs at least one term")
    return " ".join('"' + w.replace('"', '""') + '"*' for w in words)


def run(conn, terms, limit=20, narrow=None):
    """List of hits {ref_id, source, kind, device, key, active, purpose, criticality, primary_content, size_bytes,
    snippet}, best first. narrow = {'kind': ..., 'device': ...} (exact match, either optional) narrows the
    hits. ref_id is the item/change/link id, or None for purposes. Raises ValueError on a bad query."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    try:
        kind, device = (narrow or {}).get("kind"), (narrow or {}).get("device")
        rows = conn.execute(SQL, (match_expr(terms), kind, kind, device, device, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        raise ValueError(f"bad search query: {exc}") from exc
    return [{"ref_id": r["ref_id"], **{k: r[k] for k in FIELDS}, "active": bool(r["active"])} for r in rows]
