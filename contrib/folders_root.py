#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Root entry point of the folder scanner. The installer puts it, root-owned, next to folders.py; the sudoers
rule allows exactly:   /usr/bin/python3 -I /usr/local/lib/the-index/folders_root.py   (no arguments)
The caller sends its options as JSON on stdin (slot, ext, markers, budget_s ...). roots, exclude and depth are
taken ONLY from the root-owned /etc/the-index/folders.json: whatever the caller sends for them is ignored, so
the sudo right cannot be used to list other trees. biggest_file is reported as a bare file name."""
import importlib.util
import json
import os
import sys

CONF = "/etc/the-index/folders.json"
SCANNER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "folders.py")
FIXED = ("roots", "exclude", "depth")


def conf_path():
    """The options file. Only a non-root process (the tests) may point elsewhere through the environment."""
    return CONF if os.geteuid() == 0 else os.environ.get("THE_INDEX_SCANNER_CONF", CONF)


def load_scanner():
    spec = importlib.util.spec_from_file_location("the_index_folders", SCANNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_options(scanner, given):
    """Caller options with roots/exclude/depth replaced by the file's (or the scanner's defaults)."""
    with open(conf_path(), encoding="utf-8") as fh:
        fixed = json.load(fh)
    opts = {k: v for k, v in given.items() if k not in FIXED}
    opts.update(roots=fixed.get("roots", scanner.DEFAULTS["roots"]), exclude=fixed.get("exclude", []),
                depth=fixed.get("depth", scanner.DEFAULTS["depth"]), privileged=True)
    if not (isinstance(opts["roots"], list) and all(isinstance(r, str) and r.startswith("/") for r in opts["roots"])):
        raise ValueError("roots in the options file must be a list of absolute paths")
    return opts


def main():
    try:
        scanner = load_scanner()
        payload = scanner.scan(build_options(scanner, json.loads(sys.stdin.read() or "{}")))
    except Exception as exc:  # noqa: BLE001 -- always print a payload; a failed run retires nothing
        payload = {"collector": "folders", "kinds": ["folder"], "status": "failed", "items": [], "gaps": [],
                   "coverage": [], "errors": [f"folders_root: {type(exc).__name__}: {exc}"]}
    print(json.dumps(payload, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
