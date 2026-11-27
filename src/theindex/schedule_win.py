# SPDX-License-Identifier: MIT
"""`schedule` on Windows: a Task Scheduler task (current user, no admin, low priority) made from an XML definition.

Unverified on a real host: the XML follows the Task Scheduler 1.2 schema and `schtasks /Create /XML`; tested with mocks."""
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from . import schedule

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
NAMES = {"hub": "THE INDEX", "member": "THE INDEX collect"}


def task_name(args):
    return NAMES[schedule.role_of(args)]


def _add(parent, tag, text=None):
    node = ET.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        node.text = text
    return node


def render_tree(args):
    """The task definition as an ElementTree: daily with up to an hour of random delay, least privilege."""
    ET.register_namespace("", NS)
    root = ET.Element(f"{{{NS}}}Task", {"version": "1.2"})
    trigger = _add(_add(root, "Triggers"), "CalendarTrigger")
    _add(trigger, "StartBoundary", "2025-01-01T03:17:00")
    _add(trigger, "Enabled", "true")
    _add(trigger, "RandomDelay", "PT1H")
    _add(_add(trigger, "ScheduleByDay"), "DaysInterval", "1")
    principal = _add(_add(root, "Principals"), "Principal")
    principal.set("id", "Author")
    _add(principal, "LogonType", "InteractiveToken")
    _add(principal, "RunLevel", "LeastPrivilege")
    settings = _add(root, "Settings")
    for tag, text in (("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
                      ("StopIfGoingOnBatteries", "false"), ("StartWhenAvailable", "true"),
                      ("ExecutionTimeLimit", "PT4H"), ("Priority", "7")):
        _add(settings, tag, text)
    actions = _add(root, "Actions")
    actions.set("Context", "Author")
    exe = _add(actions, "Exec")
    _add(exe, "Command", sys.executable)
    _add(exe, "Arguments", subprocess.list2cmdline(schedule.scan_argv(args)[1:]))
    return root


def render(args):
    """The XML as text."""
    return ET.tostring(render_tree(args), encoding="unicode")


def _schtasks(*cmd):
    try:
        return subprocess.run(("schtasks", *cmd), capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def show(args):
    print(f'# schtasks /Create /TN "{task_name(args)}" /XML ...\n{render(args)}')
    return 0


def install(args):
    data = ET.tostring(render_tree(args), encoding="UTF-16", xml_declaration=True)   # schtasks wants UTF-16
    fd, name = tempfile.mkstemp(suffix=".xml", prefix="the-index-task-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        done = _schtasks("/Create", "/TN", task_name(args), "/XML", name, "/F")
    finally:
        Path(name).unlink(missing_ok=True)
    if done is None or done.returncode != 0:
        raise OSError(f"could not create task {task_name(args)!r}: {(done.stderr if done else '').strip()}")
    print(f"scheduled: task {task_name(args)!r} (daily, low priority)")
    return 0


def remove(args):
    done = _schtasks("/Delete", "/TN", task_name(args), "/F")
    print("schedule removed" if done is not None and done.returncode == 0 else "nothing scheduled")
    return 0
