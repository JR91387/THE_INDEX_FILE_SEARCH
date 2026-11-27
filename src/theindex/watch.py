# SPDX-License-Identifier: MIT
"""`the-index watch`: keep the file index current from the OS change feed (see docs/DESIGN.md, Live updates).

Events become a set of changed folders, debounced: a flush runs when no event came for `debounce_s`, or at the
latest every 10 x `debounce_s` under constant churn. Each flush lists exactly those folders (watch_flush.py) and
is skipped, the folders kept, while a scan holds the lock. Lost events (a full OS queue, too many changed folders
at once, a failed listing) mark the next scan as a full walk and open one gap. Prints nothing; errors are one
line on stderr. The backend is watch_linux / watch_mac / watch_win, picked by sys.platform."""
import os
import sqlite3
import sys
import time
from contextlib import closing

from . import db, files_ingest, files_run, watch_flush

MAX_PENDING = 20_000          # changed folders held at once; more = lost events (bounded memory)
RESYNC_S = 3600               # re-read the folder list (new watches) and refresh the watch's gaps
IDLE_S = 1.0                  # longest wait for events, so a stop request is seen


class Pending:
    """The changed folders not yet listed, with the debounce clock."""

    def __init__(self, debounce, cap=MAX_PENDING, clock=time.monotonic):
        self.debounce, self.cap, self.clock = float(debounce), cap, clock
        self.dirs, self.first, self.last, self.not_before, self.overflow = set(), None, None, 0.0, False

    def add(self, path):
        if path not in self.dirs and len(self.dirs) >= self.cap:
            self.overflow = True
            return
        now = self.clock()
        self.dirs.add(path)
        self.first = self.first if self.first is not None else now
        self.last = now

    def ready_at(self):
        """Monotonic time of the next flush, or None when nothing is pending."""
        if not self.dirs:
            return None
        return max(self.not_before, min(self.last + self.debounce, self.first + 10 * self.debounce))

    def due(self):
        at = self.ready_at()
        return at is not None and self.clock() >= at

    def wait(self):
        at = self.ready_at()
        return IDLE_S if at is None else min(IDLE_S, max(0.0, at - self.clock()))

    def take(self):
        dirs = self.dirs
        self.dirs, self.first, self.last, self.overflow = set(), None, None, False
        return dirs

    def defer(self, dirs):
        """A scan holds the lock: keep the folders, try again one debounce later."""
        for path in dirs:
            self.add(path)
        self.not_before = self.clock() + self.debounce


def open_backend(roots):
    if sys.platform == "darwin":
        from . import watch_mac
        return watch_mac.FSEvents(roots)
    if sys.platform == "win32":
        from . import watch_win
        return watch_win.DirChanges(roots)
    from . import watch_linux
    return watch_linux.Inotify()


def watch_dirs(conn, cfg, roots):
    """Folders to watch, the roots first, then the most recently changed (dir.mtime_ns) first."""
    ci = watch_flush.case_insensitive()
    keys = [files_ingest.root_key(r, ci) for r in roots]
    rows = conn.execute("SELECT d.path, d.path_key FROM dir d JOIN device v ON v.id = d.device_id WHERE v.name = ? "
                        "AND d.retired_run IS NULL AND d.is_cache = 0 ORDER BY d.mtime_ns DESC", (cfg.device_name,))
    found = [os.path.normpath(r) for r in roots]
    seen = set(found)
    for path, key in rows:
        if path not in seen and files_ingest.under(key, keys):
            found.append(path)
    return found


class Watcher:
    def __init__(self, conn, cfg, backend):
        self.conn, self.cfg, self.backend = conn, cfg, backend
        self.pending = Pending(cfg.watch.get("debounce_s", 2))
        self.roots = watch_flush.watch_roots(conn, cfg)
        self.unwatched, self.synced = 0, 0.0

    def sync(self):
        """Add watches (inotify only: the others watch whole subtrees) and record the watch's gaps."""
        if self.backend.limit is not None:
            paths = watch_dirs(self.conn, self.cfg, self.roots)
            added = sum(1 for p in paths if self.backend.add(p))
            self.unwatched = len(paths) - added if self.backend.full else 0
        self.synced = time.monotonic()
        watch_flush.record(self.conn, self.cfg, self.gaps())

    def gaps(self):
        out = []
        if self.unwatched:
            out.append({"kind": "budget", "target": "watch: folders", "reason":
                        f"{self.unwatched} folders not watched (inotify budget {self.backend.limit}); "
                        "the scheduled scan covers them"})
        if files_run.full_marked(self.conn):
            reason = self.conn.execute("SELECT value FROM setting WHERE key = ?", (files_run.FULL_NEXT,)).fetchone()[0]
            out.append({"kind": "budget", "target": "watch: events", "reason": f"{reason}; the next scan walks everything"})
        return out

    def lost(self, reason):
        files_run.mark_full(self.conn, reason)
        self.pending.take()
        watch_flush.record(self.conn, self.cfg, self.gaps())

    def handle(self, events):
        for kind, path in events:
            if kind == "overflow":
                return self.lost("watch: the OS change queue overflowed")
            if kind == "newdir":
                self.backend.add(path)
            self.pending.add(path)
        if self.pending.overflow:
            self.lost(f"watch: more than {self.pending.cap} folders changed at once")
        return None

    def flush(self):
        dirs = self.pending.take()
        result = watch_flush.flush(self.conn, self.cfg, dirs)
        if result is None:
            self.pending.defer(dirs)
        elif self.backend.limit is not None:
            for (path,) in self.conn.execute("SELECT path FROM dir WHERE seen_run = ? AND is_cache = 0 "
                                             "AND retired_run IS NULL", (result["run_id"],)).fetchall():
                if not self.backend.watched(path) and self.backend.add(path):
                    self.pending.add(path)    # list it once more: it may have changed before its watch existed
        return result

    def step(self):
        self.handle(self.backend.read(self.pending.wait()))
        if self.pending.due():
            try:
                self.flush()
            except (OSError, sqlite3.Error, ValueError, KeyError) as exc:
                print(f"watch: {exc}", file=sys.stderr)
                self.lost(f"watch: listing failed ({exc})")
        if time.monotonic() - self.synced >= RESYNC_S:
            self.sync()


def run(cfg, stop, backend=None):
    """Watch until stop.is_set(). backend: tests pass a fake; None opens the OS one."""
    with closing(db.init(cfg.db_path)) as conn:
        watcher = Watcher(conn, cfg, None)
        watcher.backend = backend or open_backend(watcher.roots)
        try:
            watcher.sync()
            while not stop.is_set():
                watcher.step()
        finally:
            watcher.backend.close()


def cmd_watch(cfg, args):
    import signal
    import threading
    if hasattr(os, "nice"):
        try:
            os.nice(10)
        except OSError:
            pass
    if getattr(args, "debounce", None):
        cfg.watch = {**cfg.watch, "debounce_s": float(args.debounce)}
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        run(cfg, stop)
    except KeyboardInterrupt:
        pass
    return 0
