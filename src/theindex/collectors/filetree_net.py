# SPDX-License-Identifier: MIT
"""filetree: network mount detection. Standalone, stdlib only, read-only. Imported by filetree_walk.py."""
import os
import re
import subprocess
import sys

NET_LINUX = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "sshfs", "fuse.sshfs", "9p", "afs", "ceph", "glusterfs", "davfs"}
NET_MAC = {"nfs", "smbfs", "afpfs", "webdav"}


def network_mounts():
    """Mount points of network filesystems (set of paths). Any failure -> empty set, never a crash."""
    return set(mount_sources())


def mount_sources():
    """{mount point: 'fstype source'} for network filesystems, e.g. {'/mnt/x': 'nfs host-b:/export'}."""
    try:
        if sys.platform.startswith("linux"):
            return linux_sources()
        if sys.platform == "darwin":
            return mac_sources()
    except Exception:  # noqa: BLE001 -- no network detection beats a crash
        return {}
    return {}


def _unescape(text):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), text)


def linux_sources():
    found = {}
    with open("/proc/self/mounts", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 3 and parts[2] in NET_LINUX:
                found[_unescape(parts[1])] = f"{parts[2]} {_unescape(parts[0])}"
    return found


def linux_mounts():
    return set(linux_sources())


def mac_sources():
    text = subprocess.run(["mount"], capture_output=True, text=True, timeout=10, check=False).stdout
    rows = re.findall(r"^(.+?) on (.+?) \((\w+)[,)]", text, re.MULTILINE)
    return {point: f"{fstype} {source}" for source, point, fstype in rows if fstype in NET_MAC}


def mac_mounts():
    return set(mac_sources())


def windows_network(root):
    try:
        import ctypes
        drive = os.path.splitdrive(root)[0] + "\\"
        return ctypes.windll.kernel32.GetDriveTypeW(drive) == 4
    except Exception:  # noqa: BLE001 -- no network detection beats a crash
        return False


def builtin_skips(skips, roots):
    """Built-in skip prefixes, minus any that holds a configured root (a root named on purpose, e.g. a folder on
    /dev/shm, is walked) unless another root sits above that prefix and would then walk it."""
    def under(path, prefix):
        return path == prefix or path.startswith(prefix.rstrip("/") + "/")
    return [s for s in skips if not any(under(r, s) for r in roots) or any(under(s, r) for r in roots)]
