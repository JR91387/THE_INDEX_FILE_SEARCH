# SPDX-License-Identifier: MIT
"""Blind spots. A collector reports what it could not see; gaps it stops reporting are closed (OK runs only)."""


def sync(conn, ctx, reported, run_ok):
    """Open or refresh each reported gap; close this collector's open gaps that were not reported."""
    seen = set()
    for gap in reported:
        kind_id = conn.ref_id("ref_gap_kind", gap["kind"])
        row = conn.execute("SELECT id FROM gap WHERE coalesce(device_id,0)=? AND gap_kind_id=? AND target=? "
                           "AND closed_run IS NULL", (ctx["device_id"], kind_id, gap["target"])).fetchone()
        if row:
            conn.execute("UPDATE gap SET last_seen_run=?, reason=? WHERE id=?",
                         (ctx["run_id"], gap.get("reason"), row[0]))
            seen.add(row[0])
            continue
        seen.add(conn.execute(
            "INSERT INTO gap (device_id, collector_id, gap_kind_id, target, reason, first_seen_run, last_seen_run) "
            "VALUES (?,?,?,?,?,?,?)", (ctx["device_id"], ctx["collector_id"], kind_id, gap["target"],
                                      gap.get("reason"), ctx["run_id"], ctx["run_id"])).lastrowid)
    if run_ok:
        close_unseen(conn, ctx, seen)


def close_unseen(conn, ctx, seen):
    rows = conn.execute("SELECT id FROM gap WHERE device_id=? AND collector_id=? AND closed_run IS NULL",
                        (ctx["device_id"], ctx["collector_id"])).fetchall()
    for row in rows:
        if row[0] not in seen:
            conn.execute("UPDATE gap SET closed_run=? WHERE id=?", (ctx["run_id"], row[0]))
