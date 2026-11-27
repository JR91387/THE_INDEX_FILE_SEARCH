-- SPDX-License-Identifier: MIT
-- seed_ref.sql -- built-in lookup rows. Re-applied on every init/upgrade: INSERT OR IGNORE keeps it idempotent
-- and never touches rows a user added. Icon SVG bodies are loaded afterwards from icons/<code>.svg.

INSERT OR IGNORE INTO ref_icon (code, display, description, emoji, color_token) VALUES
 ('ok','OK','Healthy or succeeded','✅','status-ok'),
 ('warn','Warning','Needs attention soon','⚠️','status-warn'),
 ('emergency','Emergency','Needs attention now','🚨','status-danger'),
 ('unknown','Unknown','Cannot tell','❔','status-muted'),
 ('running','Running','In progress or running','▶️','status-info'),
 ('skipped','Skipped','Did not run on purpose','⏭️','status-muted'),
 ('partial','Partial','Ran but could not read everything','🟡','status-warn'),
 ('failed','Failed','Did not complete','❌','status-danger'),
 ('expected','Expected','Matches a declared change','📅','status-ok'),
 ('routine','Routine','Normal churn','🔁','status-muted'),
 ('unreviewed','Unreviewed','Not yet looked at','👁️','status-info'),
 ('suspicious','Suspicious','Undeclared change that matters','🚩','status-danger'),
 ('folder','Folder','A directory','📁',NULL),
 ('job','Job','A scheduled job','⏰',NULL),
 ('container','Container','A container','📦',NULL),
 ('backup','Backup','A backup set','💾',NULL),
 ('mount','Mount','A mount or link','🔗',NULL),
 ('filesystem','Filesystem','A mounted disk','🗄️',NULL),
 ('device','Device','A machine','🖥️',NULL),
 ('denied','Denied','Permission denied','🔒','status-warn'),
 ('no_route','No route','Cannot reach','📵','status-warn'),
 ('not_visible','Not visible','Cannot be observed from here','🙈','status-warn'),
 ('stale_push','Stale push','Pushed status is out of date','⌛','status-warn'),
 ('irreplaceable','Irreplaceable','Cannot be recreated if lost','💎','status-danger'),
 ('rebuildable','Rebuildable','Can be recreated from elsewhere','🔧',NULL),
 ('scratch','Scratch','Safe to lose','🗑️','status-muted'),
 ('documents','Documents','Office files, PDFs, text','📄',NULL),
 ('photos','Photos','Images','🖼️',NULL),
 ('video','Video','Video files','🎞️',NULL),
 ('audio','Audio','Music and recordings','🎵',NULL),
 ('code_repo','Code','Source code or a git repo','💻',NULL),
 ('database','Database','Live database files','🛢️',NULL),
 ('db_dump','DB dump','Database dumps and exports','🗃️',NULL),
 ('archive','Archive','Compressed archives','🗜️',NULL),
 ('logs','Logs','Log files','📜',NULL),
 ('config','Config','Configuration files','⚙️',NULL),
 ('vm_image','VM image','Disk and VM images','💿',NULL),
 ('cache','Cache','Rebuildable cache','⚡',NULL),
 ('mixed','Mixed','No single type dominates','🔀',NULL),
 ('empty','Empty','No files','⬜','status-muted');

INSERT OR IGNORE INTO ref_health (code, display, description, sort_order, severity) VALUES
 ('ok','OK','Within limits',1,0), ('warn','Warning','Past its normal limit',2,1),
 ('unknown','Unknown','No data to judge',3,2), ('emergency','Emergency','Past the emergency limit',4,3);

INSERT OR IGNORE INTO ref_reach (code, display, description, sort_order) VALUES
 ('local','Local','Scanned on this machine',1), ('ssh','SSH','Scanned over ssh',2),
 ('push','Push','Sends its own status file',3), ('none','No route','Cannot be reached',4);

INSERT OR IGNORE INTO ref_device_status (code, display, description, sort_order) VALUES
 ('active','Active','In service',1), ('unreachable','Unreachable','In service but not reachable',2),
 ('retired','Retired','Out of service; history kept',3);

INSERT OR IGNORE INTO ref_collector (code, display, description, sort_order) VALUES
 ('jobs','Jobs','Crontabs and systemd timers',1), ('containers','Containers','Container runtime',2),
 ('filesystems','Filesystems','Mounted disks',3), ('folders','Folders','Folder walk and content',4),
 ('backups','Backups','Backup checks',5), ('push','Push','Status files pushed by other machines',6),
 ('files','Files','Purposes and links files',7);

