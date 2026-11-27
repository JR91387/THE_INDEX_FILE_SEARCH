#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collector: Docker containers. Standalone, stdlib only:
    ssh host python3 - < containers.py
Prints one JSON document (see collectors/README.md). Uses the docker CLI; no docker = nothing to report."""
import json
import shutil
import socket
import subprocess
from datetime import UTC, datetime


def utc_now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def docker(*args):
    """Run the docker CLI; raises RuntimeError with its message on failure."""
    done = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120, check=False)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout).strip()[:300] or f"exit {done.returncode}")
    return done.stdout


def mounts_of(info):
    """Sorted, stable mount list: type, source, destination, rw."""
    found = [{"type": m.get("Type"), "source": m.get("Source"), "destination": m.get("Destination"),
              "rw": bool(m.get("RW"))} for m in info.get("Mounts") or []]
    return sorted(found, key=lambda m: (m["destination"] or "", m["source"] or ""))


def item_of(info, now):
    """docker inspect record -> catalog item."""
    name = (info.get("Name") or "").lstrip("/")
    state = (info.get("State") or {}).get("Status")
    labels = (info.get("Config") or {}).get("Labels") or {}
    attrs = {"image": (info.get("Config") or {}).get("Image"), "image_id": info.get("Image"), "state": state,
             "restart_policy": ((info.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name"),
             "compose_project": labels.get("com.docker.compose.project"), "mounts": mounts_of(info)}
    metrics = {"last_running_at": now} if state == "running" else {}
    return {"kind": "container", "key": name, "attrs": attrs, "metrics": metrics}


def links_of(item):
    """Each host path a container mounts -> a `mounts` link to that folder."""
    return [{"from": ["container", item["key"]], "type": "mounts", "to": ["folder", m["source"]]}
            for m in item["attrs"]["mounts"] if m["source"] and m["type"] in ("bind", "volume")]


def collect(out):
    ids = docker("ps", "-aq", "--no-trunc").split()
    out["coverage"].append("")            # docker lists every container: all keys are covered
    if not ids:
        return
    now = utc_now()
    for info in json.loads(docker("inspect", *ids)):
        item = item_of(info, now)
        out["items"].append(item)
        out["links"] += links_of(item)


def main():
    out = {"collector": "containers", "script": "containers", "host": socket.gethostname(), "kinds": ["container"],
           "started_at": utc_now(), "items": [], "links": [], "gaps": [], "errors": [], "coverage": []}
    if shutil.which("docker"):
        try:
            collect(out)
        except (RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            denied = "permission denied" in str(exc).lower()
            if denied:
                out["gaps"].append({"kind": "denied", "target": "docker socket", "reason": str(exc)[:200]})
            else:
                out["errors"].append(f"docker: {exc}")
    out["status"] = "partial" if out["errors"] else "ok"
    out["finished_at"] = utc_now()
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
