# SPDX-License-Identifier: MIT
"""schedule per OS and role: LaunchAgent plist, Task Scheduler XML, member = collect. subprocess is always mocked."""
import plistlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from test_cli_errors import run
from test_schedule import ScheduleCase

OK = subprocess.CompletedProcess([], 0, "", "")


class Args:
    def __init__(self, role=None):
        self.role, self.config, self.db, self.print, self.remove = role, None, None, False, False


class TestMac(ScheduleCase):
    def setUp(self):
        super().setUp()
        self.home = self.dir / "home"
        self.agents = self.home / "Library" / "LaunchAgents"
        for patch in (mock.patch("pathlib.Path.home", return_value=self.home),
                      mock.patch.object(sys, "platform", "darwin"), mock.patch("os.getuid", return_value=501)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_plist_carries_argv_and_low_priority(self):
        from theindex import schedule_mac
        data = plistlib.loads(schedule_mac.render(Args("hub")))
        self.assertEqual(data["Label"], "io.the-index.scan")
        self.assertEqual(data["ProgramArguments"], [sys.executable, "-m", "theindex", "scan", "--quiet"])
        self.assertEqual((data["LowPriorityIO"], data["Nice"], data["RunAtLoad"]), (True, 19, False))
        self.assertIn("Hour", data["StartCalendarInterval"])
        member = plistlib.loads(schedule_mac.render(Args("member")))
        self.assertEqual((member["Label"], member["ProgramArguments"][3:]), ("io.the-index.collect", ["collect"]))

    def test_install_boots_out_when_loaded_then_bootstraps(self):
        with mock.patch("subprocess.run", return_value=OK) as sp:
            code, _, _ = run("schedule")
        plist = self.agents / "io.the-index.scan.plist"
        self.assertEqual(code, 0)
        self.assertTrue(plist.exists())
        self.assertEqual([c.args[0] for c in sp.call_args_list],
                         [("launchctl", "print", "gui/501/io.the-index.scan"),
                          ("launchctl", "bootout", "gui/501/io.the-index.scan"),
                          ("launchctl", "bootstrap", "gui/501", str(plist))])

    def test_not_loaded_skips_bootout(self):
        results = [subprocess.CompletedProcess([], 113, "", ""), OK]
        with mock.patch("subprocess.run", side_effect=results) as sp:
            run("schedule")
        self.assertEqual([c.args[0][1] for c in sp.call_args_list], ["print", "bootstrap"])

    def test_remove_unloads_and_unlinks(self):
        with mock.patch("subprocess.run", return_value=OK):
            run("schedule", "--role", "member")
            code, out, _ = run("schedule", "--role", "member", "--remove")
        self.assertEqual((code, out.strip()), (0, "schedule removed"))
        self.assertFalse((self.agents / "io.the-index.collect.plist").exists())

    def test_print_changes_nothing(self):
        with mock.patch("subprocess.run") as sp:
            code, out, _ = run("schedule", "--print")
        self.assertEqual(code, 0)
        self.assertIn("ProgramArguments", out)
        sp.assert_not_called()
        self.assertFalse(self.home.exists())


class TestWindows(ScheduleCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(sys, "platform", "win32")
        patch.start()
        self.addCleanup(patch.stop)

    def test_xml_parses_with_the_task_fields(self):
        from theindex import schedule_win
        ns = {"t": schedule_win.NS}
        root = ET.fromstring(schedule_win.render(Args("hub")))

        def text(path):
            return root.find(path, ns).text
        self.assertEqual(text(".//t:Exec/t:Command"), sys.executable)
        self.assertEqual(text(".//t:Exec/t:Arguments"), "-m theindex scan --quiet")
        self.assertEqual(text(".//t:CalendarTrigger/t:RandomDelay"), "PT1H")
        self.assertEqual(text(".//t:ScheduleByDay/t:DaysInterval"), "1")
        self.assertEqual((text(".//t:LogonType"), text(".//t:RunLevel")), ("InteractiveToken", "LeastPrivilege"))
        self.assertEqual([text(f".//t:{k}") for k in ("Priority", "StartWhenAvailable",
                                                      "DisallowStartIfOnBatteries", "ExecutionTimeLimit")],
                         ["7", "true", "false", "PT4H"])
        member = ET.fromstring(schedule_win.render(Args("member")))
        self.assertEqual(member.find(".//t:Exec/t:Arguments", ns).text, "-m theindex collect")

    def test_install_writes_utf16_and_calls_schtasks(self):
        seen = {}

        def fake(cmd, **_):
            seen["cmd"], seen["file"] = cmd, Path(cmd[cmd.index("/XML") + 1])
            seen["xml"] = seen["file"].read_bytes()
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch("subprocess.run", side_effect=fake):
            code, _, _ = run("schedule")
        self.assertEqual(code, 0)
        self.assertEqual(seen["cmd"][:4], ("schtasks", "/Create", "/TN", "THE INDEX"))
        self.assertEqual((seen["cmd"][-3], seen["cmd"][-1]), ("/XML", "/F"))
        self.assertTrue(seen["xml"].startswith((b"\xff\xfe", b"\xfe\xff")))
        self.assertIn("Task", seen["xml"].decode("utf-16"))
        self.assertFalse(seen["file"].exists())

    def test_remove_and_member_name(self):
        with mock.patch("subprocess.run", return_value=OK) as sp:
            code, out, _ = run("schedule", "--role", "member", "--remove")
        self.assertEqual(sp.call_args.args[0], ("schtasks", "/Delete", "/TN", "THE INDEX collect", "/F"))
        self.assertEqual((code, out.strip()), (0, "schedule removed"))


class TestLinuxMember(ScheduleCase):
    def test_member_role_schedules_collect_unit(self):
        self.stub("systemctl")
        self.stub("loginctl", "echo Linger=yes")
        run("schedule", "--role", "member")
        service = (self.units() / "the-index-collect.service").read_text()
        self.assertIn(f"ExecStart={sys.executable} -m theindex collect", service)
        self.assertNotIn("--quiet", service)
        self.assertIn("--user enable --now the-index-collect.timer", "\n".join(self.calls()))
        self.assertFalse((self.units() / "the-index.service").exists())
        run("schedule", "--role", "member", "--remove")
        self.assertEqual(list(self.units().glob("the-index*")), [])

    def test_role_defaults_from_config(self):
        cfg = self.dir / "c.toml"
        cfg.write_text('[inbox]\nrole = "member"\n')
        out = run("--config", str(cfg), "schedule", "--print")[1]
        self.assertIn("the-index-collect.service", out)

    def test_platform_routing(self):
        for plat, module in (("darwin", "schedule_mac"), ("win32", "schedule_win"), ("linux", "schedule")):
            with mock.patch.object(sys, "platform", plat), \
                    mock.patch(f"theindex.{module}.install", return_value=0) as inst:
                self.assertEqual(run("schedule")[0], 0)
                inst.assert_called_once()
