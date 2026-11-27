-- SPDX-License-Identifier: MIT
-- views_fleet.sql -- machines that serve each other's disks. Re-applied on every init/upgrade: DROP + CREATE.

-- Network mounts not walked: each open `network` gap with its device, mount path and reason (the filetree
-- collector writes the mount source into the reason, e.g. 'nfs host-b:/export'). served_by = the device whose
-- name appears in the reason (the longest name wins), or NULL when no known device is named.
DROP VIEW IF EXISTS v_network_mounts;
CREATE VIEW v_network_mounts AS
SELECT g.id, d.name AS device, g.target AS mount_path, g.reason,
       (SELECT s.name FROM device s
         WHERE s.id <> g.device_id AND length(s.name) > 0 AND instr(lower(g.reason), lower(s.name)) > 0
         ORDER BY length(s.name) DESC, s.name LIMIT 1) AS served_by,
       r.started_at AS since
FROM gap g JOIN device d ON d.id = g.device_id JOIN ref_gap_kind k ON k.id = g.gap_kind_id
JOIN scan_run r ON r.id = g.first_seen_run
WHERE k.code = 'network' AND g.closed_run IS NULL;
