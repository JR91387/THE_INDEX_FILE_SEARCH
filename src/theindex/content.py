# SPDX-License-Identifier: MIT
"""Folder content mix: one folder_content row per content type per measurement; the primary type is the
folder's attrs.primary_content (decided by the collector: marker, else most bytes, else mixed)."""


def write(conn, ctx, item_id, mix):
    """Store a measured content mix (list of {type, files, bytes}); unknown type codes count as 'unknown'."""
    if not mix:
        return
    primary = conn.execute("SELECT attrs ->> 'primary_content' FROM item WHERE id=?", (item_id,)).fetchone()[0]
    totals = {}
    for entry in mix:
        code = entry["type"] if known(conn, entry["type"]) else "unknown"
        files, size = totals.get(code, (0, 0))
        totals[code] = (files + int(entry["files"]), size + int(entry["bytes"]))
    for code, (files, size) in totals.items():
        conn.execute("INSERT INTO folder_content (item_id, run_id, content_type_id, file_count, bytes, is_primary) "
                     "VALUES (?,?,?,?,?,?)", (item_id, ctx["run_id"], conn.ref_id("ref_content_type", code),
                                             files, size, int(code == primary)))


def known(conn, code):
    try:
        conn.ref_id("ref_content_type", code)
        return True
    except KeyError:
        return False
