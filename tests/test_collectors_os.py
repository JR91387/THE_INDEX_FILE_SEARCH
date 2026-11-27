# SPDX-License-Identifier: MIT
"""Per-OS job collectors and portability guards. Unit-tested only: no real macOS or Windows host."""
import contextlib
import io
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT

from theindex import collectors

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_collectors import load

launchd = load("jobs_launchd")
schtasks = load("jobs_schtasks")
folders = load("folders")


def run_main(module, opts=None, platform=None):
    """Run a collector's main() in-process with argv options and (optionally) sys.platform patched."""
    argv = ["x", json.dumps(opts)] if opts else ["x"]
    buf = io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "argv", argv))
        if platform:
            stack.enter_context(mock.patch.object(sys, "platform", platform))
        stack.enter_context(contextlib.redirect_stdout(buf))
        module.main()
    return json.loads(buf.getvalue())


def task_xml(uri, command, args, user="alice"):
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    return (f'<?xml version="1.0" encoding="UTF-16"?>\n<Task version="1.2" xmlns="{ns}">'
            f"<RegistrationInfo><URI>{uri}</URI></RegistrationInfo>"
            "<Triggers><CalendarTrigger/><BootTrigger/></Triggers>"
            f"<Principals><Principal><UserId>{user}</UserId></Principal></Principals>"
            "<Settings><Enabled>true</Enabled></Settings>"
            f"<Actions><Exec><Command>{command}</Command><Arguments>{args}</Arguments></Exec></Actions></Task>\n")


class TestLaunchd(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        agents = Path(self.root + "/Library/LaunchAgents")
        agents.mkdir(parents=True)
        plists = {"a": {"Label": "com.example.cal", "Program": "/usr/bin/backup",
                        "StartCalendarInterval": {"Hour": 3, "Minute": 0}},
                  "b": {"Label": "com.example.tick", "ProgramArguments": ["/bin/echo", "hi"], "StartInterval": 300},
                  "c": {"Label": "com.example.svc", "ProgramArguments": ["/opt/svc", "--run"], "UserName": "bob",
                        "RunAtLoad": True, "KeepAlive": True}}
        for name, data in plists.items():
            (agents / f"{name}.plist").write_bytes(plistlib.dumps(data))
        (agents / "bad.plist").write_bytes(b"not a plist")

    def test_items_and_gap(self):
        out = run_main(launchd, {"root": self.root}, "darwin")
        items = {i["key"]: i["attrs"] for i in out["items"]}
        self.assertEqual(set(items), {"launchd:agents:com.example.cal", "launchd:agents:com.example.tick",
                                      "launchd:agents:com.example.svc"})
        self.assertEqual(items["launchd:agents:com.example.cal"]["schedule"], "calendar Hour=3 Minute=0")
        self.assertEqual(items["launchd:agents:com.example.cal"]["command"], "/usr/bin/backup")
        self.assertEqual(items["launchd:agents:com.example.tick"]["schedule"], "every 300s")
        self.assertEqual(items["launchd:agents:com.example.tick"]["command"], "/bin/echo hi")
        svc = items["launchd:agents:com.example.svc"]
        self.assertEqual((svc["run_as"], svc["schedule"]), ("bob", "at load; keepalive"))
        self.assertIn("launchd:agents:", out["coverage"])
        self.assertEqual([g["target"].endswith("bad.plist") for g in out["gaps"]], [True])
        self.assertEqual(out["status"], "ok")

    def test_other_platform_is_one_gap(self):
        out = run_main(launchd, {"root": self.root}, "linux")
        self.assertEqual((out["status"], out["items"]), ("ok", []))
        self.assertEqual([g["kind"] for g in out["gaps"]], ["unsupported"])

    def test_force_platform_option(self):
        out = run_main(launchd, {"root": self.root, "force_platform": "darwin"})
        self.assertEqual(len(out["items"]), 3)


class TestSchtasks(unittest.TestCase):
    def test_skips_microsoft_tasks(self):
        text = task_xml("\\Backup\\Nightly", "C:\\bin\\bk.exe", "/all") + task_xml("\\Microsoft\\Windows\\X", "x", "")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.xml"
            path.write_text(text, encoding="utf-8")
            out = run_main(schtasks, {"xml_file": str(path)}, "win32")
            both = run_main(schtasks, {"xml_file": str(path), "system": True}, "win32")
        self.assertEqual(len(out["items"]), 1)
        item = out["items"][0]
        self.assertEqual(item["key"], "schtasks:\\Backup\\Nightly")
        self.assertEqual(item["attrs"]["command"], "C:\\bin\\bk.exe /all")
        self.assertEqual((item["attrs"]["run_as"], item["attrs"]["enabled"]), ("alice", True))
        self.assertEqual(item["attrs"]["schedule"], "CalendarTrigger, BootTrigger")
        self.assertEqual(len(both["items"]), 2)

    def test_other_platform_is_one_gap(self):
        out = run_main(schtasks, None, "linux")
        self.assertEqual((out["status"], out["items"]), ("ok", []))
        self.assertEqual([g["kind"] for g in out["gaps"]], ["unsupported"])


class TestUnsupportedPlatforms(unittest.TestCase):
    def test_systemd_and_filesystems_on_macos(self):
        for name in ("jobs_systemd", "filesystems"):
            out = run_main(load(name), None, "darwin")
            self.assertEqual((out["status"], out["items"]), ("ok", []), name)
            self.assertEqual([g["kind"] for g in out["gaps"]], ["unsupported"], name)

    def test_cron_on_windows(self):
        out = run_main(load("jobs_cron"), None, "win32")
        self.assertEqual((out["status"], out["items"]), ("ok", []))
        self.assertEqual([g["kind"] for g in out["gaps"]], ["unsupported"])


class TestFoldersPortable(unittest.TestCase):
    def test_blank_owners_without_pwd(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(folders, "pwd", None), \
                mock.patch.object(folders, "grp", None):
            out = folders.scan({"roots": [tmp], "depth": 0})
        attrs = out["items"][0]["attrs"]
        self.assertEqual((attrs["owner"], attrs["group"]), ("", ""))

    def test_linux_roots_unchanged_and_per_os_table(self):
        self.assertEqual(folders.ROOTS.get("linux", ["/home", "/srv", "/opt", "/var/lib"]),
                         ["/home", "/srv", "/opt", "/var/lib"])
        self.assertIn("/Applications", folders.ROOTS["darwin"])
        self.assertTrue(folders.ROOTS["win32"])


class TestRegistry(unittest.TestCase):
    def test_jobs_per_platform(self):
        pick = collectors.registry_for
        self.assertEqual(pick("linux")["jobs"], ["jobs_cron.py", "jobs_systemd.py"])
        self.assertEqual(pick("darwin")["jobs"], ["jobs_launchd.py", "jobs_cron.py"])
        self.assertEqual(pick("win32")["jobs"], ["jobs_schtasks.py"])
        self.assertEqual(pick("freebsd")["jobs"], pick("linux")["jobs"])
        for name in ("folders", "containers", "filesystems", "backups"):
            self.assertEqual(pick("darwin")[name], collectors.REGISTRY[name])
        for scripts in (pick(p)["jobs"] for p in ("linux", "darwin", "win32")):
            self.assertTrue(all((ROOT / "src/theindex/collectors" / s).exists() for s in scripts))


if __name__ == "__main__":
    unittest.main()
