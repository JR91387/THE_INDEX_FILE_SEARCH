-- SPDX-License-Identifier: MIT
-- search.sql -- full-text search index. Derived data: rebuilt from scratch on every init/upgrade/scan.
-- (A virtual table holds no source data, so clearing it does not break the never-delete rule.)

-- Only `_` joins a token: / . - : split words, so a mid-path word (docker in /var/lib/docker) is found, and a
-- path query is a phrase of its words with prefix matching on the last one.
DROP TABLE IF EXISTS search_fts;
CREATE VIRTUAL TABLE search_fts USING fts5(
  source UNINDEXED, ref_id UNINDEXED, device, kind, key, body, tokenize = 'unicode61'
);

INSERT INTO search_fts (source, ref_id, device, kind, key, body)
SELECT 'item', i.id, i.device, i.kind, i.key,
       coalesce((SELECT group_concat(t.value, ' ') FROM json_tree(i.attrs) t
                 WHERE t.type IN ('text', 'integer', 'real')), '')
       || coalesce(' ' || f.purpose, '')
       || coalesce((SELECT ' ' || group_concat(c.content_type, ' ') FROM v_folder_content c
                    WHERE c.item_id = i.id AND c.pct >= 10), '')
FROM v_item i LEFT JOIN v_folders f ON f.id = i.id WHERE i.is_active;

INSERT INTO search_fts (source, ref_id, device, kind, key, body)
SELECT 'purpose', NULL, coalesce(d.name, '*'), 'purpose', coalesce(d.name, '*') || ':' || p.path_glob,
       p.description || ' ' || coalesce(p.used_by, '')
FROM purpose p LEFT JOIN device d ON d.id = p.device_id;

INSERT INTO search_fts (source, ref_id, device, kind, key, body)
SELECT 'gap', g.id, coalesce(g.device, '*'), 'gap', g.target, g.kind || ' ' || coalesce(g.reason, '')
FROM v_gaps_open g;

-- Relations between active items: "<from> <type> <to>" so either end finds the link.
INSERT INTO search_fts (source, ref_id, device, kind, key, body)
SELECT 'link', l.id, l.device, 'link', l.from_key || ' ' || l.link_type || ' ' || l.to_key, l.source FROM v_link l;

-- What changed in the last 30 days: the item's key, then action, class, reason and the changed values.
INSERT INTO search_fts (source, ref_id, device, kind, key, body)
SELECT 'change', c.id, c.device, 'change', c.key,
       c.action || ' ' || c.kind || ' ' || c.class || coalesce(' ' || c.reason, '')
       || coalesce((SELECT ' ' || group_concat(t.value, ' ') FROM json_tree(c.diff) t
                    WHERE t.type IN ('text', 'integer', 'real')), '')
FROM v_changes_recent c;
