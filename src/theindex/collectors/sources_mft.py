# SPDX-License-Identifier: MIT
"""sources: the NTFS master file table as a native source (Everything's method). Standalone, stdlib only, READ-ONLY.
Imported by sources_tools.py. Windows + Administrator + NTFS only: opens the volume (device path of the drive) read
only, reads the USN journal's next USN (FSCTL_QUERY_USN_JOURNAL), then walks every file record (FSCTL_ENUM_USN_DATA,
parsing USN_RECORD_V2). Records carry names and parent references only, no size or time, so sources_model stats each
file under the configured roots, exactly as it does for plocate. Reparse-point directories are listed, not entered.
UNVERIFIED: written without a Windows host; structs and control codes follow Microsoft's documentation and are
exercised only through fakes in tests/test_sources_mft.py. Any failure means "not usable": the caller falls back."""
import ctypes
import os
import struct
import sys

FSCTL_QUERY_USN_JOURNAL, FSCTL_ENUM_USN_DATA = 0x900F4, 0x900B3
ERROR_HANDLE_EOF = 38
GENERIC_READ, SHARE_READ_WRITE, OPEN_EXISTING, BACKUP_SEMANTICS = 0x80000000, 3, 3, 0x02000000
ATTR_REPARSE = 0x400
FRN_MASK, NTFS_ROOT_FRN, BUFFER_SIZE = (1 << 48) - 1, 5, 1 << 20
RECORD_HEAD = struct.Struct("<IHHQQqqIIIIHH")                     # USN_RECORD_V2 up to FileNameOffset: 60 bytes
CACHE = {}


class IoError(OSError):
    """DeviceIoControl failed; `code` is the Win32 error."""
    def __init__(self, code):
        super().__init__(f"Win32 error {code}")
        self.code = code


def parse_records(buf):
    """Yield (frn, parent_frn, attributes, name) for each USN_RECORD_V2 in one ENUM_USN_DATA output buffer."""
    pos = 8                                                         # the buffer starts with the next start FRN
    while pos + RECORD_HEAD.size <= len(buf):
        f = RECORD_HEAD.unpack_from(buf, pos)
        length, major, frn, parent, attrs, nlen, noff = f[0], f[1], f[3], f[4], f[10], f[11], f[12]
        if length < RECORD_HEAD.size or pos + length > len(buf):
            break
        if major == 2:
            name = buf[pos + noff:pos + noff + nlen].decode("utf-16-le", "replace")
            yield frn & FRN_MASK, parent & FRN_MASK, attrs, name
        pos += length


def enumerate_records(device_io, high_usn):
    """All records of a volume: `device_io(code, data, outsize) -> bytes` is called until it raises EOF (38)."""
    start = 0
    while True:
        try:
            buf = device_io(FSCTL_ENUM_USN_DATA, struct.pack("<Qqq", start, 0, high_usn), BUFFER_SIZE)
        except IoError as err:
            if err.code == ERROR_HANDLE_EOF:
                return
            raise
        if len(buf) <= 8:
            return
        start = struct.unpack_from("<Q", buf)[0]
        yield from parse_records(buf)


def resolve_paths(records, root_frn, drive):
    """{frn: full path} for every record reachable from `root_frn`; nothing below a reparse-point directory."""
    table = {frn: (parent, attrs, name) for frn, parent, attrs, name in records}
    paths, skipped = {root_frn: drive.rstrip("\\/") + "\\"}, set()
    for start in table:
        chain, frn = [], start
        while frn not in paths and frn not in skipped and frn in table and len(chain) < 4096:
            chain.append(frn)
            frn = table[frn][0]
        for item in reversed(chain):
            parent, _attrs, name = table[item]
            base = paths.get(parent)
            if base is None or table.get(parent, (0, 0, ""))[1] & ATTR_REPARSE:
                skipped.add(item)
            else:
                paths[item] = base.rstrip("\\") + "\\" + name
    return {frn: paths[frn] for frn in table if frn in paths}


