# SPDX-License-Identifier: MIT
"""`schedule --watch` (systemd user service, LaunchAgent, logon task; print-only and mocked) and `[watch]` config."""
import contextlib
import io
import plistlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from unittest import mock

from test_cli_errors import run
from test_schedule import ScheduleCase

from theindex import config, config_inbox

OK = subprocess.CompletedProcess([], 0, "", "")
NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"


class Args:
    def __init__(self, role="hub", remove=False):
        self.role, self.config, self.db, self.print, self.remove, self.watch = role, None, None, False, remove, True


class TestLinuxWatchService(ScheduleCase):
    def test_install_writes_and_enables_service(self):
        self.stub("systemctl")
        self.stub("loginctl", "echo Linger=yes")
        code, out, _ = run("--db", self.db, "schedule", "--watch")
        self.assertEqual(code, 0)
        unit = (self.units() / "the-index-watch.service").read_text()
        for needle in ("Type=simple", f"ExecStart={sys.executable} -m theindex --db {self.db} watch",
                       "Restart=on-failure", "Nice=19", "IOSchedulingClass=idle", "WantedBy=default.target"):
            self.assertIn(needle, unit)
        self.assertIn("--user enable --now the-index-watch.service", "\n".join(self.calls()))
        self.assertTrue((self.units() / "the-index.timer").exists())
        self.assertIn("watching", out)

    def test_print_changes_nothing(self):
        code, out, _ = run("--db", self.db, "schedule", "--print", "--watch")
        self.assertEqual(code, 0)
        self.assertIn("the-index-watch.service", out)
        self.assertIn("Restart=on-failure", out)
        self.assertFalse(self.units().exists())

    def test_without_flag_no_service_and_remove_takes_it(self):
        self.stub("systemctl")
        self.stub("loginctl", "echo Linger=yes")
        run("--db", self.db, "schedule")
        self.assertFalse((self.units() / "the-index-watch.service").exists())
        run("--db", self.db, "schedule", "--watch")
        code, out, _ = run("--db", self.db, "schedule", "--remove")
        self.assertEqual(code, 0)
        self.assertFalse((self.units() / "the-index-watch.service").exists())
        self.assertIn("watch removed", out)

    def test_member_role_refused(self):
        self.stub("systemctl")
        code, _, err = run("--db", self.db, "schedule", "--role", "member", "--watch")
        self.assertEqual(code, 2)
        self.assertIn("role hub", err)


class TestMacWindowsWatch(ScheduleCase):
    def test_launch_agent_keeps_alive(self):
        from theindex import schedule_watch
        data = plistlib.loads(schedule_watch.render_mac(Args()))
        self.assertEqual(data["Label"], "io.the-index.watch")
        self.assertEqual(data["ProgramArguments"][-1], "watch")
        self.assertTrue(data["KeepAlive"] and data["RunAtLoad"] and data["LowPriorityIO"])

    def test_mac_install_bootstraps(self):
        from theindex import schedule_watch_os
        home = self.dir / "home"
        with mock.patch("pathlib.Path.home", return_value=home), mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("os.getuid", return_value=501), mock.patch("subprocess.run", return_value=OK) as sp, \
                contextlib.redirect_stdout(io.StringIO()):
            schedule_watch_os.apply(Args())
        plist = home / "Library" / "LaunchAgents" / "io.the-index.watch.plist"
        self.assertTrue(plist.exists())
        self.assertIn(("launchctl", "bootstrap", "gui/501", str(plist)), [c.args[0] for c in sp.call_args_list])

    def test_logon_task(self):
        from theindex import schedule_watch
        root = ET.fromstring(schedule_watch.render_win(Args()))
        self.assertIsNotNone(root.find(f"{NS}Triggers/{NS}LogonTrigger"))
        self.assertEqual(root.find(f"{NS}Settings/{NS}ExecutionTimeLimit").text, "PT0S")
        self.assertTrue(root.find(f"{NS}Actions/{NS}Exec/{NS}Arguments").text.endswith("watch"))

    def test_windows_install_and_print(self):
        with mock.patch.object(sys, "platform", "win32"), mock.patch("subprocess.run", return_value=OK) as sp:
            code, out, _ = run("--db", self.db, "schedule", "--print", "--watch")
            from theindex import schedule_watch_os
            with contextlib.redirect_stdout(io.StringIO()):
                schedule_watch_os.apply(Args())
        self.assertEqual(code, 0)
        self.assertIn('/TN "THE INDEX watch"', out)
        names = [c.args[0][:4] for c in sp.call_args_list]
        self.assertIn(("schtasks", "/Create", "/TN", "THE INDEX watch"), names)


class TestWatchConfig(ScheduleCase):
    def test_defaults_and_values(self):
        self.assertEqual(config_inbox.watch({}), {"debounce_s": 2.0})
        got = config_inbox.watch({"enabled": True, "roots": ["/srv/data"], "debounce_s": 0.5})
        self.assertEqual(got, {"enabled": True, "roots": ["/srv/data"], "debounce_s": 0.5})

    def test_errors_name_the_key(self):
        for table, key in (({"enabled": "yes"}, "watch.enabled"), ({"roots": "/srv"}, "watch.roots"),
                           ({"debounce_s": 0}, "watch.debounce_s"), ({"debounce_s": True}, "watch.debounce_s")):
            with self.assertRaisesRegex(ValueError, key):
                config_inbox.watch(table)

    def test_loaded_from_file_and_enabled_installs(self):
        conf = self.dir / "c.toml"
        conf.write_text("[watch]\nenabled = true\ndebounce_s = 1\n")
        self.assertEqual(config.load(conf).watch, {"enabled": True, "debounce_s": 1.0})
        code, out, _ = run("--config", str(conf), "--db", self.db, "schedule", "--print")
        self.assertEqual(code, 0)
        self.assertIn("the-index-watch.service", out)
