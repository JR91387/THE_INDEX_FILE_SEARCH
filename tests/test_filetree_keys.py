# SPDX-License-Identifier: MIT
"""filetree path keys and network-mount detection."""
import sys
import unittest
from unittest import mock

from test_filetree import FiletreeCase, net, walk


class TestKeys(FiletreeCase):
    def test_nfd_name_gets_nfc_key(self):
        nfd = "cafe\u0301"
        nfc = "caf\u00e9"
        try:
            (self.root / nfd).mkdir()
        except OSError:
            self.skipTest("filesystem rejects this name")
        recs = self.run_ft()
        rec = next(r for r in self.of(recs, "dir") if r["path"].endswith("cafe\u0301"))
        self.assertTrue(rec["key"].endswith(nfc))
        self.assertTrue(rec["path"].endswith(nfd))

    def test_path_key_unit(self):
        self.assertEqual(walk.path_key("C:\\Users\\Alice\\Caf\u00e9", False), "C:/Users/Alice/Caf\u00e9")
        self.assertEqual(walk.path_key("/srv/Data/cafe\u0301", False), "/srv/Data/caf\u00e9")
        self.assertEqual(walk.path_key("C:\\Users\\Alice\\Caf\u00e9", True), "c:/users/alice/caf\u00e9")

    def test_case_insensitive_platforms(self):
        for plat, expected in (("darwin", True), ("win32", True), ("linux", False)):
            with mock.patch.object(sys, "platform", plat):
                self.assertEqual(walk.case_insensitive(), expected)
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(walk.path_key("/Users/Alice/Docs", walk.case_insensitive()), "/users/alice/docs")

    def test_linux_network_mounts(self):
        mounts = "host-a:/x /mnt/share\\040one nfs4 rw 0 0\n/dev/sda1 / ext4 rw 0 0\n//host-b/s /mnt/win cifs rw 0 0\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=mounts)):
            found = net.linux_mounts()
        self.assertEqual(found, {"/mnt/share one", "/mnt/win"})

    def test_network_mount_gap_not_walked(self):
        (self.root / "share").mkdir()
        (self.root / "share" / "s.txt").write_text("x")
        w = walk.Walker({"roots": [str(self.root)]}, {}, lambda r: None)
        w.mounts = {str(self.root / "share")}
        got = []
        w.write = got.append
        w.run()
        self.assertEqual([(g["kind"], g["target"]) for g in got if g["t"] == "gap"],
                         [("network", str(self.root / "share"))])
        self.assertFalse([r for r in got if r["t"] == "dir" and r["path"].endswith("share")])




if __name__ == "__main__":
    unittest.main()


class BuiltinSkipTest(unittest.TestCase):
    def test_named_root_under_builtin_skip_is_walked(self):
        skips = ["/proc", "/dev", "/run"]
        self.assertEqual(net.builtin_skips(skips, ["/dev/shm/bench"]), ["/proc", "/run"])
        self.assertEqual(net.builtin_skips(skips, ["/srv/data"]), skips)
        self.assertEqual(net.builtin_skips(skips, ["/", "/dev/shm/bench"]), skips)   # "/" would walk /dev
