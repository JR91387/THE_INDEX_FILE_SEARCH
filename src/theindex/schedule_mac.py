# SPDX-License-Identifier: MIT
"""`schedule` on macOS: a LaunchAgent plist in ~/Library/LaunchAgents, loaded with `launchctl bootstrap`.

Unverified on a real host: written to the documented launchd plist keys and launchctl verbs, tested with mocks."""
import os
import plistlib
import subprocess
from pathlib import Path

from . import schedule

LABELS = {"hub": "io.the-index.scan", "member": "io.the-index.collect"}


def label(args):
    return LABELS[schedule.role_of(args)]


def plist_path(args):
    return Path.home() / "Library" / "LaunchAgents" / f"{label(args)}.plist"


def render(args):
    """The plist as bytes: daily 03:17, low priority, not run at load."""
    data = {"Label": label(args), "ProgramArguments": schedule.scan_argv(args),
            "StartCalendarInterval": {"Hour": 3, "Minute": 17}, "LowPriorityIO": True, "Nice": 19,
            "RunAtLoad": False}
    env = schedule.package_path()
    if env:
        data["EnvironmentVariables"] = {"PYTHONPATH": str(env)}
    return plistlib.dumps(data)


def _launchctl(*cmd):
    try:
        return subprocess.run(("launchctl", *cmd), capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _unload(args):
    """bootout the agent if launchd has it loaded."""
    target = f"gui/{os.getuid()}/{label(args)}"
    loaded = _launchctl("print", target)
    if loaded is not None and loaded.returncode == 0:
        _launchctl("bootout", target)


def show(args):
    print(f"# {plist_path(args)}\n{render(args).decode()}", end="")
    return 0


def install(args):
    path = plist_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render(args))
    _unload(args)
    done = _launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
    if done is None or done.returncode != 0:
        raise OSError(f"could not load {path.name}: {(done.stderr if done else '').strip()}")
    print(f"scheduled: {path} (daily, low priority)")
    return 0


def remove(args):
    path = plist_path(args)
    _unload(args)
    if not path.exists():
        print("nothing scheduled")
        return 0
    path.unlink()
    print("schedule removed")
    return 0
