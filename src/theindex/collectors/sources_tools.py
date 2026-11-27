# SPDX-License-Identifier: MIT
"""sources: readers for the index the OS already keeps. Standalone, stdlib only, READ-ONLY. Imported by sources.py.
Each reader yields absolute path strings for one root; sources_model.py stats them. Tool flags that could not be
verified on a real host are marked UNVERIFIED; output is parsed defensively and any failure becomes an error."""
import csv
import os
import re
import shutil
import subprocess
import sys
import time

import sources_mft as mft

STALE_S = 2 * 86400
LOCATE_DBS = ["/var/lib/plocate/plocate.db", "/var/lib/mlocate/mlocate.db", "/var/lib/locate/locatedb",
              "/var/lib/findutils/locatedb", "/var/db/locate.database"]
GLOB_CHARS = set("*?[\\")
ABSOLUTE = re.compile(r"^(/|[A-Za-z]:[\\/]|\\\\)")


def locate_fresh(opts):
    """True when a locate database was rebuilt within the last 2 days. Test hook: THE_INDEX_LOCATE_DB (a path
    list separated by os.pathsep) or option `locate_db` replaces the default database paths."""
    env = os.environ.get("THE_INDEX_LOCATE_DB")
    for path in opts.get("locate_db") or (env.split(os.pathsep) if env else LOCATE_DBS):
        try:
            if time.time() - os.stat(path).st_mtime <= STALE_S:
                return True
        except OSError:
            continue
    return False


def detect(opts):
    """(source, exe, reason). source is None when nothing usable is installed; reason says why."""
    platform = opts.get("platform") or sys.platform
    if platform == "darwin":
        exe = shutil.which("mdfind")
        return ("spotlight", exe, "") if exe else (None, None, "mdfind not found")
    if platform == "win32":
        if mft.usable(opts):                                   # Administrator on NTFS: the file table, before es
            return "mft", None, ""
        exe = shutil.which("es") or shutil.which("es.exe")
        return ("everything", exe, "") if exe else (None, None, "Everything command line (es) not found")
    exe = shutil.which("plocate") or shutil.which("locate")
    if not exe:
        return None, None, "plocate/locate not found"
    if not locate_fresh(opts):
        return None, None, "locate database missing or older than 2 days"
    return "plocate", exe, ""


def pieces(proc, sep):
    """Split a binary stdout on `sep` without holding it all; names keep undecodable bytes (surrogateescape)."""
    buf = b""
    for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
        parts = (buf + chunk).split(sep)
        buf = parts.pop()
        for part in parts:
            if part:
                yield os.fsdecode(part)
    if buf:
        yield os.fsdecode(buf)


def spawn(argv, text=False):
    kw = {"encoding": "utf-8", "errors": "replace"} if text else {}
    return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            text=text, **kw)


def guard(proc, gen, name, ok_codes=(0,)):
    """Yield from `gen`; a clean end needs an accepted exit code; always reap the child."""
    try:
        yield from gen
        proc.stdout.close()
        if proc.wait() not in ok_codes:
            raise RuntimeError(f"{name} exited {proc.returncode}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def es_paths(proc):
    """First CSV column (the full path in es's default layout). A header row or relative row is ignored."""
    for row in csv.reader(proc.stdout):
        if row and ABSOLUTE.match(row[0]):
            yield row[0]


def run_reader(source, exe, root):
    """Generator of paths below `root` from the tool; the caller filters by prefix and stats."""
    if source == "plocate":
        if GLOB_CHARS & set(root):
            raise RuntimeError("root contains glob characters; locate cannot match it literally")
        proc = spawn([exe, "-0", "--", root])                  # exit 1 = no match
        return guard(proc, pieces(proc, b"\0"), "locate", (0, 1))
    if source == "spotlight":
        proc = spawn([exe, "-0", "-onlyin", root, 'kMDItemFSName == "*"'])
        return guard(proc, pieces(proc, b"\0"), "mdfind")
    if source == "mft":
        return mft.paths_under(root)                           # UNVERIFIED on a real host (see sources_mft.py)
    # UNVERIFIED on a real host: -path, -csv, -size, -dm (as documented by the Everything command line help)
    proc = spawn([exe, "-path", root, "-csv", "-size", "-dm"], text=True)
    return guard(proc, es_paths(proc), "es")


def mdls_titles(paths, limit):
    """{path: title} from Spotlight's kMDItemTitle for `paths`, 64 per call; a batch that does not parse is dropped."""
    exe = shutil.which("mdls")
    out = {}
    if not exe:
        return out
    for start in range(0, min(len(paths), limit), 64):
        batch = paths[start:start + 64]
        try:
            raw = subprocess.run([exe, "-raw", "-name", "kMDItemTitle", *batch], capture_output=True, timeout=60,
                                 check=False).stdout.split(b"\0")
        except (OSError, subprocess.TimeoutExpired):
            continue
        if len(raw) == len(batch) + 1 and raw[-1] == b"":
            raw.pop()
        if len(raw) != len(batch):
            continue
        for path, value in zip(batch, raw, strict=True):
            title = value.decode("utf-8", "replace").strip()
            if title and title != "(null)":
                out[path] = title[:300]
    return out
