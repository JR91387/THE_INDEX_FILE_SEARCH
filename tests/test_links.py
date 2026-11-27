# SPDX-License-Identifier: MIT
from helpers import DbCase

from theindex import config, ingest

HOST = "host-a"


def run(conn, source, items, links=()):
    collector, kind = source
    return ingest.ingest(conn, {"collector": collector, "kinds": [kind], "status": "ok", "coverage": [""],
                                "items": items, "links": list(links), "gaps": []}, HOST)


def item(kind, key, **attrs):
    return {"kind": kind, "key": key, "attrs": attrs, "metrics": {}}


MOUNT = {"from": ["container", "app"], "type": "mounts", "to": ["folder", "/srv/app"]}


class TestLinks(DbCase):
    def test_unresolved_until_target_exists(self):
        result = run(self.conn, ("containers", "container"), [item("container", "app")], [MOUNT])
        self.assertEqual(result["unresolved_links"], 1)
        run(self.conn, ("folders", "folder"), [item("folder", "/srv/app")])
        result = run(self.conn, ("containers", "container"), [item("container", "app")], [MOUNT])
        self.assertEqual(result["unresolved_links"], 0)
        self.assertEqual(self.one("SELECT folder FROM v_container_data"), "/srv/app")
        self.assertEqual(self.one("SELECT count(*) FROM v_folders_no_purpose"), 0)  # explained by the mount

    def test_unreported_link_is_retired(self):
        run(self.conn, ("folders", "folder"), [item("folder", "/srv/app")])
        run(self.conn, ("containers", "container"), [item("container", "app")], [MOUNT])
        run(self.conn, ("containers", "container"), [item("container", "app")])
        self.assertEqual(self.one("SELECT count(*) FROM v_link"), 0)
        self.assertEqual(self.one("SELECT count(*) FROM item_link"), 1)  # retired, not deleted


class TestFilesystemView(DbCase):
    def test_fullness_health(self):
        fs = {"kind": "filesystem", "key": "/", "attrs": {"fstype": "ext4"},
              "metrics": {"size_bytes": 100, "used_bytes": 96}}
        run(self.conn, ("filesystems", "filesystem"), [fs])
        self.assertEqual(self.one("SELECT health FROM v_filesystems"), "emergency")
        self.assertEqual(self.one("SELECT filesystems_full FROM v_front_page"), 1)


class TestBackupConfig(DbCase):
    def test_max_age_becomes_seconds(self):
        self.assertEqual(config.backup_check({"name": "a", "max_age": "2d"})["max_age_s"], 172800)