INSERT OR IGNORE INTO ref_run_status (code, display, description, sort_order) VALUES
 ('running','Running','Started, not finished',1), ('ok','OK','Finished and read everything',2),
 ('partial','Partial','Finished but could not read everything',3), ('failed','Failed','Did not finish',4),
 ('skipped','Skipped','Gate or blackout window stopped it',5);

INSERT OR IGNORE INTO ref_item_kind (code, display, description, sort_order) VALUES
 ('folder','Folder','A directory',1), ('job','Job','A scheduled job',2), ('container','Container','A container',3),
 ('backup','Backup','A backup set',4), ('mount','Mount','A container or bind mount',5),
 ('filesystem','Filesystem','A mounted disk',6);

INSERT OR IGNORE INTO ref_metric (code, display, description, unit, value_type, sort_order) VALUES
 ('size_bytes','Size','Total size','bytes','int',1), ('used_bytes','Used','Space used','bytes','int',2),
 ('file_count','Files','Number of files','count','int',3),
 ('newest_mtime','Newest file','Time of the newest file','timestamp','timestamp',4),
 ('biggest_file','Biggest file','Path of the largest file','text','text',5),
 ('next_run','Next run','When the job runs next','timestamp','timestamp',6),
 ('last_run','Last run','When the job last ran','timestamp','timestamp',7),
 ('last_result','Last result','Result of the last run','text','text',8),
 ('last_running_at','Last running','Last time seen running','timestamp','timestamp',9),
 ('newest_good_at','Newest good copy','Time of the newest good backup','timestamp','timestamp',10);

INSERT OR IGNORE INTO ref_link_type (code, display, description, sort_order) VALUES
 ('mounts','Mounts','Container mounts a folder',1), ('writes','Writes','Job writes to a folder',2),
 ('reads','Reads','Job reads from a folder',3), ('backs_up','Backs up','Backup copies this folder',4),
 ('lands_in','Lands in','Backup is stored here',5), ('on_filesystem','On disk','Folder lives on this filesystem',6);

INSERT OR IGNORE INTO ref_link_source (code, display, description, sort_order) VALUES
 ('auto','Detected','Found by a collector',1), ('declared','Declared','Written in the links file',2);

INSERT OR IGNORE INTO ref_change_action (code, display, description, sort_order) VALUES
 ('new','New','Seen for the first time',1), ('gone','Gone','No longer seen',2),
 ('modified','Modified','Attributes changed',3), ('back','Came back','Seen again after being gone',4),
 ('threshold','Threshold','A metric crossed a limit',5);

INSERT OR IGNORE INTO ref_declared_action (code, display, description, sort_order) VALUES
 ('new','New','Will appear',1), ('gone','Gone','Will disappear',2),
 ('modified','Modified','Will change',3), ('any','Any','Any change',4);

INSERT OR IGNORE INTO ref_change_class (code, display, description, sort_order, severity) VALUES
 ('expected','Expected','Matches a declared change',1,0), ('routine','Routine','Normal churn',2,1),
 ('unreviewed','Unreviewed','Needs a look',3,2), ('suspicious','Suspicious','Undeclared change that matters',4,3);

INSERT OR IGNORE INTO ref_declared_status (code, display, description, sort_order) VALUES
 ('active','Active','In force',1), ('expired','Expired','Past its expiry date',2),
 ('withdrawn','Withdrawn','Cancelled by its declarer',3);

INSERT OR IGNORE INTO ref_gap_kind (code, display, description, sort_order) VALUES
 ('denied','Denied','Permission denied',1), ('no_route','No route','Machine cannot be reached',2),
 ('not_visible','Not visible','Cannot be observed from here',3), ('stale_push','Stale push','Pushed status is old',4);

INSERT OR IGNORE INTO ref_criticality (code, display, description, sort_order) VALUES
 ('irreplaceable','Irreplaceable','Cannot be recreated if lost',1),
 ('rebuildable','Rebuildable','Can be recreated from elsewhere',2), ('scratch','Scratch','Safe to lose',3);

INSERT OR IGNORE INTO ref_expected_state (code, display, description, sort_order) VALUES
 ('running','Running','Should be running',1), ('stopped','Stopped','Should be stopped',2),
 ('any','Any','Either is fine',3);

