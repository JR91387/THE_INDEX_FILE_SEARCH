-- SPDX-License-Identifier: MIT
-- views.sql -- saved questions. Dropped and recreated on every init/upgrade, so edit freely.
-- Ages are computed against 'now' at query time.

DROP VIEW IF EXISTS v_item;
CREATE VIEW v_item AS
SELECT i.id, d.name AS device, k.code AS kind, i.key, i.attrs, i.first_seen_run, i.last_seen_run,
       i.retired_run, (i.retired_run IS NULL) AS is_active
FROM item i JOIN device d ON d.id = i.device_id JOIN ref_item_kind k ON k.id = i.kind_id;

-- Newest sample of every metric for every item. Driven from item x metric, each looked up by index
-- (newest run first), so history is never scanned.
DROP VIEW IF EXISTS v_metric_latest;
CREATE VIEW v_metric_latest AS
SELECT i.id AS item_id, m.code AS metric, ms.value, ms.run_id
FROM item i JOIN ref_metric m
JOIN metric_sample ms ON ms.id = (SELECT x.id FROM metric_sample x
                                  WHERE x.item_id = i.id AND x.metric_id = m.id ORDER BY x.run_id DESC LIMIT 1);

-- Every ref row in one place, with its icon, for the frontend.
DROP VIEW IF EXISTS v_ref_all;
CREATE VIEW v_ref_all AS
WITH r(tbl, id, code, display, description, sort_order, icon_id, retired_at) AS (
  SELECT 'health', id, code, display, description, sort_order, icon_id, retired_at FROM ref_health
  UNION ALL SELECT 'reach', id, code, display, description, sort_order, icon_id, retired_at FROM ref_reach
  UNION ALL SELECT 'device_status', id, code, display, description, sort_order, icon_id, retired_at FROM ref_device_status
  UNION ALL SELECT 'device_role', id, code, display, description, sort_order, icon_id, retired_at FROM ref_device_role
  UNION ALL SELECT 'collector', id, code, display, description, sort_order, icon_id, retired_at FROM ref_collector
  UNION ALL SELECT 'run_status', id, code, display, description, sort_order, icon_id, retired_at FROM ref_run_status
  UNION ALL SELECT 'item_kind', id, code, display, description, sort_order, icon_id, retired_at FROM ref_item_kind
  UNION ALL SELECT 'metric', id, code, display, description, sort_order, icon_id, retired_at FROM ref_metric
  UNION ALL SELECT 'link_type', id, code, display, description, sort_order, icon_id, retired_at FROM ref_link_type
  UNION ALL SELECT 'link_source', id, code, display, description, sort_order, icon_id, retired_at FROM ref_link_source
  UNION ALL SELECT 'change_action', id, code, display, description, sort_order, icon_id, retired_at FROM ref_change_action
  UNION ALL SELECT 'declared_action', id, code, display, description, sort_order, icon_id, retired_at FROM ref_declared_action
  UNION ALL SELECT 'change_class', id, code, display, description, sort_order, icon_id, retired_at FROM ref_change_class
  UNION ALL SELECT 'declared_status', id, code, display, description, sort_order, icon_id, retired_at FROM ref_declared_status
  UNION ALL SELECT 'gap_kind', id, code, display, description, sort_order, icon_id, retired_at FROM ref_gap_kind
  UNION ALL SELECT 'criticality', id, code, display, description, sort_order, icon_id, retired_at FROM ref_criticality
  UNION ALL SELECT 'expected_state', id, code, display, description, sort_order, icon_id, retired_at FROM ref_expected_state
  UNION ALL SELECT 'content_type', id, code, display, description, sort_order, icon_id, retired_at FROM ref_content_type)
SELECT r.*, ic.code AS icon, ic.emoji, ic.svg, ic.color_token FROM r LEFT JOIN ref_icon ic ON ic.id = r.icon_id;

-- Backups by age of their newest good copy. No copy at all counts as an emergency.
DROP VIEW IF EXISTS v_backups_stale;
CREATE VIEW v_backups_stale AS
WITH b AS (
  SELECT i.id, i.device, i.key, CAST(i.attrs ->> 'max_age_s' AS INTEGER) AS max_age_s, m.value AS newest_good_at,
         CAST((julianday('now') - julianday(m.value)) * 86400 AS INTEGER) AS age_s
  FROM v_item i LEFT JOIN v_metric_latest m ON m.item_id = i.id AND m.metric = 'newest_good_at'
  WHERE i.kind = 'backup' AND i.is_active)
SELECT b.*, CASE
  WHEN b.newest_good_at IS NULL THEN 'emergency'
  WHEN b.age_s > (SELECT CAST(value AS INTEGER) FROM setting WHERE key = 'emergency_after_s') THEN 'emergency'
  WHEN b.max_age_s IS NOT NULL AND b.age_s > b.max_age_s THEN 'warn'
  ELSE 'ok' END AS health
FROM b;

-- Containers not running now that were seen running before.
DROP VIEW IF EXISTS v_containers_was_running;
CREATE VIEW v_containers_was_running AS
SELECT i.id, i.device, i.key, i.attrs ->> 'state' AS state, m.value AS last_running_at
FROM v_item i JOIN v_metric_latest m ON m.item_id = i.id AND m.metric = 'last_running_at'
WHERE i.kind = 'container' AND (i.attrs ->> 'state' IS NOT 'running' OR NOT i.is_active);

DROP VIEW IF EXISTS v_change;
CREATE VIEW v_change AS
SELECT c.id, r.started_at, i.device, i.kind, i.key, a.code AS action, cl.code AS class, cl.severity,
       c.diff, c.reason, c.declared_id, c.reviewed_by, c.reviewed_at, c.review_note,
       coalesce(c.reason = 'first scan (baseline)', 0) AS is_baseline   -- the reason classify.py gives first-scan sightings
