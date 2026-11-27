-- SPDX-License-Identifier: MIT
-- 006_files.sql -- locations and files: every walked directory and every non-cache file, updated in place.
-- File rows carry no history; documents record first sighting, title change and retirement as columns.
-- Nothing is erased: gone rows get retired_run and are revived (retired_run cleared) when they come back.

CREATE TABLE ref_agent_marker (   -- a file or folder name that marks an AI-agent project folder
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);
CREATE TABLE ref_title_type (     -- extensions whose title is read; code = '.pdf', definition = reader name
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK (length(code) <= 32),
  display TEXT NOT NULL CHECK (length(display) <= 32), description TEXT NOT NULL CHECK (length(description) <= 128),
  definition TEXT, sort_order INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 1 CHECK (is_builtin IN (0,1)),
  icon_id INTEGER REFERENCES ref_icon(id), retired_at TEXT
);

ALTER TABLE device ADD COLUMN machine_hash TEXT;   -- sha256('the-index:' + OS machine id); name is a label
CREATE UNIQUE INDEX device_machine ON device (machine_hash) WHERE machine_hash IS NOT NULL;

CREATE TABLE dir (
  id            INTEGER PRIMARY KEY,
  device_id     INTEGER NOT NULL REFERENCES device(id),
  path_key      TEXT NOT NULL,             -- NFC, '/' separators, case-folded on case-insensitive volumes
  path          TEXT NOT NULL,             -- as found
  parent_id     INTEGER REFERENCES dir(id),
  depth         INTEGER NOT NULL,          -- '/' count of path_key; rollups run deepest first
  mtime_ns      INTEGER, ctime_ns INTEGER,
  size_bytes    INTEGER NOT NULL DEFAULT 0, -- direct files (cache dir: whole subtree)
  file_count    INTEGER NOT NULL DEFAULT 0,
  size_total    INTEGER NOT NULL DEFAULT 0, -- whole subtree, rolled up after each run
  files_total   INTEGER NOT NULL DEFAULT 0,
  is_cache      INTEGER NOT NULL DEFAULT 0 CHECK (is_cache IN (0,1)),
  agent_files   TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(agent_files)),
  first_seen_run INTEGER NOT NULL REFERENCES scan_run(id),
  seen_run      INTEGER NOT NULL REFERENCES scan_run(id),
  retired_run   INTEGER REFERENCES scan_run(id),
  UNIQUE (device_id, path_key)
);
CREATE INDEX dir_parent ON dir (parent_id);
CREATE INDEX dir_device_depth ON dir (device_id, depth);
CREATE INDEX dir_projects ON dir (device_id) WHERE agent_files <> '[]' AND retired_run IS NULL;

CREATE TABLE file (
  id            INTEGER PRIMARY KEY,
  device_id     INTEGER NOT NULL REFERENCES device(id),
  dir_id        INTEGER NOT NULL REFERENCES dir(id),
  name          TEXT NOT NULL,
  ext           TEXT NOT NULL DEFAULT '',  -- lower case, with the dot; '' when none
  size_bytes    INTEGER NOT NULL DEFAULT 0,
  mtime_ns      INTEGER, ctime_ns INTEGER, inode INTEGER,
  title         TEXT,
  title_src     TEXT,                      -- md_front | md_heading | html | ooxml | odf | epub | pdf_xmp | pdf_info | native
  title_sig     TEXT,                      -- 'size:mtime_ns' when the title was read; differs = read again
  first_seen_run INTEGER NOT NULL REFERENCES scan_run(id),
  seen_run      INTEGER NOT NULL REFERENCES scan_run(id),
  title_run     INTEGER REFERENCES scan_run(id),   -- run in which the title last changed
  retired_run   INTEGER REFERENCES scan_run(id),
  UNIQUE (dir_id, name)
);
CREATE INDEX file_ext ON file (ext) WHERE retired_run IS NULL;
CREATE INDEX file_first_seen ON file (first_seen_run);
CREATE INDEX file_title_run ON file (title_run) WHERE title_run IS NOT NULL;
CREATE INDEX file_retired ON file (retired_run) WHERE retired_run IS NOT NULL;

-- Payloads taken from the inbox: a payload id seen once is never ingested again.
CREATE TABLE inbox_receipt (
  payload_id  TEXT PRIMARY KEY,
  device_id   INTEGER REFERENCES device(id),
  file_name   TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  status      TEXT NOT NULL CHECK (status IN ('ingested','bad','duplicate'))
);

-- Name/title search, kept current by triggers (no rebuild per scan). Only active rows are indexed.
-- unicode61 splits on . - _ / so mid-name words match.
CREATE VIRTUAL TABLE file_fts USING fts5(name, title, content='file', content_rowid='id', tokenize='unicode61');
CREATE VIRTUAL TABLE dir_fts USING fts5(path, content='dir', content_rowid='id', tokenize='unicode61');

CREATE TRIGGER file_fts_ai AFTER INSERT ON file WHEN new.retired_run IS NULL BEGIN
  INSERT INTO file_fts (rowid, name, title) VALUES (new.id, new.name, new.title);
END;
CREATE TRIGGER file_fts_au AFTER UPDATE OF name, title, retired_run ON file BEGIN
  INSERT INTO file_fts (file_fts, rowid, name, title)
    SELECT 'delete', old.id, old.name, old.title WHERE old.retired_run IS NULL;
  INSERT INTO file_fts (rowid, name, title)
    SELECT new.id, new.name, new.title WHERE new.retired_run IS NULL;
END;
CREATE TRIGGER dir_fts_ai AFTER INSERT ON dir WHEN new.retired_run IS NULL BEGIN
  INSERT INTO dir_fts (rowid, path) VALUES (new.id, new.path);
END;
CREATE TRIGGER dir_fts_au AFTER UPDATE OF path, retired_run ON dir BEGIN
  INSERT INTO dir_fts (dir_fts, rowid, path) SELECT 'delete', old.id, old.path WHERE old.retired_run IS NULL;
  INSERT INTO dir_fts (rowid, path) SELECT new.id, new.path WHERE new.retired_run IS NULL;
END;

CREATE TRIGGER ref_agent_marker_no_delete BEFORE DELETE ON ref_agent_marker
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_title_type_no_delete BEFORE DELETE ON ref_title_type
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER dir_no_delete BEFORE DELETE ON dir
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER file_no_delete BEFORE DELETE ON file
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER inbox_receipt_no_delete BEFORE DELETE ON inbox_receipt
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
