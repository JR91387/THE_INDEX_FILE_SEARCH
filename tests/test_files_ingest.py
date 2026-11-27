# SPDX-License-Identifier: MIT
"""filetree end to end on a temp tree: stream ingest, skip carry, retire/revive, rollups, titles worklist."""
import json
import os
import tempfile
from pathlib import Path

from helpers import DbCase

from theindex import config, files_ingest, files_run


class FilesIngestTest(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "data"
        (self.root / "docs" / "deep").mkdir(parents=True)
        (self.root / "node_modules" / "pkg").mkdir(parents=True)
        (self.root / "docs" / "plan.md").write_text("---\ntitle: Garden plan\n---\nbody\n")
        (self.root / "docs" / "deep" / "notes.txt").write_bytes(b"n" * 40)
        (self.root / "top.bin").write_bytes(b"t" * 100)
        (self.root / "node_modules" / "pkg" / "i.js").write_bytes(b"j" * 7)
        (self.root / "AGENTS.md").write_text("# Agents\n")
        self.cfg = config.Config(device_name="host-a")
        self.cfg.filetree = {"roots": [str(self.root)]}
        self.cfg.sources = {"native": "off"}          # these tests are about the walk, whatever tools the host has

    def scan(self, full=None):
        return files_run.run(self.conn, self.cfg, full=full)

    def active(self, table):
        return self.one(f"SELECT count(*) FROM {table} WHERE retired_run IS NULL")

    def test_first_run_rows_rollups_and_title(self):
        result = self.scan()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.active("file"), 4)           # plan.md, notes.txt, top.bin, AGENTS.md
        root_total = self.one("SELECT size_total FROM dir WHERE path = ?", (str(self.root),))
        on_disk = sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())
        self.assertEqual(root_total, on_disk)
        self.assertEqual(self.one("SELECT title FROM file WHERE name = 'plan.md'"), "Garden plan")
        self.assertEqual(self.one("SELECT is_cache FROM dir WHERE path LIKE '%node_modules'"), 1)
        self.assertEqual(self.one("SELECT path FROM v_projects"), str(self.root))
        self.assertEqual(self.one("SELECT count(*) FROM v_file_events"), 0)   # baseline

    def test_second_run_carries_skipped_dirs_and_reads_no_titles(self):
        self.scan()
        again = self.scan()
        self.assertEqual(again["status"], "ok")
        self.assertEqual(again["titles"], 0)
        self.assertEqual(self.active("file"), 4)
        self.assertEqual(self.active("dir"), 4)

    def test_removed_file_retires_and_comes_back(self):
        self.scan()
        doc = self.root / "docs" / "plan.md"
        text = doc.read_text()
        doc.unlink()
        self.scan()
        self.assertIsNotNone(self.one("SELECT retired_run FROM file WHERE name = 'plan.md'"))
        self.assertEqual(self.one("SELECT action FROM v_file_events"), "gone")
        doc.write_text(text)
        self.scan()
        self.assertIsNone(self.one("SELECT retired_run FROM file WHERE name = 'plan.md'"))

    def test_removed_dir_retires_its_files(self):
        self.scan()
        for f in (self.root / "docs" / "deep").iterdir():
            f.unlink()
        (self.root / "docs" / "deep").rmdir()
        self.scan()
        self.assertIsNotNone(self.one("SELECT retired_run FROM dir WHERE path LIKE '%deep'"))
        self.assertIsNotNone(self.one("SELECT retired_run FROM file WHERE name = 'notes.txt'"))

    def test_new_document_is_an_event_and_title_change_rereads(self):
        self.scan()
        doc = self.root / "docs" / "report.md"
        doc.write_text("# First title\n")
        self.scan()
        self.assertEqual(self.one("SELECT name FROM v_file_events WHERE action = 'new'"), "report.md")
        doc.write_text("# Second title, longer\n")
        os.utime(self.root / "docs")      # an edit in place does not touch the dir: force a full listing instead
        self.scan(full=True)
        self.assertEqual(self.one("SELECT title FROM file WHERE name = 'report.md'"), "Second title, longer")
        self.assertEqual(self.one("SELECT count(*) FROM v_file_events WHERE action = 'retitled'"), 1)

    def test_stream_without_trailer_is_partial_and_retires_nothing(self):
        self.scan()
        r = str(self.root)
        lines = [json.dumps({"t": "header", "roots": [r]}), json.dumps({"t": "dir", "key": r, "path": r, "parent": None})]
        result = files_ingest.ingest_stream(self.conn, lines, "host-a")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.active("file"), 4)

    def stored(self, name):
        raw = self.one("SELECT meta FROM file WHERE name = ?", (name,))
        return raw if raw is None else json.loads(raw)

    def post(self):
        (self.root / "docs" / "post.md").write_text("---\ntitle: Post\nauthor: Alice\ntags: [garden, tax]\n---\nbody\n")

    def test_meta_stored_end_to_end_and_empty_read_is_marked(self):
        self.post()
        self.scan()
        self.assertEqual(self.stored("post.md"), {"author": "Alice", "tags": ["garden", "tax"]})
        self.assertEqual(self.stored("plan.md"), {})
        self.assertIsNone(self.stored("notes.txt"))                 # not a document type: never read

    def test_old_rows_are_reread_once_and_keep_their_title(self):
        self.post()
        self.scan()
        self.conn.execute("UPDATE file SET meta = NULL, title = 'Native title', title_src = 'native'")
        self.assertEqual(self.scan()["titles"], 3)                  # the three .md files, by meta IS NULL
        self.assertEqual(self.stored("post.md")["author"], "Alice")
        self.assertEqual(self.one("SELECT title FROM file WHERE name = 'post.md'"), "Native title")
        self.assertEqual(self.scan()["titles"], 0)                  # '{}' and JSON both count as read

    def test_meta_off_stores_nothing_and_does_not_reread(self):
        self.post()
        self.cfg.filetree["meta"] = False
        self.scan()
        self.assertIsNone(self.stored("post.md"))
        self.assertEqual(self.scan()["titles"], 0)

    def test_meta_inside_the_stream(self):
        r = str(self.root)
        rec = {"t": "file", "dir": r, "size": 3, "mtime_ns": 1, "title_src": "pdf_info", "title_sig": "3:1"}
        lines = [json.dumps({"t": "header", "collector": "catalog", "roots": [r]}),
                 json.dumps({"t": "dir", "key": r, "path": r, "parent": None, "size": 6, "files": 2}),
                 json.dumps({**rec, "name": "a.pdf", "title": "A", "meta": {"tags": ["x"]}}),
                 json.dumps({**rec, "name": "b.pdf", "title": "B"}),
                 json.dumps({"t": "trailer", "status": "ok"})]
        files_ingest.ingest_stream(self.conn, lines, "host-b")
        self.assertEqual(self.stored("a.pdf"), {"tags": ["x"]})
        self.assertIsNone(self.stored("b.pdf"))                     # no meta key: unknown, not "nothing found"
        files_ingest.ingest_stream(self.conn, [*lines[:2], lines[2].replace('"x"', '"y"'), *lines[3:]], "host-b")
        self.assertEqual(self.stored("a.pdf"), {"tags": ["x"]})     # same sig: kept

    def test_titles_off(self):
        self.cfg.filetree["titles"] = False
        self.scan()
        self.assertIsNone(self.one("SELECT title FROM file WHERE name = 'plan.md'"))

    def test_titles_inside_the_stream_and_catalog_collector(self):
        r = str(self.root)
        lines = [json.dumps({"t": "header", "collector": "catalog", "roots": [r]}),
                 json.dumps({"t": "dir", "key": r, "path": r, "parent": None, "size": 3, "files": 1}),
                 json.dumps({"t": "file", "dir": r, "name": "a.pdf", "size": 3, "mtime_ns": 1,
                             "title": "Sent title", "title_src": "pdf_info", "title_sig": "3:1"}),
                 json.dumps({"t": "trailer", "status": "ok"})]
        result = files_ingest.ingest_stream(self.conn, lines, "host-b")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.one("SELECT title FROM file WHERE name = 'a.pdf'"), "Sent title")
        self.assertEqual(self.one("SELECT c.code FROM scan_run r JOIN ref_collector c ON c.id = r.collector_id "
                                  "WHERE r.id = ?", (result["run_id"],)), "catalog")
