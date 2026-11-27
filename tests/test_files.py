# SPDX-License-Identifier: MIT
"""Purposes and links file loaders."""
import tempfile
from pathlib import Path

from helpers import DbCase

from theindex import config, files, ingest

HOST = "host-a"


def payload(collector, kind, items):
    return {"collector": collector, "kinds": [kind], "status": "ok", "coverage": [""], "gaps": [], "items": items}


def item(kind, key, **attrs):
    return {"kind": kind, "key": key, "attrs": attrs, "metrics": {}}


class FilesCase(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.cfg = config.Config(device_name=HOST, purposes_file=self.dir / "p.txt", links_file=self.dir / "l.txt")
        ingest.ingest(self.conn, payload("folders", "folder", [item("folder", "/srv"), item("folder", "/srv/photos"),
                                                                 item("folder", "/srv/backups")]), HOST)
        ingest.ingest(self.conn, payload("jobs", "job", [item("job", "crontab:alice:1")]), HOST)

    def write(self, purposes, links=""):
        (self.dir / "p.txt").write_text(purposes)
        (self.dir / "l.txt").write_text(links)
        return files.load(self.conn, self.cfg)


class TestPurposes(FilesCase):
    def test_load_and_unexplained(self):
        warnings = self.write("# comment\n/srv/photos | irreplaceable | Family photos #1 | alice\n")
        self.assertEqual(warnings, [])
        self.assertEqual(self.one("SELECT purpose FROM v_folders WHERE key='/srv/photos'"), "Family photos #1")
        self.assertEqual(self.one("SELECT key FROM v_folders_no_purpose"), "/srv/backups")
        self.assertEqual(self.one("SELECT count(*) FROM v_unbacked_irreplaceable"), 1)

    def test_bad_lines_warn_and_reload_replaces(self):
        warnings = self.write("/srv/x | precious | nope\n[ghost]\n/srv/y | scratch | tmp\n")
        self.assertEqual(len(warnings), 2)
        self.write("/srv/photos | scratch | replaced\n")
        self.assertEqual(self.one("SELECT count(*) FROM purpose"), 1)
        self.assertEqual(self.one("SELECT gate_result IS NULL FROM scan_run ORDER BY id DESC LIMIT 1"), 1)


class TestDeclaredLinks(FilesCase):
    def test_links_resolve_globs_and_retire(self):
        purposes = "/srv/photos | irreplaceable | photos\n"
        self.write(purposes, "job:crontab:alice:* | writes | folder:/srv/backups\n"
                             "folder:/srv/photos | backs_up | folder:/srv/backups\n")
        self.assertEqual(self.one("SELECT folder FROM v_job_writes"), "/srv/backups")
        self.write(purposes, "")
        self.assertEqual(self.one("SELECT count(*) FROM v_link"), 0)

    def test_backup_coverage_clears_unbacked(self):
        ingest.ingest(self.conn, payload("backups", "backup", [item("backup", "nightly")]), HOST)
        self.write("/srv/photos/* | irreplaceable | photos\n/srv/photos | irreplaceable | photos\n",
                   "backup:nightly | backs_up | folder:/srv/photos\n")
        self.assertEqual(self.one("SELECT count(*) FROM v_unbacked_irreplaceable"), 0)


class TestContainersDown(FilesCase):
    def test_expected_and_assumed(self):
        ingest.ingest(self.conn, payload("containers", "container", [
            item("container", "web", state="exited", restart_policy="no"),
            item("container", "db", state="exited", restart_policy="unless-stopped")]), HOST)
        self.write("container:web | rebuildable | web app | | running\n")
        rows = self.conn.execute("SELECT key, assumed FROM v_containers_down ORDER BY key").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("db", 1), ("web", 0)])
