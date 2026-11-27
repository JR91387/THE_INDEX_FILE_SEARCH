# SPDX-License-Identifier: MIT
"""Per-collector timeouts: a hung collector (and its children) is killed and becomes a failed payload."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (puts src/ on the path)

from theindex import collectors

HANG = ("import os, subprocess, sys, time\n"
        "p = subprocess.Popen(['sleep', '60'])\n"
        "open(sys.argv[1], 'w').write(str(p.pid))\n"
        "time.sleep(60)\n")


def alive(pid):
    """Running (a zombie waiting to be reaped counts as gone)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state != "Z"


class TestTimeouts(unittest.TestCase):
    def test_table(self):
        self.assertEqual([collectors.timeout_for(n) for n in ("jobs", "containers", "filesystems", "backups")],
                         [60, 120, 60, 600])
        self.assertEqual(collectors.timeout_for("folders", ['{"budget_s": 100}']), 400)
        self.assertEqual(collectors.timeout_for("folders", ["not json"]), 2100)
        self.assertEqual(collectors.timeout_for("folders"), 2100)

    def test_hang_is_killed_with_its_children(self):
        pidfile = Path(tempfile.mkdtemp()) / "pid"
        started = time.monotonic()
        out = collectors.run_script(Path("hang.py"), [str(pidfile)], [sys.executable, "-c", HANG, str(pidfile)], 1)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(out["status"], "failed")
        self.assertIn("timed out", out["errors"][0])
        child = int(pidfile.read_text())
        for _ in range(50):
            if not alive(child):
                break
            time.sleep(0.1)
        self.assertFalse(alive(child))

    def test_kill_refused_is_not_fatal(self):
        with mock.patch.object(collectors.os, "killpg", side_effect=PermissionError("sudo")):
            out = collectors.run_script(Path("hang.py"), [], [sys.executable, "-c", "import time; time.sleep(60)"], 1)
        self.assertEqual(out["status"], "failed")

    def test_missing_program_is_a_failed_payload(self):
        out = collectors.run_script(Path("x.py"), [], ["/nonexistent/program"], 5)
        self.assertEqual(out["status"], "failed")

    def test_normal_run_still_parses(self):
        out = collectors.run_script(Path("ok.py"), [], [sys.executable, "-c", "print('{\"status\": \"ok\"}')"], 30)
        self.assertEqual(json.loads(json.dumps(out)), {"status": "ok"})
