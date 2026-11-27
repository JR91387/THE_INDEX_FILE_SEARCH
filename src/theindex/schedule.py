# SPDX-License-Identifier: MIT
"""`schedule`: install (or remove, or print) a daily job at low priority: `scan` (role hub) or `collect` (role member).

Linux: a systemd user timer; without `systemctl --user` it prints a crontab line and never edits the crontab.
macOS and Windows are in `schedule_mac.py` and `schedule_win.py`; `cmd_schedule` picks by `sys.platform`."""
import getpass
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

NAMES = {"hub": "the-index", "member": "the-index-collect"}


def unit_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"


def role_of(args):
    return getattr(args, "role", None) or "hub"


def unit_name(args):
    return NAMES[role_of(args)]


def scan_argv(args):
    """The command line the timer runs: this Python, `-m theindex`, any --config/--db given now."""
    argv = [sys.executable, "-m", "theindex"]
    for flag in ("config", "db"):
        value = getattr(args, flag, None)
        if value:
            argv += [f"--{flag}", str(Path(value).expanduser().resolve())]
    return argv + (["collect"] if role_of(args) == "member" else ["scan", "--quiet"])


def package_path():
    """Directory to put on PYTHONPATH when running from a checkout (not installed), else None."""
    root = Path(__file__).resolve().parent.parent
    return None if "site-packages" in root.parts or "dist-packages" in root.parts else root


def render(args):
    """(service text, timer text)."""
    exec_start = shlex.join(scan_argv(args)).replace("%", "%%")
    env = package_path()
    what = "collect" if role_of(args) == "member" else "scan"
    lines = ["[Unit]", f"Description=THE INDEX {what}", "", "[Service]", "Type=oneshot",
             f"ExecStart={exec_start}", "Nice=19", "IOSchedulingClass=idle", "CPUWeight=10"]
    if env:
        lines.insert(lines.index("Nice=19"), f"Environment=PYTHONPATH={env}")
    timer = ["[Unit]", f"Description=Run THE INDEX {what} daily", "", "[Timer]", "OnCalendar=daily",
             "RandomizedDelaySec=1h", "Persistent=true", "", "[Install]", "WantedBy=timers.target"]
    return "\n".join(lines) + "\n", "\n".join(timer) + "\n"


def _run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def user_systemd():
    """True if `systemctl --user` answers."""
    if not shutil.which("systemctl"):
        return False
    done = _run("systemctl", "--user", "show-environment")
    return done is not None and done.returncode == 0


def cron_line(args):
    prefix = " ".join(p for p in (("nice -n 19" if shutil.which("nice") else ""),
                                  ("ionice -c3" if shutil.which("ionice") else "")) if p)
    return f"17 3 * * * {prefix + ' ' if prefix else ''}{shlex.join(scan_argv(args))}"


def _linger_hint():
    done = _run("loginctl", "show-user", getpass.getuser(), "-p", "Linger") if shutil.which("loginctl") else None
    if done is not None and done.stdout.strip() == "Linger=no":
        print(f"hint: run `loginctl enable-linger {getpass.getuser()}` so the timer also runs while you are logged out")


def _write_if_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def install(args):
    if not user_systemd():
        print("systemd user session not available; add this line to your crontab (`crontab -e`):")
        print(cron_line(args))
        return 0
    service, timer = render(args)
    folder = unit_dir()
    folder.mkdir(parents=True, exist_ok=True)
    unit = unit_name(args)
    _write_if_changed(folder / f"{unit}.service", service)
    _write_if_changed(folder / f"{unit}.timer", timer)
    _run("systemctl", "--user", "daemon-reload")
    done = _run("systemctl", "--user", "enable", "--now", f"{unit}.timer")
    if done is None or done.returncode != 0:
        raise OSError(f"could not enable {unit}.timer: {(done.stderr if done else '').strip()}")
    print(f"scheduled: {folder / (unit + '.timer')} (daily, low priority)")
    _linger_hint()
    return 0


def remove(args):
    folder, unit = unit_dir(), unit_name(args)
    if user_systemd():
        _run("systemctl", "--user", "disable", "--now", f"{unit}.timer")
    gone = False
    for suffix in ("timer", "service"):
        path = folder / f"{unit}.{suffix}"
        if path.exists():
            path.unlink()
            gone = True
    if gone and user_systemd():
        _run("systemctl", "--user", "daemon-reload")
    print("schedule removed" if gone else "nothing scheduled")
    return 0


def print_linux(args):
    service, timer = render(args)
    unit = unit_name(args)
    print(f"# {unit_dir() / (unit + '.service')}\n{service}\n# {unit_dir() / (unit + '.timer')}\n{timer}"
          f"# no systemd user session? crontab line:\n# {cron_line(args)}")
    return 0


def cmd_schedule(cfg, args):
    """Dispatch on the OS. Role: --role, else `[inbox] role` from the config (default hub)."""
    args.role = args.role or cfg.inbox_role
    if sys.platform == "darwin":
        from . import schedule_mac as target
    elif sys.platform == "win32":
        from . import schedule_win as target
    else:
        if args.print:
            return print_linux(args)
        return remove(args) if args.remove else install(args)
    if args.print:
        return target.show(args)
    return target.remove(args) if args.remove else target.install(args)
