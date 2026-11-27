-- SPDX-License-Identifier: MIT
-- 003_change.sql -- planned change vs. what actually changed.

-- A planned change, declared ahead of time. A change that matches an active, unexpired declaration
-- is classed `expected`. declared_by is required: a person, or an agent acting on a person's word.
CREATE TABLE declared_change (
  id          INTEGER PRIMARY KEY,
  device_id   INTEGER REFERENCES device(id),        -- NULL = any device
  kind_id     INTEGER REFERENCES ref_item_kind(id), -- NULL = any kind
  key_glob    TEXT NOT NULL,
  action_id   INTEGER NOT NULL REFERENCES ref_declared_action(id),
  reason      TEXT NOT NULL CHECK (length(trim(reason)) > 0),
  declared_by TEXT NOT NULL CHECK (length(trim(declared_by)) > 0),
  declared_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  expires_at  TEXT NOT NULL,
  status_id   INTEGER NOT NULL REFERENCES ref_declared_status(id),
  closed_by   TEXT,                                 -- who withdrew it (NULL while active or when expired)
  closed_at   TEXT,
  CHECK (expires_at > declared_at)
);

-- Every difference between one run and the previous one.
CREATE TABLE change (
  id          INTEGER PRIMARY KEY,
  run_id      INTEGER NOT NULL REFERENCES scan_run(id),
  item_id     INTEGER NOT NULL REFERENCES item(id),
  action_id   INTEGER NOT NULL REFERENCES ref_change_action(id),
  diff        TEXT CHECK (diff IS NULL OR json_valid(diff)),  -- {"field": [old, new]}
  class_id    INTEGER NOT NULL REFERENCES ref_change_class(id),
  reason      TEXT,                                           -- which rule set the class
  declared_id INTEGER REFERENCES declared_change(id),
  reviewed_by TEXT,
  reviewed_at TEXT,
  review_note TEXT,
  CHECK ((reviewed_by IS NULL) = (reviewed_at IS NULL))
);
CREATE INDEX change_run ON change (run_id);
CREATE INDEX change_item ON change (item_id);
