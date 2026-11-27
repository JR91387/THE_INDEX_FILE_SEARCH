# SPDX-License-Identifier: MIT
"""Schema 006: dir/file tables, never-delete guards, trigger-kept name/title search, file views."""
import sqlite3

from helpers import DbCase


class FilesSchemaTest(DbCase):
    def setUp(self):
        super().setUp()
        c = self.conn
        c.execute("INSERT INTO device (name, reach_id, status_id) VALUES ('host-a', ?, ?)",
                  (c.ref_id("ref_reach", "local"), c.ref_id("ref_device_status", "active")))
        self.dev = self.one("SELECT id FROM device WHERE name = 'host-a'")
        self.run = self.new_run()
        self.root = self.add_dir("/srv/data", None)

    def new_run(self):
        cur = self.conn.execute(
            "INSERT INTO scan_run (device_id, collector_id, started_at, status_id) VALUES (?,?,?,?)",
            (self.dev, self.conn.ref_id("ref_collector", "filetree"), "2026-01-01T00:00:00Z",
             self.conn.ref_id("ref_run_status", "ok")))
        return cur.lastrowid

    def add_dir(self, path, parent):
        cur = self.conn.execute(
            "INSERT INTO dir (device_id, path_key, path, parent_id, depth, first_seen_run, seen_run) "
            "VALUES (?,?,?,?,?,?,?)", (self.dev, path, path, parent, path.count("/"), self.run, self.run))
        return cur.lastrowid

    def add_file(self, name, title=None, ext=".pdf"):
        cur = self.conn.execute(
            "INSERT INTO file (device_id, dir_id, name, ext, title, first_seen_run, seen_run) "
            "VALUES (?,?,?,?,?,?,?)", (self.dev, self.root, name, ext, title, self.run, self.run))
        return cur.lastrowid

    def hits(self, word):
        return [r[0] for r in self.conn.execute(
            "SELECT rowid FROM file_fts WHERE file_fts MATCH ?", (f'"{word}"*',))]

    def test_seeds_present(self):
        self.assertGreaterEqual(self.one("SELECT count(*) FROM ref_agent_marker WHERE code='AGENTS.md'"), 1)
        self.assertEqual(self.one("SELECT definition FROM ref_title_type WHERE code='.pdf'"), "pdf")
        self.assertEqual(self.one("SELECT count(*) FROM ref_reach WHERE code='offline'"), 1)

    def test_delete_blocked(self):
        fid = self.add_file("a.pdf")
        for sql in ("DELETE FROM file WHERE id = ?", "DELETE FROM dir WHERE id = ?"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(sql, (fid if "file" in sql else self.root,))

    def test_fts_mid_name_word_and_title(self):
        fid = self.add_file("tax-return_2024.final.pdf", title="Annual Report")
        self.assertEqual(self.hits("return"), [fid])
        self.assertEqual(self.hits("2024"), [fid])
        self.assertEqual(self.hits("annual"), [fid])

    def test_fts_follows_update_and_retire(self):
        fid = self.add_file("notes.md", ext=".md")
        self.conn.execute("UPDATE file SET title = 'Garden plan' WHERE id = ?", (fid,))
        self.assertEqual(self.hits("garden"), [fid])
        self.conn.execute("UPDATE file SET retired_run = ? WHERE id = ?", (self.run, fid))
        self.assertEqual(self.hits("garden"), [])
        self.conn.execute("UPDATE file SET retired_run = NULL WHERE id = ?", (fid,))
        self.assertEqual(self.hits("notes"), [fid])

    def test_views(self):
        child = self.add_dir("/srv/data/proj", self.root)
        self.conn.execute("UPDATE dir SET agent_files = '[\"AGENTS.md\"]', size_total = 25 WHERE id = ?", (child,))
        self.conn.execute("UPDATE dir SET size_total = 100 WHERE id = ?", (self.root,))
        self.add_file("a.pdf", title="T")
        self.assertEqual(self.one("SELECT path FROM v_projects"), "/srv/data/proj")
        self.assertEqual(self.one("SELECT pct_of_parent FROM v_tree WHERE id = ?", (child,)), 25.0)
        self.assertEqual(self.one("SELECT path FROM v_documents"), "/srv/data/a.pdf")

    def test_baseline_files_are_not_events(self):
        self.add_file("old.pdf")
        self.conn.execute("UPDATE file SET seen_run = ?", (self.new_run(),))
        self.assertEqual(self.one("SELECT count(*) FROM v_file_events"), 0)
        self.run = self.new_run()
        self.add_file("new.pdf")
        self.assertEqual(self.one("SELECT name FROM v_file_events WHERE action = 'new'"), "new.pdf")

    def test_projects_skip_home_and_hidden_folders(self):
        for path in ("/home/alice", "/home/alice/.claude", "/srv/data/app/.claude/worktrees/x",
                     "C:\\Users\\alice", "/srv/data/app"):
            did = self.add_dir(path, None)
            self.conn.execute("UPDATE dir SET agent_files = '[\"CLAUDE.md\"]' WHERE id = ?", (did,))
        self.assertEqual([r[0] for r in self.conn.execute("SELECT path FROM v_projects")], ["/srv/data/app"])
