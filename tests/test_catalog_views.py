# SPDX-License-Identifier: MIT
"""Views behind the front page: first-scan noise, link ends, unbacked folders, stale scans, query plans."""
from test_search_catalog import HOST, SearchCase, folder, folders_payload

from theindex import ingest


class TestFirstScanNoise(SearchCase):
    def fresh(self, items):
        ingest.ingest(self.conn, {k: v for k, v in folders_payload(items).items() if k != "started_at"}, HOST)

    def front(self, name):
        return self.one(f"SELECT {name} FROM v_front_page")

    def test_baseline_not_in_changes_24h_and_only_top_level_folders_nag(self):
        tree = [folder("/srv"), folder("/srv/a"), folder("/srv/a/deep"), folder("/srv/b")]
        self.fresh(tree)
        self.assertEqual((self.front("changes_24h"), self.front("folders_no_purpose")), (0, 2))
        self.fresh(tree + [folder("/srv/c")])
        self.assertEqual((self.front("changes_24h"), self.front("folders_no_purpose")), (1, 3))


class TestLinkEnds(SearchCase):
    def test_link_of_a_retired_item_is_not_live(self):
        from test_links import MOUNT, item, run
        self.load([folder("/srv/app")])
        run(self.conn, ("containers", "container"), [item("container", "web")],
            [{**MOUNT, "from": ["container", "web"]}])
        self.assertEqual(self.one("SELECT count(*) FROM v_link"), 1)
        run(self.conn, ("containers", "container"), [])    # the container is gone; its link row is not retired yet
        self.assertEqual(self.one("SELECT count(*) FROM v_link"), 0)
        self.assertEqual(self.one("SELECT count(*) FROM item_link WHERE retired_run IS NULL"), 1)


class TestUnbacked(SearchCase):
    def purpose(self, glob, crit, text):
        self.conn.execute("INSERT INTO purpose (device_id, path_glob, criticality_id, description) VALUES (?,?,?,?)",
                          (None, glob, self.conn.ref_id("ref_criticality", crit), text))

    def test_longest_glob_decides_and_percent_is_not_a_wildcard(self):
        from test_links import item, run
        self.load([folder("/srv/data/a%"), folder("/srv/data/abc"), folder("/srv/data/abc/x")])
        run(self.conn, ("backups", "backup"), [item("backup", "bk")],
            [{"from": ["backup", "bk"], "type": "backs_up", "to": ["folder", "/srv/data/a%"]}])
        self.purpose("/srv/data/abc/*", "irreplaceable", "ledgers")
        self.purpose("/srv/data/abc", "irreplaceable", "ledgers")
        self.assertEqual(self.one("SELECT count(*) FROM v_unbacked_irreplaceable"), 2)
        self.purpose("/srv/data/abc/x*", "scratch", "tmp")       # longer glob wins over the irreplaceable one
        self.assertEqual([r[0] for r in self.conn.execute("SELECT key FROM v_unbacked_irreplaceable")],
                         ["/srv/data/abc"])
        self.assertEqual(self.one("SELECT criticality FROM v_folders WHERE key = '/srv/data/abc/x'"), "scratch")


class TestScanStale(SearchCase):
    def stale(self):
        return self.one("SELECT scan_stale FROM v_front_page")

    def test_stale_only_when_runs_exist_and_none_is_recent_and_ok(self):
        from theindex import report
        from theindex.pages import markdown, model
        self.assertEqual(self.stale(), 0)                       # empty DB: nothing to complain about
        self.load([folder("/srv/data/x")])                      # a fixed 2026-01-01 finish time: long ago
        self.assertEqual(self.stale(), 1)
        self.assertTrue(report.front_page(self.conn).splitlines()[2].startswith("🚨 scan out of date"))
        self.assertTrue(markdown.front(model.build(self.conn)).split("\n\n")[2].startswith("- 🚨 scan out of date"))
        ingest.ingest(self.conn, {k: v for k, v in folders_payload([folder("/srv/data/x")]).items()
                                  if k not in ("started_at", "finished_at")}, HOST)
        self.conn.execute("UPDATE scan_run SET finished_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = 2")
        self.assertEqual(self.stale(), 0)
        self.assertNotIn("scan out of date", report.front_page(self.conn))   # quiet when fresh
        self.conn.execute("UPDATE scan_run SET status_id = ? WHERE id = 2", (self.conn.ref_id("ref_run_status", "failed"),))
        self.assertEqual(self.stale(), 1)                       # runs exist, none finished OK recently


class TestQueryPlans(SearchCase):
    def plan(self, sql):
        return " | ".join(r[3] for r in self.conn.execute("EXPLAIN QUERY PLAN " + sql))

    def test_indexes_are_used(self):
        self.assertIn("change_open", self.plan(
            "SELECT count(*) FROM change WHERE class_id = 1 AND reviewed_at IS NULL"))
        self.assertIn("item_link_active_to", self.plan(
            "SELECT 1 FROM item_link WHERE to_item_id = 1 AND link_type_id = 1 AND retired_run IS NULL"))
        plan = self.plan("SELECT value FROM v_metric_latest WHERE item_id = 1 AND metric = 'size_bytes'")
        self.assertIn("metric_sample_latest", plan)
        self.assertNotIn("SCAN ms", plan)
        self.assertNotIn("SCAN metric_sample", plan)

    def test_latest_metric_is_the_newest_run(self):
        item = folder("/srv/data/x", size=1)
        self.load([item])
        self.load([folder("/srv/data/x", size=5)], run=2)
        self.assertEqual(self.one("SELECT value FROM v_metric_latest WHERE metric = 'size_bytes'"), "5")
