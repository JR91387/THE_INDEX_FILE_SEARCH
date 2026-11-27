# SPDX-License-Identifier: MIT
"""`watch` on Windows: ReadDirectoryChangesW through ctypes, one directory handle per root (subtree TRUE), each
read by a daemon thread into a thread-safe queue.

Unverified on a real host: written to the documented kernel32 calls (CreateFileW with
FILE_FLAG_BACKUP_SEMANTICS, ReadDirectoryChangesW, FILE_NOTIFY_INFORMATION); tested with recorded buffers and a
mocked kernel32."""
import ctypes
import ntpath
import queue
import struct
import threading

FILE_LIST_DIRECTORY, SHARE_ALL, OPEN_EXISTING = 0x1, 0x7, 3
BACKUP_SEMANTICS = 0x02000000
NOTIFY = 0x1 | 0x2 | 0x8 | 0x10          # FILE_NOTIFY_CHANGE_FILE_NAME | DIR_NAME | SIZE | LAST_WRITE
ADDED, REMOVED, MODIFIED, RENAMED_OLD, RENAMED_NEW = 1, 2, 3, 4, 5
INFO = struct.Struct("<III")              # NextEntryOffset, Action, FileNameLength (bytes); then WCHAR FileName[]
BUFFER = 1 << 16
INVALID = ctypes.c_void_p(-1).value


def parse(data, root):
    """A FILE_NOTIFY_INFORMATION chain -> [(kind, path)]. Zero bytes returned means the buffer overflowed."""
    if not data:
        return [("overflow", None)]
    out, at = [], 0
    while at + INFO.size <= len(data):
        step, _action, size = INFO.unpack_from(data, at)   # every action (ADDED...RENAMED_NEW) lists the folder
        name = data[at + INFO.size:at + INFO.size + size].decode("utf-16-le", "replace")
        path = ntpath.join(root, name)
        out.append(("dir", ntpath.dirname(path) or root))   # a new subfolder is listed with its parent
        if not step:
            break
        at += step
    return out


def kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = ctypes.c_void_p
    k.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                              ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    k.ReadDirectoryChangesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                        ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
                                        ctypes.c_void_p]
    k.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


class DirChanges:
    """One handle and one reader thread per root. add() is a no-op (the subtree is watched); no watch budget."""

    def __init__(self, roots, k32=None):
        self.k = k32 or kernel32()
        self.events, self.full, self.limit, self.handles = queue.SimpleQueue(), False, None, []
        for root in roots:
            handle = self.k.CreateFileW(root, FILE_LIST_DIRECTORY, SHARE_ALL, None, OPEN_EXISTING,
                                        BACKUP_SEMANTICS, None)
            if handle in (None, INVALID):
                raise OSError(f"cannot open {root} for change notification")
            self.handles.append(handle)
            threading.Thread(target=self._reader, args=(handle, root), daemon=True).start()

    def read_once(self, handle, root):
        """One blocking ReadDirectoryChangesW; False when the handle is closed or the call fails."""
        buf, got = ctypes.create_string_buffer(BUFFER), ctypes.c_uint32(0)
        if not self.k.ReadDirectoryChangesW(handle, buf, BUFFER, True, NOTIFY, ctypes.byref(got), None, None):
            return False
        for item in parse(buf.raw[:got.value], root):
            self.events.put(item)
        return True

    def _reader(self, handle, root):
        while self.read_once(handle, root):
            pass

    def add(self, path):
        return True

    def read(self, timeout):
        try:
            out = [self.events.get(timeout=timeout)]
        except queue.Empty:
            return []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        for handle in self.handles:
            self.k.CancelIoEx(handle, None)
            self.k.CloseHandle(handle)
