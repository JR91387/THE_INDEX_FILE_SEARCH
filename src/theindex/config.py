# SPDX-License-Identifier: MIT
"""Config file loading (TOML). Every key is optional; see docs/CONFIG.md and examples/config.example.toml."""
import os
import re
import shlex
import socket
import tomllib
from datetime import datetime
from pathlib import Path

from . import config_inbox

APP = "the-index"
_DURATION = re.compile(r"^\s*(\d+)\s*([smhdw]?)\s*$")
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def xdg(var, fallback):
    """An XDG base directory joined with the app name."""
    return Path(os.environ.get(var) or Path.home() / fallback) / APP


def parse_duration(value):
    """'3d', '12h', '30m', '90s' or a number of seconds -> seconds."""
    if isinstance(value, int):
        return value
    match = _DURATION.match(str(value))
    if not match:
        raise ValueError(f"bad duration: {value!r} (use e.g. 3d, 12h, 30m)")
    return int(match.group(1)) * _UNITS[match.group(2)]


def _defaults():
    """Every config attribute and its default (fresh lists and dicts each time)."""
    return {
        "db_path": xdg("XDG_DATA_HOME", ".local/share") / "index.db",
        "pages_dir": xdg("XDG_STATE_HOME", ".local/state") / "pages",
        "pages_on_scan": True, "device_name": socket.gethostname(), "device_role": None,
        "collectors": ["folders", "jobs", "containers", "filesystems", "backups", "filetree"],
        "filetree": {}, "sources": {}, "folders": {},  # [filetree] roots, titles...; [sources] native; [folders] roots...
        "backups": [],                    # [[backups]] checks, max_age converted to max_age_s
        "pre_run_gate": None,             # command; non-zero exit = skip this run
        "blackout": [],                   # ["02:30-04:45"], local time, may wrap midnight
        "emergency_after_s": 3 * 86400, "size_drop_suspicious": 0.5, "mixed_threshold": 0.6,
        "fs_warn_pct": 85.0, "fs_emergency_pct": 95.0,
        "purposes_file": None, "links_file": None, "serve_port": 8765, "inbox_dir": None, "inbox_role": "hub",
        "pulls": [],                      # [[pull]]: members the hub fetches over ssh
    }


class Config:
    """Settings for one run; a plain class because importing dataclasses costs ~10 ms per command."""

    def __init__(self, **given):
        values = _defaults()
        unknown = set(given) - set(values)
        if unknown:
            raise TypeError(f"unknown config field(s): {', '.join(sorted(unknown))}")
        self.__dict__.update(values, **given)

    def __repr__(self):
        return f"Config({self.__dict__!r})"

    def settings(self):
        """Values the views need, written to the `setting` table."""
        return {"emergency_after_s": self.emergency_after_s,
                "size_drop_suspicious": self.size_drop_suspicious,
                "mixed_threshold": self.mixed_threshold, "fs_warn_pct": self.fs_warn_pct,
                "fs_emergency_pct": self.fs_emergency_pct}


def default_path():
    return xdg("XDG_CONFIG_HOME", ".config") / "config.toml"


def load(path=None):
    """Read the config file if it exists; missing default file = all defaults; a missing explicit path is an error."""
    explicit = bool(path)
    path = Path(path).expanduser() if path else default_path()
    cfg = Config()
    if not path.exists():
        if explicit:
            raise ValueError(f"config file not found: {path}")
        return cfg
    data = tomllib.loads(path.read_text())
    _apply(cfg, data)
    return cfg


