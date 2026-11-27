# SPDX-License-Identifier: MIT
"""Plain-text front page. Numbers and rows come from pages.model, shared with the Markdown pages."""
from .pages import model

LIMIT = 10

ICON = {"emergency": "🚨", "warn": "⚠️", "ok": "✅", "unknown": "❔", "suspicious": "🚩", "unreviewed": "👁️"}


def front_page(conn):
    """About 30 lines: when it last ran, what is wrong, what changed, what it cannot see."""
    page = model.overview(conn)
    f = page["front"]
    out = [f"THE INDEX -- last run {f['last_run'] or 'never'}, last OK run {f['last_ok_run'] or 'never'}", ""]
    stale = [f"{ICON['emergency']} scan out of date: no OK run in 2 days"] if f["scan_stale"] else []
    out += stale + [
            f"{ICON['emergency']} backups past emergency age: {f['backups_emergency']}",
            f"{ICON['warn']} backups past max age: {f['backups_warn']}",
            f"{ICON['suspicious']} suspicious changes open: {f['changes_suspicious']}",
            f"{ICON['unreviewed']} unreviewed changes open: {f['changes_unreviewed']}",
            (f"changes in last 24h: {f['changes_24h']}   bad runs in last 24h: {f['runs_bad_24h']}   "
             f"skipped runs in last 24h: {f['runs_skipped_24h']}"),
            (f"containers stopped that were running: {f['containers_stopped']}   "
             f"filesystems nearly full: {f['filesystems_full']}"),
            f"containers that should be running but are not: {f['containers_down']}",
            (f"folders with no known purpose: {f['folders_no_purpose']}   "
             f"irreplaceable without backup: {f['unbacked_irreplaceable']}"),
            f"blind spots: {f['gaps_open']}", ""]
    out += _section("Open changes", page["changes"], lambda r: f"  #{r['id']} {ICON.get(r['class'], '')} "
                    f"{r['action']} {r['device']}:{r['key']}  {r['reason'] or ''}")
    out += _section("Blind spots", page["gaps"], lambda r: f"  {r['kind']}: {r['device'] or '*'} {r['target']}")
    return "\n".join(out)


def _section(title, rows, fmt):
    return [f"{title}:"] + ([fmt(r) for r in rows[:LIMIT]] or ["  (none)"]) + [""]
