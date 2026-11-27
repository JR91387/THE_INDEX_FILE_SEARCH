#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collector: folders. Standalone, stdlib only, READ-ONLY. `python3 -I folders.py '<options JSON>'` (as root
via sudo: contrib/folders_root.py). Every folder down to `depth` under each root gets an item (owner, group,
mode; blank owners without pwd/grp). Sizes and types are measured in rotation (one slot per run). Options: roots
(default per OS), depth, slots, slot, exclude, budget_s (an unfinished unit becomes a gap), ext, markers,
mixed_threshold, privileged."""
import contextlib
import importlib
import json
import os
import socket
import stat
import sys
import time
import zlib
from datetime import UTC, datetime

pwd, grp = (importlib.import_module(m) if os.name == "posix" else None for m in ("pwd", "grp"))

SKIP = ["/var/lib/docker", "/var/lib/containers", "/var/lib/snapd", "/var/cache", "/proc", "/sys", "/dev", "/run",
        "lost+found"]
HOME = os.path.expanduser("~")
ROOTS = {"darwin": [HOME, "/Users", "/Applications"],     # per-OS scan roots; Linux keeps its fixed list
         "win32": [os.environ.get("USERPROFILE", HOME), *(os.listdrives() if hasattr(os, "listdrives") else ["C:\\"])]}
DEFAULTS = {"roots": ROOTS.get(sys.platform, ["/home", "/srv", "/opt", "/var/lib"]), "depth": 2, "slots": 7,
            "slot": 0, "exclude": [], "budget_s": 1800, "ext": {}, "markers": {}, "mixed_threshold": 0.6}


def utc(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def name_of(db, func, ident):
    """Name for a user/group id; the id itself if unknown; blank without the pwd/grp modules."""
    with contextlib.suppress(KeyError):
        return getattr(db, func)(ident)[0] if db else ""
    return str(ident)


def folder_item(path, st):
    return {"kind": "folder", "key": path, "carry": ["primary_content"], "metrics": {},
            "attrs": {"owner": name_of(pwd, "getpwuid", st.st_uid), "group": name_of(grp, "getgrgid", st.st_gid),
                      "mode": oct(stat.S_IMODE(st.st_mode))}}


def type_of(filename, ext_map):
    """Longest matching extension wins ('.sql.gz' before '.gz')."""
    parts = filename.lower().split(".")
    for n in range(min(3, len(parts) - 1), 0, -1):
        if hit := ext_map.get("." + ".".join(parts[-n:])):
            return hit
    return "unknown"


class Tally:
    """Size, count, newest, biggest and bytes-per-type for one tracked folder."""

    def __init__(self):
        self.size = self.files = 0
        self.newest = self.biggest = (-1, None)
        self.types = {}
        self.marker = None

    def add(self, path, st, kind):
        self.size += st.st_size
        self.files += 1
        self.newest = max(self.newest, (st.st_mtime, path), key=lambda t: t[0])   # numbers only: paths may tie
        self.biggest = max(self.biggest, (st.st_size, path), key=lambda t: t[0])
        count, size = self.types.get(kind, (0, 0))
        self.types[kind] = (count + 1, size + st.st_size)

    def primary(self, threshold):
        if self.marker or not self.files:
            return self.marker or "empty"
        kind, (_, size) = max(self.types.items(), key=lambda kv: kv[1][1])
        return kind if self.size and size / self.size >= threshold else "mixed"


def add_gap(out, target, reason, kind="denied"):
    if len(out["gaps"]) < 50:
        out["gaps"].append({"kind": kind, "target": target, "reason": reason[:200]})


def count_files(root, files, owners, ext_map):
    for name in files:
        path = os.path.join(root, name)
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            kind = type_of(name, ext_map)
            for tally in owners:
                tally.add(path, st, kind)


def walk_unit(top, tracked, opts, out):
    """Walk one rotation unit once (one filesystem, no symlinks); None when the time budget ran out."""
    dev = os.lstat(top).st_dev
    tallies = {p: Tally() for p in tracked if p == top or p.startswith(top + "/")}

    def denied(err):
        add_gap(out, err.filename or top, "cannot list folder")
        out["coverage_except"].append((err.filename or top) + "/")

    for root, dirs, files in os.walk(top, onerror=denied):
        if time.monotonic() > opts["_deadline"]:
            return None
        dirs[:] = [d for d in dirs if not excluded(os.path.join(root, d), opts) and same_dev(os.path.join(root, d), dev)]
        owners = [t for p, t in tallies.items() if root == p or root.startswith(p + "/")]
        if root in tallies:
            tallies[root].marker = next((opts["markers"][n] for n in dirs + files if n in opts["markers"]), None)
        count_files(root, files, owners, opts["ext"])
    return tallies


def same_dev(path, dev):
    """True if path is on filesystem `dev` (other mounts are their own roots); vanished paths -> False."""
    with contextlib.suppress(OSError):
        return os.lstat(path).st_dev == dev
    return False


def excluded(path, opts):
    """An exclude entry with a '/' is a path prefix; one without matches any folder of that name."""
    return any(path == e or path.startswith(e + "/") if "/" in e else os.path.basename(path) == e
               for e in opts["exclude"])


def list_tracked(opts, out):
    """Every folder down to `depth` under each root: {path: lstat}. Unlistable folders become gaps."""
    found = {}
    for root in opts["roots"]:
        stack = [(root.rstrip("/") or "/", 0)]
        while stack:
            path, level = stack.pop()
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not stat.S_ISDIR(st.st_mode) or excluded(path, opts):
                continue
            found[path] = st
            if level < opts["depth"]:
                stack += [(e.path, level + 1) for e in scandir(path, out) if e.is_dir(follow_symlinks=False)]
        out["coverage"].append(root.rstrip("/") + "/")
    return found


def scandir(path, out):
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError as exc:
        add_gap(out, path, str(exc))
        out["coverage_except"].append(path + "/")
        return []


def measure(tracked, opts, out):
    """Walk this slot's units (folders one level under a root); one past budget_s keeps its last values."""
    opts["_deadline"] = time.monotonic() + float(opts["budget_s"])
    roots = {r.rstrip("/") or "/" for r in opts["roots"]}
    units = [p for p in tracked if p not in roots and os.path.dirname(p) in roots]
    slots = max(1, opts["slots"])
    for unit in (u for u in units if zlib.crc32(u.encode()) % slots == opts["slot"] % slots):
        tallies = walk_unit(unit, tracked, opts, out)
        if tallies is None:
            add_gap(out, unit, "budget exceeded", "not_visible")
        for path, tally in (tallies or {}).items():
            item = out["_items"][path]
            item["attrs"]["primary_content"] = tally.primary(opts["mixed_threshold"])
            big = tally.biggest[1]
            item["metrics"] = {"size_bytes": tally.size, "file_count": tally.files,
                               "newest_mtime": utc(tally.newest[0]) if tally.newest[1] else None,
                               "biggest_file": os.path.basename(big) if big and opts.get("privileged") else big}
            item["content"] = [{"type": k, "files": c, "bytes": b} for k, (c, b) in sorted(tally.types.items())]


def scan(given):
    """The payload for one run; `given` = options (defaults, caller options and the built-in SKIP list merged)."""
    out = {"collector": "folders", "script": "folders", "host": socket.gethostname(), "kinds": ["folder"],
           "started_at": utc(), "items": [], "gaps": [], "errors": [], "coverage": [], "coverage_except": []}
    try:
        opts = {**DEFAULTS, **given}
        opts["exclude"] = sorted(set(SKIP) | set(opts["exclude"]))
        tracked = list_tracked(opts, out)
        out["_items"] = {p: folder_item(p, st) for p, st in tracked.items()}
        measure(tracked, opts, out)
        out["items"] = list(out.pop("_items").values())
    except Exception as exc:  # noqa: BLE001 -- always print a payload; an error makes the run partial
        out["errors"].append(f"folders: {type(exc).__name__}: {exc}")
        out.pop("_items", None)
    out.update(status="partial" if out["errors"] else "ok", finished_at=utc())
    return out


if __name__ == "__main__":
    print(json.dumps(scan(json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}), indent=1, sort_keys=True))
