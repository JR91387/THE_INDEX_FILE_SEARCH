# SPDX-License-Identifier: MIT
"""First load of a device's files without per-row search-index triggers.

Each file insert fires the name/title/meta and the trigram name index triggers; on a first scan of a million
files that is most of the time. When the device has no file rows yet, the triggers are dropped inside the run's
transaction, the rows are loaded, both indexes are rebuilt once from the table, and the triggers are put back
exactly as they were (their SQL is read from sqlite_master first). Readers in WAL mode see the old state until
the transaction commits; a failure rolls the drop back with everything else."""

TRIGGERS = ("file_fts_ai", "file_fts_au", "file_name_tri_ai", "file_name_tri_au")
INDEXES = ("file_fts", "file_name_tri")


def begin(conn, device_id):
    """Drop the file search triggers when this device has no file rows yet. Returns what end() needs, or None."""
    if conn.execute("SELECT 1 FROM file WHERE device_id = ? LIMIT 1", (device_id,)).fetchone():
        return None
    saved = conn.execute(f"SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name IN "
                         f"({','.join('?' * len(TRIGGERS))})", TRIGGERS).fetchall()
    if len(saved) != len(TRIGGERS):
        return None                       # an unexpected schema: keep the triggers, load row by row
    for name, _ in saved:
        conn.execute(f"DROP TRIGGER {name}")
    return saved


def end(conn, saved):
    """Rebuild the search indexes from the table and restore the triggers (no-op when begin() returned None)."""
    if not saved:
        return
    for index in INDEXES:
        conn.execute(f"INSERT INTO {index} ({index}) VALUES ('rebuild')")
    for _, sql in saved:
        conn.execute(sql)
