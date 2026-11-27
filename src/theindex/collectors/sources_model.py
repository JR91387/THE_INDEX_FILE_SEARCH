# SPDX-License-Identifier: MIT
"""sources: turns a flat path listing into the filetree record model. Standalone, stdlib only, READ-ONLY.
Imported by sources.py. Directories are derived from the parents of the files; a cache directory (marker name or
CACHEDIR.TAG) collapses to one record with subtree totals. Dir mtimes are left out on purpose: a directory the
native source listed is never mistaken for 'unchanged' by the next walk."""
import os
import stat
import time

import filetree_net as net
import filetree_walk as walk


class Budget(Exception):
    pass


class Model:
    def __init__(self, opts):
        self.o, self.ci = opts, walk.case_insensitive()
        self.skip = walk.SKIP + list(opts.get("exclude", []))
        self.mounts = net.network_mounts()
        self.markers = set(opts.get("cache_markers", []))
        self.dirs, self.root_of, self.memo, self.cmemo, self.ticks = {}, {}, {}, {}, 0
        self.deadline = time.monotonic() + float(opts.get("budget_s", 1800))
        self.tagged = set()

    def allowed(self, path, root):
        hit = self.memo.get(path)
        if hit is None:
            hit = not walk.excluded(path, self.skip) and path not in self.mounts and (
                path == root or self.allowed(os.path.dirname(path), root))
            self.memo[path] = hit
        return hit

    def add(self, path, root):
        """Keep one regular file below `root` (the native list also holds dirs, links and stale names)."""
        self.ticks += 1
        if self.ticks % 2048 == 0 and time.monotonic() > self.deadline:
            raise Budget("budget exceeded")
        prefix = os.path.normcase(root).rstrip(os.sep) + os.sep
        if not os.path.normcase(path).startswith(prefix):
            return
        folder, name = os.path.split(path)
        if not self.allowed(folder, root):
            return
        try:
            st = os.lstat(path)
        except OSError:
            return
        if stat.S_ISREG(st.st_mode):
            self.dirs.setdefault(folder, {})[name] = st
            self.root_of.setdefault(folder, root)

    def cache_root(self, folder):
        """The topmost cache directory at or above `folder` (within its root), or None."""
        if folder in self.cmemo:
            return self.cmemo[folder]
        root, chain, cur = self.root_of[folder], [], folder
        while True:
            chain.append(cur)
            if cur == root or os.path.dirname(cur) == cur:
                break
            cur = os.path.dirname(cur)
        found = next((c for c in reversed(chain) if os.path.basename(c) in self.markers or c in self.tagged), None)
        self.cmemo[folder] = found
        return found

    def resolve(self):
        """After all files are in: totals per cache root, listed dirs, and files counted per root."""
        self.tagged = {d for d, files in self.dirs.items() if "CACHEDIR.TAG" in files}
        self.totals, self.listed, self.counts = {}, set(), {}
        for folder, files in self.dirs.items():
            self.counts[self.root_of[folder]] = self.counts.get(self.root_of[folder], 0) + len(files)
            cache = self.cache_root(folder)
            if cache is None:
                self.listed.add(folder)
                continue
            self.root_of.setdefault(cache, self.root_of[folder])
            tot = self.totals.setdefault(cache, [0, 0])
            tot[0] += sum(st.st_size for st in files.values())
            tot[1] += len(files)

    def wanted(self):
        """{dir: root} for every record to emit: listed dirs, cache roots and all their ancestors."""
        want = {}
        for folder in self.listed | set(self.totals):
            root, cur = self.root_of[folder], folder
            while cur not in want:
                want[cur] = root
                if cur == root or os.path.dirname(cur) == cur:
                    break
                cur = os.path.dirname(cur)
        return want

    def key(self, path):
        return walk.path_key(path, self.ci)

    def dir_record(self, folder, root, ctx):
        files = self.dirs.get(folder, {}) if folder not in self.totals else {}
        size, count = self.totals.get(folder, (sum(s.st_size for s in files.values()), len(files)))
        names = set(files)
        agents = [m for m in ctx.get("agent_markers", [])
                  if (os.path.lexists(os.path.join(folder, m)) if "/" in m else m in names)] if files else []
        return {"t": "dir", "key": self.key(folder), "path": folder,
                "parent": None if folder == root else self.key(os.path.dirname(folder)),
                "mtime_ns": None, "ctime_ns": None, "size": size, "files": count,
                "cache": folder in self.totals, "agents": sorted(agents)}

    def file_records(self, folder, titles):
        for name, st in sorted(self.dirs.get(folder, {}).items()):
            rec = {"t": "file", "dir": self.key(folder), "name": name, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                   "ctime_ns": st.st_ctime_ns, "inode": st.st_ino}
            title = titles.get(os.path.join(folder, name))
            if title:
                rec.update(title=title, title_src="native", title_sig=f"{st.st_size}:{st.st_mtime_ns}")
            yield rec

    def records(self, titles):
        """Dir records parent-first (sorted by key), each followed by its files; cache dirs have no files."""
        want = self.wanted()
        for folder in sorted(want, key=self.key):
            yield self.dir_record(folder, want[folder], self.o)
            if folder in self.listed:
                yield from self.file_records(folder, titles)

    def title_candidates(self, exts, limit):
        """Newest title-type files in listed dirs: [path], at most `limit`."""
        found = [(st.st_mtime_ns, os.path.join(f, n)) for f in self.listed for n, st in self.dirs[f].items()
                 if os.path.splitext(n)[1].lower() in exts]
        return [p for _, p in sorted(found, reverse=True)[:limit]]
