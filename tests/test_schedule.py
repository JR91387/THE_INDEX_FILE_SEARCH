# SPDX-License-Identifier: MIT
"""schedule: unit files, idempotence, remove, print, cron fallback. Fake systemctl/loginctl on PATH; temp XDG dir."""
import os
import stat
import sys
from unittest import mock

from test_cli_errors import CliCase, run

STUB = '#!/bin/sh\necho "$0 $@" >> "{log}"\n{body}\n'


class ScheduleCase(CliCase):
    def setUp(self):
        super().setUp()
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.log = self.dir / "calls.log"
        self.xdg = self.dir / "xdg"
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.xdg), "PATH": f"{self.bin}:/usr/bin:/bin"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def stub(self, name, body="exit 0"):
        path = self.bin / name
        path.write_text(STUB.format(log=self.log, body=body))
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def units(self):
        return self.xdg / "systemd" / "user"


class TestSchedule(ScheduleCase):
    def test_install_writes_units_and_enables(self):
        self.stub("systemctl")
        self.stub("loginctl", "echo Linger=no")
        code, out, _ = run("--db", self.db, "schedule")
        self.assertEqual(code, 0)
        service = (self.units() / "the-index.service").read_text()
        timer = (self.units() / "the-index.timer").read_text()
        for needle in ("Type=oneshot", f"ExecStart={sys.executable} -m theindex --db {self.db} scan", "Nice=19",
                       "IOSchedulingClass=idle", "CPUWeight=10"):
            self.assertIn(needle, service)
        for needle in ("OnCalendar=daily", "RandomizedDelaySec=1h", "Persistent=true", "WantedBy=timers.target"):
            self.assertIn(needle, timer)
        joined = "\n".join(self.calls())
        self.assertIn("--user daemon-reload", joined)
        self.assertIn("--user enable --now the-index.timer", joined)
        self.assertIn("enable-linger", out)

    def test_idempotent(self):
        self.stub("systemctl")
        self.stub("loginctl", "echo Linger=yes")
        run("schedule")
        first = (self.units() / "the-index.service").read_text()
        code, out, _ = run("schedule")
        self.assertEqual(code, 0)
        self.assertEqual(first, (self.units() / "the-index.service").read_text())
        self.assertNotIn("enable-linger", out)

    def test_remove(self):
        self.stub("systemctl")
        run("schedule")
        code, out, _ = run("schedule", "--remove")
        self.assertEqual((code, out.strip()), (0, "schedule removed"))
        self.assertEqual(list(self.units().glob("the-index.*")), [])
        self.assertIn("--user disable --now the-index.timer", "\n".join(self.calls()))
        self.assertEqual(run("schedule", "--remove")[1].strip(), "nothing scheduled")

    def test_print_changes_nothing(self):
        self.stub("systemctl")
        code, out, _ = run("schedule", "--print")
        self.assertEqual(code, 0)
        self.assertIn("OnCalendar=daily", out)
        self.assertFalse(self.xdg.exists())
        self.assertEqual(self.calls(), [])

    def test_no_user_systemd_prints_cron_line(self):
        self.stub("systemctl", "exit 1")
        code, out, _ = run("schedule")
        self.assertEqual(code, 0)
        self.assertIn("crontab", out)
        self.assertIn("-m theindex scan", out)
        self.assertFalse(self.xdg.exists())
