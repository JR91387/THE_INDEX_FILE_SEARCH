# SPDX-License-Identifier: MIT
"""Render the page model to Markdown files: index.md plus one page per section. Same DB, same bytes."""
import os
import re
import tempfile
from pathlib import Path

from ..units import size
from . import model

EMPTY = "Nothing yet."
MAX_FOLDERS = 100
_VALUE = r"""(?:"[^"]*"|'[^']*'|[^\s"']+)"""
SECRET = re.compile(r"((?:--(?:password|passwd|token|secret|api-key|apikey)(?:=|\s+)"
                    r"|\b(?:password|passwd|token|secret|apikey|api_key)="
                    r"|\b\w*_(?:token|secret|password|key)=))" + _VALUE, re.IGNORECASE)
SECTIONS = ("folders", "jobs", "containers", "filesystems", "backups", "changes", "gaps")
ICON = {"emergency": "🚨", "warn": "⚠️", "ok": "✅", "unknown": "❔", "suspicious": "🚩", "unreviewed": "👁️"}


def redact(text):
    """Mask secret values in a command line (render time only; stored data is never changed)."""
    return SECRET.sub(r"\1***", text) if isinstance(text, str) else text


def redacted(m):
    """The page model as it may be shown: job commands masked, folders capped at the biggest MAX_FOLDERS
    (the model sorts sized folders first); `folders_more` counts the rest. A copy: the input is not changed."""
    jobs = {**m["jobs"], "items": [{**r, "command": redact(r["command"])} for r in m["jobs"]["items"]]}
    out = {**m, "jobs": jobs}
    if len(m["folders"]) > MAX_FOLDERS:
        out["folders"] = m["folders"][:MAX_FOLDERS]
        out["folders_more"] = len(m["folders"]) - MAX_FOLDERS
    return out


def cell(value):
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def table(headers, rows):
    """A Markdown table, or the empty-section sentence."""
    if not rows:
        return [EMPTY]
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return out + ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]


def page(title, body):
    return "\n".join([f"# {title}", "", "[index](index.md)", "", *body, ""])


def _health(value):
    return f"{ICON.get(value, '')} {value}".strip()


def folders(m):
    rows = [(r["device"], r["key"], r["primary_content"], r["purpose"], r["criticality"], size(r["size_bytes"]),
             r["file_count"]) for r in m["folders"]]
    body = table(["device", "path", "content", "purpose", "criticality", "size", "files"], rows)
    more = m.get("folders_more", 0)
    return body + (["", f"{more} more folders: use `the-index search`"] if more else [])


def jobs(m):
    j = m["jobs"]
    body = table(["device", "job", "schedule", "run as", "command"],
                 [(r["device"], r["key"], r["schedule"], r["run_as"], r["command"]) for r in j["items"]])
    if j["collisions"]:
        body += ["", "## Same-minute collisions", ""]
        body += table(["device", "minute", "jobs", "which"],
                      [(r["device"], r["minute"], r["jobs"], r["keys"]) for r in j["collisions"]])
    return body


def containers(m):
    rows = [(r["device"], r["key"], r["image"], r["state"], f"down (expected {r['expected']})" if r["down"] else "")
            for r in m["containers"]["items"]]
    return table(["device", "container", "image", "state", "problem"], rows)


def filesystems(m):
    rows = [(r["device"], r["key"], r["fstype"], size(r["size_bytes"]), size(r["used_bytes"]),
             "" if r["used_pct"] is None else f"{r['used_pct']}%", _health(r["health"])) for r in m["filesystems"]]
    return table(["device", "mount", "type", "size", "used", "used %", "health"], rows)


def backups(m):
    rows = [(r["device"], r["key"], _health(r["health"]), r["newest_good_at"] or "never", r["max_age_s"])
            for r in m["backups"]]
    return table(["device", "backup", "health", "newest good copy", "max age (s)"], rows)


