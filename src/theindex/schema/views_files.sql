-- SPDX-License-Identifier: MIT
-- views_files.sql -- locations and files. Re-applied on every init/upgrade: DROP + CREATE keeps it idempotent.

DROP VIEW IF EXISTS v_dirs;
CREATE VIEW v_dirs AS
SELECT d.id, dev.name AS device, d.path, d.path_key, d.parent_id, d.depth, d.size_bytes, d.file_count,
       d.size_total, d.files_total, d.is_cache, d.agent_files, d.mtime_ns, d.seen_run,
       (dev_r.code = 'offline') AS offline
FROM dir d JOIN device dev ON dev.id = d.device_id JOIN ref_reach dev_r ON dev_r.id = dev.reach_id
WHERE d.retired_run IS NULL;

-- Size tree: each directory's total and its share of its parent's total.
DROP VIEW IF EXISTS v_tree;
CREATE VIEW v_tree AS
SELECT c.id, c.device, c.path, c.depth, c.parent_id, c.size_total, c.files_total, c.is_cache,
       CASE WHEN p.size_total > 0 THEN round(100.0 * c.size_total / p.size_total, 1) END AS pct_of_parent
FROM v_dirs c LEFT JOIN dir p ON p.id = c.parent_id;

DROP VIEW IF EXISTS v_dirs_largest;
CREATE VIEW v_dirs_largest AS
SELECT id, device, path, size_total, files_total FROM v_dirs WHERE NOT is_cache ORDER BY size_total DESC;

-- Folders holding AI-agent instructions: good places to start an agent from. Home folders (their ~/.claude,
-- ~/.cursor are user-wide settings) and anything inside a hidden folder (.claude/worktrees...) are not projects.
DROP VIEW IF EXISTS v_projects;
CREATE VIEW v_projects AS
SELECT d.id, d.device, d.path, d.agent_files, d.size_total, d.files_total, d.mtime_ns
FROM v_dirs d
WHERE d.agent_files <> '[]'
  AND d.path NOT LIKE '%/.%' AND d.path NOT LIKE '%\.%'
  AND d.path NOT IN ('/root', '/var/root')
  AND NOT (lower(replace(rtrim(d.path, '/\'), '\', '/')) GLOB '/home/*'
           AND lower(replace(rtrim(d.path, '/\'), '\', '/')) NOT GLOB '/home/*/*')
  AND NOT (lower(replace(rtrim(d.path, '/\'), '\', '/')) GLOB '/users/*'
           AND lower(replace(rtrim(d.path, '/\'), '\', '/')) NOT GLOB '/users/*/*')
  AND NOT (lower(replace(rtrim(d.path, '/\'), '\', '/')) GLOB '?:/users/*'
           AND lower(replace(rtrim(d.path, '/\'), '\', '/')) NOT GLOB '?:/users/*/*');

DROP VIEW IF EXISTS v_files;
CREATE VIEW v_files AS
SELECT f.id, dev.name AS device, d.path AS dir_path,
       d.path || CASE WHEN substr(d.path, -1) IN ('/', '\') THEN '' ELSE '/' END || f.name AS path,
       f.name, f.ext, f.size_bytes, f.mtime_ns, f.title, f.title_src, f.first_seen_run, f.title_run,
       (t.id IS NOT NULL) AS is_document, (r.code = 'offline') AS offline
FROM file f JOIN dir d ON d.id = f.dir_id JOIN device dev ON dev.id = f.device_id
JOIN ref_reach r ON r.id = dev.reach_id
LEFT JOIN ref_title_type t ON t.code = f.ext AND t.retired_at IS NULL
WHERE f.retired_run IS NULL;

DROP VIEW IF EXISTS v_documents;
CREATE VIEW v_documents AS SELECT * FROM v_files WHERE is_document;

-- Document events for `changes --since`: never front-page changes.
DROP VIEW IF EXISTS v_file_events;
CREATE VIEW v_file_events AS
SELECT f.id AS file_id, dev.name AS device, f.name, f.title, 'new' AS action, r.started_at AS at
FROM file f JOIN device dev ON dev.id = f.device_id JOIN scan_run r ON r.id = f.first_seen_run
JOIN ref_title_type t ON t.code = f.ext
WHERE f.first_seen_run > (SELECT min(x.id) FROM scan_run x JOIN ref_collector c ON c.id = x.collector_id
                          WHERE x.device_id = f.device_id AND c.code IN ('filetree', 'catalog'))
UNION ALL
SELECT f.id, dev.name, f.name, f.title, 'retitled', r.started_at
FROM file f JOIN device dev ON dev.id = f.device_id JOIN scan_run r ON r.id = f.title_run
WHERE f.title_run IS NOT NULL AND f.title_run <> f.first_seen_run
UNION ALL
SELECT f.id, dev.name, f.name, f.title, 'gone', r.started_at
FROM file f JOIN device dev ON dev.id = f.device_id JOIN scan_run r ON r.id = f.retired_run
JOIN ref_title_type t ON t.code = f.ext;
