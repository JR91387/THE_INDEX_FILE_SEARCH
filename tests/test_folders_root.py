# SPDX-License-Identifier: MIT
"""The sudo entry point of the folder scanner: fixed options file, options on stdin, no wildcard rule."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT

from theindex import collect, collectors, config

COLLECTOR = ROOT / "src/theindex/collectors/folders.py"
WRAPPER = ROOT / "contrib/folders_root.py"
INSTALLER = ROOT / "contrib/install_folder_scanner.sh"


class TestFoldersRoot(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.lib = self.tmp / "lib"
        self.lib.mkdir()
        shutil.copy(COLLECTOR, self.lib / "folders.py")
        shutil.copy(WRAPPER, self.lib / "folders_root.py")
        self.tree = self.tmp / "data"
        (self.tree / "app").mkdir(parents=True)
        (self.tree / "app" / "big.bin").write_bytes(b"x" * 100)
        self.other = self.tmp / "other"
        (self.other / "secret").mkdir(parents=True)
        self.conf = self.tmp / "folders.json"

    def run_root(self, options, conf=True):
        if conf:
            self.conf.write_text(json.dumps({"roots": [str(self.tree)], "exclude": [], "depth": 1}))
        env = {**os.environ, "THE_INDEX_SCANNER_CONF": str(self.conf), "SUDO_USER": "alice"}
        done = subprocess.run([sys.executable, "-I", str(self.lib / "folders_root.py")], input=json.dumps(options),
                              capture_output=True, text=True, env=env, timeout=60, check=False)
        return json.loads(done.stdout)

    def test_caller_roots_exclude_and_depth_are_ignored(self):
        out = self.run_root({"roots": [str(self.other)], "exclude": [str(self.tree / "app")], "depth": 5,
                             "slots": 1})
        self.assertEqual(out["status"], "ok")
        keys = {i["key"] for i in out["items"]}
        self.assertEqual(keys, {str(self.tree), str(self.tree / "app")})
        self.assertEqual(out["coverage"], [str(self.tree) + "/"])

    def test_biggest_file_is_a_bare_name_when_privileged(self):
        out = self.run_root({"slots": 1})
        app = next(i for i in out["items"] if i["key"].endswith("/app"))
        self.assertEqual(app["metrics"]["biggest_file"], "big.bin")

    def test_plain_scan_still_reports_the_full_path(self):
        done = subprocess.run([sys.executable, "-I", str(COLLECTOR), json.dumps(
            {"roots": [str(self.tree)], "depth": 1, "slots": 1})], capture_output=True, text=True, check=False)
        app = next(i for i in json.loads(done.stdout)["items"] if i["key"].endswith("/app"))
        self.assertEqual(app["metrics"]["biggest_file"], str(self.tree / "app" / "big.bin"))

    def test_missing_options_file_fails_closed(self):
        out = self.run_root({"roots": [str(self.other)]}, conf=False)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["items"], [])

    def test_bad_roots_in_file_fail(self):
        self.conf.write_text(json.dumps({"roots": ["relative"]}))
        self.assertEqual(self.run_root({}, conf=False)["status"], "failed")

    def test_launcher_has_fixed_argv_and_options_go_on_stdin(self):
        cfg = config.Config(folders={"sudo": True})
        cmd = collect.launcher(cfg, "folders")
        self.assertEqual(cmd[:3], ["sudo", "-n", "/usr/bin/python3"])
        self.assertTrue(cmd[-1].endswith("folders_root.py"))
        echo = "import sys, json; print(json.dumps({'status': 'ok', 'items': [], 'echo': sys.stdin.read()}))"
        payload = collectors.run_script(Path("x.py"), ['{"a": 1}'], [sys.executable, "-c", echo])
        self.assertEqual(payload["echo"], '{"a": 1}')

    def test_sudoers_rule_has_no_wildcard(self):
        rule = next(line for line in INSTALLER.read_text().splitlines() if "NOPASSWD" in line and "printf" in line)
        self.assertNotIn("*", rule)
        self.assertIn("folders_root.py", rule)
