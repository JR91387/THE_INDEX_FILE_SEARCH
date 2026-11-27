# SPDX-License-Identifier: MIT
"""`schedule --watch`: run `the-index watch` as a long-lived user service, restarted on failure, low priority.

Linux: systemd user service `the-index-watch.service`. macOS: LaunchAgent `io.the-index.watch` (KeepAlive).
Windows: Task Scheduler task "THE INDEX watch" started at logon. The macOS and Windows parts are unverified on a
real host (written to the documented plist keys and Task Scheduler 1.2 schema; tested print-only and with mocks)."""
import plistlib
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET

from . import schedule

UNIT, LABEL, TASK = "the-index-watch", "io.the-index.watch", "THE INDEX watch"


def watch_argv(args):
    return schedule.base_argv(args) + ["watch"]


def render_linux(args):
    lines = ["[Unit]", "Description=THE INDEX watch (live file index updates)", "", "[Service]", "Type=simple",
             f"ExecStart={shlex.join(watch_argv(args)).replace('%', '%%')}", "Restart=on-failure", "RestartSec=30",
             "Nice=19", "IOSchedulingClass=idle", "CPUWeight=10", "", "[Install]", "WantedBy=default.target"]
    env = schedule.package_path()
    if env:
        lines.insert(lines.index("Nice=19"), f"Environment=PYTHONPATH={env}")
    return "\n".join(lines) + "\n"


def render_mac(args):
    data = {"Label": LABEL, "ProgramArguments": watch_argv(args), "RunAtLoad": True, "KeepAlive": True,
            "LowPriorityIO": True, "Nice": 19, "ProcessType": "Background"}
    env = schedule.package_path()
    if env:
        data["EnvironmentVariables"] = {"PYTHONPATH": str(env)}
    return plistlib.dumps(data)


def render_win(args):
    from . import schedule_win as win
    ET.register_namespace("", win.NS)
    root = ET.Element(f"{{{win.NS}}}Task", {"version": "1.2"})
    win._add(win._add(win._add(root, "Triggers"), "LogonTrigger"), "Enabled", "true")
    principal = win._add(win._add(root, "Principals"), "Principal")
    principal.set("id", "Author")
    win._add(principal, "LogonType", "InteractiveToken")
    win._add(principal, "RunLevel", "LeastPrivilege")
    settings = win._add(root, "Settings")
    for tag, text in (("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
                      ("StopIfGoingOnBatteries", "false"), ("ExecutionTimeLimit", "PT0S"), ("Priority", "7")):
        win._add(settings, tag, text)
    restart = win._add(settings, "RestartOnFailure")
    win._add(restart, "Interval", "PT1M")
    win._add(restart, "Count", "3")
    actions = win._add(root, "Actions")
    actions.set("Context", "Author")
    exe = win._add(actions, "Exec")
    win._add(exe, "Command", sys.executable)
    win._add(exe, "Arguments", subprocess.list2cmdline(watch_argv(args)[1:]))
    return ET.tostring(root, encoding="unicode")


def show(args):
    if sys.platform == "darwin":
        from . import schedule_mac
        path = schedule_mac.plist_path(args).with_name(f"{LABEL}.plist")
        print(f"# {path}\n{render_mac(args).decode()}", end="")
    elif sys.platform == "win32":
        print(f'# schtasks /Create /TN "{TASK}" /XML ...\n{render_win(args)}')
    else:
        print(f"# {schedule.unit_dir() / (UNIT + '.service')}\n{render_linux(args)}", end="")
    return 0


def apply(args):
    """Install, remove or print the watch service next to the schedule. The watch writes the database: hub only."""
    if args.print:
        return show(args)
    if sys.platform in ("darwin", "win32"):
        from . import schedule_watch_os
        return schedule_watch_os.apply(args)
    return linux_remove() if args.remove else linux_install(args)


def linux_install(args):
    if schedule.role_of(args) != "hub":
        raise ValueError("watch writes the database: schedule it with role hub")
    if not schedule.user_systemd():
        print("systemd user session not available; start `the-index watch` at login yourself")
        return 0
    folder = schedule.unit_dir()
    folder.mkdir(parents=True, exist_ok=True)
    schedule._write_if_changed(folder / f"{UNIT}.service", render_linux(args))
    schedule._run("systemctl", "--user", "daemon-reload")
    done = schedule._run("systemctl", "--user", "enable", "--now", f"{UNIT}.service")
    if done is None or done.returncode != 0:
        raise OSError(f"could not enable {UNIT}.service: {(done.stderr if done else '').strip()}")
    print(f"watching: {UNIT}.service (restarts on failure, low priority)")
    return 0


def linux_remove():
    path = schedule.unit_dir() / f"{UNIT}.service"
    if not path.exists():
        return 0
    if schedule.user_systemd():
        schedule._run("systemctl", "--user", "disable", "--now", f"{UNIT}.service")
    path.unlink()
    if schedule.user_systemd():
        schedule._run("systemctl", "--user", "daemon-reload")
    print("watch removed")
    return 0
