# SPDX-License-Identifier: MIT
"""Member side: the title cache. A member has no index database, so document titles it has read live in a small
SQLite file in its data dir: titles(path_key PRIMARY KEY, sig, title, src, meta), sig = 'size:mtime_ns'. Only files
whose sig changed are read again (collectors/titles.py, through its worklist contract, under a budget)."""
import json
import os
import sqlite3
import sys
from contextlib import closing

from . import config, files_run


def data_dir():
    return config.xdg("XDG_DATA_HOME", ".local/share")


def open_cache(path=None):
    path = path or data_dir() / "member.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("CREATE TABLE IF NOT EXISTS titles (path_key TEXT PRIMARY KEY, sig TEXT, title TEXT, src TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    if "meta" not in [r[1] for r in conn.execute("PRAGMA table_info(titles)")]:
        conn.execute("ALTER TABLE titles ADD COLUMN meta TEXT")      # NULL = read before front matter existed
    return conn


def lookup(cache, key, sig, with_meta=True):
    """(title, src, meta JSON or None) when the cached sig still matches (and meta was read, if wanted), else None."""
    row = cache.execute("SELECT sig, title, src, meta FROM titles WHERE path_key = ?", (key,)).fetchone()
    if not row or row[0] != sig or (with_meta and row[3] is None):
        return None
    return row[1], row[2], row[3]


def bump_runs(cache):
    """Count of filetree runs made here (decides when to list every directory again)."""
    cache.execute("INSERT INTO meta (key, value) VALUES ('runs', '1') "
                  "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")
    return int(cache.execute("SELECT value FROM meta WHERE key = 'runs'").fetchone()[0])


def read_titles(cache, wanted, job):
    """wanted = [(mtime_ns, key, path, sig)]; job = (settings, scratch dir). Reads the newest files first, at most
    title_budget of them, and stores what came back. Returns how many titles were read."""
    s, tmp = job
    wanted = sorted(wanted, key=lambda w: w[0] or 0, reverse=True)[:int(s["title_budget"])]
    if not wanted:
        return 0
    worklist = os.path.join(tmp, "titles.jsonl")
    with open(worklist, "w", encoding="utf-8") as out:
        out.writelines(json.dumps({"id": i, "path": w[2]}) + "\n" for i, w in enumerate(wanted))
    budget = min(600, float(s["budget_s"]))
    argv = [sys.executable, "-I", str(files_run.HERE / "titles.py"), "--worklist", worklist,
            json.dumps({"budget_s": budget, "max_files": len(wanted)})]
    got = files_run.stream(argv, budget + 120, lambda lines: _collect(lines, len(wanted)))
    with closing(cache.cursor()) as cur:
        cur.execute("BEGIN")
        cur.executemany("INSERT INTO titles (path_key, sig, title, src, meta) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(path_key) DO UPDATE SET sig = excluded.sig, title = excluded.title, "
                        "src = excluded.src, meta = excluded.meta",
                        [(wanted[i][1], wanted[i][3], t, src, m) for i, (t, src, m) in got.items()])
        cur.execute("COMMIT")
    return len(got)


def _collect(lines, size):
    got = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec.get("id"), int) and 0 <= rec["id"] < size:
            got[rec["id"]] = (rec.get("title"), rec.get("src"), files_run.meta_json(rec))
    return got
