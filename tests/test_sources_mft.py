# SPDX-License-Identifier: MIT
"""sources_mft: USN_RECORD_V2 parsing, path resolution, root filtering, fallbacks and the enumeration loop (fakes)."""
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src/theindex/collectors"))
import sources_mft as mft
import sources_tools as tools

DIR, REPARSE = 0x10, 0x400
UNI = "\u00fcber \u65e5\u672c.txt"


def record(frn, parent, name, attrs=0):
    raw = name.encode("utf-16-le")
    length = (mft.RECORD_HEAD.size + len(raw) + 7) & ~7
    head = mft.RECORD_HEAD.pack(length, 2, 0, frn | (7 << 48), parent, 0, 0, 0, 0, 0, attrs, len(raw), 60)
    return (head + raw).ljust(length, b"\0")


def v3(rec):
    return rec[:4] + struct.pack("<H", 3) + rec[6:]


def buffer(*records, next_frn=0):
    return struct.pack("<Q", next_frn) + b"".join(records)


class ParseTest(unittest.TestCase):
    def test_multi_record_unicode_and_reparse(self):
        buf = buffer(record(30, 5, "Users", DIR), record(31, 30, UNI), record(32, 5, "lnk", DIR | REPARSE))
        got = list(mft.parse_records(buf))
        self.assertEqual(got, [(30, 5, DIR, "Users"), (31, 30, 0, UNI), (32, 5, DIR | REPARSE, "lnk")])

    def test_masks_sequence_bits_and_skips_other_versions(self):
        got = list(mft.parse_records(buffer(v3(record(40, 5, "a")), record(41, 5, "b"))))
        self.assertEqual(got, [(41, 5, 0, "b")])

    def test_truncated_buffer_stops(self):
        self.assertEqual(list(mft.parse_records(buffer(record(41, 5, "b"))[:-8])), [])


class PathsTest(unittest.TestCase):
    RECS = ((30, 5, DIR, "Users"), (31, 30, DIR, "alice"), (32, 31, 0, "Doc.TXT"), (33, 5, DIR | REPARSE, "Link"),
            (34, 33, 0, "hidden.txt"), (35, 99, 0, "orphan.txt"))

    def test_resolve_skips_reparse_subtree_and_orphans(self):
        paths = mft.resolve_paths(self.RECS, 5, "C:")
        self.assertEqual(paths[32], "C:\\Users\\alice\\Doc.TXT")
        self.assertEqual(paths[33], "C:\\Link")
        self.assertNotIn(34, paths)
        self.assertNotIn(35, paths)

    def test_filter_to_roots_case_insensitive(self):
        paths = list(mft.resolve_paths(self.RECS, 5, "C:\\").values())
        self.assertEqual(list(mft.under(paths, "c:\\users\\ALICE")), ["C:\\Users\\alice", "C:\\Users\\alice\\Doc.TXT"])
        self.assertEqual(list(mft.under(paths, "C:\\Use")), [])


class LoopTest(unittest.TestCase):
    def test_two_buffers_then_eof(self):
        bufs = [buffer(record(30, 5, "a"), next_frn=31), buffer(record(31, 5, "b"), next_frn=32)]
        calls = []

        def fake(code, data, size):
            calls.append(struct.unpack("<Qqq", data))
            if not bufs:
                raise mft.IoError(38)
            return bufs.pop(0)
        got = [r[3] for r in mft.enumerate_records(fake, 1000)]
        self.assertEqual(got, ["a", "b"])
        self.assertEqual(calls, [(0, 0, 1000), (31, 0, 1000), (32, 0, 1000)])

    def test_other_error_propagates(self):
        def fake(code, data, size):
            raise mft.IoError(5)
        with self.assertRaises(mft.IoError):
            list(mft.enumerate_records(fake, 1))


class FallbackTest(unittest.TestCase):
    def test_not_windows(self):
        self.assertFalse(mft.usable({"platform": "linux", "roots": ["C:\\x"]}))

    def test_not_admin(self):
        with mock.patch.object(mft, "is_admin", return_value=False):
            self.assertFalse(mft.usable({"platform": "win32", "roots": ["C:\\x"]}))

    def test_volume_failure_is_not_usable(self):
        with mock.patch.object(mft, "is_admin", return_value=True), \
                mock.patch.object(mft, "read_volume", side_effect=mft.IoError(1)):
            self.assertFalse(mft.usable({"platform": "win32", "roots": ["C:\\x"]}))

    def test_detect_prefers_mft_then_everything(self):
        opts = {"platform": "win32", "roots": ["C:\\x"]}
        with mock.patch.object(mft, "usable", return_value=True):
            self.assertEqual(tools.detect(opts), ("mft", None, ""))
        with mock.patch.object(mft, "usable", return_value=False), mock.patch("shutil.which", return_value=None):
            self.assertIsNone(tools.detect(opts)[0])

    def test_reader_uses_volume_table(self):
        with mock.patch.object(mft, "read_volume", return_value=["C:\\x\\a.txt", "C:\\y\\b.txt"]):
            self.assertEqual(list(tools.run_reader("mft", None, "C:\\x")), ["C:\\x\\a.txt"])


if __name__ == "__main__":
    unittest.main()
