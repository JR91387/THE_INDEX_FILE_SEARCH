-- SPDX-License-Identifier: MIT
-- views_folders.sql -- folders, purposes and expected container state. Re-applied on every init/upgrade.

-- Every active folder with its latest measurement, primary content and purpose (longest matching glob).
-- Latest values are per-row index lookups (newest run first), so a lookup by id never reads all folders.
DROP VIEW IF EXISTS v_folders;
CREATE VIEW v_folders AS
SELECT i.id, i.device, i.key, i.attrs ->> 'owner' AS owner, i.attrs ->> 'group' AS grp, i.attrs ->> 'mode' AS mode,
       i.attrs ->> 'primary_content' AS primary_content,
       CAST((SELECT x.value FROM metric_sample x WHERE x.item_id = i.id AND x.metric_id = (SELECT id FROM ref_metric WHERE code = 'size_bytes') ORDER BY x.run_id DESC LIMIT 1) AS INTEGER) AS size_bytes,
       CAST((SELECT x.value FROM metric_sample x WHERE x.item_id = i.id AND x.metric_id = (SELECT id FROM ref_metric WHERE code = 'file_count') ORDER BY x.run_id DESC LIMIT 1) AS INTEGER) AS file_count,
       (SELECT x.value FROM metric_sample x WHERE x.item_id = i.id AND x.metric_id = (SELECT id FROM ref_metric WHERE code = 'newest_mtime') ORDER BY x.run_id DESC LIMIT 1) AS newest_mtime,
       (SELECT x.run_id FROM metric_sample x WHERE x.item_id = i.id AND x.metric_id = (SELECT id FROM ref_metric WHERE code = 'size_bytes') ORDER BY x.run_id DESC LIMIT 1) AS measured_run,
       (SELECT p.description FROM purpose p JOIN item it ON it.id = i.id WHERE i.key GLOB p.path_glob
          AND (p.device_id IS NULL OR p.device_id = it.device_id) ORDER BY length(p.path_glob) DESC LIMIT 1) AS purpose,
       (SELECT c.code FROM purpose p JOIN item it ON it.id = i.id JOIN ref_criticality c ON c.id = p.criticality_id
          WHERE i.key GLOB p.path_glob AND (p.device_id IS NULL OR p.device_id = it.device_id)
          ORDER BY length(p.path_glob) DESC LIMIT 1) AS criticality
FROM v_item i
WHERE i.kind = 'folder' AND i.is_active;

-- Biggest measured folders first; irreplaceable ones are the ones to check for backups.
DROP VIEW IF EXISTS v_folders_biggest;
CREATE VIEW v_folders_biggest AS
SELECT * FROM v_folders WHERE size_bytes IS NOT NULL ORDER BY size_bytes DESC;

-- Containers that should be running but are not. Expected state comes from a purpose line whose glob
-- matches 'container:<name>'; without one, restart policy always/unless-stopped means "should run" (assumed).
DROP VIEW IF EXISTS v_containers_down;
CREATE VIEW v_containers_down AS
SELECT * FROM (
  SELECT i.id, i.device, i.key, i.attrs ->> 'state' AS state,
         coalesce(es.code, CASE WHEN i.attrs ->> 'restart_policy' IN ('always', 'unless-stopped')
                                THEN 'running' END) AS expected,
         (es.code IS NULL) AS assumed
  FROM v_item i JOIN item it ON it.id = i.id
  LEFT JOIN purpose p ON ('container:' || i.key) GLOB p.path_glob
       AND (p.device_id IS NULL OR p.device_id = it.device_id)
  LEFT JOIN ref_expected_state es ON es.id = p.expected_state_id
  WHERE i.kind = 'container' AND i.is_active)
WHERE expected = 'running' AND state IS NOT 'running';

-- Content mix of each active folder from its latest measurement: types, files, bytes and share of bytes.
DROP VIEW IF EXISTS v_folder_content;
CREATE VIEW v_folder_content AS
WITH latest AS (SELECT item_id, max(run_id) AS run_id FROM folder_content GROUP BY item_id),
c AS (SELECT fc.item_id, t.code AS content_type, fc.file_count, fc.bytes, fc.is_primary,
             sum(fc.bytes) OVER (PARTITION BY fc.item_id) AS total
      FROM folder_content fc JOIN latest l ON l.item_id = fc.item_id AND l.run_id = fc.run_id
      JOIN ref_content_type t ON t.id = fc.content_type_id)
SELECT i.id AS item_id, i.device, i.key, c.content_type, c.file_count, c.bytes, c.is_primary,
       round(100.0 * c.bytes / nullif(c.total, 0), 1) AS pct
FROM c JOIN v_item i ON i.id = c.item_id WHERE i.is_active;

-- Top-level folders (one level under a scanned root) with neither a purpose nor a container mount.
-- Deeper folders are explained by their top-level parent, so counting them would only nag.
DROP VIEW IF EXISTS v_folders_no_purpose;
CREATE VIEW v_folders_no_purpose AS
SELECT f.id, f.device, f.key FROM v_folders f JOIN item it ON it.id = f.id
WHERE f.purpose IS NULL
  AND EXISTS (SELECT 1 FROM item p WHERE p.device_id = it.device_id AND p.kind_id = it.kind_id
                AND p.retired_run IS NULL AND p.key = rtrim(rtrim(f.key, replace(f.key, '/', '')), '/')
                AND NOT EXISTS (SELECT 1 FROM item g WHERE g.device_id = p.device_id AND g.kind_id = p.kind_id
                                  AND g.retired_run IS NULL
                                  AND g.key = rtrim(rtrim(p.key, replace(p.key, '/', '')), '/')))
  AND NOT EXISTS (SELECT 1 FROM item_link l JOIN ref_link_type t ON t.id = l.link_type_id
                  WHERE l.to_item_id = f.id AND t.code = 'mounts' AND l.retired_run IS NULL);

-- Folders mounted into containers, with the folder's purpose (longest matching glob, same device) and criticality.
DROP VIEW IF EXISTS v_container_data;
CREATE VIEW v_container_data AS
SELECT l.device, l.from_key AS container, l.to_key AS folder, f.purpose, f.criticality
FROM v_link l LEFT JOIN v_folders f ON f.id = l.to_id WHERE l.link_type = 'mounts';

-- Irreplaceable folders that no backup covers (directly or via a parent folder). Paths compare by prefix, not
-- LIKE, so % and _ in a name are plain characters.
DROP VIEW IF EXISTS v_unbacked_irreplaceable;
CREATE VIEW v_unbacked_irreplaceable AS
SELECT f.id, f.device, f.key, f.purpose AS description
FROM v_folders f
WHERE f.criticality = 'irreplaceable'
  AND NOT EXISTS (SELECT 1 FROM v_link b WHERE b.link_type = 'backs_up' AND b.device = f.device
                  AND (f.key = b.to_key OR substr(f.key, 1, length(b.to_key) + 1) = b.to_key || '/'));
