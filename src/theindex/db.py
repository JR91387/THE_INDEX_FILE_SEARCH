# SPDX-License-Identifier: MIT
"""Database access: connect, migrate, re-apply seeds/views/search, resolve ref codes.

Two kinds of schema files live in schema/:
  NNN_*.sql   migrations, applied once each, tracked by PRAGMA user_version
  seed_*.sql, views.sql, search.sql   re-applied on every init/upgrade (idempotent)
"""
import hashlib
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

PKG = Path(__file__).resolve().parent
SCHEMA_DIR = PKG / "schema"
ICON_DIR = PKG / "icons"
REAPPLY = ("seed_ref.sql", "seed_content_rules.sql", "seed_files.sql", "views.sql", "views_folders.sql",
           "views_files.sql", "views_fleet.sql", "views_front.sql")  # search.sql runs via rebuild_search()
_MIGRATION = re.compile(r"^(\d{3})_.*\.sql$")


class IndexConnection(sqlite3.Connection):
    """A connection that caches ref code -> id lookups."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._refs = {}

    def ref_id(self, table, code):
        """Id of `code` in ref table `table` (e.g. 'ref_change_class', 'suspicious'). Raises if unknown."""
        if not table.startswith("ref_") or not table.replace("_", "").isalnum():
            raise ValueError(f"not a ref table: {table}")
        hit = self._refs.get((table, code))
        if hit is None:
            row = self.execute(f"SELECT id FROM {table} WHERE code = ?", (code,)).fetchone()
            if row is None:
                raise KeyError(f"{table} has no code {code!r}")
            hit = self._refs[(table, code)] = row[0]
        return hit


def now():
    """Current UTC time in the schema's text format."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path):
    """Open (creating folders as needed) with the PRAGMAs every connection must have."""
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), factory=IndexConnection, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")    # SQLite only checks FKs when this is set per connection
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def migrations():
    """(number, path) for every migration file, in order."""
    found = []
    for path in sorted(SCHEMA_DIR.glob("*.sql")):
        match = _MIGRATION.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return found


def migrate(conn):
    """Apply pending migrations, each in its own transaction with its user_version bump."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, path in migrations():
        if number > current:
            conn.executescript(f"BEGIN;\n{path.read_text()}\nPRAGMA user_version = {number};\nCOMMIT;")
    return conn.execute("PRAGMA user_version").fetchone()[0]


def load_icons(conn):
    """Fill built-in icon SVG bodies from icons/<code>.svg (re-applied so icon edits propagate)."""
    for svg in sorted(ICON_DIR.glob("*.svg")):
        conn.execute("UPDATE ref_icon SET svg = ? WHERE code = ? AND is_builtin = 1",
                     (svg.read_text().strip(), svg.stem))


def reapply(conn):
    """Seeds, icons, views, search: safe to run any number of times."""
    for name in REAPPLY:
        conn.executescript(f"BEGIN;\n{(SCHEMA_DIR / name).read_text()}\nCOMMIT;")
    conn.execute("BEGIN")
    load_icons(conn)
    conn.execute("COMMIT")
    rebuild_search(conn)


def rebuild_search(conn):
    """Recreate the full-text index from current data."""
    conn.executescript(f"BEGIN;\n{(SCHEMA_DIR / 'search.sql').read_text()}\nCOMMIT;")


def schema_hash():
    """Fingerprint of every re-applied schema file and icon; a change means seeds/views/search need re-applying."""
    digest = hashlib.sha256()
    for path in [SCHEMA_DIR / n for n in (*REAPPLY, "search.sql")] + sorted(ICON_DIR.glob("*.svg")):
        digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()


def stored_hash(conn):
    try:
        row = conn.execute("SELECT value FROM setting WHERE key = 'schema_hash'").fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def init(path):
    """Create or upgrade a database and return an open (writable) connection.

    Seeds, icons, views and search are re-applied only when the schema version moved or the schema files changed."""
    conn = connect(path)
    before = conn.execute("PRAGMA user_version").fetchone()[0]
    if migrate(conn) != before or stored_hash(conn) != schema_hash():
        reapply(conn)
        conn.execute("INSERT INTO setting (key, value) VALUES ('schema_hash', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (schema_hash(),))
    return conn


def _uri_path(path):
    """Percent-encode what a SQLite file: URI treats as special (urllib.parse costs ~4 ms to import)."""
    return "".join(c if c.isalnum() or c in "/._-~" else "".join(f"%{b:02X}" for b in c.encode()) for c in str(path))


def _open_ro(path):
    """A read-only connection, or None if the file cannot be opened that way."""
    for mode in ("mode=ro", "immutable=1"):
        conn = sqlite3.connect(f"file:{_uri_path(path)}?{mode}", uri=True, factory=IndexConnection,
                               isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return conn
        except sqlite3.Error:
            conn.close()
    return None


def is_current(conn):
    """True when the schema version and the re-applied files match this code (nothing to migrate or re-apply)."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    return version == migrations()[-1][0] and stored_hash(conn) == schema_hash()


def open(path, write=False):
    """Connection for a command. Readers get a read-only one when the database exists and is current
    (so `search` and `status` never take a write lock and work on a read-only file); otherwise this
    migrates, which needs write access. write=True always returns init()'s writable connection."""
    path = Path(path)
    if not write and path.exists():
        conn = _open_ro(path)
        if conn is not None and is_current(conn):
            return conn
        if conn is not None:
            conn.close()
    return init(path)


def write_settings(conn, settings):
    """Upsert engine settings (from the config) that views read."""
    for key, value in settings.items():
        conn.execute("INSERT INTO setting (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
