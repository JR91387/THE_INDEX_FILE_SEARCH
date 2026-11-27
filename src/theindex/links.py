# SPDX-License-Identifier: MIT
"""Detected relations between items (container mounts folder, backup backs_up folder...).

A link is recorded only when both ends already exist on the same device; unresolved links are counted and
picked up on a later run once the other collector has seen the target. On an OK run, auto links from items
seen in this run that were not reported again are retired."""


def resolve(conn, device_id, end):
    """[kind, key] -> active item id on this device, or None."""
    row = conn.execute("SELECT i.id FROM item i JOIN ref_item_kind k ON k.id = i.kind_id "
                       "WHERE i.device_id=? AND k.code=? AND i.key=? AND i.retired_run IS NULL",
                       (device_id, end[0], end[1])).fetchone()
    return row[0] if row else None


def upsert(conn, ctx, ends, kinds):
    """Insert or refresh one link. ends = (from_id, to_id); kinds = (link_type_id, source_code). Returns id."""
    from_id, to_id = ends
    link_type_id, source = kinds
    row = conn.execute("SELECT id FROM item_link WHERE from_item_id=? AND to_item_id=? AND link_type_id=?",
                       (from_id, to_id, link_type_id)).fetchone()
    if row:
        conn.execute("UPDATE item_link SET last_seen_run=?, retired_run=NULL WHERE id=?", (ctx["run_id"], row[0]))
        return row[0]
    return conn.execute("INSERT INTO item_link (from_item_id, to_item_id, link_type_id, source_id, first_seen_run, "
                        "last_seen_run) VALUES (?,?,?,?,?,?)",
                        (from_id, to_id, link_type_id, conn.ref_id("ref_link_source", source),
                         ctx["run_id"], ctx["run_id"])).lastrowid


def sync(conn, ctx, reported, seen_items):
    """Record reported links; retire stale auto links from seen items (OK runs only, ctx['run_ok']).
    Returns the number of links whose ends do not exist yet."""
    kept, unresolved = set(), 0
    for link in reported:
        ends = (resolve(conn, ctx["device_id"], link["from"]), resolve(conn, ctx["device_id"], link["to"]))
        if None in ends:
            unresolved += 1
            continue
        kept.add(upsert(conn, ctx, ends, (conn.ref_id("ref_link_type", link["type"]), "auto")))
    if ctx.get("run_ok"):
        retire_stale(conn, ctx, seen_items, kept)
    return unresolved


def retire_stale(conn, ctx, seen_items, kept):
    auto = conn.ref_id("ref_link_source", "auto")
    for item_id in seen_items:
        rows = conn.execute("SELECT id FROM item_link WHERE from_item_id=? AND source_id=? AND retired_run IS NULL",
                            (item_id, auto)).fetchall()
        for row in rows:
            if row[0] not in kept:
                conn.execute("UPDATE item_link SET retired_run=? WHERE id=?", (ctx["run_id"], row[0]))
