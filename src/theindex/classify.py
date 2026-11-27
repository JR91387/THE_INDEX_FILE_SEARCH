# SPDX-License-Identifier: MIT
"""Change classification. Order: declared -> baseline -> suspicious -> routine -> unreviewed.

A change is a dict: {item_id, kind, key, action, diff}. decide() returns (class_code, reason, declared_id).
"""

PERMISSION_FIELDS = {"owner", "group", "mode"}
JOB_IDENTITY_FIELDS = {"command", "run_as"}
ROUTINE_FIELDS = {"started_at", "image_id", "status_text", "pid"}
FLIP_TO = {"unknown", "archive"}           # content suddenly unreadable or packed: possible ransomware
DECLARED_ACTION = {"new": "new", "back": "new", "gone": "gone", "modified": "modified", "threshold": "modified"}

MATCH_SQL = """
SELECT dc.id FROM declared_change dc
JOIN ref_declared_status s ON s.id = dc.status_id
JOIN ref_declared_action a ON a.id = dc.action_id
LEFT JOIN ref_item_kind k ON k.id = dc.kind_id
WHERE s.code = 'active' AND dc.expires_at > :now
  AND (dc.device_id IS NULL OR dc.device_id = :device_id)
  AND (dc.kind_id IS NULL OR k.code = :kind)
  AND :key GLOB dc.key_glob
  AND a.code IN (:action, 'any')
ORDER BY dc.id LIMIT 1"""


def match_declared(conn, ctx, change):
    """Id of the first active, unexpired declaration covering this change, or None."""
    row = conn.execute(MATCH_SQL, {"now": ctx["now"], "device_id": ctx["device_id"], "kind": change["kind"],
                                   "key": change["key"], "action": DECLARED_ACTION[change["action"]]}).fetchone()
    return row[0] if row else None


def suspicious_reason(change):
    """Why a change is suspicious, or None."""
    action, kind, diff = change["action"], change["kind"], change.get("diff") or {}
    fields = set(diff)
    if action == "threshold":
        return "metric crossed a limit: " + ", ".join(sorted(fields))
    if kind == "job" and action == "new":
        return "new scheduled job"
    if kind == "container" and action == "gone":
        return "container disappeared"
    if fields & PERMISSION_FIELDS:
        return "ownership or permissions changed: " + ", ".join(sorted(fields & PERMISSION_FIELDS))
    if kind == "job" and fields & JOB_IDENTITY_FIELDS:
        return "job command or user changed"
    if "primary_content" in diff and diff["primary_content"][1] in FLIP_TO:
        return f"content type flipped to {diff['primary_content'][1]}"
    return None


def routine_reason(change):
    diff = change.get("diff") or {}
    if change["action"] == "modified" and diff and set(diff) <= ROUTINE_FIELDS:
        return "only routine fields changed"
    return None


def decide(conn, ctx, change):
    """Classify one change. ctx: {now, device_id, baseline}. baseline = first good scan of this collector."""
    declared = match_declared(conn, ctx, change)
    if declared:
        return "expected", f"declared change #{declared}", declared
    if ctx.get("baseline") and change["action"] == "new":
        return "routine", "first scan (baseline)", None
    reason = suspicious_reason(change)
    if reason:
        return "suspicious", reason, None
    reason = routine_reason(change)
    if reason:
        return "routine", reason, None
    return "unreviewed", None, None


def size_drop(previous, current, drop):
    """True if a size fell by at least `drop` (fraction) between two samples."""
    try:
        before, after = int(previous), int(current)
    except (TypeError, ValueError):
        return False
    return before > 0 and after <= before * (1 - drop)