def fold(path):
    return path.replace("/", "\\").lower().rstrip("\\")


def under(paths, root):
    """Paths equal to or below `root`, compared case-insensitively (NTFS)."""
    top = fold(root)
    for path in paths:
        low = fold(path)
        if low == top or low.startswith(top + "\\"):
            yield path


def api():
    """kernel32 entry points with explicit argtypes/restype; only ever called on Windows."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)           
    void, dword = ctypes.c_void_p, ctypes.c_uint32
    k32.CreateFileW.argtypes = [ctypes.c_wchar_p, dword, dword, void, dword, dword, void]
    k32.CreateFileW.restype = void
    k32.DeviceIoControl.argtypes = [void, dword, void, dword, void, dword, ctypes.POINTER(dword), void]
    k32.DeviceIoControl.restype = ctypes.c_int
    k32.GetFileInformationByHandle.argtypes = [void, void]
    k32.GetFileInformationByHandle.restype = ctypes.c_int
    k32.CloseHandle.argtypes = [void]
    k32.CloseHandle.restype = ctypes.c_int
    return k32


def open_handle(k32, name, flags):
    handle = k32.CreateFileW(name, GENERIC_READ, SHARE_READ_WRITE, None, OPEN_EXISTING, flags, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise IoError(ctypes.get_last_error())                   
    return handle


def make_device_io(k32, handle):
    def device_io(code, data, outsize):
        out, got = ctypes.create_string_buffer(outsize), ctypes.c_uint32(0)
        if not k32.DeviceIoControl(handle, code, data, len(data), out, outsize, ctypes.byref(got), None):
            raise IoError(ctypes.get_last_error())
        return out.raw[:got.value]
    return device_io


def root_frn(k32, drive):
    """The volume root's record number from its directory handle (5 on NTFS when that fails)."""
    try:
        handle = open_handle(k32, drive.rstrip("\\/") + "\\", BACKUP_SEMANTICS)
    except IoError:
        return NTFS_ROOT_FRN
    try:
        info = (ctypes.c_uint32 * 13)()                             # BY_HANDLE_FILE_INFORMATION
        if not k32.GetFileInformationByHandle(handle, ctypes.addressof(info)):
            return NTFS_ROOT_FRN
        return ((info[11] << 32) | info[12]) & FRN_MASK
    finally:
        k32.CloseHandle(handle)


def drive_of(path):
    drive = os.path.splitdrive(path)[0]
    return drive if len(drive) == 2 and drive[1] == ":" else None


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())        
    except (AttributeError, OSError):
        return False


def journal_high_usn(device_io):
    """NextUsn from USN_JOURNAL_DATA_V0 (journal id, first USN, next USN); fails when the volume is not NTFS."""
    _journal_id, _first, next_usn = struct.unpack_from("<Qqq", device_io(FSCTL_QUERY_USN_JOURNAL, b"", 64))
    return next_usn


def read_volume(drive):
    """Every path of the volume (cached for the run); raises on any failure."""
    key = drive.upper()
    if key not in CACHE:
        k32 = api()
        handle = open_handle(k32, "\\\\.\\" + drive, 0)
        try:
            device_io = make_device_io(k32, handle)
            records = list(enumerate_records(device_io, journal_high_usn(device_io)))
        finally:
            k32.CloseHandle(handle)
        CACHE[key] = list(resolve_paths(records, root_frn(k32, drive), drive + "\\").values())
    return CACHE[key]


def usable(opts):
    """True when this is Windows, running as Administrator, and every configured root's volume reads as NTFS."""
    if (opts.get("platform") or sys.platform) != "win32" or not is_admin():
        return False
    try:
        return all(drive_of(r) and read_volume(drive_of(r)) is not None for r in opts.get("roots", []))
    except (OSError, ValueError, struct.error, AttributeError):
        return False


def paths_under(root):
    """Generator of every path at or below `root` from the volume's file table."""
    return under(read_volume(drive_of(root)), root)
