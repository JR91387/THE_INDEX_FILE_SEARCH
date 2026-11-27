-- SPDX-License-Identifier: MIT
-- views_front.sql -- the front page counts. Applied last: it reads views from every other views file.

DROP VIEW IF EXISTS v_front_page;
CREATE VIEW v_front_page AS
SELECT -- 1 when scans were recorded but none finished OK in the last 2 days (a dead timer); 0 on an empty DB
       (SELECT count(*) > 0 AND coalesce(
          (SELECT julianday(max(coalesce(r.finished_at, r.started_at))) < julianday('now') - 2
           FROM scan_run r JOIN ref_run_status s ON s.id = r.status_id WHERE s.code = 'ok'), 1)
        FROM scan_run) AS scan_stale,
       (SELECT max(finished_at) FROM scan_run) AS last_run,
       (SELECT max(r.finished_at) FROM scan_run r JOIN ref_run_status s ON s.id = r.status_id
        WHERE s.code = 'ok') AS last_ok_run,
       (SELECT count(*) FROM scan_run r JOIN ref_run_status s ON s.id = r.status_id
        WHERE s.code = 'skipped' AND julianday(r.started_at) > julianday('now') - 1) AS runs_skipped_24h,
       (SELECT count(*) FROM scan_run r JOIN ref_run_status s ON s.id = r.status_id
        WHERE s.code IN ('failed','partial') AND julianday(r.started_at) > julianday('now') - 1) AS runs_bad_24h,
       (SELECT count(*) FROM v_backups_stale WHERE health = 'emergency') AS backups_emergency,
       (SELECT count(*) FROM v_backups_stale WHERE health = 'warn') AS backups_warn,
       (SELECT count(*) FROM v_changes_open WHERE class = 'suspicious') AS changes_suspicious,
       (SELECT count(*) FROM v_changes_open WHERE class = 'unreviewed') AS changes_unreviewed,
       (SELECT count(*) FROM v_changes_24h) AS changes_24h,
       (SELECT count(*) FROM v_containers_was_running) AS containers_stopped,
       (SELECT count(*) FROM v_containers_down) AS containers_down,
       (SELECT count(*) FROM v_folders_no_purpose) AS folders_no_purpose,
       (SELECT count(*) FROM v_unbacked_irreplaceable) AS unbacked_irreplaceable,
       (SELECT count(*) FROM v_filesystems WHERE health IN ('warn','emergency')) AS filesystems_full,
       (SELECT count(*) FROM v_gaps_open) AS gaps_open;
