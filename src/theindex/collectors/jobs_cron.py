#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collector: cron jobs. Standalone (stdlib only, no package imports) so it can run over ssh:
    ssh host python3 - < jobs_cron.py
Prints one JSON document (see collectors/README.md). Reads: the current user's crontab, /etc/crontab,
/etc/cron.d/*, /etc/cron.{hourly,daily,weekly,monthly}/, and other users' spool crontabs if readable."""
import getpass
import hashlib
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

SPOOLS = ("/var/spool/cron/crontabs", "/var/spool/cron")
PERIODIC = ("hourly", "daily", "weekly", "monthly")
MACROS = {"@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
          "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@hourly": "0 * * * *"}
RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
NAMES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
         "oct": 10, "nov": 11, "dec": 12, "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def utc(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_field(text, low, high):
    """One cron field -> set of ints. Supports *, lists, ranges, steps and month/day names."""
    values = set()
    for part in text.lower().split(","):
        rng, _, step = part.partition("/")
        if rng == "*":
            start, end = low, high
        else:
            a, _, b = rng.partition("-")
            start = int(NAMES.get(a, a))
            end = int(NAMES.get(b, b)) if b else (high if step else start)
        values.update(range(start, end + 1, int(step or 1)))
    return values


def next_run(schedule, start, horizon_days=8):
    """Next local time matching a 5-field schedule, or None (e.g. @reboot or beyond the horizon)."""
    fields = MACROS.get(schedule, schedule).split()
    if len(fields) != 5:
        return None
    try:
        minute, hour, dom, month, dow = (parse_field(f, *r) for f, r in zip(fields, RANGES))
    except ValueError:
        return None
    dow = {d % 7 for d in dow}
    dom_any, dow_any = fields[2] == "*", fields[4] == "*"
    t = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(horizon_days * 1440):
        day_ok = (t.day in dom or t.isoweekday() % 7 in dow) if not (dom_any or dow_any) else \
                 (t.day in dom and t.isoweekday() % 7 in dow)
        if t.minute in minute and t.hour in hour and t.month in month and day_ok:
            return t
        t += timedelta(minutes=1)
    return None


def split_line(line, has_user):
    """'<schedule> [user] command' -> (schedule, user, command) or None for comments/env lines."""
    line = line.strip()
    if not line or line.startswith("#") or ("=" in line.split()[0] and not line.startswith("@")):
        return None
    parts = line.split(None, 1 if line.startswith("@") else 5)
    n = 1 if line.startswith("@") else 5
    if len(parts) <= n:
        return None
    rest = parts[n].split(None, 1) if has_user else [None, parts[n]]
    if has_user and len(rest) < 2:
        return None
    return " ".join(parts[:n]), rest[0], rest[1]


def job(source, parsed, now):
    schedule, user, command = parsed
    digest = hashlib.sha1(f"{schedule} {user} {command}".encode()).hexdigest()[:10]
    nxt = next_run(schedule, now)
    return {"kind": "job", "key": f"{source}:{digest}",
            "attrs": {"source": source, "schedule": schedule, "run_as": user, "command": command, "type": "cron"},
            "metrics": {"next_run": utc(nxt) if nxt else None}}


def read_table(path_or_text, source, owner, out):
    """Parse a crontab (a path, or text already read) into out['items']; unreadable -> a gap.
    owner=None means a system table whose lines carry their own user field."""
    try:
        text = path_or_text.read_text() if isinstance(path_or_text, Path) else path_or_text
    except PermissionError:
        out["gaps"].append({"kind": "denied", "target": str(path_or_text), "reason": "cannot read crontab"})
        return
    except (FileNotFoundError, IsADirectoryError):
        text = ""
    out["coverage"].append(f"{source}:")  # read in full: unseen items under this prefix may be retired
    for line in text.splitlines():
        parsed = split_line(line, owner is None)
        if parsed:
            out["items"].append(job(source, (parsed[0], parsed[1] or owner, parsed[2]), out["_now"]))


def collect_user(out):
    me = getpass.getuser()
    try:
        done = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return
    if done.returncode == 0 or "no crontab" in done.stderr.lower():
        read_table(done.stdout if done.returncode == 0 else "", f"crontab:{me}", me, out)


def collect_system(out):
    read_table(Path("/etc/crontab"), "/etc/crontab", None, out)
    if Path("/etc/cron.d").is_dir() and os.access("/etc/cron.d", os.R_OK):
        out["coverage"].append("/etc/cron.d/")
        for path in sorted(Path("/etc/cron.d").glob("*")):
            read_table(path, str(path), None, out)
    for period in PERIODIC:
        folder = Path(f"/etc/cron.{period}")
        out["coverage"].append(f"cron.{period}:")
        for script in sorted(folder.glob("*")) if folder.is_dir() else []:
            if script.name.startswith(".") or not os.access(script, os.X_OK):
                continue
            out["items"].append({"kind": "job", "key": f"cron.{period}:{script.name}", "metrics": {},
                                 "attrs": {"source": str(folder), "schedule": f"@{period}", "run_as": "root",
                                           "command": str(script), "type": "cron"}})


def collect_spool(out):
    """Other users' crontabs: readable only as root. Unreadable spool = a visible gap."""
    me = getpass.getuser()
    for spool in (Path(s) for s in SPOOLS):
        if not spool.is_dir():
            continue
        try:
            files = sorted(p for p in spool.iterdir() if p.is_file())
        except PermissionError:
            out["gaps"].append({"kind": "denied", "target": str(spool), "reason": "other users' crontabs"})
            return
        out["coverage"].append("crontab:")
        for path in files:
            if path.name != me:
                read_table(path, f"crontab:{path.name}", path.name, out)
        return


def main():
    started = datetime.now().astimezone()
    out = {"collector": "jobs", "script": "jobs_cron", "host": socket.gethostname(), "kinds": ["job"],
           "started_at": utc(started), "items": [], "gaps": [], "errors": [], "coverage": [], "_now": started}
    steps = () if sys.platform == "win32" else (collect_user, collect_system, collect_spool)
    if not steps:
        out["gaps"].append({"kind": "unsupported", "target": "cron jobs", "reason": "no cron on this OS"})
    for step in steps:
        try:
            step(out)
        except Exception as exc:  # noqa: BLE001 -- one failing source must not hide the others
            out["errors"].append(f"{step.__name__}: {exc}")
    del out["_now"]
    out["status"] = "partial" if out["errors"] else "ok"
    out["finished_at"] = utc(datetime.now())
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
