# SPDX-License-Identifier: MIT
"""files_run with a native source: used when present and fresh, the walk otherwise, never retires, verifies."""
import json

from sources_fixture import NativeCase

from theindex import config, config_inbox, files_ingest, files_run


class FilesSourceTest(NativeCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.Config(device_name="host-a")
        self.cfg.filetree = {"roots": [str(self.root)], "cache_markers": ["node_modules"], "titles": False}

    def run_files(self, full=None):
        return files_run.run(self.conn, self.cfg, full=full)

    def active(self, name):
        return self.one("SELECT count(*) FROM file WHERE name = ? AND retired_run IS NULL", (name,))

    def remove_then_scan(self):
        """Baseline walk, delete top.txt, then a non-full run: did it notice?"""
        self.run_files(full=True)
        (self.root / "top.txt").unlink()
        result = self.run_files(full=False)
        return result, self.active("top.txt") == 0

    def native_listing(self):
        return [p for p in self.listing() if p.name != "top.txt"]

    def test_native_run_never_retires(self):
        self.run_files(full=True)
        (self.root / "top.txt").unlink()
        self.fake_plocate(self.native_listing())
        self.assertEqual(self.run_files(full=False)["status"], "ok")
        self.assertEqual(self.active("top.txt"), 1)                  # a walk would have retired it
        self.assertEqual(self.one("SELECT count(*) FROM file WHERE retired_run IS NULL"), 5)

    def test_absent_tool_uses_the_walk(self):
        _, retired = self.remove_then_scan()
        self.assertTrue(retired)

    def test_stale_database_uses_the_walk(self):
        self.fake_plocate()
        self.stale()
        _, retired = self.remove_then_scan()
        self.assertTrue(retired)

    def test_off_uses_the_walk(self):
        self.fake_plocate()
        self.cfg.sources = {"native": "off"}
        _, retired = self.remove_then_scan()
        self.assertTrue(retired)

    def test_partial_native_run_falls_back_in_the_same_scan(self):
        self.run_files(full=True)
        (self.root / "top.txt").unlink()
        self.fake_plocate(self.native_listing(), code=3)
        result = self.run_files(full=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.active("top.txt"), 0)                 # the walk ran and retired it
        self.assertEqual(self.one("SELECT count(*) FROM scan_run r JOIN ref_run_status s ON s.id = r.status_id "
                                  "WHERE s.code = 'partial'"), 1)

    def test_full_run_with_count_mismatch_records_gap(self):
        for n in range(60):
            (self.root / "docs" / f"extra{n}.txt").write_text("e")
        self.fake_plocate([self.root, self.root / "top.txt"])
        result = self.run_files(full=True)
        self.assertEqual(result["status"], "ok")
        gap = self.conn.execute("SELECT g.target, g.reason FROM gap g JOIN ref_gap_kind k ON k.id = g.gap_kind_id "
                                "WHERE k.code = 'index_mismatch' AND g.closed_run IS NULL").fetchall()
        self.assertEqual([tuple(g) for g in gap], [(str(self.root), "walk counted 67 files, plocate counted 1")])
        self.fake_plocate()
        self.run_files(full=True)                                  # now they agree: the gap closes
        self.assertEqual(self.one("SELECT count(*) FROM gap WHERE closed_run IS NULL"), 0)

    def test_full_run_within_tolerance_has_no_gap(self):
        self.fake_plocate()
        self.run_files(full=True)
        self.assertEqual(self.one("SELECT count(*) FROM gap"), 0)

    def test_no_retire_header_keeps_rows(self):
        self.run_files(full=True)
        head = {"t": "header", "collector": "filetree", "roots": [str(self.root)], "no_retire": True, "full": False}
        lines = [json.dumps(head), json.dumps({"t": "trailer", "status": "ok", "errors": []})]
        files_ingest.ingest_stream(self.conn, lines, "host-a")
        self.assertEqual(self.one("SELECT count(*) FROM file WHERE retired_run IS NULL"), 5)
        lines[0] = json.dumps({**head, "no_retire": False})
        files_ingest.ingest_stream(self.conn, lines, "host-a")
        self.assertEqual(self.one("SELECT count(*) FROM file WHERE retired_run IS NULL"), 0)

    def test_config_validates_native(self):
        with self.assertRaises(ValueError):
            config_inbox.sources({"native": "yes"})
        self.assertEqual(config_inbox.sources({"native": "off"}), {"native": "off"})
