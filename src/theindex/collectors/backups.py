#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collector: backup checks defined in the config ([[backups]]). Standalone, stdlib only:
    ssh host python3 - '<checks JSON>' < backups.py
Check types:
  file_age     newest file matching `path` (a glob) with at least `min_bytes` is the newest good copy
  log_pattern  last line in `path` matching `success` (regex); a named group `when` gives the time,
               otherwise the log file's mtime is used
  command      run `command`; exit 0 = a good copy as of now
A failing backup is a result, not a collector error: the run stays OK so the catalog stays complete."""
import glob
import json
import os
import re
import shlex
import socket
import subprocess
import sys
from datetime import UTC, datetime


def utc(ts=None):
    dt = datetime.now(UTC) if ts is None else datetime.fromtimestamp(ts, UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def file_age(check):
    """(newest_good_at, size_bytes, result) for the newest matching file."""
    good = []
    for path in glob.glob(os.path.expanduser(check["path"])):
        st = os.stat(path)
        if os.path.isfile(path) and st.st_size >= int(check.get("min_bytes", 1)):
            good.append((st.st_mtime, st.st_size))
    if not good:
        return None, None, "no matching file"
    mtime, size = max(good)
    return utc(mtime), size, "ok"


def log_pattern(check):
    path = os.path.expanduser(check["path"])
    pattern = re.compile(check["success"])
    with open(path, errors="replace") as fh:
        hits = [m for m in (pattern.search(line) for line in fh) if m]
    if not hits:
        return None, None, "no success line"
    when = hits[-1].groupdict().get("when")
    if when:
        parsed = datetime.fromisoformat(when)  # 3.11+ accepts a trailing Z
        return utc(parsed.timestamp()), None, "ok"
    return utc(os.stat(path).st_mtime), None, "ok"


def command(check):
    done = subprocess.run(shlex.split(check["command"]), capture_output=True, text=True,
                          timeout=int(check.get("timeout_s", 300)), check=False)
    if done.returncode == 0:
        return utc(), None, "ok"
    return None, None, f"exit {done.returncode}"


TYPES = {"file_age": file_age, "log_pattern": log_pattern, "command": command}


def links_of(check):
    """Declared source/destination folders -> backs_up / lands_in links."""
    links = [{"from": ["backup", check["name"]], "type": "backs_up", "to": ["folder", src]}
             for src in check.get("sources", [])]
    if check.get("destination"):
        links.append({"from": ["backup", check["name"]], "type": "lands_in", "to": ["folder", check["destination"]]})
    return links


def run_check(check, out):
    attrs = {k: check.get(k) for k in ("type", "path", "command", "sources", "destination", "max_age_s")}
    item = {"kind": "backup", "key": check["name"], "attrs": attrs, "metrics": {}}
    try:
        good_at, size, result = TYPES[check["type"]](check)
    except PermissionError as exc:
        out["gaps"].append({"kind": "denied", "target": check.get("path") or check["name"], "reason": str(exc)[:200]})
        good_at, size, result = None, None, "denied"
    except (OSError, ValueError, re.error, subprocess.TimeoutExpired) as exc:
        good_at, size, result = None, None, f"error: {exc}"[:200]
    item["metrics"] = {"last_result": result}
    if good_at:
        item["metrics"]["newest_good_at"] = good_at
    if size is not None:
        item["metrics"]["size_bytes"] = size
    out["items"].append(item)
    out["links"] += links_of(check)


def main():
    out = {"collector": "backups", "script": "backups", "host": socket.gethostname(), "kinds": ["backup"],
           "started_at": utc(), "items": [], "links": [], "gaps": [], "errors": [], "coverage": []}
    try:
        checks = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []
        out["coverage"].append("")          # the config lists every backup: a removed check retires
    except json.JSONDecodeError as exc:
        checks = []
        out["errors"].append(f"bad checks JSON: {exc}")
    for check in checks:
        if check.get("type") not in TYPES or not check.get("name"):
            out["errors"].append(f"bad check: {check.get('name')!r} type {check.get('type')!r}")
            continue
        run_check(check, out)
    out["status"] = "partial" if out["errors"] else "ok"
    out["finished_at"] = utc()
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
