# SPDX-License-Identifier: MIT
"""`watch`: live inotify on a temp tree with a temp database, debounce, lost events, watch budget, scan lock."""
import shutil
import sys
import threading
import time
import unittest

from test_files_target import TargetCase

from theindex import db, files_run, query, scan, watch

LINUX = sys.platform.startswith("linux")


class FakeBackend:
    def __init__(self, events=(), limit=None):
        self.events, self.limit, self.full, self.added = list(events), limit, False, []

    def watched(self, path):
        return path in self.added

    def add(self, path):
        if self.limit is not None and len(self.added) >= self.limit:
            self.full = True
            return False
        self.added.append(path)
        return True

    def read(self, timeout):
        out, self.events = self.events, []
        return out

    def close(self):
        pass


class TestPending(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.p = watch.Pending(1.0, cap=3, clock=lambda: self.now)

    def test_quiet_period(self):
        self.p.add("/srv/data/a")
        self.now = 0.9
        self.assertFalse(self.p.due())
        self.now = 1.0
        self.assertTrue(self.p.due())

    def test_constant_churn_flushes_at_ten_debounces(self):
        for step in range(11):
            self.now = step * 0.95
            self.p.add("/srv/data/a")
        self.assertFalse(self.p.due())
        self.now = 10.0
        self.assertTrue(self.p.due())

    def test_cap_and_defer(self):
        for name in "abcd":
            self.p.add(f"/srv/data/{name}")
        self.assertTrue(self.p.overflow)
        dirs = self.p.take()
        self.assertEqual(len(dirs), 3)
        self.now = 5.0
        self.p.defer(dirs)
        self.now = 5.5
        self.assertFalse(self.p.due())
        self.now = 6.0
        self.assertTrue(self.p.due())


class WatchCase(TargetCase):
    def watcher(self, backend):
        w = watch.Watcher(self.conn, self.cfg, backend)
        w.sync()
        return w

    def open_gaps(self):
        return self.conn.execute("SELECT g.target, g.reason FROM gap g JOIN ref_collector c ON c.id = g.collector_id "
                                 "WHERE c.code = 'watch' AND g.closed_run IS NULL").fetchall()


class TestWatcher(WatchCase):
    def test_overflow_marks_full_walk_and_opens_gap(self):
        w = self.watcher(FakeBackend([("dir", str(self.root / "a")), ("overflow", None)]))
        w.step()
        self.assertTrue(files_run.full_marked(self.conn))
        self.assertEqual([g[0] for g in self.open_gaps()], ["watch: events"])
        self.assertEqual(w.pending.dirs, set())
        files_run.run(self.conn, self.cfg)                # the full walk clears the mark ...
        w.sync()
        self.assertEqual(self.open_gaps(), [])            # ... and the next watch run closes the gap

    def test_too_many_changed_folders_is_lost_events(self):
        w = self.watcher(FakeBackend())
        w.pending.cap = 2
        w.handle([("dir", f"/srv/data/{n}") for n in "abc"])
        self.assertTrue(files_run.full_marked(self.conn))

    def test_budget_watches_newest_first_and_opens_one_gap(self):
        (self.root / "b" / "newer.txt").write_bytes(b"x")
        self.flush("b")
        backend = FakeBackend(limit=2)
        self.watcher(backend)
        self.assertEqual(backend.added, [str(self.root), str(self.root / "b")])
        gaps = self.open_gaps()
        self.assertEqual(len(gaps), 1)
        self.assertIn("3 folders not watched", gaps[0][1])

    def test_scan_lock_defers_flush(self):
        w = self.watcher(FakeBackend())
        w.pending.debounce = 0.0
        (self.root / "a" / "later.txt").write_bytes(b"l")
        w.handle([("dir", str(self.root / "a"))])
        with scan.scan_lock(self.path):
            w.step()
        self.assertEqual(w.pending.dirs, {str(self.root / "a")})
        w.pending.not_before = 0.0
        w.step()
        self.assertEqual(w.pending.dirs, set())
        self.assertEqual([h["name"] for h in query.find(self.conn, {"words": ["later"]})["results"]], ["later.txt"])


class LiveCase(WatchCase):
    def setUp(self):
        super().setUp()
        self.cfg.watch = {"debounce_s": 0.3}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=watch.run, args=(self.cfg, self.stop), daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 10)
        self.addCleanup(self.stop.set)
        self.reader = db.connect(self.path)
        self.addCleanup(self.reader.close)
        self.wait_for(lambda: self.reader.execute("SELECT count(*) FROM scan_run r JOIN ref_collector c "
                                                  "ON c.id = r.collector_id WHERE c.code = 'watch'").fetchone()[0])

    def wait_for(self, check, limit=3.0):
        """Seconds until check() is true; fails after `limit`."""
        start = time.monotonic()
        while time.monotonic() - start < limit:
            if check():
                return time.monotonic() - start
            time.sleep(0.02)
        self.fail("not visible within the time limit")

    def found(self, word):
        return [h["name"] for h in query.find(self.reader, {"words": [word]})["results"]]


@unittest.skipUnless(LINUX, "inotify is Linux only")
class TestLiveInotify(LiveCase):
    def test_create_rename_delete_nested(self):
        (self.root / "b" / "created.txt").write_bytes(b"c")
        self.wait_for(lambda: self.found("created") == ["created.txt"])
        (self.root / "b" / "created.txt").rename(self.root / "b" / "renamed.txt")
        self.wait_for(lambda: self.found("renamed") == ["renamed.txt"] and not self.found("created"))
        shutil.rmtree(self.root / "a" / "deep")
        self.wait_for(lambda: not self.found("three") and not self.found("two"))
        (self.root / "b" / "n1" / "n2").mkdir(parents=True)
        (self.root / "b" / "n1" / "n2" / "nested.txt").write_bytes(b"n")
        self.wait_for(lambda: self.found("nested") == ["nested.txt"])
        (self.root / "b" / "n1" / "n2" / "later.txt").write_bytes(b"l")     # the new dir is watched now
        self.wait_for(lambda: self.found("later") == ["later.txt"])
        self.assertEqual(self.found("one"), ["one.txt"])                   # nothing else retired
        self.assertEqual(self.found("four"), ["four.txt"])


def latency(case, samples=10):
    """Median seconds from file creation to visible in find (used by the report, not asserted)."""
    times = []
    for i in range(samples):
        (case.root / "b" / f"lat{i}x.txt").write_bytes(b"l")
        times.append(case.wait_for(lambda i=i: case.found(f"lat{i}x") == [f"lat{i}x.txt"]))
    return sorted(times)[samples // 2]


@unittest.skipUnless(LINUX, "inotify is Linux only")
class TestLatency(LiveCase):
    def test_create_to_find_latency(self):
        median = latency(self)
        self.assertLess(median, 3.0)
        if "-v" in sys.argv:
            print(f"\nwatch latency median of 10: {median:.3f} s", file=sys.stderr)
