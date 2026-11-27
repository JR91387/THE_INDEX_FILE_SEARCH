# SPDX-License-Identifier: MIT
"""watch backends: event parsers fed recorded bytes (inotify, FSEvents, ReadDirectoryChangesW), the inotify
budget, and the macOS / Windows backends driven through mocked ctypes libraries."""
import ctypes
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (puts src/ on the path)

from theindex import watch_linux, watch_mac, watch_win


def inotify_event(wd, mask, name=b""):
    padded = name + b"\0" * (16 - len(name) % 16) if name else b""
    return struct.pack("iIII", wd, mask, 0, len(padded)) + padded


class TestInotifyParse(unittest.TestCase):
    def test_events_to_dirs(self):
        paths = {1: "/srv/data", 2: "/srv/data/sub"}
        data = (inotify_event(1, watch_linux.IN_CREATE, b"a.txt")
                + inotify_event(1, watch_linux.IN_CREATE | watch_linux.IN_ISDIR, b"new")
                + inotify_event(2, watch_linux.IN_MODIFY, b"b.txt")
                + inotify_event(2, watch_linux.IN_DELETE_SELF)
                + inotify_event(2, watch_linux.IN_IGNORED))
        self.assertEqual(watch_linux.parse(data, paths), [
            ("dir", "/srv/data"), ("dir", "/srv/data"), ("newdir", "/srv/data/new"), ("dir", "/srv/data/sub")])
        self.assertEqual(paths, {1: "/srv/data"})              # the kernel dropped wd 2

    def test_overflow(self):
        data = inotify_event(-1, watch_linux.IN_Q_OVERFLOW)
        self.assertEqual(watch_linux.parse(data, {}), [("overflow", None)])

    def test_budget_leaves_headroom(self):
        with tempfile.TemporaryDirectory() as tmp:
            limit = Path(tmp) / "max_user_watches"
            limit.write_text("8192\n")
            self.assertEqual(watch_linux.budget(str(limit)), 7168)          # limit - 1024
            limit.write_text("100000\n")
            self.assertEqual(watch_linux.budget(str(limit)), 90000)         # 90 %
            self.assertEqual(watch_linux.budget(str(Path(tmp) / "missing")), 7168)

    @unittest.skipUnless(Path("/proc/sys/fs/inotify").exists(), "needs inotify")
    def test_real_instance_budget_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            ino = watch_linux.Inotify(limit=1)
            self.addCleanup(ino.close)
            (Path(tmp) / "sub").mkdir()
            self.assertTrue(ino.add(tmp))
            self.assertFalse(ino.add(str(Path(tmp) / "sub")))
            self.assertTrue(ino.full)
            (Path(tmp) / "f.txt").write_bytes(b"x")
            self.assertIn(("dir", tmp), ino.read(2.0))


def fsevents_args(paths, flags):
    names = (ctypes.c_char_p * len(paths))(*[p.encode() for p in paths])
    return len(paths), ctypes.cast(names, ctypes.c_void_p), (ctypes.c_uint32 * len(flags))(*flags)


class TestFSEvents(unittest.TestCase):
    def test_parse_dirs(self):
        count, ptr, flags = fsevents_args(["/srv/data/docs/", "/srv/data"], [0x10, 0])
        self.assertEqual(watch_mac.parse(count, ptr, flags), [("dir", "/srv/data/docs"), ("dir", "/srv/data")])

    def test_dropped_or_must_scan_is_overflow(self):
        for flag in (watch_mac.MUST_SCAN, watch_mac.USER_DROPPED, watch_mac.KERNEL_DROPPED, watch_mac.ROOT_CHANGED):
            count, ptr, flags = fsevents_args(["/srv/data"], [flag])
            self.assertEqual(watch_mac.parse(count, ptr, flags), [("overflow", None)])

    def test_stream_created_started_and_delivers(self):
        cs, cf, system = mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
        cs.FSEventStreamCreate.return_value = 77
        cs.FSEventStreamStart.return_value = True
        cf.CFStringCreateWithCString.side_effect = [11, 12]
        with mock.patch.object(watch_mac, "array_callbacks", return_value=0):
            fs = watch_mac.FSEvents(["/srv/data", "/home/alice"], libs=(cs, cf, system))
        self.assertEqual(cf.CFStringCreateWithCString.call_count, 2)
        args = cs.FSEventStreamCreate.call_args.args
        self.assertEqual((args[4], args[6]), (watch_mac.SINCE_NOW, watch_mac.NO_DEFER))
        cs.FSEventStreamSetDispatchQueue.assert_called_once()
        cs.FSEventStreamStart.assert_called_once_with(77)
        fs._on_events(None, None, *fsevents_args(["/srv/data/x/"], [0]), None)
        self.assertEqual(fs.read(0.5), [("dir", "/srv/data/x")])
        self.assertEqual(fs.read(0.01), [])
        fs.close()
        cs.FSEventStreamRelease.assert_called_once_with(77)


def notify_info(entries):
    """FILE_NOTIFY_INFORMATION chain, each entry DWORD-aligned."""
    out = b""
    for i, (action, name) in enumerate(entries):
        raw = name.encode("utf-16-le")
        body = struct.pack("<III", 0, action, len(raw)) + raw
        body += b"\0" * (-len(body) % 4)
        step = len(body) if i < len(entries) - 1 else 0
        out += struct.pack("<I", step) + body[4:]
    return out


class TestReadDirectoryChanges(unittest.TestCase):
    def test_parse_chain(self):
        data = notify_info([(watch_win.ADDED, "docs\\a.txt"), (watch_win.RENAMED_NEW, "b.txt"),
                            (watch_win.REMOVED, "docs\\old\\c.txt")])
        self.assertEqual(watch_win.parse(data, "C:\\Users\\alice"), [
            ("dir", "C:\\Users\\alice\\docs"), ("dir", "C:\\Users\\alice"), ("dir", "C:\\Users\\alice\\docs\\old")])

    def test_zero_bytes_is_overflow(self):
        self.assertEqual(watch_win.parse(b"", "C:\\data"), [("overflow", None)])

    def test_reader_thread_with_mocked_kernel32(self):
        k = mock.MagicMock()
        k.CreateFileW.return_value = 5
        data = notify_info([(watch_win.MODIFIED, "docs\\a.txt")])
        calls = []

        def fake_read(*args):
            handle, buf, size, subtree, notify, got = args[:6]
            calls.append((handle, size, subtree, notify))
            if len(calls) > 1:
                return 0                                  # the handle was closed: the thread ends
            ctypes.memmove(buf, data, len(data))
            got._obj.value = len(data)
            return 1

        k.ReadDirectoryChangesW.side_effect = fake_read
        dc = watch_win.DirChanges(["C:\\data"], k32=k)
        self.assertEqual(dc.read(2.0), [("dir", "C:\\data\\docs")])
        self.assertEqual(calls[0], (5, watch_win.BUFFER, True, watch_win.NOTIFY))
        self.assertEqual(k.CreateFileW.call_args.args[5], watch_win.BACKUP_SEMANTICS)
        dc.close()
        k.CancelIoEx.assert_called_once_with(5, None)
        k.CloseHandle.assert_called_once_with(5)
