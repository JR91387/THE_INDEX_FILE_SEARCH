# SPDX-License-Identifier: MIT
"""Builds each collector's arguments (and launcher) from the config and database, then runs it."""
import json
from datetime import date

from . import collectors

FOLDER_KEYS = ("roots", "depth", "slots", "exclude", "budget_s")


def folder_options(conn, cfg, measure_all=False):
    """Options JSON for folders.py: config + content rules from ref_content_rule + tonight's rotation slot."""
    opts = {k: cfg.folders[k] for k in FOLDER_KEYS if k in cfg.folders}
    slots = 1 if measure_all else int(opts.get("slots", 7))
    opts.update(slots=slots, slot=date.today().toordinal() % slots, mixed_threshold=cfg.mixed_threshold)
    rules = conn.execute("SELECT r.match_kind, r.pattern, t.code FROM ref_content_rule r "
                         "JOIN ref_content_type t ON t.id = r.content_type_id "
                         "WHERE r.retired_at IS NULL ORDER BY r.weight, r.id").fetchall()
    opts["ext"] = {p: code for kind, p, code in rules if kind == "ext"}
    opts["markers"] = {p: code for kind, p, code in rules if kind == "marker"}
    return opts


def launcher(cfg, name):
    """sudo command for the folder scanner when [folders] sudo = true (see contrib/), else None. The command
    line is fixed; the options travel on stdin (see collectors.run_script)."""
    if name != "folders" or not cfg.folders.get("sudo"):
        return None
    return ["sudo", "-n", cfg.folders.get("sudo_python", "/usr/bin/python3"), "-I",
            cfg.folders.get("script", "/usr/local/lib/the-index/folders_root.py")]


def run(conn, cfg, name, measure_all=False):
    args = []
    if name == "backups":
        args = [json.dumps(cfg.backups)]
    elif name == "folders":
        args = [json.dumps(folder_options(conn, cfg, measure_all))]
    return collectors.run(name, args, launcher(cfg, name))
