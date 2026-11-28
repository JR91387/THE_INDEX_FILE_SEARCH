# SPDX-License-Identifier: MIT
"""Collector: sources. Standalone, stdlib only, READ-ONLY (never opens file contents, never writes).
    python3 -I sources.py '<options JSON>'      the filetree JSON Lines stream, built from the OS's own index
    python3 -I sources.py --probe '<options>'   one JSON line: {"source": name-or-null, "reason": text}
Sources: plocate/locate (Linux), Spotlight (macOS), Everything's `es` (Windows); first match for the platform.
Options: roots, exclude, cache_markers, agent_markers, budget_s, title_exts, title_budget (as filetree), plus
`count_only` (print only a trailer with files per root) and the test hooks `platform`, `locate_db`.
The header carries `source` and `no_retire: true`: a native listing never retires rows (the walk does).
Any failure prints a header and a `partial` trailer with the error so the caller falls back to the walk."""
import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filetree_walk as walk
import sources_model as model
import sources_tools as tools

OS_NAMES = {"win32": "windows", "darwin": "darwin"}
DEFAULT_TITLE_EXTS = [".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub", ".md", ".html", ".htm"]


def emit(record):
    sys.stdout.write(walk.json_line(record) + "\n")


def header(opts, source):
    platform = opts.get("platform") or sys.platform
    return {"t": "header", "collector": "filetree", "script": "sources.py", "host": socket.gethostname(),
            "os": OS_NAMES.get(platform, "linux"), "case_insensitive": walk.case_insensitive(), "full": False,
            "roots": [os.path.normpath(r) for r in opts.get("roots", [])], "started_at": walk.utc(),
            "source": source, "no_retire": True}


def parse(argv):
    rest = [a for a in argv if a != "--probe"]
    return (json.loads(rest[0]) if rest else {}), "--probe" in argv


def read_all(source, exe, opts):
    """Build the model from every root; titles (Spotlight only) as a second dict."""
    built = model.Model(opts)
    for root in (os.path.normpath(r) for r in opts.get("roots", [])):
        if built.allowed(root, root) and os.path.isdir(root):
            for path in tools.run_reader(source, exe, root):
                built.add(path, root)
    built.resolve()
    titles = {}
    if source == "spotlight" and not opts.get("count_only"):
        exts = {e.lower() for e in opts.get("title_exts") or DEFAULT_TITLE_EXTS}
        wanted = built.title_candidates(exts, int(opts.get("title_budget", 20000)))
        titles = tools.mdls_titles(wanted, len(wanted))
    return built, titles


def run(opts, source, exe):
    """Emit the records (or just per-root counts); returns the trailer counts."""
    built, titles = read_all(source, exe, opts)
    counts = {"dirs": 0, "files": 0, "roots": built.counts}
    if opts.get("count_only"):
        counts["files"] = sum(built.counts.values())
        return counts
    for rec in built.records(titles):
        counts["dirs" if rec["t"] == "dir" else "files"] += 1
        emit(rec)
    return counts


def main(argv):
    errors, opts, counts, source = [], {}, {"dirs": 0, "files": 0}, None
    try:
        opts, probing = parse(argv)
        source, exe, reason = tools.detect(opts)
        if probing:
            print(json.dumps({"source": source, "reason": reason}))
            return 0
        if source is None:
            errors.append(f"native index unavailable: {reason}")
    except (ValueError, TypeError) as err:
        errors.append(f"bad options: {err}")
    emit(header(opts, source))
    if not errors:
        try:
            counts = run(opts, source, exe)
        except model.Budget as err:
            errors.append(str(err))
        except Exception as err:  # noqa: BLE001 -- always print a trailer; an error makes the run partial
            errors.append(f"{type(err).__name__}: {err}")
    emit({"t": "trailer", "status": "partial" if errors else "ok", "finished_at": walk.utc(), "counts": counts,
          "errors": errors})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
