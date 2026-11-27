# SPDX-License-Identifier: MIT
from helpers import DbCase, job, payload

from theindex import declare, ingest

HOST = "host-a"


class IngestCase(DbCase):
    def run_scan(self, items, **kw):
        return ingest.ingest(self.conn, payload(items, **kw), HOST)

    def changes(self):
        return [(r["action"], r["class"], r["key"]) for r in
                self.conn.execute("SELECT action, class, key FROM v_change ORDER BY id")]


class TestLifecycle(IngestCase):
    def test_first_scan_is_baseline_routine(self):
        result = self.run_scan([job("crontab:alice:1")])
        self.assertTrue(result["baseline"])
        self.assertEqual(self.changes(), [("new", "routine", "crontab:alice:1")])

    def test_new_job_after_baseline_is_suspicious(self):
        self.run_scan([job("crontab:alice:1")])
        self.run_scan([job("crontab:alice:1"), job("crontab:alice:2")])
        self.assertEqual(self.changes()[-1], ("new", "suspicious", "crontab:alice:2"))

    def test_modified_writes_version_and_diff(self):
        self.run_scan([job("crontab:alice:1")])
        self.run_scan([job("crontab:alice:1", command="/usr/bin/false")])
        self.assertEqual(self.changes()[-1][:2], ("modified", "suspicious"))
        self.assertEqual(self.one("SELECT count(*) FROM item_version"), 2)
        self.assertIn("/usr/bin/false", self.one("SELECT diff FROM change ORDER BY id DESC LIMIT 1"))

    def test_unchanged_records_nothing(self):
        self.run_scan([job("crontab:alice:1")])
        self.run_scan([job("crontab:alice:1")])
        self.assertEqual(len(self.changes()), 1)

    def test_gone_then_back(self):
        self.run_scan([job("crontab:alice:1"), job("crontab:alice:2")])
        self.run_scan([job("crontab:alice:1")])
        self.assertEqual(self.changes()[-1][:1], ("gone",))
        self.run_scan([job("crontab:alice:1"), job("crontab:alice:2")])
        self.assertEqual(self.changes()[-1][:1], ("back",))
        self.assertEqual(self.one("SELECT count(*) FROM item WHERE retired_run IS NOT NULL"), 0)

    def test_partial_run_never_retires(self):
        self.run_scan([job("crontab:alice:1"), job("crontab:alice:2")])
        self.run_scan([job("crontab:alice:1")], status="partial")
        self.assertEqual(self.one("SELECT count(*) FROM item WHERE retired_run IS NOT NULL"), 0)

    def test_uncovered_prefix_never_retires(self):
        self.run_scan([job("crontab:alice:1"), job("systemd-user:x.timer")],
                      coverage=("crontab:", "systemd-user:"))
        self.run_scan([job("crontab:alice:1")], coverage=("crontab:",))
        self.assertEqual(self.one("SELECT count(*) FROM item WHERE retired_run IS NOT NULL"), 0)

    def test_metrics_and_collisions(self):
        when = "2026-01-02T01:00:00Z"
        self.run_scan([job("crontab:alice:1", next_run=when), job("crontab:alice:2", next_run=when)])
        self.assertEqual(self.one("SELECT jobs FROM v_job_collisions"), 2)


class TestDeclaredAndReview(IngestCase):
    def test_declared_change_is_expected(self):
        self.run_scan([job("crontab:alice:1")])
        did = declare.add(self.conn, {"key_glob": "crontab:alice:*", "action": "new", "reason": "new backup job",
                                      "declared_by": "alice", "expires": "1d", "kind": "job"})
        self.run_scan([job("crontab:alice:1"), job("crontab:alice:2")])
        self.assertEqual(self.changes()[-1][:2], ("new", "expected"))
        self.assertEqual(self.one("SELECT declared_id FROM change ORDER BY id DESC LIMIT 1"), did)

    def test_withdrawn_declaration_no_longer_matches(self):
        self.run_scan([job("crontab:alice:1")])
        did = declare.add(self.conn, {"key_glob": "*", "action": "any", "reason": "r", "declared_by": "alice",
                                      "expires": "1d"})
        self.assertTrue(declare.withdraw(self.conn, did, "alice"))
        self.run_scan([job("crontab:alice:1"), job("crontab:alice:2")])
        self.assertEqual(self.changes()[-1][1], "suspicious")

    def test_declaration_requires_reason_and_declarer(self):
        with self.assertRaises(ValueError):
            declare.add(self.conn, {"key_glob": "*", "action": "any", "reason": " ", "declared_by": "a",
                                    "expires": "1d"})

    def test_review_closes_open_change(self):
        self.run_scan([job("crontab:alice:1")])
        self.run_scan([job("crontab:alice:1"), job("crontab:alice:2")])
        open_id = self.one("SELECT id FROM v_changes_open")
        self.assertTrue(declare.review(self.conn, open_id, "alice", "fine"))
        self.assertFalse(declare.review(self.conn, open_id, "alice"))
        self.assertEqual(self.one("SELECT count(*) FROM v_changes_open"), 0)


class TestGapsAndBackups(IngestCase):
    def test_gap_opens_and_closes(self):
        gap = {"kind": "denied", "target": "/var/spool/cron/crontabs", "reason": "x"}
        self.run_scan([], gaps=[gap])
        self.run_scan([], gaps=[gap])
        self.assertEqual(self.one("SELECT count(*) FROM v_gaps_open"), 1)
        self.run_scan([])
        self.assertEqual(self.one("SELECT count(*) FROM v_gaps_open"), 0)

    def test_backup_size_drop_is_suspicious(self):
        def backup(size):
            return {"kind": "backup", "key": "nightly", "attrs": {"max_age_s": 86400},
                    "metrics": {"size_bytes": size, "newest_good_at": "2026-01-01T00:00:00Z"}}
        base = {"collector": "backups", "kinds": ["backup"], "status": "ok", "coverage": [""], "gaps": []}
        ingest.ingest(self.conn, {**base, "items": [backup(1000)]}, HOST)
        ingest.ingest(self.conn, {**base, "items": [backup(400)]}, HOST)
        self.assertEqual(self.changes()[-1][:2], ("threshold", "suspicious"))
        self.assertEqual(self.one("SELECT health FROM v_backups_stale"), "emergency")  # copy is years old

    def test_duplicate_keys_do_not_crash_and_do_not_retire(self):
        self.run_scan([job("crontab:alice:1"), job("crontab:alice:2")])
        result = self.run_scan([job("crontab:alice:1"), job("crontab:alice:1", command="/bin/other")])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.one("SELECT count(*) FROM item WHERE retired_run IS NOT NULL"), 0)
        self.assertIn("duplicate", self.one("SELECT error FROM scan_run ORDER BY id DESC LIMIT 1"))

    def test_front_page_shows_skips(self):
        ingest.record_skip(self.conn, HOST, "jobs", "gate")
        row = self.conn.execute("SELECT last_ok_run, runs_skipped_24h FROM v_front_page").fetchone()
        self.assertEqual((row[0], row[1]), (None, 1))

    def test_skip_is_recorded(self):
        ingest.record_skip(self.conn, HOST, "jobs", "blackout window")
        self.assertEqual(self.one("SELECT gate_result FROM scan_run"), "blackout window")
