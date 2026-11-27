# SPDX-License-Identifier: MIT
"""Schema 007: file.meta JSON and the three-column file_fts (name, title, meta)."""
import json
import tempfile
import unittest
from pathlib import Path

from helpers import DbCase

from theindex import db


def seed(c):
    """One device, one ok run, one directory (id 1); returns the run id."""
    c.execute("INSERT INTO device (name, reach_id, status_id) VALUES ('host-a', ?, ?)",
              (c.ref_id("ref_reach", "local"), c.ref_id("ref_device_status", "active")))
    run = c.execute("INSERT INTO scan_run (device_id, collector_id, started_at, status_id) VALUES (1,?,?,?)",
                    (c.ref_id("ref_collector", "filetree"), "2026-01-01T00:00:00Z",
                     c.ref_id("ref_run_status", "ok"))).lastrowid
    c.execute("INSERT INTO dir (device_id, path_key, path, depth, first_seen_run, seen_run) "
              "VALUES (1,'/srv/data','/srv/data',2,?,?)", (run, run))
    return run


def add_file(c, run, name, title=None):
    return c.execute("INSERT INTO file (device_id, dir_id, name, ext, title, first_seen_run, seen_run) "
                     "VALUES (1,1,?,'.pdf',?,?,?)", (name, title, run, run)).lastrowid


def hits(c, word):
    return [r[0] for r in c.execute("SELECT rowid FROM file_fts WHERE file_fts MATCH ?", (f'"{word}"*',))]


class MetaSchemaTest(DbCase):
    def setUp(self):
        super().setUp()
        self.run = seed(self.conn)

    def add(self, name, title=None, meta=None):
        fid = add_file(self.conn, self.run, name, title)
        if meta is not None:
            self.set_meta(fid, meta)
        return fid

    def set_meta(self, fid, meta):
        self.conn.execute("UPDATE file SET meta = ? WHERE id = ?", (json.dumps(meta), fid))

    def test_fts_finds_tag_author_description(self):
        fid = self.add("scan0001.pdf", "Invoice", {"author": "Zelda Quimby", "tags": ["taxes", "q3 filing"],
                                                   "description": "Gardening receipts"})
        for word in ("taxes", "filing", "quimby", "gardening", "invoice", "scan0001"):
            self.assertEqual(hits(self.conn, word), [fid], word)

    def test_json_keys_date_and_lang_are_not_indexed(self):
        fid = self.add("a.pdf", meta={"author": "Al", "date": "2024-05-03", "lang": "en"})
        self.assertEqual((hits(self.conn, "author"), hits(self.conn, "lang"), hits(self.conn, "2024")), ([], [], []))
        self.assertEqual(hits(self.conn, "al"), [fid])

    def test_meta_follows_update_and_retire(self):
        fid = self.add("a.pdf", meta={"tags": ["alpha"]})
        self.set_meta(fid, {"tags": ["beta"]})
        self.assertEqual((hits(self.conn, "alpha"), hits(self.conn, "beta")), ([], [fid]))
        self.conn.execute("UPDATE file SET retired_run = ? WHERE id = ?", (self.run, fid))
        self.assertEqual(hits(self.conn, "beta"), [])
        self.conn.execute("UPDATE file SET retired_run = NULL WHERE id = ?", (fid,))
        self.assertEqual(hits(self.conn, "beta"), [fid])

    def test_null_and_empty_meta_keep_name_and_title_searchable(self):
        fid = self.add("a.pdf", "Plain")
        self.assertEqual(hits(self.conn, "plain"), [fid])
        self.set_meta(fid, {})
        self.assertEqual((hits(self.conn, "plain"), hits(self.conn, "a")), ([fid], [fid]))


class UpgradeFrom006(unittest.TestCase):
    def test_existing_titles_survive_and_meta_is_added(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "old.db"
        old = db.connect(path)
        for number, sql in db.migrations():
            if number <= 6:
                old.executescript(f"BEGIN;\n{sql.read_text()}\nPRAGMA user_version = {number};\nCOMMIT;")
        db.reapply(old)
        add_file(old, seed(old), "old.pdf", "Legacy title")
        old.close()
        conn = db.init(path)
        self.addCleanup(conn.close)
        self.assertIsNone(conn.execute("SELECT meta FROM file").fetchone()[0])
        self.assertEqual(len(hits(conn, "legacy")), 1)
        self.assertEqual([r[1] for r in conn.execute("PRAGMA table_info(file_fts)")], ["name", "title", "meta"])
        conn.execute("UPDATE file SET meta = '{\"tags\":[\"newtag\"]}'")
        self.assertEqual(len(hits(conn, "newtag")), 1)
        db.init(path).close()
