# SPDX-License-Identifier: MIT
"""Folder scanner (on a temp tree) and how its output is ingested."""
import os
import tempfile
from pathlib import Path

from helpers import DbCase
from test_collectors import load

from theindex import collect, config, ingest

folders = load("folders")
HOST = "host-a"


class TreeCase(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "data"
        (self.root / "photos").mkdir(parents=True)
        (self.root / "photos" / "a.jpg").write_bytes(b"x" * 4000)
        (self.root / "app" / ".git").mkdir(parents=True)
        (self.root / "app" / "main.py").write_text("print()\n")
        (self.root / "empty").mkdir()
        (self.root / "photos" / "zero.jpg").write_bytes(b"")     # a 0-byte file first must not crash
        self.cfg = config.Config(folders={"roots": [str(self.root)], "depth": 1})

    def scan(self, measure_all=True):
        opts = {**folders.DEFAULTS, **collect.folder_options(self.conn, self.cfg, measure_all)}
        out = {"items": [], "gaps": [], "errors": [], "coverage": [], "coverage_except": []}
        tracked = folders.list_tracked(opts, out)
        out["_items"] = {p: folders.folder_item(p, st) for p, st in tracked.items()}
        folders.measure(tracked, opts, out)
        out["items"] = list(out.pop("_items").values())
        return {**out, "collector": "folders", "kinds": ["folder"], "status": "ok"}

    def item(self, payload, name):
        return next(i for i in payload["items"] if i["key"] == str(self.root / name))


class TestScanner(TreeCase):
    def test_primary_content_and_metrics(self):
        out = self.scan()
        self.assertEqual(self.item(out, "photos")["attrs"]["primary_content"], "photos")
        self.assertEqual(self.item(out, "app")["attrs"]["primary_content"], "code_repo")  # marker wins
        self.assertEqual(self.item(out, "empty")["attrs"]["primary_content"], "empty")
        self.assertEqual(self.item(out, "photos")["metrics"]["size_bytes"], 4000)

    def test_rotation_measures_only_this_slot(self):
        self.cfg.folders["slots"] = 1000
        out = self.scan(measure_all=False)
        measured = [i for i in out["items"] if i["metrics"]]
        self.assertLess(len(measured), 3)

    def test_unreadable_folder_is_a_gap_and_not_retired(self):
        ingest.ingest(self.conn, self.scan(), HOST)
        locked = self.root / "photos"
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        if os.access(locked, os.R_OK):
            self.skipTest("running as root")
        (self.root / "photos2").mkdir()
        out = self.scan()
        self.assertTrue(any(g["target"] == str(locked) for g in out["gaps"]))
        ingest.ingest(self.conn, out, HOST)
        self.assertEqual(self.one("SELECT count(*) FROM item WHERE retired_run IS NOT NULL"), 0)


class TestDefaultsAndBudget(TreeCase):
    def run_scan(self, **opts):
        return folders.scan({"roots": [str(self.root)], "depth": 1, "slots": 1, **opts})

    def test_builtin_excludes_merge_with_user_excludes(self):
        (self.root / "lost+found").mkdir()
        (self.root / "skipme").mkdir()
        keys = {i["key"] for i in self.run_scan(exclude=[str(self.root / "skipme")])["items"]}
        self.assertIn(str(self.root / "photos"), keys)
        self.assertFalse({str(self.root / "lost+found"), str(self.root / "skipme")} & keys)
        self.assertIn("/var/lib/docker", folders.SKIP)

    def test_budget_exceeded_is_a_gap_and_the_unit_carries(self):
        ingest.ingest(self.conn, self.scan(), HOST)
        out = self.run_scan(budget_s=-1)
        self.assertEqual(out["status"], "ok")
        self.assertTrue(any(g["reason"] == "budget exceeded" for g in out["gaps"]))
        self.assertTrue(all("primary_content" not in i["attrs"] and not i["metrics"] for i in out["items"]))
        result = ingest.ingest(self.conn, out, HOST)
        self.assertEqual(result["changes"], 0)
        self.assertEqual(self.one("SELECT primary_content FROM v_folders WHERE key LIKE '%photos'"), "photos")

    def test_generous_budget_measures(self):
        out = self.run_scan(budget_s=60)
        self.assertEqual(self.item(out, "photos")["metrics"]["size_bytes"], 4000)
        self.assertFalse([g for g in out["gaps"] if g["reason"] == "budget exceeded"])


class TestIngestFolders(TreeCase):
    def test_content_rows_and_carry(self):
        ingest.ingest(self.conn, self.scan(), HOST)
        self.assertEqual(self.one("SELECT count(*) FROM folder_content WHERE is_primary = 1"), 2)  # empty: no rows
        unmeasured = self.scan()
        for item in unmeasured["items"]:
            item["attrs"].pop("primary_content", None)
            item["metrics"], item["content"] = {}, None
        result = ingest.ingest(self.conn, unmeasured, HOST)
        self.assertEqual(result["changes"], 0)          # carried forward, so nothing looks modified
        self.assertEqual(self.one("SELECT primary_content FROM v_folders WHERE key LIKE '%photos'"), "photos")

    def test_content_flip_is_suspicious(self):
        ingest.ingest(self.conn, self.scan(), HOST)
        out = self.scan()
        self.item(out, "photos")["attrs"]["primary_content"] = "unknown"
        ingest.ingest(self.conn, out, HOST)
        self.assertEqual(self.one("SELECT class FROM v_change ORDER BY id DESC LIMIT 1"), "suspicious")

    def test_budget_s_reaches_the_scanner(self):
        self.cfg.folders["budget_s"] = 42
        self.assertEqual(collect.folder_options(self.conn, self.cfg)["budget_s"], 42)
