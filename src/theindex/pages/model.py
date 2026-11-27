# SPDX-License-Identifier: MIT
"""The page model: the views as plain JSON-serialisable dicts and lists. One entry point: build(conn)."""
import json

CHANGES = ("SELECT id, class, action, device, kind, key, reason, started_at FROM v_changes_open "
           "ORDER BY severity DESC, id DESC")
GAPS = "SELECT id, device, kind, target, reason, since FROM v_gaps_open ORDER BY id"
FOLDERS = ("SELECT device, key, primary_content, purpose, criticality, size_bytes, file_count FROM v_folders "
           "ORDER BY coalesce(size_bytes, -1) DESC, device, key")
FILESYSTEMS = ("SELECT device, key, fstype, size_bytes, used_bytes, used_pct, health FROM v_filesystems "
               "ORDER BY device, key")
BACKUPS = ("SELECT device, key, health, newest_good_at, max_age_s FROM v_backups_stale "
           "ORDER BY CASE health WHEN 'emergency' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, device, key")
COLLISIONS = "SELECT device, minute, jobs, keys FROM v_job_collisions ORDER BY device, minute"
JOBS = "SELECT device, key, attrs FROM v_item WHERE kind = 'job' AND is_active ORDER BY device, key"
CONTAINERS = "SELECT id, device, key, attrs FROM v_item WHERE kind = 'container' AND is_active ORDER BY device, key"
SINCE = ("SELECT id, started_at, class, action, device, kind, key, reason, diff, reviewed_at IS NOT NULL AS reviewed "
         "FROM v_change WHERE julianday(started_at) > julianday('now') - ? / 86400.0 AND NOT is_baseline "
         "ORDER BY id DESC")
PROJECTS = ("SELECT device, path, agent_files, size_total FROM v_projects "
            "ORDER BY mtime_ns IS NULL, mtime_ns DESC, path LIMIT 10")
LARGEST = "SELECT device, path, size_total FROM v_dirs_largest ORDER BY size_total DESC, path LIMIT 10"
DOWN = "SELECT id, expected, assumed FROM v_containers_down"


def _all(conn, sql):
    return [dict(r) for r in conn.execute(sql).fetchall()]


def _attrs(row):
    out = dict(row)
    out["attrs"] = json.loads(out["attrs"] or "{}")
    return out


def jobs(conn):
    rows = [_attrs(r) for r in conn.execute(JOBS).fetchall()]
    items = [{"device": r["device"], "key": r["key"], "schedule": r["attrs"].get("schedule"),
              "run_as": r["attrs"].get("run_as"), "command": r["attrs"].get("command")} for r in rows]
    return {"items": items, "collisions": _all(conn, COLLISIONS)}


def containers(conn):
    down = {r["id"]: r for r in conn.execute(DOWN).fetchall()}
    items = []
    for r in (_attrs(x) for x in conn.execute(CONTAINERS).fetchall()):
        d = down.get(r["id"])
        items.append({"device": r["device"], "key": r["key"], "image": r["attrs"].get("image"),
                      "state": r["attrs"].get("state"), "down": d is not None,
                      "expected": d["expected"] if d else None})
    return {"items": items}


def changes_since(conn, seconds):
    """Changes recorded in the last `seconds` (first-scan sightings left out), newest first; diff decoded."""
    out = []
    for row in conn.execute(SINCE, (int(seconds),)).fetchall():
        item = dict(row)
        item["diff"] = json.loads(item["diff"]) if item["diff"] else None
        item["reviewed"] = bool(item["reviewed"])
        out.append(item)
    return out


def overview(conn):
    """The front page: counts from v_front_page plus open changes and gaps."""
    projects = [{**r, "agent_files": json.loads(r["agent_files"])} for r in _all(conn, PROJECTS)]
    return {"front": dict(conn.execute("SELECT * FROM v_front_page").fetchone()),
            "changes": _all(conn, CHANGES), "gaps": _all(conn, GAPS),
            "projects": projects, "largest": _all(conn, LARGEST)}


def build(conn):
    """Everything a page needs: the overview plus one section per kind, each from its own view."""
    return {**overview(conn), "folders": _all(conn, FOLDERS), "jobs": jobs(conn),
            "containers": containers(conn), "filesystems": _all(conn, FILESYSTEMS),
            "backups": _all(conn, BACKUPS)}
