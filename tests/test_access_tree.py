# SPDX-License-Identifier: MIT
"""Scan the awkward tree (tests/access_tree.py): the run stays ok, every case is listed or not as it says, and
documents that work get their titles while broken ones get none."""
import tempfile
from pathlib import Path

import access_tree
from helpers import DbCase

from theindex import config, files_run


class AccessTreeTest(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "tree"
        self.addCleanup(access_tree.unlock, self.root)
        self.cases = access_tree.build(self.root)
        self.cfg = config.Config(device_name="host-a")
        self.cfg.filetree = {"roots": [str(self.root)]}
        self.cfg.sources = {"native": "off"}

    def stored(self):
        files = {str(Path(r[0]).relative_to(self.root)): r[1] for r in self.conn.execute("SELECT path, title FROM v_files")}
        dirs = {str(Path(r[0]).relative_to(self.root)) for r in self.conn.execute("SELECT path FROM v_dirs")
                if Path(r[0]) != self.root}
        return files, dirs

    def test_every_case(self):
        self.assertEqual(files_run.run(self.conn, self.cfg)["status"], "ok")
        files, dirs = self.stored()
        for case in self.cases:
            with self.subTest(case.rel):
                listed = case.rel in files or case.rel in dirs
                self.assertEqual(listed, case.want.listed)
                if case.rel in files and case.want.title is not access_tree.ANY:
                    self.assertEqual(files[case.rel], case.want.title)

    def test_rescan_changes_nothing(self):
        files_run.run(self.conn, self.cfg)
        before = self.stored()
        self.assertEqual(files_run.run(self.conn, self.cfg)["status"], "ok")
        self.assertEqual(self.stored(), before)
        self.assertEqual(self.one("SELECT count(*) FROM v_file_events WHERE action = 'gone'"), 0)