def changes(m):
    rows = [(r["id"], _health(r["class"]), r["action"], r["device"], r["key"], r["reason"], r["started_at"])
            for r in m["changes"]]
    return table(["id", "class", "action", "device", "key", "reason", "seen"], rows)


def gaps(m):
    rows = [(r["device"] or "*", r["kind"], r["target"], r["reason"], r["since"]) for r in m["gaps"]]
    return table(["device", "kind", "target", "reason", "since"], rows)


def _counts(m):
    f = m["front"]
    return [("folders", len(m["folders"]) + m.get("folders_more", 0)), ("jobs", len(m["jobs"]["items"])),
            ("containers", len(m["containers"]["items"])), ("filesystems", len(m["filesystems"])),
            ("backups", len(m["backups"])), ("changes", f["changes_suspicious"] + f["changes_unreviewed"]),
            ("gaps", f["gaps_open"])]


def _lists(m):
    """Projects and largest folders (top 10 each); a list with no rows is left out."""
    out = []
    if m.get("projects"):
        rows = [(r["device"], r["path"], ", ".join(r["agent_files"]), size(r["size_total"])) for r in m["projects"]]
        out += ["## Projects", "", *table(["device", "path", "agent files", "size"], rows), ""]
    if m.get("largest"):
        rows = [(r["device"], r["path"], size(r["size_total"])) for r in m["largest"]]
        out += ["## Largest folders", "", *table(["device", "path", "size"], rows), ""]
    return out


def front(m):
    f = m["front"]
    stale = [f"{ICON['emergency']} scan out of date: no OK run in 2 days"] if f["scan_stale"] else []
    facts = stale + [
             f"{ICON['emergency']} backups past emergency age: {f['backups_emergency']}",
             f"{ICON['warn']} backups past max age: {f['backups_warn']}",
             f"{ICON['suspicious']} suspicious changes open: {f['changes_suspicious']}",
             f"{ICON['unreviewed']} unreviewed changes open: {f['changes_unreviewed']}",
             f"changes in last 24h: {f['changes_24h']}",
             f"bad runs in last 24h: {f['runs_bad_24h']}",
             f"skipped runs in last 24h: {f['runs_skipped_24h']}",
             f"containers stopped that were running: {f['containers_stopped']}",
             f"containers that should be running but are not: {f['containers_down']}",
             f"filesystems nearly full: {f['filesystems_full']}",
             f"folders with no known purpose: {f['folders_no_purpose']}",
             f"irreplaceable without backup: {f['unbacked_irreplaceable']}",
             f"blind spots: {f['gaps_open']}"]
    head = f"Last run {f['last_run'] or 'never'}, last OK run {f['last_ok_run'] or 'never'}."
    links = [f"- [{name}]({name}.md) ({n})" for name, n in _counts(m)]
    return "\n".join(["# THE INDEX", "", head, "", *(f"- {x}" for x in facts), "", *_lists(m), "## Pages", "", *links, ""])


RENDER = {"folders": folders, "jobs": jobs, "containers": containers, "filesystems": filesystems,
          "backups": backups, "changes": changes, "gaps": gaps}


def render(m):
    """Map file name -> text, for the whole page set."""
    m = redacted(m)
    files = {"index.md": front(m)}
    for name in SECTIONS:
        files[f"{name}.md"] = page(name.capitalize(), RENDER[name](m))
    return files


def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def private_dir(out_dir):
    """The pages folder; created 0700 when new. An existing folder keeps its mode (never loosened)."""
    out = Path(out_dir).expanduser()
    if not out.exists():
        out.mkdir(parents=True, exist_ok=True)
        os.chmod(out, 0o700)
    return out


def write(conn, out_dir):
    """Write every page into out_dir (created if needed); returns the directory."""
    out = private_dir(out_dir)
    for name, text in render(model.build(conn)).items():
        write_atomic(out / name, text)
    return out
