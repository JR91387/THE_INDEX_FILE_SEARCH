# SPDX-License-Identifier: MIT
"""Containers, filesystems and backups collectors: parsing only (no docker or real mounts needed)."""
import os
import tempfile
import unittest
from pathlib import Path

from test_collectors import load

containers = load("containers")
filesystems = load("filesystems")
backups = load("backups")

INSPECT = {"Name": "/app", "Image": "sha256:abc", "State": {"Status": "running"},
           "Config": {"Image": "example/app:1", "Labels": {"com.docker.compose.project": "demo"}},
           "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
           "Mounts": [{"Type": "bind", "Source": "/srv/app", "Destination": "/data", "RW": True},
                      {"Type": "tmpfs", "Source": "", "Destination": "/tmp", "RW": True}]}


class TestContainers(unittest.TestCase):
    def test_item_and_links(self):
        item = containers.item_of(INSPECT, "2026-01-01T00:00:00Z")
        self.assertEqual((item["key"], item["attrs"]["state"], item["attrs"]["restart_policy"]),
                         ("app", "running", "unless-stopped"))
        self.assertEqual(item["metrics"], {"last_running_at": "2026-01-01T00:00:00Z"})
        self.assertEqual(containers.links_of(item),
                         [{"from": ["container", "app"], "type": "mounts", "to": ["folder", "/srv/app"]}])

    def test_stopped_has_no_running_metric(self):
        stopped = {**INSPECT, "State": {"Status": "exited"}}
        self.assertEqual(containers.item_of(stopped, "x")["metrics"], {})


class TestFilesystems(unittest.TestCase):
    def test_only_real_mounts(self):
        text = (
            "/dev/sda1 / ext4 rw,relatime 0 0\nproc /proc proc rw 0 0\n"
            "//nas/share /mnt/my\\040share cifs rw 0 0\n/dev/loop0 /snap/core squashfs ro 0 0\n"
            "/dev/sdb1 /run/media/usb vfat rw 0 0\n/dev/sdc1 /development ext4 rw 0 0\n"
            "overlay /var/lib/docker/overlay2/x overlay rw 0 0\n")
        targets = [m[1] for m in filesystems.mounts(text)]
        self.assertEqual(targets, ["/", "/mnt/my share", "/run/media/usb", "/development"])

    def test_statvfs_reports_sizes(self):
        size, used = filesystems.statvfs("/")
        self.assertGreater(size, 0)
        self.assertGreaterEqual(size, used)


class TestBackups(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def run_one(self, check):
        out = {"items": [], "links": [], "gaps": []}
        backups.run_check(check, out)
        return out

    def test_file_age_picks_newest_big_enough(self):
        (self.dir / "a.dump").write_bytes(b"x" * 10)
        (self.dir / "b.dump").write_bytes(b"x")
        os.utime(self.dir / "a.dump", (1767225600, 1767225600))
        os.utime(self.dir / "b.dump", (1767312000, 1767312000))
        out = self.run_one({"name": "db", "type": "file_age", "path": str(self.dir / "*.dump"), "min_bytes": 5,
                            "sources": ["/srv/db"], "destination": str(self.dir)})
        metrics = out["items"][0]["metrics"]
        self.assertEqual((metrics["newest_good_at"], metrics["size_bytes"]), ("2026-01-01T00:00:00Z", 10))
        self.assertEqual([link["type"] for link in out["links"]], ["backs_up", "lands_in"])

    def test_log_pattern_with_time_group(self):
        log = self.dir / "backup.log"
        log.write_text("2026-01-01T03:00:00Z start\n2026-01-01T03:10:00Z backup OK\nlater noise\n")
        out = self.run_one({"name": "nightly", "type": "log_pattern", "path": str(log),
                            "success": r"^(?P<when>\S+) backup OK"})
        self.assertEqual(out["items"][0]["metrics"]["newest_good_at"], "2026-01-01T03:10:00Z")

    def test_missing_file_is_a_result_not_a_crash(self):
        out = self.run_one({"name": "gone", "type": "log_pattern", "path": str(self.dir / "nope"), "success": "x"})
        self.assertTrue(out["items"][0]["metrics"]["last_result"].startswith("error"))
        self.assertNotIn("newest_good_at", out["items"][0]["metrics"])

    def test_command_check(self):
        out = self.run_one({"name": "cmd", "type": "command", "command": "false"})
        self.assertEqual(out["items"][0]["metrics"]["last_result"], "exit 1")
