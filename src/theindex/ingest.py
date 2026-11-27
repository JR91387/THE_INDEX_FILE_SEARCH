# SPDX-License-Identifier: MIT
"""Load one merged collector payload into the database and record every change.

Rules: an item first seen -> new; attrs hash differs -> modified (+ item_version); retired then seen -> back;
active, unseen, and under a covered prefix of an OK run -> gone. Partial runs never retire anything.
"""
import hashlib
import json

from . import classify, collectors, content, db, gaps, links


def attrs_json(attrs):
    """Canonical JSON so equal attrs always hash the same."""
    return json.dumps(attrs or {}, sort_keys=True, separators=(",", ":"))


def diff(old, new):
    """{field: [old, new]} for every top-level field that differs."""
    return {k: [old.get(k), new.get(k)] for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)}


def ensure_device(conn, name):
    row = conn.execute("SELECT id FROM device WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    return conn.execute("INSERT INTO device (name, reach_id, status_id) VALUES (?, ?, ?)",
                        (name, conn.ref_id("ref_reach", "local"), conn.ref_id("ref_device_status", "active"))).lastrowid


def start_run(conn, device_id, payload):
    collector_id = conn.ref_id("ref_collector", payload["collector"])
    ok = conn.ref_id("ref_run_status", "ok")
    prior = conn.execute("SELECT 1 FROM scan_run WHERE device_id = ? AND collector_id = ? AND status_id = ?",
                         (device_id, collector_id, ok)).fetchone()
    run_id = conn.execute("INSERT INTO scan_run (device_id, collector_id, started_at, status_id) VALUES (?,?,?,?)",
                          (device_id, collector_id, payload.get("started_at") or db.now(),
                           conn.ref_id("ref_run_status", "running"))).lastrowid
    return {"run_id": run_id, "device_id": device_id, "collector_id": collector_id, "now": db.now(),
            "baseline": prior is None, "changes": 0}


def record_change(conn, ctx, change):
    klass, reason, declared_id = classify.decide(conn, ctx, change)
    conn.execute("INSERT INTO change (run_id, item_id, action_id, diff, class_id, reason, declared_id) "
                 "VALUES (?,?,?,?,?,?,?)",
                 (ctx["run_id"], change["item_id"], conn.ref_id("ref_change_action", change["action"]),
                  json.dumps(change["diff"]) if change.get("diff") else None,
                  conn.ref_id("ref_change_class", klass), reason, declared_id))
    ctx["changes"] += 1


def write_version(conn, ctx, item_id, version):
    text, digest = version
    conn.execute("INSERT INTO item_version (item_id, run_id, attrs, attrs_hash) VALUES (?,?,?,?)",
                 (item_id, ctx["run_id"], text, digest))


def carried(obs, row):
    """attrs, with fields named in obs['carry'] copied from the stored item when this run did not measure
    them (e.g. a folder's primary_content is only computed on its rotation night)."""
    attrs = dict(obs.get("attrs") or {})
    old = json.loads(row["attrs"]) if row else {}
    for name in obs.get("carry", []):
        if name not in attrs and name in old:
            attrs[name] = old[name]
    return attrs


def upsert_item(conn, ctx, obs):
    """Insert or update one observed item; record new/modified/back. Returns item id."""
    kind_id = conn.ref_id("ref_item_kind", obs["kind"])
    row = conn.execute("SELECT id, attrs, attrs_hash, retired_run FROM item WHERE device_id=? AND kind_id=? AND key=?",
                       (ctx["device_id"], kind_id, obs["key"])).fetchone()
    text = attrs_json(carried(obs, row))
    digest = hashlib.sha256(text.encode()).hexdigest()
    change = {"kind": obs["kind"], "key": obs["key"], "diff": None}
    if row is None:
        item_id = conn.execute("INSERT INTO item (device_id, kind_id, key, attrs, attrs_hash, first_seen_run, "
                               "last_seen_run) VALUES (?,?,?,?,?,?,?)",
                               (ctx["device_id"], kind_id, obs["key"], text, digest,
                                ctx["run_id"], ctx["run_id"])).lastrowid
        write_version(conn, ctx, item_id, (text, digest))
        record_change(conn, ctx, {**change, "item_id": item_id, "action": "new"})
        return item_id
    item_id, changed = row["id"], row["attrs_hash"] != digest
    conn.execute("UPDATE item SET attrs=?, attrs_hash=?, last_seen_run=?, retired_run=NULL WHERE id=?",
                 (text, digest, ctx["run_id"], item_id))
    if changed:
        write_version(conn, ctx, item_id, (text, digest))
        change["diff"] = diff(json.loads(row["attrs"]), json.loads(text))
    if row["retired_run"] is not None:
        record_change(conn, ctx, {**change, "item_id": item_id, "action": "back"})
    elif changed:
        record_change(conn, ctx, {**change, "item_id": item_id, "action": "modified"})
    return item_id


