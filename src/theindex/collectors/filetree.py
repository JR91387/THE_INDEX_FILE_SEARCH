# SPDX-License-Identifier: MIT
"""Collector: filetree. Standalone, stdlib only, READ-ONLY (never opens file contents, never writes).
    python3 -I filetree.py '<options JSON>' [--state FILE]
Prints JSON Lines (one record per line): header, dir/file/skip/gap records, trailer. See README.md, section
`filetree`. Options: roots, exclude (added to the built-in list), cache_markers, agent_markers, full, budget_s.
State file (TSV `path_key  mtime_ns  ctime_ns`): a directory unchanged since then is not listed again (`skip`).
The walk lives in filetree_walk.py, next to this script."""
import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filetree_target as target
import filetree_walk as walk

OS_NAMES = {"win32": "windows", "darwin": "darwin"}


def emit(record):
    sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")


def load_state(path):
    """TSV -> {path_key: (mtime_ns, ctime_ns)}. A missing or damaged file means no state (list everything)."""
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rows = [line.rstrip("\n").split("\t") for line in fh]
    except OSError:
        return {}
    return {r[0]: (int(r[1]), int(r[2])) for r in rows if len(r) == 3 and r[1].isdigit() and r[2].isdigit()}


def parse_args(argv):
    opts, state_file, rest = {}, None, list(argv)
    if "--state" in rest:
        at = rest.index("--state")
        state_file = rest[at + 1] if at + 1 < len(rest) else None
        del rest[at:at + 2]
    if rest:
        opts = json.loads(rest[0])
    return opts, state_file


def header(opts):
    return {"t": "header", "collector": "filetree", "script": "filetree.py", "host": socket.gethostname(),
            "os": OS_NAMES.get(sys.platform, "linux"), "case_insensitive": walk.case_insensitive(),
            "full": bool(opts.get("full")), "roots": list(opts.get("roots", [])), "started_at": walk.utc(),
            "targeted": bool(opts.get("targets") or opts.get("targets_file"))}


def main(argv):
    errors, opts, state_file = [], {}, None
    try:
        opts, state_file = parse_args(argv)
    except (ValueError, TypeError) as err:
        errors.append(f"bad options: {err}")
    head = header(opts)
    emit(head)
    walker = (target.Targeted if head["targeted"] else walk.Walker)(opts, load_state(state_file), emit)
    try:
        walker.run()
    except Exception as err:  # noqa: BLE001 -- always print a trailer; an error makes the run partial
        errors.append(f"{type(err).__name__}: {err}")
    errors += walker.errors
    status = "partial" if errors or walker.partial else "ok"
    emit({"t": "trailer", "status": status, "finished_at": walk.utc(), "counts": walker.counts, "errors": errors})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