def _apply(cfg, data):
    paths, device = data.get("paths", {}), data.get("device", {})
    schedule, rules = data.get("schedule", {}), data.get("rules", {})
    for key in ("db_path", "pages_dir", "purposes_file", "links_file"):
        if key in paths:
            setattr(cfg, key, Path(paths[key]).expanduser())
    cfg.pages_on_scan = _flag(paths, "pages_on_scan", cfg.pages_on_scan)
    cfg.serve_port = _number(data.get("serve", {}), ("serve.port", "port", 1, 65535), cfg.serve_port)
    cfg.device_name = device.get("name", cfg.device_name)
    cfg.device_role = device.get("role", cfg.device_role)
    cfg.collectors = _names(schedule.get("collectors", cfg.collectors))
    cfg.pre_run_gate = schedule.get("pre_run_gate", cfg.pre_run_gate)
    cfg.blackout = _windows(schedule.get("blackout", cfg.blackout))
    if "emergency_after" in rules:
        try:
            cfg.emergency_after_s = parse_duration(rules["emergency_after"])
        except ValueError as exc:
            raise ValueError(f"rules.emergency_after: {exc}") from exc
    cfg.size_drop_suspicious = _number(rules, ("rules.size_drop_suspicious", "size_drop_suspicious", 0, 1), cfg.size_drop_suspicious)
    cfg.mixed_threshold = _number(rules, ("rules.mixed_threshold", "mixed_threshold", 0, 1), cfg.mixed_threshold)
    cfg.fs_warn_pct = _number(rules, ("rules.fs_warn_pct", "fs_warn_pct", 0, 100), cfg.fs_warn_pct)
    cfg.fs_emergency_pct = _number(rules, ("rules.fs_emergency_pct", "fs_emergency_pct", 0, 100), cfg.fs_emergency_pct)
    cfg.backups = [backup_check(b) for b in data.get("backups", [])]
    cfg.folders = dict(data.get("folders", {}))
    cfg.filetree = _filetree(data.get("filetree", {}))
    cfg.sources = config_inbox.sources(data.get("sources", {}))
    config_inbox.apply(cfg, data.get("inbox", {}))
    cfg.pulls = config_inbox.pulls(data.get("pull", []))


def _number(table, spec, default):
    """A numeric setting; spec = (label, key, low, high). The error names the key. Type follows `default`."""
    label, key, low, high = spec
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        raise ValueError(f"{label} must be a number from {low} to {high}")
    return type(default)(value)


def _filetree(table):
    """[filetree]: typed keys, errors name the key."""
    out = dict(table)
    for key, low, high in (("full_every", 1, 365), ("budget_s", 1, 86400), ("title_budget", 0, 10_000_000)):
        if key in out:
            out[key] = _number(out, (f"filetree.{key}", key, low, high), 1)
    for key in ("enabled", "titles", "meta"):
        if key in out:
            out[key] = _flag(out, key, True)
    return out


def _names(value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError('schedule.collectors must be a list of names, e.g. ["folders", "jobs"]')
    return value


_WINDOW = re.compile(r"^(\d\d):(\d\d)-(\d\d):(\d\d)$")


def _windows(value):
    """schedule.blackout: a list of 'HH:MM-HH:MM' (00-23 : 00-59) strings."""
    if not isinstance(value, list):
        raise ValueError('schedule.blackout must be a list, e.g. ["02:30-04:45"]')  # noqa: TRY004
    for window in value:
        match = _WINDOW.match(window) if isinstance(window, str) else None
        if not match or any(int(h) > 23 or int(m) > 59 for h, m in (match.groups()[:2], match.groups()[2:])):
            raise ValueError(f"schedule.blackout: bad window {window!r} (use HH:MM-HH:MM, 00:00 to 23:59)")
    return value


def _flag(table, key, default):
    """A true/false setting; anything else is an error (a string 'false' would otherwise read as true)."""
    value = table.get(key, default)
    if value is not True and value is not False:
        raise ValueError(f"{key} must be true or false")
    return value


def backup_check(check):
    """A [[backups]] table with max_age ('2d') converted to max_age_s for the collector."""
    out = dict(check)
    if "max_age" in out:
        out["max_age_s"] = parse_duration(out.pop("max_age"))
    return out


def in_blackout(windows, at=None):
    """True if local time `at` falls inside any 'HH:MM-HH:MM' window (windows may wrap midnight)."""
    at = at or datetime.now()
    minute = at.hour * 60 + at.minute
    for window in windows:
        start, end = (int(h) * 60 + int(m) for h, m in (part.split(":") for part in window.split("-")))
        inside = start <= minute < end if start <= end else (minute >= start or minute < end)
        if inside:
            return True
    return False


def run_gate(command, timeout=60):
    """Run pre_run_gate. Returns (ok, message). No command = always ok."""
    if not command:
        return True, ""
    import subprocess  # only scans run a gate; keep it off the quick commands' path
    try:
        done = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"gate failed to run: {exc}"
    message = (done.stdout + done.stderr).strip()[:500]
    return done.returncode == 0, message or f"exit {done.returncode}"