FROM change c JOIN scan_run r ON r.id = c.run_id JOIN v_item i ON i.id = c.item_id
JOIN ref_change_action a ON a.id = c.action_id JOIN ref_change_class cl ON cl.id = c.class_id;

DROP VIEW IF EXISTS v_changes_24h;
CREATE VIEW v_changes_24h AS
SELECT * FROM v_change WHERE julianday(started_at) > julianday('now') - 1 AND NOT is_baseline;

-- Everything that changed in the last 30 days (first-scan sightings left out); also what search indexes.
DROP VIEW IF EXISTS v_changes_recent;
CREATE VIEW v_changes_recent AS
SELECT * FROM v_change WHERE julianday(started_at) > julianday('now') - 30 AND NOT is_baseline;

DROP VIEW IF EXISTS v_changes_open;
CREATE VIEW v_changes_open AS
SELECT * FROM v_change WHERE class IN ('unreviewed', 'suspicious') AND reviewed_at IS NULL;

DROP VIEW IF EXISTS v_gaps_open;
CREATE VIEW v_gaps_open AS
SELECT g.id, d.name AS device, k.code AS kind, g.target, g.reason, r.started_at AS since
FROM gap g LEFT JOIN device d ON d.id = g.device_id JOIN ref_gap_kind k ON k.id = g.gap_kind_id
JOIN scan_run r ON r.id = g.first_seen_run WHERE g.closed_run IS NULL;

-- Jobs due in the same minute on the same device.
DROP VIEW IF EXISTS v_job_collisions;
CREATE VIEW v_job_collisions AS
SELECT i.device, substr(m.value, 1, 16) AS minute, count(*) AS jobs, group_concat(i.key, ' | ') AS keys
FROM v_item i JOIN v_metric_latest m ON m.item_id = i.id AND m.metric = 'next_run'
WHERE i.kind = 'job' AND i.is_active AND m.value IS NOT NULL
GROUP BY i.device, minute HAVING count(*) > 1;

-- Active links whose two ends are both active items.
DROP VIEW IF EXISTS v_link;
CREATE VIEW v_link AS
SELECT l.id, t.code AS link_type, s.code AS source, f.id AS from_id, f.kind AS from_kind, f.key AS from_key,
       o.id AS to_id, o.kind AS to_kind, o.key AS to_key, f.device
FROM item_link l JOIN ref_link_type t ON t.id = l.link_type_id JOIN ref_link_source s ON s.id = l.source_id
JOIN v_item f ON f.id = l.from_item_id JOIN v_item o ON o.id = l.to_item_id
WHERE l.retired_run IS NULL AND f.is_active AND o.is_active;

DROP VIEW IF EXISTS v_job_writes;
CREATE VIEW v_job_writes AS
SELECT device, from_key AS job, to_key AS folder, source FROM v_link WHERE link_type = 'writes';

-- Jobs due in the same minute that write to folders on the same filesystem.
DROP VIEW IF EXISTS v_job_disk_overlap;
CREATE VIEW v_job_disk_overlap AS
WITH jf AS (
  SELECT w.from_id AS job_id, w.from_key AS job, fs.to_key AS filesystem, substr(m.value, 1, 16) AS minute, w.device
  FROM v_link w JOIN v_link fs ON fs.from_id = w.to_id AND fs.link_type = 'on_filesystem'
  JOIN v_metric_latest m ON m.item_id = w.from_id AND m.metric = 'next_run'
  WHERE w.link_type = 'writes')
SELECT a.device, a.minute, a.filesystem, a.job AS job_a, b.job AS job_b
FROM jf a JOIN jf b ON a.device = b.device AND a.minute = b.minute AND a.filesystem = b.filesystem
  AND a.job_id < b.job_id;

DROP VIEW IF EXISTS v_backup_coverage;
CREATE VIEW v_backup_coverage AS
SELECT s.device, s.from_key AS backup, s.to_key AS source_folder, d.to_key AS lands_in
FROM v_link s LEFT JOIN v_link d ON d.from_id = s.from_id AND d.link_type = 'lands_in'
WHERE s.link_type = 'backs_up';

-- Filesystems by how full they are (limits from settings fs_warn_pct / fs_emergency_pct).
DROP VIEW IF EXISTS v_filesystems;
CREATE VIEW v_filesystems AS
WITH f AS (
  SELECT i.id, i.device, i.key, i.attrs ->> 'fstype' AS fstype, CAST(s.value AS INTEGER) AS size_bytes,
         CAST(u.value AS INTEGER) AS used_bytes
  FROM v_item i LEFT JOIN v_metric_latest s ON s.item_id = i.id AND s.metric = 'size_bytes'
  LEFT JOIN v_metric_latest u ON u.item_id = i.id AND u.metric = 'used_bytes'
  WHERE i.kind = 'filesystem' AND i.is_active)
SELECT f.*, round(100.0 * used_bytes / nullif(size_bytes, 0), 1) AS used_pct, CASE
  WHEN size_bytes IS NULL THEN 'unknown'
  WHEN 100.0 * used_bytes / nullif(size_bytes, 0) >= (SELECT CAST(value AS REAL) FROM setting WHERE key='fs_emergency_pct') THEN 'emergency'
  WHEN 100.0 * used_bytes / nullif(size_bytes, 0) >= (SELECT CAST(value AS REAL) FROM setting WHERE key='fs_warn_pct') THEN 'warn'
  ELSE 'ok' END AS health
FROM f;
