-- SPDX-License-Identifier: MIT
-- 004_guards.sql -- nothing is erased: DELETE aborts on every table. Retire rows instead.
-- `purpose` is the one exception: it is reloaded from the purposes file (git keeps its history).

CREATE TRIGGER ref_icon_no_delete BEFORE DELETE ON ref_icon
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_health_no_delete BEFORE DELETE ON ref_health
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_reach_no_delete BEFORE DELETE ON ref_reach
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_device_status_no_delete BEFORE DELETE ON ref_device_status
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_device_role_no_delete BEFORE DELETE ON ref_device_role
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_collector_no_delete BEFORE DELETE ON ref_collector
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_run_status_no_delete BEFORE DELETE ON ref_run_status
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_item_kind_no_delete BEFORE DELETE ON ref_item_kind
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_metric_no_delete BEFORE DELETE ON ref_metric
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_link_type_no_delete BEFORE DELETE ON ref_link_type
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_link_source_no_delete BEFORE DELETE ON ref_link_source
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_change_action_no_delete BEFORE DELETE ON ref_change_action
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_declared_action_no_delete BEFORE DELETE ON ref_declared_action
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_change_class_no_delete BEFORE DELETE ON ref_change_class
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_declared_status_no_delete BEFORE DELETE ON ref_declared_status
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_gap_kind_no_delete BEFORE DELETE ON ref_gap_kind
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_criticality_no_delete BEFORE DELETE ON ref_criticality
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_expected_state_no_delete BEFORE DELETE ON ref_expected_state
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_content_type_no_delete BEFORE DELETE ON ref_content_type
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER ref_content_rule_no_delete BEFORE DELETE ON ref_content_rule
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER setting_no_delete BEFORE DELETE ON setting
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER device_no_delete BEFORE DELETE ON device
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER scan_run_no_delete BEFORE DELETE ON scan_run
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER item_no_delete BEFORE DELETE ON item
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER item_version_no_delete BEFORE DELETE ON item_version
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER metric_sample_no_delete BEFORE DELETE ON metric_sample
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER item_link_no_delete BEFORE DELETE ON item_link
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER folder_content_no_delete BEFORE DELETE ON folder_content
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER gap_no_delete BEFORE DELETE ON gap
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER declared_change_no_delete BEFORE DELETE ON declared_change
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
CREATE TRIGGER change_no_delete BEFORE DELETE ON change
  BEGIN SELECT RAISE(ABORT, 'THE INDEX never deletes: retire the row instead'); END;
