# SPDX-License-Identifier: MIT
"""The single-file build: build the .pyz into a temp dir and run it with a temp cache (never the real one)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers  # puts src/ on the path

sys.path.insert(0, str(helpers.ROOT / "tools"))
import build_zipapp


class ZipappTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        cls.pyz = build_zipapp.build(base / "dist" / "the-index.pyz")
        cls.tree = base / "tree"
        (cls.tree / "sub").mkdir(parents=True)
        (cls.tree / "sub" / "zipprobe-notes.txt").write_text("hello\n")
        cls.config = base / "config" / "config.toml"
        cls.config.parent.mkdir()
        cls.config.write_text(f'[filetree]\nroots = ["{cls.tree.as_posix()}"]\ntitles = false\n')
        cls.db = base / "index.db"
        cls.env = {**os.environ, "XDG_CACHE_HOME": str(base / "cache"), "XDG_CONFIG_HOME": str(base / "config")}

    def run_pyz(self, *args):
        return subprocess.run([sys.executable, str(self.pyz), "--config", str(self.config), "--db", str(self.db),
                               *args], env=self.env, capture_output=True, text=True, timeout=300, check=False)

    def test_help(self):
        proc = subprocess.run([sys.executable, str(self.pyz), "--help"], env=self.env, capture_output=True,
                              text=True, timeout=300, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage:", proc.stdout)

    def test_describe_json(self):
        proc = self.run_pyz("describe", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["schema_version"], 1)

    def test_scan_then_find_from_zip(self):
        # Proves the SQL schema and the filetree collector script both load from the extracted copy.
        scan = self.run_pyz("scan", "--collector", "filetree", "--quiet")
        self.assertEqual(scan.returncode, 0, scan.stderr)
        found = self.run_pyz("find", "zipprobe", "--json")
        self.assertEqual(found.returncode, 0, found.stderr)
        names = [row["name"] for row in json.loads(found.stdout)["results"]]
        self.assertIn("zipprobe-notes.txt", names)


if __name__ == "__main__":
    unittest.main()
