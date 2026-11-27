# SPDX-License-Identifier: MIT
"""Retirement for a targeted `filetree` run (header `targeted`, sent by `the-index watch`).

Only inside the listed directories: files missing from a listed dir, child dirs of a listed dir that were
neither listed nor skipped, and targets the collector reported `gone`; a retired dir takes its whole subtree
with it. Nothing outside the listed dirs is touched, and never under a gap target."""

CHILDREN = "SELECT id, path_key FROM dir WHERE parent_id = ? AND retired_run IS NULL"
SUBTREE = ("SELECT id FROM dir WHERE device_id = ? AND retired_run IS NULL "
           "AND (path_key = ? OR (path_key >= ? AND path_key < ?))")      # '0' sorts right after '/'


def retire(loader):
    loader.close_dir()
    conn, run = loader.conn, loader.run
    conn.executemany("UPDATE file SET retired_run=? WHERE id=?", [(run, i) for i in loader.unseen_files])
    blind = tuple(g["target"].rstrip("/") + "/" for g in loader.gaps if g.get("target"))
    doomed = [key for key in loader.gone if key and loader.dirs.get(key, (None, 1))[1] is None]
    for dir_id in loader.listed:
        doomed += [key for child, key in conn.execute(CHILDREN, (dir_id,)) if child not in loader.seen]
    for key in doomed:
        if not blind_to(key, blind):
            retire_tree(conn, (loader.ctx["device_id"], run), key)


def blind_to(key, blind):
    return any(key == b.rstrip("/") or key.startswith(b) for b in blind)


def retire_tree(conn, where, key):
    """Retire the dir `key`, every dir below it, and their files. where = (device_id, run_id)."""
    device_id, run = where
    ids = [row[0] for row in conn.execute(SUBTREE, (device_id, key, key + "/", key + "0"))]
    conn.executemany("UPDATE dir SET retired_run=? WHERE id=?", [(run, i) for i in ids])
    conn.executemany("UPDATE file SET retired_run=? WHERE dir_id=? AND retired_run IS NULL", [(run, i) for i in ids])
    return len(ids)
