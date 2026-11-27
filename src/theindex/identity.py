# SPDX-License-Identifier: MIT
"""Machine identity: the OS machine id, hashed, keys a device so a renamed host stays one device."""
import hashlib
import re
import subprocess
import sys

LINUX_IDS = ("/etc/machine-id", "/var/lib/dbus/machine-id")
_IOREG = re.compile(r'"IOPlatformUUID"\s*=\s*"([^"]+)"')


def _first_line(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.readline().strip() or None
    except OSError:
        return None


def _linux_id():
    return next((found for found in map(_first_line, LINUX_IDS) if found), None)


def _mac_id():
    out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True,
                         timeout=10, check=False).stdout
    match = _IOREG.search(out)
    return match.group(1) if match else None


def _windows_id():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                        access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        return winreg.QueryValueEx(key, "MachineGuid")[0] or None


def machine_id():
    """The raw OS machine id, or None when this OS does not give one."""
    try:
        if sys.platform.startswith("linux"):
            return _linux_id()
        if sys.platform == "darwin":
            return _mac_id()
        if sys.platform == "win32":
            return _windows_id()
    except Exception:  # noqa: BLE001 -- no identity beats a crash; the device is then keyed by name
        return None
    return None


def machine_hash():
    """sha256('the-index:' + id), first 32 hex characters; the raw id never leaves the machine."""
    raw = machine_id()
    return hashlib.sha256(f"the-index:{raw}".encode()).hexdigest()[:32] if raw else None


def resolve_device(conn, name, machine):
    """The device name to record under. `machine` is a machine_hash (or None).
    Known hash: the device keeps its row and takes the new name (unless another device already has it).
    Else an unhashed device of that name adopts the hash. Else `name` (ingest creates the device)."""
    if not machine:
        return name
    row = conn.execute("SELECT name FROM device WHERE machine_hash = ?", (machine,)).fetchone()
    if row:
        taken = conn.execute("SELECT 1 FROM device WHERE name = ?", (name,)).fetchone()
        if row[0] != name and not taken:
            conn.execute("UPDATE device SET name = ? WHERE machine_hash = ?", (name, machine))
            return name
        return row[0]
    named = conn.execute("SELECT machine_hash FROM device WHERE name = ?", (name,)).fetchone()
    if named and named[0] is None:
        conn.execute("UPDATE device SET machine_hash = ? WHERE name = ?", (machine, name))
    elif named:                           # another machine already uses this host name
        return resolve_device(conn, f"{name}-{machine[:6]}", machine)
    return name


def claim_local(conn, name):
    """Record this machine's hash on its device (used by `scan`); returns the name to record under."""
    return resolve_device(conn, name, machine_hash())
