# SPDX-License-Identifier: MIT
"""Small config tables: `[inbox]` (`dir`, `role` = hub|member) and `[sources]` (`native` = auto|off)."""
from pathlib import Path

ROLES = ("hub", "member")


def apply(cfg, table):
    """Set cfg.inbox_dir and cfg.inbox_role from the table; errors name the key."""
    if not isinstance(table, dict):
        raise ValueError("[inbox] must be a table")  # noqa: TRY004 (the CLI reports ValueError)
    if "dir" in table:
        if not isinstance(table["dir"], str) or not table["dir"].strip():
            raise ValueError("inbox.dir must be a folder path")
        cfg.inbox_dir = Path(table["dir"]).expanduser()
    role = table.get("role", cfg.inbox_role)
    if role not in ROLES:
        raise ValueError("inbox.role must be hub or member")
    cfg.inbox_role = role


def sources(table):
    """[sources]: native is "auto" or "off"."""
    out = dict(table)
    if out.get("native", "auto") not in ("auto", "off"):
        raise ValueError('sources.native must be "auto" or "off"')
    return out


def pulls(tables):
    """[[pull]] tables -> list of {host, ssh_options, timeout_s, command}; errors name the key."""
    if not isinstance(tables, list) or not all(isinstance(t, dict) for t in tables):
        raise ValueError("[[pull]] must be an array of tables")
    out = []
    for t in tables:
        host, opts = t.get("host"), t.get("ssh_options", [])
        secs, command = t.get("timeout_s", 900), t.get("command", "the-index")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("pull.host is required (an ssh destination)")
        if not isinstance(opts, list) or not all(isinstance(o, str) for o in opts):
            raise ValueError("pull.ssh_options must be a list of strings")
        if isinstance(secs, bool) or not isinstance(secs, int) or secs < 1:
            raise ValueError("pull.timeout_s must be a whole number of seconds, 1 or more")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("pull.command must be a command name")
        out.append({"host": host.strip(), "ssh_options": opts, "timeout_s": secs, "command": command.strip()})
    return out
