# SPDX-License-Identifier: MIT
"""`the-index bench`: build a seeded synthetic tree, time each scenario, print one table, optionally write JSON.

Runs entirely in a temporary folder (or --root) with its own database; never reads or writes the user's index and
sends nothing anywhere. Scenarios: bare walk (the floor), first scan, unchanged rescan, 1 % changed rescan,
`find` in-process and from the command line, database bytes per file."""
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import bench_tree, config, db, files_run, query

QUERIES = [[w] for w in bench_tree.WORDS[:40:2]] + [[w[:3]] for w in bench_tree.WORDS[1:40:4]] + \
          [list(p) for p in zip(bench_tree.WORDS[::9], bench_tree.WORDS[5::9])][:10]


def _clock(fn, *args):
    start = time.perf_counter()
    out = fn(*args)
    return time.perf_counter() - start, out


def _pct(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


def _cfg(tree, db_path):
    cfg = config.Config(device_name="bench", db_path=db_path)
    cfg.filetree = {"roots": [str(tree)]}
    cfg.sources = {"native": "off"}
    return cfg


def _scans(tree, db_path, out):
    conn = db.init(db_path)
    cfg = _cfg(tree, db_path)
    out["first_scan_s"], first = _clock(files_run.run, conn, cfg, True)
    out["titles_read"] = first.get("titles", 0)
    out["rescan_unchanged_s"], _ = _clock(files_run.run, conn, cfg, False)
    out["changed_folders"] = bench_tree.change(tree)
    out["rescan_1pct_s"], _ = _clock(files_run.run, conn, cfg, False)
    conn.close()


def _finds(db_path, out):
    conn = db.open(db_path)
    find = query.COMMANDS["find"]
    find(conn, {"words": ["warmup"], "limit": 25})
    times = [_clock(find, conn, {"words": q, "limit": 25})[0] for q in QUERIES]
    out["find_inproc_p50_ms"] = round(statistics.median(times) * 1000, 2)
    out["find_inproc_p95_ms"] = round(_pct(times, 95) * 1000, 2)
    conn.close()
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    argv = [sys.executable, "-m", "theindex", "--db", str(db_path), "find", "--json", "--"]
    cli = [_cli_once(argv + q, env) for q in QUERIES[:10]]
    out["find_cli_p50_ms"] = round(statistics.median(cli) * 1000, 1)
    out["find_cli_p95_ms"] = round(_pct(cli, 95) * 1000, 1)


def _cli_once(argv, env):
    start = time.perf_counter()
    subprocess.run(argv, env=env, capture_output=True, check=True)
    return time.perf_counter() - start


def _peak_rss_mb():
    try:
        import resource
    except ImportError:                       # Windows
        return None
    scale = 1 if sys.platform == "darwin" else 1024
    usage = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return round(usage * scale / 1e6, 1)


def run(files, root=None, keep=False):
    """Returns the result dict. root: folder to build in (default a new temp folder)."""
    base = Path(root) if root else Path(tempfile.mkdtemp(prefix="the-index-bench-"))
    tree, db_path = base / "tree", base / "bench.db"
    out = {"schema_version": 1, "files_requested": files, "machine": {
        "os": platform.system(), "release": platform.release(), "cpus": os.cpu_count(),
        "python": platform.python_version(), "sqlite": db.sqlite3.sqlite_version}}
    try:
        out["make_tree_s"], (out["files"], out["folders"]) = _clock(bench_tree.make, tree, files)
        out["reference_walk_s"], _ = _clock(bench_tree.reference_walk, tree)
        _scans(tree, db_path, out)
        _finds(db_path, out)
        out["db_bytes_per_file"] = round(db_path.stat().st_size / max(1, out["files"]), 1)
        out["peak_rss_mb"] = _peak_rss_mb()
    finally:
        if not keep:
            shutil.rmtree(base, ignore_errors=True)
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in out.items()}


def table(result):
    rows = [(k, v) for k, v in result.items() if k != "machine"]
    width = max(len(k) for k, _ in rows)
    lines = [f"{k:<{width}}  {v}" for k, v in rows]
    m = result["machine"]
    return "\n".join([f"{m['os']} {m['release']} · {m['cpus']} CPUs · Python {m['python']} · SQLite {m['sqlite']}"]
                     + lines)


def cmd_bench(cfg, args):
    result = run(args.files, args.root, args.keep)
    print(table(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return 0
