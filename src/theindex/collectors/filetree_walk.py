# SPDX-License-Identifier: MIT
"""filetree walker. Standalone, stdlib only, READ-ONLY (stats entries, never opens a file or writes).
Imported by filetree.py (which puts this folder on sys.path). See README.md, section `filetree`."""
import os
import sys
import time
import unicodedata
from collections import deque
from datetime import UTC, datetime
from typing import NamedTuple

import filetree_net as net

SKIP = ["/var/lib/docker", "/var/lib/containers", "/var/lib/snapd", "/var/cache", "/proc", "/sys", "/dev", "/run",
        "lost+found"]


class Node(NamedTuple):
    path: str
    key: str
    parent: str | None
    st: os.stat_result
    dev: int


def utc(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def case_insensitive():
    return sys.platform in ("win32", "darwin")


def path_key(path, ci):
    key = unicodedata.normalize("NFC", path).replace("\\", "/")
    return key.casefold() if ci else key


def excluded(path, patterns):
    """A pattern with a '/' is a path prefix; one without matches any folder of that name."""
    return any(path == e or path.startswith(e + "/") if "/" in e else os.path.basename(path) == e for e in patterns)


def gap_kind(err):
    return "denied" if isinstance(err, PermissionError) else "unreadable"


class Walker:
    def __init__(self, opts, state, emit):
        self.o, self.state, self.write = opts, state, emit
        self.ci, self.win = case_insensitive(), sys.platform == "win32"
        self.skip_patterns = net.builtin_skips(SKIP, opts.get("roots", [])) + list(opts.get("exclude", []))
        self.sources = net.mount_sources()
        self.mounts = set(self.sources)
        self.seen_gaps, self.queue, self.errors = set(), deque(), []
        self.counts = {"dirs": 0, "files": 0, "skips": 0, "gaps": 0}
        self.partial, self.deadline = False, time.monotonic() + float(opts.get("budget_s", 1800))

    def gap(self, kind, target, reason):
        if (kind, target) in self.seen_gaps:
            return
        self.seen_gaps.add((kind, target))
        self.counts["gaps"] += 1
        self.write({"t": "gap", "kind": kind, "target": target, "reason": str(reason)[:200]})

    def expired(self):
        return time.monotonic() >= self.deadline

    def run(self):
        for root in self.o.get("roots", []):
            self.add_root(os.path.normpath(root))
        while self.queue:
            if self.expired():
                return self.out_of_time()
            self.process(self.queue.popleft())

    def add_root(self, root):
        if root in self.mounts or (self.win and net.windows_network(root)):
            return self.gap("network", root, self.sources.get(root, "network mount"))
        if excluded(root, self.skip_patterns):
            return None
        try:
            st = os.lstat(root)
        except OSError as err:
            return self.gap(gap_kind(err), root, err.strerror or "cannot stat")
        self.queue.append(Node(root, path_key(root, self.ci), None, st, st.st_dev))

    def out_of_time(self):
        self.partial = True
        self.gap("budget", self.queue[0].path, "budget exceeded")
        while self.queue:
            self.skip(self.queue.popleft())

    def skip(self, node):
        self.counts["skips"] += 1
        self.write({"t": "skip", "key": node.key, "path": node.path, "parent": node.parent,
                    "mtime_ns": node.st.st_mtime_ns, "ctime_ns": node.st.st_ctime_ns})

    def unchanged(self, node):
        if self.o.get("full") or node.key not in self.state:
            return False
        mtime, ctime = self.state[node.key]
        return mtime == node.st.st_mtime_ns and (self.win or ctime == node.st.st_ctime_ns)

    def process(self, node):
        if os.path.basename(node.path) in self.o.get("cache_markers", []):
            return self.skip(node) if self.unchanged(node) else self.cache(node)
        try:
            with os.scandir(node.path) as it:
                entries = list(it)
        except OSError as err:
            return self.gap(gap_kind(err), node.path, err.strerror or "cannot list")
        names = {e.name for e in entries}
        if "CACHEDIR.TAG" in names:
            return self.skip(node) if self.unchanged(node) else self.cache(node)
        if self.unchanged(node):
            self.skip(node)
        else:
            self.list_dir(node, entries, names)
        self.queue_children(node, entries)

    def queue_children(self, node, entries):
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                self.queue_dir(node, entry.path, entry.stat(follow_symlinks=False))
            except OSError:
                continue

    def queue_dir(self, parent, path, st):
        if excluded(path, self.skip_patterns):
            return
        if path in self.mounts:
            return self.gap("network", path, self.sources.get(path, "network mount"))
        if st.st_dev == parent.dev:
            self.queue.append(Node(path, path_key(path, self.ci), parent.key, st, parent.dev))

    def agents(self, node, names):
        found = []
        for marker in self.o.get("agent_markers", []):
            hit = os.path.lexists(os.path.join(node.path, marker)) if "/" in marker else marker in names
            if hit:
                found.append(marker)
        return sorted(found)

    def list_dir(self, node, entries, names):
        files = []
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=False):
                    files.append((entry.name, entry.stat(follow_symlinks=False)))
            except OSError:
                continue
        self.counts["dirs"] += 1
        self.counts["files"] += len(files)
        self.write({"t": "dir", "key": node.key, "path": node.path, "parent": node.parent,
                    "mtime_ns": node.st.st_mtime_ns, "ctime_ns": node.st.st_ctime_ns,
                    "size": sum(st.st_size for _, st in files), "files": len(files), "cache": False,
                    "agents": self.agents(node, names)})
        for name, st in files:
            self.write({"t": "file", "dir": node.key, "name": name, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                        "ctime_ns": st.st_ctime_ns, "inode": st.st_ino})

    def cache(self, node):
        """One dir record holding the subtree totals; the subtree itself is not listed."""
        size = files = 0
        stack = [node.path]
        while stack:
            if self.expired():
                self.queue.appendleft(node)     # unfinished: the budget check at the loop top reports it
                return
            more, add_size, add_files = self.cache_level(stack.pop(), node.dev)
            stack.extend(more)
            size, files = size + add_size, files + add_files
        self.counts["dirs"] += 1
        self.counts["files"] += files
        self.write({"t": "dir", "key": node.key, "path": node.path, "parent": node.parent,
                    "mtime_ns": node.st.st_mtime_ns, "ctime_ns": node.st.st_ctime_ns, "size": size,
                    "files": files, "cache": True, "agents": []})

    def cache_level(self, path, dev):
        subdirs, size, files = [], 0, 0
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except OSError as err:
            self.gap(gap_kind(err), path, err.strerror or "cannot list")
            return subdirs, size, files
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if entry.is_dir(follow_symlinks=False):
                if st.st_dev == dev:
                    subdirs.append(entry.path)
            elif entry.is_file(follow_symlinks=False):
                size, files = size + st.st_size, files + 1
        return subdirs, size, files
