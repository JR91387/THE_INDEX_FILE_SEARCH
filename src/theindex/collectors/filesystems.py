#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collector: mounted filesystems (real disks and network shares). Standalone, stdlib only:
    ssh host python3 - < filesystems.py
Reads /proc/self/mounts and statvfs. A mount that does not answer in time becomes a gap, not a hang."""
import json
import os
import socket
import sys
import threading
from datetime import UTC, datetime

NETWORK = {"cifs", "smb3", "nfs", "nfs4", "fuse.sshfs", "fuse.rclone", "9p", "davfs"}
SKIP = ("/proc", "/sys", "/dev", "/run", "/snap", "/var/lib/docker", "/var/snap")  # pseudo or runtime
KEEP = ("/run/media",)                                   # removable drives
TIMEOUT_S = 5


def utc_now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def unescape(field):
    """/proc/mounts escapes spaces and tabs as octal (\\040)."""
    return field.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def skipped(target):
    """True for pseudo/runtime mountpoints (a path equal to or under SKIP, unless under KEEP)."""
    def under(roots):
        return any(target == r or target.startswith(r + "/") for r in roots)
    return under(SKIP) and not under(KEEP)


def mounts(text):
    """(source, mountpoint, fstype, options) for real disks and network shares only."""
    found = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        source, target, fstype, options = unescape(parts[0]), unescape(parts[1]), parts[2], parts[3]
        real = source.startswith("/dev/") or fstype in NETWORK or fstype == "zfs"
        if real and not skipped(target) and fstype != "squashfs":
            found.append((source, target, fstype, options))
    return found


def statvfs(path):
    """(size_bytes, used_bytes) or None if the mount does not answer within TIMEOUT_S."""
    result = {}

    def probe():
        try:
            st = os.statvfs(path)
            result["v"] = (st.f_blocks * st.f_frsize, (st.f_blocks - st.f_bfree) * st.f_frsize)
        except OSError as exc:
            result["e"] = exc

    worker = threading.Thread(target=probe, daemon=True)  # daemon: a hung mount cannot block exit
    worker.start()
    worker.join(TIMEOUT_S)
    if "e" in result:
        raise result["e"]
    return result.get("v")


def item_of(entry, out):
    source, target, fstype, options = entry
    item = {"kind": "filesystem", "key": target, "metrics": {},
            "attrs": {"source": source, "fstype": fstype, "read_only": "ro" in options.split(",")}}
    try:
        sizes = statvfs(target)
    except OSError as exc:
        out["gaps"].append({"kind": "denied", "target": target, "reason": str(exc)[:200]})
        return item
    if sizes is None:
        out["gaps"].append({"kind": "not_visible", "target": target, "reason": f"no answer in {TIMEOUT_S}s"})
    else:
        item["metrics"] = {"size_bytes": sizes[0], "used_bytes": sizes[1]}
    return item


def collect(out):
    try:
        with open("/proc/self/mounts") as fh:
            entries = mounts(fh.read())
        out["coverage"].append("")
        seen = set()
        for entry in entries:
            if entry[1] not in seen:          # the same mountpoint can appear twice (stacked mounts)
                seen.add(entry[1])
                out["items"].append(item_of(entry, out))
    except OSError as exc:
        out["errors"].append(f"/proc/self/mounts: {exc}")


def main():
    out = {"collector": "filesystems", "script": "filesystems", "host": socket.gethostname(),
           "kinds": ["filesystem"], "started_at": utc_now(), "items": [], "gaps": [], "errors": [], "coverage": []}
    if not sys.platform.startswith("linux"):
        out["gaps"].append({"kind": "unsupported", "target": "filesystems", "reason": "needs /proc/self/mounts"})
    else:
        collect(out)
    out["status"] = "partial" if out["errors"] else "ok"
    out["finished_at"] = utc_now()
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
