-- SPDX-License-Identifier: MIT
-- 005_indexes.sql -- indexes for the questions the front page asks on every refresh.
-- (metric_sample (item_id, metric_id, run_id) already exists as metric_sample_latest in 002.)

-- Open (unreviewed) changes: a small slice of a table that only grows.
CREATE INDEX change_open ON change (class_id) WHERE reviewed_at IS NULL;

-- "Is something linked to this item?": active links only, looked up by target.
CREATE INDEX item_link_active_to ON item_link (to_item_id, link_type_id) WHERE retired_run IS NULL;