INSERT OR IGNORE INTO ref_content_type (code, display, description, sort_order) VALUES
 ('documents','Documents','Office files, PDFs, text',1), ('photos','Photos','Images',2), ('video','Video','Video files',3),
 ('audio','Audio','Music and recordings',4), ('code_repo','Code','Source code or a git repo',5),
 ('database','Database','Live database files',6), ('db_dump','DB dump','Database dumps and exports',7),
 ('archive','Archive','Compressed archives',8), ('logs','Logs','Log files',9), ('config','Config','Configuration files',10),
 ('container_volume','Container volume','Data owned by a container',11), ('vm_image','VM image','Disk and VM images',12),
 ('cache','Cache','Rebuildable cache',13), ('mixed','Mixed','No single type dominates',14),
 ('empty','Empty','No files',15), ('unknown','Unknown','Unrecognised file types',16);

-- Icons: built-in rows whose code matches an icon code get that icon.
UPDATE ref_health          SET icon_id = (SELECT id FROM ref_icon i WHERE i.code = ref_health.code)          WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_run_status      SET icon_id = (SELECT id FROM ref_icon i WHERE i.code = ref_run_status.code)      WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_item_kind       SET icon_id = (SELECT id FROM ref_icon i WHERE i.code = ref_item_kind.code)       WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_change_class    SET icon_id = (SELECT id FROM ref_icon i WHERE i.code = ref_change_class.code)    WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_gap_kind        SET icon_id = (SELECT id FROM ref_icon i WHERE i.code = ref_gap_kind.code)        WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_criticality     SET icon_id = (SELECT id FROM ref_icon i WHERE i.code = ref_criticality.code)     WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_content_type    SET icon_id = (SELECT id FROM ref_icon i WHERE i.code = ref_content_type.code)    WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_change_action   SET icon_id = (SELECT id FROM ref_icon i WHERE i.code = ref_change_action.code)   WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_expected_state  SET icon_id = (SELECT id FROM ref_icon i WHERE i.code = ref_expected_state.code)  WHERE icon_id IS NULL AND is_builtin = 1;

-- Icons whose ref code differs from the icon code: (table, ref code, icon code).
UPDATE ref_reach SET icon_id = (SELECT id FROM ref_icon WHERE code = CASE ref_reach.code
  WHEN 'local' THEN 'device' WHEN 'ssh' THEN 'mount' WHEN 'push' THEN 'backup' ELSE 'no_route' END)
  WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_device_status SET icon_id = (SELECT id FROM ref_icon WHERE code = CASE ref_device_status.code
  WHEN 'active' THEN 'ok' WHEN 'unreachable' THEN 'no_route' ELSE 'scratch' END)
  WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_change_action SET icon_id = (SELECT id FROM ref_icon WHERE code = CASE ref_change_action.code
  WHEN 'new' THEN 'running' WHEN 'gone' THEN 'failed' WHEN 'modified' THEN 'unreviewed' WHEN 'back' THEN 'routine'
  ELSE 'warn' END) WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_collector SET icon_id = (SELECT id FROM ref_icon WHERE code = CASE ref_collector.code
  WHEN 'jobs' THEN 'job' WHEN 'containers' THEN 'container' WHEN 'filesystems' THEN 'filesystem'
  WHEN 'folders' THEN 'folder' WHEN 'backups' THEN 'backup' WHEN 'files' THEN 'documents' ELSE 'stale_push' END)
  WHERE icon_id IS NULL AND is_builtin = 1;
UPDATE ref_content_type SET icon_id = (SELECT id FROM ref_icon WHERE code = 'container')
  WHERE code = 'container_volume' AND icon_id IS NULL AND is_builtin = 1;
UPDATE ref_expected_state SET icon_id = (SELECT id FROM ref_icon WHERE code = CASE ref_expected_state.code
  WHEN 'stopped' THEN 'skipped' ELSE 'unknown' END) WHERE icon_id IS NULL AND is_builtin = 1;

-- Default settings (the config file overwrites these on every run).
INSERT OR IGNORE INTO setting (key, value) VALUES
 ('emergency_after_s', '259200'),        -- 3 days: a backup older than this is an emergency
 ('mixed_threshold', '0.6'),             -- below this byte share, a folder's content is "mixed"
 ('size_drop_suspicious', '0.5'),        -- a backup that shrinks by this fraction is suspicious
 ('fs_warn_pct', '85'),                  -- filesystem fullness that counts as a warning
 ('fs_emergency_pct', '95');             -- filesystem fullness that counts as an emergency
