# SPDX-License-Identifier: MIT
"""Targeted filetree runs (what `watch` sends): only the listed dirs change, subtrees of vanished dirs retire,
totals stay right, the run is a `watch` run, and the full-walk mark."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import DbCase

from theindex import config, files_run, query, watch_flush

SCRIPT = Path(__file__).resolve().parent.parent / "src/theindex/collectors/filetree.py"


class TargetCase(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "data"
        for rel in ("a/deep/deeper", "b"):
            (self.root / rel).mkdir(parents=True)
        (self.root / "a" / "one.txt").write_bytes(b"1" * 10)
        (self.root / "a" / "deep" / "two.txt").write_bytes(b"2" * 20)
        (self.root / "a" / "deep" / "deeper" / "three.txt").write_bytes(b"3" * 30)
        (self.root / "b" / "four.txt").write_bytes(b"4" * 40)
        self.cfg = config.Config(device_name="host-a", db_path=self.path)
        self.cfg.filetree = {"roots": [str(self.root)], "titles": False}
        self.cfg.sources = {"native": "off"}
        files_run.run(self.conn, self.cfg, full=True)

    def flush(self, *rels):
        return watch_flush.flush(self.conn, self.cfg, {str(self.root / r).rstrip("/") for r in rels})

    def names(self, word):
        return [h["name"] for h in query.find(self.conn, {"words": [word]})["results"]]

    def active(self, rel):
        return self.one("SELECT count(*) FROM dir WHERE path = ? AND retired_run IS NULL",
                        (str(self.root / rel).rstrip("/"),))

    def total(self, rel=""):
        return self.one("SELECT size_total FROM dir WHERE path = ?", (str(self.root / rel).rstrip("/"),))


class TestTargetedIngest(TargetCase):
    def test_new_file_listed_dir_only(self):
        (self.root / "a" / "fresh.txt").write_bytes(b"f" * 5)
        (self.root / "b" / "four.txt").unlink()           # outside the listed dir: must stay
        result = self.flush("a")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.names("fresh"), ["fresh.txt"])
        self.assertEqual(self.names("four"), ["four.txt"])
        self.assertEqual(self.one("SELECT c.code FROM scan_run r JOIN ref_collector c ON c.id = r.collector_id "
                                  "WHERE r.id = ?", (result["run_id"],)), "watch")

    def test_missing_file_retired_and_totals(self):
        (self.root / "a" / "one.txt").unlink()
        self.flush("a")
        self.assertEqual(self.names("one"), [])
        self.assertEqual(self.total("a"), 50)
        self.assertEqual(self.total(), 90)

    def test_vanished_child_retires_subtree(self):
        shutil.rmtree(self.root / "a" / "deep")
        self.flush("a")
        self.assertEqual((self.active("a/deep"), self.active("a/deep/deeper")), (0, 0))
        self.assertEqual(self.names("three"), [])
        self.assertEqual(self.total(), 50)

    def test_gone_target_retires_subtree(self):
        shutil.rmtree(self.root / "a" / "deep")
        self.flush("a/deep")                                # parent not listed: the `gone` record does it
        self.assertEqual((self.active("a/deep"), self.active("a/deep/deeper")), (0, 0))
        self.assertEqual(self.active("a"), 1)
        self.assertEqual(self.names("one"), ["one.txt"])

    def test_new_nested_dirs_listed_and_known_children_skipped(self):
        (self.root / "a" / "new" / "inner").mkdir(parents=True)
        (self.root / "a" / "new" / "inner" / "nested.txt").write_bytes(b"n")
        (self.root / "a" / "deep" / "deeper" / "three.txt").unlink()     # in a known child: not listed now
        self.flush("a")
        self.assertEqual(self.names("nested"), ["nested.txt"])
        self.assertEqual(self.names("three"), ["three.txt"])
        parent = self.one("SELECT p.path FROM dir d JOIN dir p ON p.id = d.parent_id WHERE d.path = ?",
                          (str(self.root / "a" / "new" / "inner"),))
        self.assertEqual(parent, str(self.root / "a" / "new"))

    def test_root_target_keeps_tree(self):
        (self.root / "top.txt").write_bytes(b"t" * 3)
        self.flush("")
        self.assertEqual(self.names("top"), ["top.txt"])
        self.assertIsNone(self.one("SELECT parent_id FROM dir WHERE path = ?", (str(self.root),)))
        self.assertEqual(self.total(), 103)

    def test_watch_runs_do_not_count_toward_full_every(self):
        before = files_run.is_full(self.conn, "host-a", 2)
        for _ in range(3):
            self.flush("a")
        self.assertEqual(files_run.is_full(self.conn, "host-a", 2), before)

    def test_lock_held_skips(self):
        from theindex import scan
        (self.root / "a" / "late.txt").write_bytes(b"l")
        with scan.scan_lock(self.path) as taken:
            self.assertTrue(taken)
            self.assertIsNone(self.flush("a"))
        self.assertEqual(self.names("late"), [])


class TestFullMark(TargetCase):
    def test_mark_forces_full_and_full_run_clears(self):
        self.assertFalse(files_run.full_marked(self.conn))
        files_run.mark_full(self.conn, "watch: lost events")
        self.assertTrue(files_run.is_full(self.conn, "host-a", 365))
        files_run.run(self.conn, self.cfg)
        self.assertFalse(files_run.full_marked(self.conn))


class TestCollectorTargets(TargetCase):
    def run_ft(self, opts, state=""):
        path = Path(self.path).parent / "state.tsv"
        path.write_text(state)
        cmd = [sys.executable, "-I", str(SCRIPT), json.dumps({"roots": [str(self.root)], **opts}), "--state", str(path)]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout
        return [json.loads(line) for line in out.splitlines()]

    def test_header_targets_file_gone_and_skip(self):
        listing = Path(self.path).parent / "targets.txt"
        listing.write_text(f"{self.root / 'a'}\n{self.root / 'missing'}\n")
        deep = self.root / "a" / "deep"
        recs = self.run_ft({"targets_file": str(listing)}, f"{deep}\t1\t1\n")
        self.assertTrue(recs[0]["targeted"])
        kinds = {(r["t"], r.get("path")) for r in recs}
        self.assertIn(("dir", str(self.root / "a")), kinds)
        self.assertIn(("skip", str(deep)), kinds)
        self.assertIn(("gone", str(self.root / "missing")), kinds)
        self.assertNotIn(("dir", str(self.root / "b")), kinds)
        self.assertEqual(recs[-1]["status"], "ok")

    def test_untargeted_header_flag_false(self):
        self.assertFalse(self.run_ft({})[0]["targeted"])
