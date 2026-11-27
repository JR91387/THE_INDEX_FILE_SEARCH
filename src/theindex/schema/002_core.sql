-- SPDX-License-Identifier: MIT
-- 002_core.sql -- what exists. All times are ISO-8601 UTC text: YYYY-MM-DDTHH:MM:SSZ.

-- Engine settings that views need (e.g. emergency_after_s). Written from the config on every run.
CREATE TABLE setting (
  id    INTEGER PRIMARY KEY,
  key   TEXT NOT NULL UNIQUE,
  value TEXT NOT NULL
);

-- One row per machine. A replaced machine points at its successor so history carries over.
CREATE TABLE device (
  id           INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  role_id      INTEGER REFERENCES ref_device_role(id),
  reach_id     INTEGER NOT NULL REFERENCES ref_reach(id),
  status_id    INTEGER NOT NULL REFERENCES ref_device_status(id),
  successor_id INTEGER REFERENCES device(id),
  notes        TEXT,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  retired_at   TEXT
);

-- One row per collector run. "Never looked at this" becomes visible here.
CREATE TABLE scan_run (
  id           INTEGER PRIMARY KEY,
  device_id    INTEGER NOT NULL REFERENCES device(id),
  collector_id INTEGER NOT NULL REFERENCES ref_collector(id),
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  status_id    INTEGER NOT NULL REFERENCES ref_run_status(id),
  gate_result  TEXT,                       -- why a run was skipped by pre_run_gate / blackout
  items_seen   INTEGER,
  error        TEXT
);
CREATE INDEX scan_run_device_collector ON scan_run (device_id, collector_id, id);

-- Everything a collector observes. attrs = fields whose change means something (diffed and hashed);
-- noisy numbers go to metric_sample instead.
CREATE TABLE item (
  id             INTEGER PRIMARY KEY,
  device_id      INTEGER NOT NULL REFERENCES device(id),
  kind_id        INTEGER NOT NULL REFERENCES ref_item_kind(id),
  key            TEXT NOT NULL,            -- path | container name | job source:id | backup name
  attrs          TEXT NOT NULL CHECK (json_valid(attrs)),
  attrs_hash     TEXT NOT NULL,
  first_seen_run INTEGER NOT NULL REFERENCES scan_run(id),
  last_seen_run  INTEGER NOT NULL REFERENCES scan_run(id),
  retired_run    INTEGER REFERENCES scan_run(id),  -- set when gone; cleared when it comes back
  UNIQUE (device_id, kind_id, key)
);

-- Full history: one row each time an item's attrs change (including its first sighting).
CREATE TABLE item_version (
  id         INTEGER PRIMARY KEY,
  item_id    INTEGER NOT NULL REFERENCES item(id),
  run_id     INTEGER NOT NULL REFERENCES scan_run(id),
  attrs      TEXT NOT NULL CHECK (json_valid(attrs)),
  attrs_hash TEXT NOT NULL,
  UNIQUE (item_id, run_id)
);

-- Numbers that move every run (size, file count, next run). Kept as samples for trends.
CREATE TABLE metric_sample (
  id        INTEGER PRIMARY KEY,
  item_id   INTEGER NOT NULL REFERENCES item(id),
  run_id    INTEGER NOT NULL REFERENCES scan_run(id),
  metric_id INTEGER NOT NULL REFERENCES ref_metric(id),
  value     TEXT,                          -- cast in views per ref_metric.value_type
  UNIQUE (item_id, run_id, metric_id)
);
CREATE INDEX metric_sample_latest ON metric_sample (item_id, metric_id, run_id);

-- Relations: container mounts folder, job writes folder, backup backs_up / lands_in folder,
-- folder on_filesystem filesystem.
CREATE TABLE item_link (
  id             INTEGER PRIMARY KEY,
  from_item_id   INTEGER NOT NULL REFERENCES item(id),
  to_item_id     INTEGER NOT NULL REFERENCES item(id),
  link_type_id   INTEGER NOT NULL REFERENCES ref_link_type(id),
  source_id      INTEGER NOT NULL REFERENCES ref_link_source(id),
  first_seen_run INTEGER NOT NULL REFERENCES scan_run(id),
  last_seen_run  INTEGER NOT NULL REFERENCES scan_run(id),
  retired_run    INTEGER REFERENCES scan_run(id),
  UNIQUE (from_item_id, to_item_id, link_type_id)
);

-- Content mix of a folder per measurement. Primary type = marker match, else most bytes.
CREATE TABLE folder_content (
  id              INTEGER PRIMARY KEY,
  item_id         INTEGER NOT NULL REFERENCES item(id),
  run_id          INTEGER NOT NULL REFERENCES scan_run(id),
  content_type_id INTEGER NOT NULL REFERENCES ref_content_type(id),
  file_count      INTEGER NOT NULL,
  bytes           INTEGER NOT NULL,
  is_primary      INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
  UNIQUE (item_id, run_id, content_type_id)
);

-- Hand-written purposes, reloaded from the purposes file on every run (git holds the history).
-- The only table that is replaced rather than retired.
CREATE TABLE purpose (
  id                INTEGER PRIMARY KEY,
  device_id         INTEGER REFERENCES device(id),       -- NULL = applies to every device
  path_glob         TEXT NOT NULL,
  criticality_id    INTEGER NOT NULL REFERENCES ref_criticality(id),
  description       TEXT NOT NULL,
  used_by           TEXT,
  expected_state_id INTEGER REFERENCES ref_expected_state(id),
  source_line       INTEGER
);
CREATE UNIQUE INDEX purpose_scope ON purpose (coalesce(device_id, 0), path_glob);

-- Blind spots: what THE INDEX cannot see. Shown on the front page.
CREATE TABLE gap (
  id             INTEGER PRIMARY KEY,
  device_id      INTEGER REFERENCES device(id),
  collector_id   INTEGER NOT NULL REFERENCES ref_collector(id),  -- a collector only closes its own gaps
  gap_kind_id    INTEGER NOT NULL REFERENCES ref_gap_kind(id),
  target         TEXT NOT NULL,            -- a path, a host, 'jobs inside containers'
  reason         TEXT,
  first_seen_run INTEGER NOT NULL REFERENCES scan_run(id),
  last_seen_run  INTEGER NOT NULL REFERENCES scan_run(id),
  closed_run     INTEGER REFERENCES scan_run(id)
);
CREATE UNIQUE INDEX gap_open ON gap (coalesce(device_id, 0), gap_kind_id, target) WHERE closed_run IS NULL;
