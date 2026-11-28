# SPDX-License-Identifier: MIT
"""Things we may not read never stop a run and never look deleted: odd names, names-only folders, locked folders
and files. POSIX permissions, so skipped on Windows and as root (root reads everything)."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import DbCase

from theindex import config, files_run

POSIX_USER = sys.platform != "win32" and hasattr(os, "geteuid") and os.geteuid() != 0


@unittest.skipUnless(POSIX_USER, "needs POSIX permissions as a normal user")
class FilesAccessTest(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "data"
        for name in ("ok", "names_only", "locked"):
            (self.root / name).mkdir(parents=True)
        (self.root / "ok" / "a.md").write_text("# Hello\n")
        (self.root / "ok" / "shut.md").write_text("# Shut\n")
        (self.root / "names_only" / "h.md").write_text("# Hidden\n")
        (self.root / "locked" / "s.md").write_text("# Secret\n")
        self.addCleanup(self.unlock)
        self.cfg = config.Config(device_name="host-a")
        self.cfg.filetree = {"roots": [str(self.root)]}
        self.cfg.sources = {"native": "off"}

    def lock(self):
        (self.root / "ok" / "shut.md").chmod(0)
        (self.root / "names_only").chmod(stat.S_IRUSR)          # list names, cannot stat or enter
        (self.root / "locked").chmod(0)

    def unlock(self):
        for p in (self.root / "names_only", self.root / "locked"):
            p.chmod(0o755)

    def scan(self):
        result = files_run.run(self.conn, self.cfg)
        self.assertEqual(result["status"], "ok")
        return result

    def active(self):
        return {r[0] for r in self.conn.execute("SELECT name FROM file WHERE retired_run IS NULL")}

    def test_locked_on_first_scan_lists_what_it_can(self):
        self.lock()
        self.scan()
        self.assertEqual(self.active(), {"a.md", "shut.md", "h.md"})   # names-only file listed; locked dir unseen
        self.assertEqual(self.one("SELECT size_bytes FROM file WHERE name = 'h.md'"), 0)
        self.assertIsNone(self.one("SELECT mtime_ns FROM file WHERE name = 'h.md'"))
        self.assertIsNone(self.one("SELECT title FROM file WHERE name = 'shut.md'"))
        kinds = {r[0] for r in self.conn.execute("SELECT kind FROM v_gaps_open")}
        self.assertEqual(kinds, {"denied"})

    def test_losing_access_is_not_deletion(self):
        self.scan()
        size = self.one("SELECT size_bytes FROM file WHERE name = 'h.md'")
        self.lock()
        self.scan()
        self.assertEqual(self.active(), {"a.md", "shut.md", "h.md", "s.md"})
        self.assertEqual(self.one("SELECT size_bytes FROM file WHERE name = 'h.md'"), size)   # stored facts kept
        self.assertEqual(self.one("SELECT count(*) FROM v_file_events WHERE action = 'gone'"), 0)

    @unittest.skipIf(sys.platform == "darwin", "APFS refuses names that are not UTF-8")
    def test_name_that_is_not_text_never_stops_a_run(self):
        os.close(os.open(os.path.join(os.fsencode(self.root / "ok"), b"bad\xffname.md"), os.O_CREAT | os.O_WRONLY))
        self.scan()
        self.assertIn("bad�name.md", self.active())
        self.assertIn("a.md", self.active())


if __name__ == "__main__":
    unittest.main()
