-- SPDX-License-Identifier: MIT
-- Substring search on file names, like Everything: a trigram index (detail none, no column sizes since it
-- never ranks: ~10 bytes per file) answers `name LIKE '%mber%'` without scanning. Active rows only, kept by triggers like file_fts.
CREATE VIEW file_name_src AS SELECT id, name FROM file WHERE retired_run IS NULL;
CREATE VIRTUAL TABLE file_name_tri USING fts5(name, content='file_name_src', content_rowid='id',
                                              tokenize='trigram', detail='none', columnsize=0);

CREATE TRIGGER file_name_tri_ai AFTER INSERT ON file WHEN new.retired_run IS NULL BEGIN
  INSERT INTO file_name_tri (rowid, name) VALUES (new.id, new.name);
END;
CREATE TRIGGER file_name_tri_au AFTER UPDATE OF name, retired_run ON file BEGIN
  INSERT INTO file_name_tri (file_name_tri, rowid, name)
    SELECT 'delete', old.id, old.name WHERE old.retired_run IS NULL;
  INSERT INTO file_name_tri (rowid, name) SELECT new.id, new.name WHERE new.retired_run IS NULL;
END;

INSERT INTO file_name_tri (file_name_tri) VALUES ('rebuild');
