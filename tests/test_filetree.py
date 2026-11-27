# SPDX-License-Identifier: MIT
"""filetree collector, run as a subprocess on a temp tree (no real hosts or paths)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_collectors import load

SCRIPT = Path(__file__).resolve().parent.parent / "src/theindex/collectors/filetree.py"
sys.path.insert(0, str(SCRIPT.parent))
walk = load("filetree_walk")
net = load("filetree_net")


class FiletreeCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "data"
        (self.root / "docs" / "sub").mkdir(parents=True)
        (self.root / "docs" / "a.md").write_bytes(b"x" * 100)
        (self.root / "docs" / "sub" / "b.txt").write_bytes(b"y" * 10)
        (self.root / "top.txt").write_bytes(b"z" * 5)

    def run_ft(self, state=None, **opts):
        opts = {"roots": [str(self.root)], **opts}
        cmd = [sys.executable, "-I", str(SCRIPT), json.dumps(opts)]
        if state:
            cmd += ["--state", str(state)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
        return [json.loads(line) for line in proc.stdout.splitlines()]

    def state_from(self, records):
        path = self.tmp / "state.tsv"
        rows = [f"{r['key']}\t{r['mtime_ns']}\t{r['ctime_ns']}" for r in records if r["t"] == "dir"]
        path.write_text("\n".join(rows) + "\n")
        return path

    @staticmethod
    def of(records, kind):
        return [r for r in records if r["t"] == kind]

    def dir_rec(self, records, rel=""):
        path = str(self.root / rel).rstrip("/")
        return next(r for r in records if r["t"] == "dir" and r["path"] == path)


class TestFullRun(FiletreeCase):
    def test_order_and_shape(self):
        recs = self.run_ft()
        self.assertEqual(recs[0]["t"], "header")
        self.assertEqual(recs[-1]["t"], "trailer")
        self.assertEqual(recs[-1]["status"], "ok")
        self.assertFalse(recs[0]["case_insensitive"])
        self.assertEqual(len(self.of(recs, "dir")), 3)
        self.assertEqual(len(self.of(recs, "file")), 3)
        self.assertEqual(recs[-1]["counts"], {"dirs": 3, "files": 3, "skips": 0, "gaps": 0})
        top = self.dir_rec(recs)
        self.assertEqual((top["size"], top["files"], top["parent"], top["cache"]), (5, 1, None, False))
        self.assertEqual(self.dir_rec(recs, "docs")["parent"], top["key"])
        f = next(r for r in self.of(recs, "file") if r["name"] == "a.md")
        self.assertEqual((f["size"], f["dir"]), (100, self.dir_rec(recs, "docs")["key"]))
        self.assertIn("inode", f)

    def test_dir_record_precedes_its_files(self):
        recs = self.run_ft()
        seen = set()
        for r in recs:
            if r["t"] == "dir":
                seen.add(r["key"])
            if r["t"] == "file":
                self.assertIn(r["dir"], seen)


class TestSkipUnchanged(FiletreeCase):
    def test_skip_but_descend_to_new_grandchild(self):
        state = self.state_from(self.run_ft())
        (self.root / "docs" / "sub" / "new").mkdir()
        (self.root / "docs" / "sub" / "new" / "c.txt").write_text("c")
        recs = self.run_ft(state)
        skipped = {r["path"] for r in self.of(recs, "skip")}
        self.assertIn(str(self.root), skipped)
        self.assertIn(str(self.root / "docs"), skipped)
        listed = {r["path"] for r in self.of(recs, "dir")}
        self.assertIn(str(self.root / "docs" / "sub" / "new"), listed)
        self.assertFalse([f for f in self.of(recs, "file") if f["name"] in ("a.md", "top.txt")])

    def test_touched_dir_is_listed_again(self):
        state = self.state_from(self.run_ft())
        (self.root / "docs" / "added.txt").write_text("new")
        recs = self.run_ft(state)
        self.assertIn(str(self.root / "docs"), {r["path"] for r in self.of(recs, "dir")})
        self.assertIn(str(self.root), {r["path"] for r in self.of(recs, "skip")})
        self.assertIn("added.txt", {f["name"] for f in self.of(recs, "file")})

    def test_full_lists_everything(self):
        state = self.state_from(self.run_ft())
        recs = self.run_ft(state, full=True)
        self.assertEqual(len(self.of(recs, "skip")), 0)
        self.assertEqual(len(self.of(recs, "dir")), 3)


class TestCacheAndAgents(FiletreeCase):
    def test_cache_dirs_give_totals_only(self):
        nm = self.root / "node_modules"
        (nm / "pkg").mkdir(parents=True)
        (nm / "pkg" / "i.js").write_bytes(b"1" * 30)
        (nm / "j.js").write_bytes(b"2" * 20)
        tagged = self.root / "tagged"
        (tagged / "deep").mkdir(parents=True)
        (tagged / "CACHEDIR.TAG").write_bytes(b"sig")
        (tagged / "deep" / "k.bin").write_bytes(b"3" * 7)
        recs = self.run_ft(cache_markers=["node_modules"])
        n = self.dir_rec(recs, "node_modules")
        self.assertEqual((n["cache"], n["size"], n["files"]), (True, 50, 2))
        t = self.dir_rec(recs, "tagged")
        self.assertEqual((t["cache"], t["size"], t["files"]), (True, 10, 2))
        self.assertFalse([r for r in recs if r["t"] == "dir" and r["path"].startswith(str(nm) + "/")])
        self.assertFalse([r for r in self.of(recs, "file") if r["name"] in ("i.js", "j.js", "k.bin")])
        again = self.run_ft(self.state_from(recs), cache_markers=["node_modules"])
        self.assertEqual({r["path"] for r in self.of(again, "skip")} >= {str(nm), str(tagged)}, True)
        full = self.run_ft(self.state_from(recs), cache_markers=["node_modules"], full=True)
        self.assertTrue(self.dir_rec(full, "node_modules")["cache"])

    def test_agent_markers(self):
        (self.root / "docs" / "CLAUDE.md").write_text("x")
        (self.root / "docs" / "AGENTS.md").write_text("x")
        (self.root / "proj" / ".github").mkdir(parents=True)
        (self.root / "proj" / ".github" / "copilot-instructions.md").write_text("x")
        (self.root / "other" / ".github").mkdir(parents=True)
        recs = self.run_ft(agent_markers=["CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md"])
        self.assertEqual(self.dir_rec(recs, "docs")["agents"], ["AGENTS.md", "CLAUDE.md"])
        self.assertEqual(self.dir_rec(recs, "proj")["agents"], [".github/copilot-instructions.md"])
        self.assertEqual(self.dir_rec(recs, "other")["agents"], [])

    def test_exclude_by_name_and_builtin(self):
        (self.root / "skipme").mkdir()
        (self.root / "lost+found").mkdir()
        recs = self.run_ft(exclude=["skipme"])
        paths = {r["path"] for r in self.of(recs, "dir")}
        self.assertNotIn(str(self.root / "skipme"), paths)
        self.assertNotIn(str(self.root / "lost+found"), paths)


class TestSafety(FiletreeCase):
    def test_symlink_loop(self):
        os.symlink(self.root, self.root / "docs" / "loop")
        os.symlink(self.root / "docs" / "a.md", self.root / "link.md")
        recs = self.run_ft()
        self.assertEqual(recs[-1]["status"], "ok")
        self.assertEqual(len(self.of(recs, "dir")), 3)
        self.assertNotIn("link.md", {f["name"] for f in self.of(recs, "file")})

    @unittest.skipIf(os.geteuid() == 0, "root can read everything")
    def test_unreadable_dir_one_gap(self):
        locked = self.root / "locked"
        locked.mkdir()
        (locked / "s1").write_text("x")
        (locked / "s2").write_text("x")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        recs = self.run_ft()
        gaps = self.of(recs, "gap")
        self.assertEqual([(g["kind"], g["target"]) for g in gaps], [("denied", str(locked))])
        self.assertEqual(recs[-1]["counts"]["gaps"], 1)

    def test_budget_zero(self):
        recs = self.run_ft(budget_s=0)
        self.assertEqual(recs[-1]["status"], "partial")
        gaps = self.of(recs, "gap")
        self.assertEqual([(g["kind"], g["target"]) for g in gaps], [("budget", str(self.root))])
        self.assertEqual([s["path"] for s in self.of(recs, "skip")], [str(self.root)])
        self.assertEqual(self.of(recs, "dir"), [])

    def test_bad_options_still_print_trailer(self):
        proc = subprocess.run([sys.executable, "-I", str(SCRIPT), "{not json"], capture_output=True, text=True,
                              timeout=60, check=True)
        recs = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual((recs[0]["t"], recs[-1]["t"], recs[-1]["status"]), ("header", "trailer", "partial"))


if __name__ == "__main__":
    unittest.main()
