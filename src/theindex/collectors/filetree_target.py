# SPDX-License-Identifier: MIT
"""filetree, targeted: list exactly the given directories (used by `the-index watch`). Standalone, stdlib only,
READ-ONLY. Imported by filetree.py. See README.md, section `filetree`.

Each target is listed whatever the state file says. A child directory found in the state file is reported as
`skip` and not entered; a child that is not there (new, or back after being retired) is listed with its whole
new subtree. A target that no longer exists is reported as `gone`, so the ingest can retire it and its subtree."""
import os
import stat

import filetree_walk as walk


def read_targets(opts):
    """Targets from `targets` (list) and `targets_file` (one path per line); a long list goes in a file
    because one command-line argument is limited to 128 KB on Linux."""
    found = list(opts.get("targets") or [])
    if opts.get("targets_file"):
        with open(opts["targets_file"], encoding="utf-8", errors="surrogateescape") as fh:
            found += [line.rstrip("\n") for line in fh if line.strip()]
    return sorted({os.path.normpath(p) for p in found}, key=lambda p: (p.count(os.sep), p))


class Targeted(walk.Walker):
    def __init__(self, opts, state, emit):
        super().__init__(opts, state, emit)
        self.targets = read_targets(opts)
        self.forced = {walk.path_key(p, self.ci) for p in self.targets}
        self.root_keys = {walk.path_key(os.path.normpath(r), self.ci) for r in opts.get("roots", [])}

    def run(self):
        for target in self.targets:
            self.add_target(target)
        while self.queue:
            if self.expired():
                return self.out_of_time()
            self.process(self.queue.popleft())

    def add_target(self, path):
        if path in self.mounts or walk.excluded(path, self.skip_patterns):
            return None
        key = walk.path_key(path, self.ci)
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return self.write({"t": "gone", "key": key, "path": path})
        except OSError as err:
            return self.gap(walk.gap_kind(err), path, err.strerror or "cannot stat")
        if not stat.S_ISDIR(st.st_mode):
            return self.write({"t": "gone", "key": key, "path": path})
        parent = None if key in self.root_keys else walk.path_key(os.path.dirname(path), self.ci)
        self.queue.append(walk.Node(path, key, parent, st, st.st_dev))
        return None

    def unchanged(self, node):
        return False                          # every directory that gets this far is listed

    def queue_dir(self, parent, path, st):
        key = walk.path_key(path, self.ci)
        if key in self.forced:
            return None                       # listed as its own target
        if key in self.state and st.st_dev == parent.dev and path not in self.mounts \
                and not walk.excluded(path, self.skip_patterns):
            return self.skip(walk.Node(path, key, parent.key, st, parent.dev))
        return super().queue_dir(parent, path, st)
