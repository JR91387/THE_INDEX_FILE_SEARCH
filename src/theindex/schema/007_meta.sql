-- SPDX-License-Identifier: MIT
-- 007_meta.sql -- document front matter (author, date, tags, description, lang) as JSON on file rows, searchable.
-- `meta` is the JSON ('{}' = read, nothing found; NULL = not read yet). `meta_text` is a virtual generated
-- column (author + tags + description) so the FTS text lives in one place; file_fts_src exposes it as the column
-- name `meta`, which is what the external-content FTS table reads. Only active rows are indexed.

ALTER TABLE file ADD COLUMN meta TEXT;
ALTER TABLE file ADD COLUMN meta_text TEXT GENERATED ALWAYS AS (
  trim(coalesce(json_extract(meta, '$.author'), '') || ' ' || coalesce(json_extract(meta, '$.tags'), '') || ' ' ||
       coalesce(json_extract(meta, '$.description'), ''))) VIRTUAL;

CREATE VIEW file_fts_src AS SELECT id, name, title, meta_text AS meta FROM file WHERE retired_run IS NULL;

DROP TRIGGER file_fts_ai;
DROP TRIGGER file_fts_au;
DROP TABLE file_fts;
CREATE VIRTUAL TABLE file_fts USING fts5(name, title, meta, content='file_fts_src', content_rowid='id', tokenize='unicode61');

CREATE TRIGGER file_fts_ai AFTER INSERT ON file WHEN new.retired_run IS NULL BEGIN
  INSERT INTO file_fts (rowid, name, title, meta) VALUES (new.id, new.name, new.title, new.meta_text);
END;
CREATE TRIGGER file_fts_au AFTER UPDATE OF name, title, meta, retired_run ON file BEGIN
  INSERT INTO file_fts (file_fts, rowid, name, title, meta)
    SELECT 'delete', old.id, old.name, old.title, old.meta_text WHERE old.retired_run IS NULL;
  INSERT INTO file_fts (rowid, name, title, meta)
    SELECT new.id, new.name, new.title, new.meta_text WHERE new.retired_run IS NULL;
END;

INSERT INTO file_fts (file_fts) VALUES ('rebuild');
