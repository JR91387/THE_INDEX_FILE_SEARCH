#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Collector: Windows Task Scheduler. Standalone (stdlib only, no package imports).
Runs `schtasks /query /xml ONE` (several <Task> documents joined). Options (JSON in argv[1]): system (bool, keep
tasks under \\Microsoft\\), xml_file (read saved output instead), force_platform (tests only).
Other platforms: ok + one 'unsupported' gap. One job item per task, key schtasks:<URI>."""
import json
import re
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
TIMEOUT_S = 60


def utc(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def split_documents(text):
    """The output is several XML documents, one after another: cut at each <?xml declaration."""
    text = text.lstrip("﻿")
    return [d for d in re.split(r"(?=<\?xml)", text) if d.strip()]


def find(node, path):
    found = node.find(path, NS)
    return (found.text or "").strip() if found is not None else ""


def schedule_of(task):
    triggers = task.find("t:Triggers", NS)
    return ", ".join(child.tag.split("}")[-1] for child in (triggers if triggers is not None else []))


def command_of(task):
    parts = []
    for exe in task.findall("t:Actions/t:Exec", NS):
        parts.append(" ".join(p for p in (find(exe, "t:Command"), find(exe, "t:Arguments")) if p))
    return "; ".join(parts)


def task_item(doc, uri_fallback):
    # the declaration says UTF-16 but the text is already decoded: drop it before parsing
    task = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", doc))
    uri = find(task, "t:RegistrationInfo/t:URI") or uri_fallback
    enabled = find(task, "t:Settings/t:Enabled") != "false"
    return {"kind": "job", "key": f"schtasks:{uri}", "metrics": {},
            "attrs": {"source": "schtasks", "type": "schtasks", "unit": uri, "schedule": schedule_of(task),
                      "command": command_of(task), "run_as": find(task, "t:Principals/t:Principal/t:UserId"),
                      "enabled": enabled}}


def read_xml(opts):
    if opts.get("xml_file"):
        with open(opts["xml_file"], encoding="utf-8-sig") as fh:
            return fh.read()
    proc = subprocess.run(["schtasks", "/query", "/xml", "ONE"], capture_output=True, text=True,
                          timeout=TIMEOUT_S, check=True)
    return proc.stdout


def collect(opts, out):
    out["coverage"].append("schtasks:")
    for number, doc in enumerate(split_documents(read_xml(opts))):
        try:
            item = task_item(doc, f"\\unnamed{number}")
        except ET.ParseError as exc:
            out["gaps"].append({"kind": "denied", "target": f"task {number}", "reason": f"bad XML: {exc}"[:200]})
            continue
        if item["attrs"]["unit"].startswith("\\Microsoft\\") and not opts.get("system"):
            continue
        out["items"].append(item)


def main():
    opts = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    out = {"collector": "jobs", "script": "jobs_schtasks", "host": socket.gethostname(), "kinds": ["job"],
           "started_at": utc(datetime.now(UTC)), "items": [], "gaps": [], "errors": [], "coverage": []}
    if (opts.get("force_platform") or sys.platform) != "win32":
        out["gaps"].append({"kind": "unsupported", "target": "Task Scheduler jobs", "reason": "not Windows"})
    else:
        try:
            collect(opts, out)
        except (OSError, subprocess.SubprocessError) as exc:
            out["errors"].append(f"schtasks: {exc}")
    out["status"] = "partial" if out["errors"] else "ok"
    out["finished_at"] = utc(datetime.now(UTC))
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
