# SPDX-License-Identifier: MIT
"""Collector registry and local runner. Each collector is one or more standalone scripts that print JSON;
their outputs are merged into one payload per collector run (see README.md in this folder)."""
import contextlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOB_SCRIPTS = {"linux": ["jobs_cron.py", "jobs_systemd.py"], "darwin": ["jobs_launchd.py", "jobs_cron.py"],
               "win32": ["jobs_schtasks.py"]}


def registry_for(platform):
    """The collector table for one sys.platform value; an unknown platform gets the Linux scripts (each script
    reports its own 'unsupported' gap when it cannot run there)."""
    jobs = JOB_SCRIPTS.get(platform, JOB_SCRIPTS["linux"])
    return {"folders": ["folders.py"], "jobs": list(jobs), "containers": ["containers.py"],
            "filesystems": ["filesystems.py"], "backups": ["backups.py"],
            "filetree": ["filetree.py"]}  # streamed by files_run, not run()


REGISTRY = registry_for(sys.platform)
TIMEOUTS = {"jobs": 60, "containers": 120, "filesystems": 60, "backups": 600}


def timeout_for(name, args=()):
    """Seconds a collector may run: its table entry; folders = its own walk budget (budget_s) + 300."""
    if name == "folders":
        try:
            return float(json.loads(args[0]).get("budget_s", 1800)) + 300
        except (IndexError, ValueError, TypeError, AttributeError):
            return 1800 + 300
    return TIMEOUTS.get(name, 600)


def stop(proc):
    """Kill the child's whole process group. A root child (sudo) may refuse the signal: then try the child alone."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        with contextlib.suppress(OSError):
            proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        proc.communicate(timeout=5)


def run_script(path, args=(), launcher=None, timeout=600):
    """Run one collector script -> parsed payload; a crash or a timeout becomes a failed payload.
    launcher replaces the default `python -I <script>` (e.g. a sudo command for the folder scanner); its
    arguments go on stdin, one per line, so the command line stays fixed (and the sudoers rule has no wildcard)."""
    cmd = launcher or [sys.executable, "-I", str(path), *args]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if launcher else subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as exc:
        return failed(path, exc)
    try:
        stdout, stderr = proc.communicate("\n".join(args) if launcher else None, timeout=timeout)
    except subprocess.TimeoutExpired:
        stop(proc)
        return failed(path, f"timed out after {timeout:.0f}s")
    except OSError as exc:
        stop(proc)
        return failed(path, exc)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return failed(path, (stderr or "no output").strip()[:300])


def failed(path, why):
    return {"status": "failed", "errors": [f"{path.name}: {why}"], "items": [], "gaps": [], "coverage": []}


def merge(name, payloads):
    """Combine script payloads. Any failed/partial script makes the whole run partial."""
    merged = {"collector": name, "items": [], "links": [], "gaps": [], "errors": [], "coverage": [], "kinds": []}
    for p in payloads:
        for key in ("items", "links", "gaps", "errors", "coverage"):
            merged[key] += p.get(key, [])
        merged["kinds"] += [k for k in p.get("kinds", []) if k not in merged["kinds"]]
    starts = [p["started_at"] for p in payloads if p.get("started_at")]
    ends = [p["finished_at"] for p in payloads if p.get("finished_at")]
    merged["started_at"] = min(starts) if starts else None
    merged["finished_at"] = max(ends) if ends else None
    merged["items"] = dedupe(merged["items"], merged["errors"])
    bad = any(p.get("status") != "ok" for p in payloads) or merged["errors"]
    merged["status"] = "partial" if bad else "ok"
    return merged


def dedupe(items, errors):
    """Keep the first item per (kind, key); a duplicate is reported as an error (so nothing retires)."""
    seen, kept = set(), []
    for item in items:
        ident = (item.get("kind"), item.get("key"))
        if ident in seen:
            errors.append(f"duplicate item {ident[0]}:{ident[1]}")
            continue
        seen.add(ident)
        kept.append(item)
    return kept


def run(name, args=(), launcher=None):
    """Run every script of a registered collector on this machine (passing `args`) and merge the results."""
    if name not in REGISTRY:
        raise KeyError(f"unknown collector {name!r}; known: {', '.join(REGISTRY)}")
    return merge(name, [run_script(HERE / script, args, launcher, timeout_for(name, args)) for script in REGISTRY[name]])
