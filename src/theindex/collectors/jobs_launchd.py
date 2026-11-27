#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collector: macOS launchd jobs. Standalone (stdlib only, no package imports).
Options (JSON in argv[1]): system (bool, also scan /System/Library/LaunchDaemons), root (path prefix put in
front of every scanned path, for tests), force_platform (tests only). Other platforms: ok + one 'unsupported' gap.
One job item per plist, key launchd:<scope>:<Label>."""
import json
import os
import plistlib
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    import pwd
except ImportError:  # no pwd module (Windows): owners stay blank
    pwd = None

DIRS = (("user", "~/Library/LaunchAgents"), ("agents", "/Library/LaunchAgents"),
        ("daemons", "/Library/LaunchDaemons"))
SYSTEM_DIR = ("system", "/System/Library/LaunchDaemons")
CAL_KEYS = ("Month", "Day", "Weekday", "Hour", "Minute")


def utc(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def calendar_text(value):
    entries = value if isinstance(value, list) else [value]
    return ", ".join(" ".join(f"{k}={e[k]}" for k in CAL_KEYS if k in e) or "any" for e in entries)


def schedule_of(plist):
    parts = []
    if "StartCalendarInterval" in plist:
        parts.append("calendar " + calendar_text(plist["StartCalendarInterval"]))
    if "StartInterval" in plist:
        parts.append(f"every {plist['StartInterval']}s")
    if plist.get("RunAtLoad"):
        parts.append("at load")
    if plist.get("KeepAlive"):
        parts.append("keepalive")
    return "; ".join(parts)


def command_of(plist):
    if plist.get("ProgramArguments"):
        return " ".join(str(a) for a in plist["ProgramArguments"])
    return str(plist.get("Program", ""))


def owner_of(path):
    if pwd is None:
        return ""
    try:
        return pwd.getpwuid(path.stat().st_uid).pw_name
    except (KeyError, OSError):
        return ""


def job_item(path, scope):
    with open(path, "rb") as fh:
        plist = plistlib.load(fh)
    label = str(plist.get("Label") or path.stem)
    return {"kind": "job", "key": f"launchd:{scope}:{label}", "metrics": {},
            "attrs": {"source": f"launchd-{scope}", "type": "launchd", "unit": label,
                      "schedule": schedule_of(plist), "command": command_of(plist),
                      "run_as": str(plist.get("UserName") or owner_of(path)),
                      "enabled": not plist.get("Disabled", False)}}


def scan_dir(scope, folder, out):
    if not folder.is_dir():
        return
    out["coverage"].append(f"launchd:{scope}:")
    try:
        files = sorted(folder.glob("*.plist"))
    except OSError as exc:
        out["gaps"].append({"kind": "denied", "target": str(folder), "reason": str(exc)[:200]})
        return
    for path in files:
        try:
            out["items"].append(job_item(path, scope))
        except (OSError, plistlib.InvalidFileException, ValueError, AttributeError) as exc:
            out["gaps"].append({"kind": "denied", "target": str(path), "reason": f"unreadable plist: {exc}"[:200]})


def collect(opts, out):
    root = opts.get("root", "")
    dirs = DIRS + (SYSTEM_DIR,) if opts.get("system") else DIRS
    for scope, raw in dirs:
        base = os.path.expanduser(raw)
        scan_dir(scope, Path(root + base if root else base), out)


def main():
    opts = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    out = {"collector": "jobs", "script": "jobs_launchd", "host": socket.gethostname(), "kinds": ["job"],
           "started_at": utc(datetime.now(UTC)), "items": [], "gaps": [], "errors": [], "coverage": []}
    if (opts.get("force_platform") or sys.platform) != "darwin":
        out["gaps"].append({"kind": "unsupported", "target": "launchd jobs", "reason": "not macOS"})
    else:
        try:
            collect(opts, out)
        except Exception as exc:  # noqa: BLE001 -- always print a payload
            out["errors"].append(f"launchd: {exc}")
    out["status"] = "partial" if out["errors"] else "ok"
    out["finished_at"] = utc(datetime.now(UTC))
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
