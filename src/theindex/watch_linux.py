# SPDX-License-Identifier: MIT
"""`watch` on Linux: inotify through ctypes on libc. One watch per directory (inotify is not recursive).

Events become (kind, path) tuples for watch.py: ("dir", folder that changed), ("newdir", folder that appeared:
watch it and list it), ("overflow", None) when the kernel queue overflowed and events were lost."""
import ctypes
import os
import select
import struct

IN_MODIFY, IN_ATTRIB, IN_CLOSE_WRITE = 0x2, 0x4, 0x8
IN_MOVED_FROM, IN_MOVED_TO, IN_CREATE, IN_DELETE = 0x40, 0x80, 0x100, 0x200
IN_DELETE_SELF, IN_MOVE_SELF, IN_Q_OVERFLOW, IN_IGNORED = 0x400, 0x800, 0x4000, 0x8000
IN_ONLYDIR, IN_DONT_FOLLOW, IN_EXCL_UNLINK, IN_ISDIR = 0x1000000, 0x2000000, 0x4000000, 0x40000000
MASK = (IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO | IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE
        | IN_DELETE_SELF | IN_ONLYDIR | IN_DONT_FOLLOW | IN_EXCL_UNLINK)
EVENT = struct.Struct("iIII")             # struct inotify_event: wd, mask, cookie, len; then name[len]
LIMIT_FILE = "/proc/sys/fs/inotify/max_user_watches"
HEADROOM = 1024


def budget(limit_file=LIMIT_FILE):
    """How many watches to use: at most min(limit - 1024, 90 % of the limit); other programs need some too."""
    try:
        with open(limit_file, encoding="ascii") as fh:
            limit = int(fh.read().strip())
    except (OSError, ValueError):
        limit = 8192
    return max(0, min(limit - HEADROOM, int(limit * 0.9)))


def parse(data, paths):
    """Raw inotify bytes -> [(kind, path)]; paths maps wd -> directory and loses wds the kernel dropped."""
    out, at = [], 0
    while at + EVENT.size <= len(data):
        wd, mask, _cookie, size = EVENT.unpack_from(data, at)
        raw = data[at + EVENT.size:at + EVENT.size + size].split(b"\0", 1)[0]
        at += EVENT.size + size
        out += event(paths, (wd, mask, os.fsdecode(raw)))
    return out


def event(paths, ev):
    wd, mask, name = ev
    if mask & IN_Q_OVERFLOW:
        return [("overflow", None)]
    base = paths.get(wd)
    if mask & IN_IGNORED:
        paths.pop(wd, None)
        return []
    if base is None or mask & (IN_DELETE_SELF | IN_MOVE_SELF):
        return []                         # the parent's own event lists the parent
    if mask & IN_ISDIR and mask & (IN_CREATE | IN_MOVED_TO) and name:
        return [("dir", base), ("newdir", os.path.join(base, name))]
    return [("dir", base)]


class Inotify:
    """One inotify instance. add() returns False when the watch could not be added (gone, denied, no budget)."""

    def __init__(self, limit=None):
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.fd = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.paths, self.wds = {}, {}
        self.limit = budget() if limit is None else limit
        self.full = False                 # the budget (or the kernel's limit) was reached

    def watched(self, path):
        return path in self.wds

    def add(self, path):
        if path in self.wds:
            return True
        if len(self.paths) >= self.limit:
            self.full = True
            return False
        wd = self.libc.inotify_add_watch(self.fd, os.fsencode(path), MASK)
        if wd < 0:
            self.full = self.full or ctypes.get_errno() == 28          # ENOSPC: the user's watch limit
            return False
        old = self.paths.get(wd)              # same inode under a new name (a moved folder): repoint it
        if old is not None:
            self.wds.pop(old, None)
        self.paths[wd], self.wds[path] = path, wd
        return True

    def read(self, timeout):
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return []
        try:
            data = os.read(self.fd, 1 << 16)
        except BlockingIOError:
            return []
        out = parse(data, self.paths)
        self.wds = {p: w for w, p in self.paths.items()} if len(self.wds) != len(self.paths) else self.wds
        return out

    def close(self):
        os.close(self.fd)
