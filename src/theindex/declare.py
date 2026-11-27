# SPDX-License-Identifier: MIT
"""Declared (planned) changes and change reviews. Every write names who made it."""
from datetime import UTC, datetime, timedelta

from . import config, db


def expires_at(value):
    """'7d' / '12h' / seconds -> UTC text from now; an ISO time passes through."""
    try:
        seconds = config.parse_duration(value)
    except ValueError:
        return value
    return (datetime.now(UTC) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_fields(f):
    """Build an add() spec from user-facing fields (CLI flags or a JSON body): key, change, reason, by, expires, ..."""
    return {"key_glob": f.get("key"), "action": f.get("change") or "any", "reason": f.get("reason"),
            "declared_by": f.get("by"), "expires": f.get("expires") or "7d", "device": f.get("device"),
            "kind": f.get("kind")}


def add(conn, spec):
    """spec: key_glob, action, reason, declared_by, expires ('7d' or ISO); optional device, kind. Returns id."""
    for field in ("key_glob", "action", "reason", "declared_by", "expires"):
        if not str(spec.get(field) or "").strip():
            raise ValueError(f"declared change needs {field}")
    device_id = None
    if spec.get("device"):
        row = conn.execute("SELECT id FROM device WHERE name = ?", (spec["device"],)).fetchone()
        if row is None:
            raise ValueError(f"unknown device {spec['device']!r}")
        device_id = row[0]
    kind_id = conn.ref_id("ref_item_kind", spec["kind"]) if spec.get("kind") else None
    return conn.execute(
        "INSERT INTO declared_change (device_id, kind_id, key_glob, action_id, reason, declared_by, expires_at, "
        "status_id) VALUES (?,?,?,?,?,?,?,?)",
        (device_id, kind_id, spec["key_glob"], conn.ref_id("ref_declared_action", spec["action"]),
         spec["reason"].strip(), spec["declared_by"].strip(), expires_at(spec["expires"]),
         conn.ref_id("ref_declared_status", "active"))).lastrowid


def withdraw(conn, declared_id, by):
    done = conn.execute("UPDATE declared_change SET status_id=?, closed_by=?, closed_at=? WHERE id=? AND status_id=?",
                        (conn.ref_id("ref_declared_status", "withdrawn"), by, db.now(), declared_id,
                         conn.ref_id("ref_declared_status", "active")))
    return done.rowcount == 1


def expire_due(conn):
    """Mark active declarations past their expiry as expired. Returns how many."""
    return conn.execute("UPDATE declared_change SET status_id=? WHERE status_id=? AND expires_at <= ?",
                        (conn.ref_id("ref_declared_status", "expired"),
                         conn.ref_id("ref_declared_status", "active"), db.now())).rowcount


def active(conn):
    return conn.execute(
        "SELECT dc.id, coalesce(d.name,'*') AS device, coalesce(k.code,'*') AS kind, dc.key_glob, a.code AS action, "
        "dc.reason, dc.declared_by, dc.expires_at FROM declared_change dc "
        "JOIN ref_declared_status s ON s.id = dc.status_id JOIN ref_declared_action a ON a.id = dc.action_id "
        "LEFT JOIN device d ON d.id = dc.device_id LEFT JOIN ref_item_kind k ON k.id = dc.kind_id "
        "WHERE s.code = 'active' ORDER BY dc.expires_at").fetchall()


def review(conn, change_id, by, note=None):
    """Mark a change reviewed. Returns False if it does not exist or was already reviewed."""
    if not str(by or "").strip():
        raise ValueError("review needs a reviewer")
    done = conn.execute("UPDATE change SET reviewed_by=?, reviewed_at=?, review_note=? "
                        "WHERE id=? AND reviewed_at IS NULL", (by.strip(), db.now(), note, change_id))
    return done.rowcount == 1
