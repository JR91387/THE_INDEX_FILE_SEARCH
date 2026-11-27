#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collector: systemd timers (system, and the current user's). Standalone, stdlib only:
    ssh host python3 - < jobs_systemd.py
Prints one JSON document (see collectors/README.md)."""
import json
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime

TIMER_PROPS = "Id,Unit,TimersCalendar,TimersMonotonic,NextElapseUSecRealtime,LastTriggerUSec"
SERVICE_PROPS = "User,ExecStart,Result,ExecMainStatus,ActiveState"


def utc(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def systemctl(scope, *args):
    """Run systemctl; returns stdout or raises RuntimeError with stderr."""
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + ["--no-pager", "--timestamp=unix", *args]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout).strip()[:300] or f"exit {done.returncode}")
    return done.stdout


def show(scope, units, props):
    """`systemctl show` for many units -> list of {prop: value} dicts (blank line separates units)."""
    if not units:
        return []
    blocks, current = [], {}
    for line in systemctl(scope, "show", "-p", props, *units).splitlines() + [""]:
        if not line.strip():
            if current:
                blocks.append(current)
            current = {}
            continue
        key, _, value = line.partition("=")
        current[key] = value
    return blocks


def stamp(value):
    """'@1731852000' (from --timestamp=unix) -> UTC text; empty/'n/a' -> None."""
    value = (value or "").strip()
    if value.startswith("@") and value[1:].isdigit() and int(value[1:]) > 0:
        return utc(datetime.fromtimestamp(int(value[1:]), UTC))
    return None


def exec_command(raw):
    """ExecStart value '{ path=/usr/bin/x ; argv[]=/usr/bin/x -a ; ... }' -> '/usr/bin/x -a'."""
    if "argv[]=" in raw:
        return raw.split("argv[]=", 1)[1].split(" ;", 1)[0].strip()
    return raw.strip() or None


def schedule_of(timer):
    """Readable schedule from TimersCalendar / TimersMonotonic."""
    cal = timer.get("TimersCalendar", "")
    if "OnCalendar=" in cal:
        return cal.split("OnCalendar=", 1)[1].split(" ;", 1)[0].strip()
    mono = timer.get("TimersMonotonic", "")
    return mono.split(";", 1)[0].strip("{ ") or None


def collect_scope(scope, out):
    listing = systemctl(scope, "list-units", "--type=timer", "--all", "--plain", "--no-legend")
    names = [line.split()[0] for line in listing.splitlines() if line.strip()]
    timers = show(scope, names, TIMER_PROPS)
    out["coverage"].append(f"systemd-{scope}:")  # listed in full
    services = dict(zip([t.get("Unit") for t in timers], show(scope, [t.get("Unit") for t in timers], SERVICE_PROPS)))
    for timer in timers:
        svc = services.get(timer.get("Unit"), {})
        result = svc.get("Result") or None
        out["items"].append({
            "kind": "job", "key": f"systemd-{scope}:{timer.get('Id')}",
            "attrs": {"source": f"systemd-{scope}", "type": "systemd", "unit": timer.get("Unit"),
                      "schedule": schedule_of(timer), "run_as": svc.get("User") or ("root" if scope == "system" else None),
                      "command": exec_command(svc.get("ExecStart", ""))},
            "metrics": {"next_run": stamp(timer.get("NextElapseUSecRealtime")),
                        "last_run": stamp(timer.get("LastTriggerUSec")), "last_result": result}})


def main():
    started = datetime.now(UTC)
    out = {"collector": "jobs", "script": "jobs_systemd", "host": socket.gethostname(), "kinds": ["job"],
           "started_at": utc(started), "items": [], "gaps": [], "errors": [], "coverage": []}
    if not sys.platform.startswith("linux"):
        out["gaps"].append({"kind": "unsupported", "target": "systemd timers", "reason": "systemd is Linux only"})
        out["status"], out["finished_at"] = "ok", utc(datetime.now(UTC))
        print(json.dumps(out, indent=1, sort_keys=True))
        return
    if not shutil.which("systemctl"):
        out["gaps"].append({"kind": "not_visible", "target": "systemd timers", "reason": "systemctl not found"})
    else:
        for scope in ("system", "user"):
            try:
                collect_scope(scope, out)
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                # no user session bus is common under cron: record it as a gap, not a failure
                kind = "not_visible" if scope == "user" else None
                if kind:
                    out["gaps"].append({"kind": kind, "target": "systemd user timers", "reason": str(exc)[:200]})
                else:
                    out["errors"].append(f"systemd {scope}: {exc}")
    out["gaps"].append({"kind": "not_visible", "target": "jobs inside containers",
                        "reason": "container schedulers are not inspected"})
    out["status"] = "partial" if out["errors"] else "ok"
    out["finished_at"] = utc(datetime.now(UTC))
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
