# SPDX-License-Identifier: MIT
"""`watch` on macOS: one FSEvents stream over all roots (recursive, directory-level events), through ctypes on
CoreServices, delivered on a private dispatch queue into a thread-safe queue.

Unverified on a real host: written to the documented FSEvents C API (FSEventStreamCreate,
FSEventStreamSetDispatchQueue, FSEventStreamStart); tested with recorded callback arguments and mocked libraries."""
import ctypes
import ctypes.util
import queue

UTF8 = 0x08000100                          # kCFStringEncodingUTF8
SINCE_NOW = 0xFFFFFFFFFFFFFFFF             # kFSEventStreamEventIdSinceNow
NO_DEFER = 0x2                             # kFSEventStreamCreateFlagNoDefer: first event of a burst right away
MUST_SCAN, USER_DROPPED, KERNEL_DROPPED = 0x1, 0x2, 0x4
ROOT_CHANGED = 0x20
LOST = MUST_SCAN | USER_DROPPED | KERNEL_DROPPED
CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                            ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint64))


def parse(count, paths_ptr, flags):
    """Callback arguments -> [(kind, path)]. Without kFSEventStreamCreateFlagUseCFTypes, eventPaths is char**."""
    names = ctypes.cast(paths_ptr, ctypes.POINTER(ctypes.c_char_p))
    out = []
    for i in range(count):
        flag = flags[i]
        if flag & (LOST | ROOT_CHANGED):
            return [("overflow", None)]   # coalesced or dropped: only a full walk is safe
        path = names[i].decode("utf-8", "surrogateescape").rstrip("/") or "/"
        out.append(("dir", path))
    return out


def load():
    """(CoreServices, CoreFoundation, libSystem) as ctypes libraries with the argument types set."""
    cs = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreServices"))
    cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
    system = ctypes.cdll.LoadLibrary(ctypes.util.find_library("System"))
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFArrayCreate.restype = ctypes.c_void_p
    cf.CFArrayCreate.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_long, ctypes.c_void_p]
    cs.FSEventStreamCreate.restype = ctypes.c_void_p
    cs.FSEventStreamCreate.argtypes = [ctypes.c_void_p, CALLBACK, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_uint64, ctypes.c_double, ctypes.c_uint32]
    cs.FSEventStreamSetDispatchQueue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cs.FSEventStreamStart.argtypes = [ctypes.c_void_p]
    for name in ("FSEventStreamStop", "FSEventStreamInvalidate", "FSEventStreamRelease"):
        getattr(cs, name).argtypes = [ctypes.c_void_p]
    system.dispatch_queue_create.restype = ctypes.c_void_p
    system.dispatch_queue_create.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    return cs, cf, system


def array_callbacks(cf):
    """Address of kCFTypeArrayCallBacks (a data symbol, so CFArray retains the CFStrings)."""
    return ctypes.addressof(ctypes.c_void_p.in_dll(cf, "kCFTypeArrayCallBacks"))


class FSEvents:
    """All roots in one stream. add() is a no-op (FSEvents is recursive); there is no watch budget."""

    def __init__(self, roots, latency=0.5, libs=None):
        self.cs, cf, system = libs or load()
        self.events, self.full, self.limit = queue.SimpleQueue(), False, None
        self.callback = CALLBACK(self._on_events)          # kept on self: a collected callback crashes
        refs = [cf.CFStringCreateWithCString(None, r.encode(), UTF8) for r in roots]
        array = (ctypes.c_void_p * len(refs))(*refs)
        paths = cf.CFArrayCreate(None, array, len(refs), array_callbacks(cf))
        self.stream = self.cs.FSEventStreamCreate(None, self.callback, None, paths, SINCE_NOW, latency, NO_DEFER)
        if not self.stream:
            raise OSError("FSEventStreamCreate failed")
        self.cs.FSEventStreamSetDispatchQueue(self.stream, system.dispatch_queue_create(b"the-index.watch", None))
        if not self.cs.FSEventStreamStart(self.stream):
            raise OSError("FSEventStreamStart failed")

    def _on_events(self, *args):
        """FSEventStreamCallback(stream, info, numEvents, eventPaths, eventFlags, eventIds)."""
        _stream, _info, count, paths, flags, _ids = args
        for item in parse(count, paths, flags):
            self.events.put(item)

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
        for name in ("FSEventStreamStop", "FSEventStreamInvalidate", "FSEventStreamRelease"):
            getattr(self.cs, name)(self.stream)