def write_metrics(conn, ctx, item_id, obs):
    """Store metric samples; unknown metric codes are skipped. Backups: check for a size drop."""
    for code, value in (obs.get("metrics") or {}).items():
        try:
            metric_id = conn.ref_id("ref_metric", code)
        except KeyError:
            continue
        if obs["kind"] == "backup" and code == "size_bytes":
            check_size_drop(conn, ctx, item_id, (metric_id, value, obs))
        conn.execute("INSERT INTO metric_sample (item_id, run_id, metric_id, value) VALUES (?,?,?,?)",
                     (item_id, ctx["run_id"], metric_id, None if value is None else str(value)))


def check_size_drop(conn, ctx, item_id, sample):
    metric_id, value, obs = sample
    prev = conn.execute("SELECT value FROM metric_sample WHERE item_id=? AND metric_id=? ORDER BY run_id DESC LIMIT 1",
                        (item_id, metric_id)).fetchone()
    drop = float(conn.execute("SELECT value FROM setting WHERE key='size_drop_suspicious'").fetchone()[0])
    if prev and classify.size_drop(prev[0], value, drop):
        record_change(conn, ctx, {"item_id": item_id, "kind": obs["kind"], "key": obs["key"],
                                  "action": "threshold", "diff": {"size_bytes": [prev[0], value]}})


def retire_unseen(conn, ctx, payload, seen):
    """Mark active items of this collector's kinds as gone, only under prefixes the run fully covered."""
    coverage, excepts = payload.get("coverage", []), payload.get("coverage_except", [])
    for kind in payload.get("kinds", []):
        rows = conn.execute("SELECT id, key FROM item WHERE device_id=? AND kind_id=? AND retired_run IS NULL",
                            (ctx["device_id"], conn.ref_id("ref_item_kind", kind))).fetchall()
        for row in rows:
            key = row["key"]
            if row["id"] in seen or not any(key.startswith(p) for p in coverage) \
                    or any(key.startswith(e) for e in excepts):
                continue
            conn.execute("UPDATE item SET retired_run=? WHERE id=?", (ctx["run_id"], row["id"]))
            record_change(conn, ctx, {"item_id": row["id"], "kind": kind, "key": row["key"],
                                      "action": "gone", "diff": None})


def finish_run(conn, ctx, payload, status):
    conn.execute("UPDATE scan_run SET finished_at=?, status_id=?, items_seen=?, error=? WHERE id=?",
                 (payload.get("finished_at") or db.now(), conn.ref_id("ref_run_status", status),
                  len(payload.get("items", [])), "; ".join(payload.get("errors", []))[:2000] or None, ctx["run_id"]))


def ingest(conn, payload, device_name):
    """Record one collector run atomically. Returns {run_id, status, items, changes, baseline}."""
    status = payload.get("status") if payload.get("status") in ("ok", "partial", "failed") else "failed"
    errors = list(payload.get("errors", []))
    payload = {**payload, "items": collectors.dedupe(payload.get("items", []), errors), "errors": errors}
    if errors and status == "ok":
        status = "partial"
    conn.execute("BEGIN")
    try:
        ctx = start_run(conn, ensure_device(conn, device_name), payload)
        seen = set()
        for obs in payload.get("items", []):
            item_id = upsert_item(conn, ctx, obs)
            write_metrics(conn, ctx, item_id, obs)
            content.write(conn, ctx, item_id, obs.get("content"))
            seen.add(item_id)
        if status == "ok":
            retire_unseen(conn, ctx, payload, seen)
        ctx["run_ok"] = status == "ok"
        unresolved = links.sync(conn, ctx, payload.get("links", []), seen)
        gaps.sync(conn, ctx, payload.get("gaps", []), status == "ok")
        finish_run(conn, ctx, payload, status)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"run_id": ctx["run_id"], "status": status, "items": len(seen),
            "changes": ctx["changes"], "baseline": ctx["baseline"], "unresolved_links": unresolved}


def record_skip(conn, device_name, collector, reason):
    """A run stopped by the gate or a blackout window still leaves a scan_run row."""
    conn.execute("BEGIN")
    ctx = start_run(conn, ensure_device(conn, device_name), {"collector": collector})
    conn.execute("UPDATE scan_run SET finished_at=?, status_id=?, gate_result=? WHERE id=?",
                 (db.now(), conn.ref_id("ref_run_status", "skipped"), reason[:500], ctx["run_id"]))
    conn.execute("COMMIT")
    return ctx["run_id"]
