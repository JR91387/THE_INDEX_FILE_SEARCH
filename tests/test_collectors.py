# SPDX-License-Identifier: MIT
import importlib.util
from datetime import datetime

from helpers import ROOT

from theindex import collectors


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src/theindex/collectors" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cron = load("jobs_cron")
systemd = load("jobs_systemd")




import unittest


class TestCronParsing(unittest.TestCase):
    def test_fields(self):
        self.assertEqual(cron.parse_field("*/15", 0, 59), {0, 15, 30, 45})
        self.assertEqual(cron.parse_field("1-3,5", 0, 7), {1, 2, 3, 5})
        self.assertEqual(cron.parse_field("mon-fri", 0, 7), {1, 2, 3, 4, 5})

    def test_next_run(self):
        start = datetime(2026, 1, 1, 10, 7)  # a Thursday
        self.assertEqual(cron.next_run("*/15 * * * *", start), datetime(2026, 1, 1, 10, 15))
        self.assertEqual(cron.next_run("0 3 * * *", start), datetime(2026, 1, 2, 3, 0))
        self.assertEqual(cron.next_run("@daily", start), datetime(2026, 1, 2, 0, 0))
        self.assertEqual(cron.next_run("0 9 * * mon", start), datetime(2026, 1, 5, 9, 0))
        self.assertIsNone(cron.next_run("@reboot", start))

    def test_split_line(self):
        self.assertEqual(cron.split_line("5 4 * * * /bin/x --y", False), ("5 4 * * *", None, "/bin/x --y"))
        self.assertEqual(cron.split_line("5 4 * * * root /bin/x", True), ("5 4 * * *", "root", "/bin/x"))
        self.assertEqual(cron.split_line("@hourly /bin/x", False), ("@hourly", None, "/bin/x"))
        self.assertIsNone(cron.split_line("MAILTO=alice", False))
        self.assertIsNone(cron.split_line("# comment", False))


class TestSystemdParsing(unittest.TestCase):
    def test_exec_and_stamp(self):
        raw = "{ path=/usr/bin/tool ; argv[]=/usr/bin/tool --run ; ignore_errors=no }"
        self.assertEqual(systemd.exec_command(raw), "/usr/bin/tool --run")
        self.assertEqual(systemd.stamp("@0"), None)
        self.assertEqual(systemd.stamp("@1767225600"), "2026-01-01T00:00:00Z")


class TestMerge(unittest.TestCase):
    def test_any_bad_script_makes_run_partial(self):
        item = {"kind": "job", "key": "a:1"}
        ok = {"status": "ok", "items": [item], "gaps": [], "errors": [], "coverage": ["a:"], "kinds": ["job"]}
        bad = {"status": "failed", "items": [], "gaps": [], "errors": ["boom"], "coverage": []}
        merged = collectors.merge("jobs", [ok, bad])
        self.assertEqual((merged["status"], merged["items"], merged["errors"]), ("partial", [item], ["boom"]))

    def test_duplicates_dropped_and_reported(self):
        item = {"kind": "job", "key": "a:1"}
        merged = collectors.merge("jobs", [{"status": "ok", "items": [item, dict(item)]}])
        self.assertEqual((merged["status"], len(merged["items"])), ("partial", 1))
