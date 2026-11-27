-- SPDX-License-Identifier: MIT
-- 001_ref.sql -- lookup ("ref") tables. Every coded value in THE INDEX is a row here, referenced by id.
-- Standard ref columns: id, code (<=32), display (<=32), description (<=128), definition, sort_order,
-- is_builtin (1 = shipped seed, 0 = added by a plugin or user), icon_id, retired_at (never delete).
-- Code never hard-codes ids: it resolves rows by `code`.

CREATE TABLE ref_icon (
  id          INTEGER PRIMARY KEY,
  code        TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display     TEXT NOT NULL CHECK (length(display) <= 32),
  description TEXT NOT NULL CHECK (length(description) <= 128),
  svg         TEXT NOT NULL DEFAULT '',    -- inline <svg> using currentColor; filled from icons/<code>.svg
  emoji       TEXT,                        -- fallback for markdown pages and AI prompts
  color_token TEXT,                        -- frontend maps to a CSS variable, e.g. status-danger
  is_builtin  INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  retired_at  TEXT
);

-- Standard ref table body, repeated (SQLite has no table inheritance).
CREATE TABLE ref_health (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT,
  severity INTEGER NOT NULL DEFAULT 0      -- higher = worse; used for sorting
);
CREATE TABLE ref_reach (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_device_status (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_device_role (           -- no built-ins: users define their own roles
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 0 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_collector (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_run_status (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_item_kind (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_metric (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT,
  unit       TEXT,                         -- bytes, count, timestamp, text
  value_type TEXT NOT NULL DEFAULT 'text' CHECK (value_type IN ('int','real','timestamp','text'))
);
CREATE TABLE ref_link_type (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_link_source (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_change_action (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_declared_action (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_change_class (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT,
  severity INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE ref_declared_status (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_gap_kind (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_criticality (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_expected_state (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_content_type (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);

-- How folder content is detected. Marker rules (a file or dir name that identifies the folder) outrank
-- extension counts. Plugins and users may add rules (is_builtin = 0).
CREATE TABLE ref_content_rule (
  id              INTEGER PRIMARY KEY,
  content_type_id INTEGER NOT NULL REFERENCES ref_content_type(id),
  match_kind      TEXT NOT NULL CHECK (match_kind IN ('ext','marker')),
  pattern         TEXT NOT NULL,           -- '.jpg' | '.git' | 'PG_VERSION'
  weight          INTEGER NOT NULL DEFAULT 1,
  is_builtin      INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  retired_at      TEXT,
  UNIQUE (match_kind, pattern)
);
