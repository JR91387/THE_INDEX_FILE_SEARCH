# SPDX-License-Identifier: MIT
import sqlite3

from helpers import DbCase, db


class TestSchema(DbCase):
    def test_user_version_matches_last_migration(self):
        self.assertEqual(self.one("PRAGMA user_version"), db.migrations()[-1][0])

    def test_reinit_is_idempotent(self):
        tables = [r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                  "AND name LIKE 'ref_%'")]
        before = {t: self.one(f"SELECT count(*) FROM {t}") for t in tables}
        self.conn.close()
        self.conn = db.init(self.path)
        self.assertEqual(before, {t: self.one(f"SELECT count(*) FROM {t}") for t in tables})

    def test_every_view_compiles(self):
        views = [r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='view'")]
        self.assertGreater(len(views), 10)
        for view in views:
            with self.subTest(view=view):
                self.conn.execute(f"SELECT * FROM {view} LIMIT 1").fetchall()

    def test_bad_foreign_key_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO device (name, reach_id, status_id) VALUES ('host-a', 9999, 9999)")

    def test_delete_is_blocked(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "never deletes"):
            self.conn.execute("DELETE FROM ref_health")

    def test_icons_loaded_and_linked(self):
        self.assertEqual(self.one("SELECT count(*) FROM ref_icon WHERE svg NOT LIKE '<svg%'"), 0)
        self.assertEqual(self.one("SELECT count(*) FROM v_ref_all WHERE tbl='change_class' AND icon IS NULL"), 0)

    def test_ref_lookup_by_code(self):
        self.assertIsInstance(self.conn.ref_id("ref_change_class", "suspicious"), int)
        with self.assertRaises(KeyError):
            self.conn.ref_id("ref_change_class", "nope")
        with self.assertRaises(ValueError):
            self.conn.ref_id("device; DROP TABLE x", "a")

    def test_search_finds_items(self):
        self.conn.execute("INSERT INTO purpose (path_glob, criticality_id, description) VALUES (?,?,?)",
                          ("/srv/photos*", self.conn.ref_id("ref_criticality", "irreplaceable"), "family photos"))
        db.rebuild_search(self.conn)
        self.assertEqual(self.one("SELECT count(*) FROM search_fts WHERE search_fts MATCH 'family'"), 1)
