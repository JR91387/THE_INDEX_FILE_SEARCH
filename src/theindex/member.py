# SPDX-License-Identifier: MIT
"""Member side of the fleet: `the-index collect --out DIR`.

Runs the collectors on this machine and writes each payload into the shared inbox as
`<machine>_<collector>_<UTC stamp>.json` (filetree: `.jsonl`). A member has no index database: the collectors'
arguments come from a throw-away scratch database holding only the built-in seeds. Every file is written to
`DIR/.tmp-<name>` and renamed into place, so the hub (which skips dot-files) never reads a partial file."""
import json
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import collect, collectors, db, files_run, identity, member_files


def _stamp(at, plus=0):
    return (at + timedelta(seconds=plus)).strftime("%Y%m%dT%H%M%SZ")


def _label(machine, host):
    return machine or re.sub(r"[^A-Za-z0-9._-]+", "-", host).strip("-") or "member"


def _write_json(final, payload):
    part = member_files.tmp_path(final)
    try:
        part.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        os.replace(part, final)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return final


def _failed(name, exc):
    return {"collector": name, "status": "failed", "items": [], "errors": [f"{type(exc).__name__}: {exc}"[:500]]}


def _collect_one(cfg, scratch, job):
    """job = (collector name, identity dict, final path, scratch dir). One failure never stops the others."""
    name, ident, final, tmp = job
    try:
        if name == "filetree":
            return member_files.run(cfg, scratch, (ident, final, tmp))
        return _write_json(final, {**collect.run(scratch, cfg, name), **ident})
    except Exception as exc:  # noqa: BLE001 -- a failed collector is still a payload: the hub records the failure
        if name == "filetree":
            final = final.with_suffix(".json")
        return _write_json(final, {**_failed(name, exc), **ident})


def _names(cfg, only):
    """Collectors to run: the one asked for, else the configured ones; unknown names and a disabled filetree are left out."""
    wanted = [only] if only else cfg.collectors
    return [n for n in wanted if n in collectors.REGISTRY and (n != "filetree" or files_run.settings(cfg)["enabled"])]


def _job(name, who, folder, tmp):
    """(name, identity dict, final path, scratch dir) for one collector; who = (machine, host, time)."""
    machine, host, at = who
    ext = ".jsonl" if name == "filetree" else ".json"
    ident = {"payload_id": uuid.uuid4().hex, "machine": machine, "host": host}
    final, plus = folder / f"{_label(machine, host)}_{name}_{_stamp(at)}{ext}", 0
    while final.exists():                     # never overwrite a file the hub has not taken yet
        plus += 1
        final = folder / f"{_label(machine, host)}_{name}_{_stamp(at, plus)}{ext}"
    return name, ident, final, tmp


def run(cfg, out_dir, only=None):
    """Write one payload file per collector into `out_dir`; returns the paths written."""
    if only and only not in collectors.REGISTRY:
        raise KeyError(f"unknown collector {only!r}; known: {', '.join(collectors.REGISTRY)}")
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    who = (identity.machine_hash(), cfg.device_name, datetime.now(UTC))
    with tempfile.TemporaryDirectory(prefix="the-index-") as tmp:
        scratch = db.init(Path(tmp) / "scratch.db")
        try:
            return [_collect_one(cfg, scratch, _job(name, who, out, tmp)) for name in _names(cfg, only)]
        finally:
            scratch.close()
