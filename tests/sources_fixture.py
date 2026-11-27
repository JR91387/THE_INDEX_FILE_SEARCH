# SPDX-License-Identifier: MIT
"""Fixtures for the native-source tests: a temp tree and fake plocate/mdfind/mdls/es scripts first on PATH."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from helpers import DbCase

SCRIPT = Path(__file__).resolve().parent.parent / "src/theindex/collectors/sources.py"


def fake_tool(directory, name, body):
    path = Path(directory) / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path


def nul_list(paths, code=0):
    return "printf '%s\\0' " + " ".join(shlex.quote(str(p)) for p in paths) + f"\nexit {code}"


class NativeCase(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.root = self.tmp / "data"
        for rel, size in (("docs/a.md", 100), ("docs/sub/b.txt", 10), ("top.txt", 5), ("AGENTS.md", 7),
                          ("node_modules/pkg/i.js", 7), ("node_modules/j.js", 3), ("docs/a.pdf", 20)):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_bytes(b"x" * size)
        self.db_file = self.tmp / "locate.db"
        self.db_file.write_bytes(b"db")
        env = {"PATH": str(self.bin), "THE_INDEX_LOCATE_DB": str(self.db_file)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def listing(self, only=None):
        """Every path below the root (dirs too, as a real locate prints them), or just `only`."""
        return [self.root, *(only or sorted(self.root.rglob("*")))]

    def fake_plocate(self, paths=None, code=0):
        fake_tool(self.bin, "plocate", nul_list(paths or self.listing(), code))

    def stale(self):
        old = time.time() - 3 * 86400
        os.utime(self.db_file, (old, old))

    def run_sources(self, **opts):
        opts = {"roots": [str(self.root)], "cache_markers": ["node_modules"], "agent_markers": ["AGENTS.md"], **opts}
        proc = subprocess.run([sys.executable, "-I", str(SCRIPT), json.dumps(opts)], capture_output=True, text=True,
                              timeout=60, check=True)
        return [json.loads(line) for line in proc.stdout.splitlines()]
