# SPDX-License-Identifier: MIT
"""scan: lock, per-collector failure, exit codes, first-scan measuring; read commands on a read-only database."""
import fcntl
import json
import os
import shutil
import sqlite3
from unittest import mock

from helpers import job, payload
from test_cli_errors import CliCase, run

from theindex import collect, db, scan


class ScanCase(CliCase):
    def setUp(self):
        super().setUp()
        self.cfg = self.dir / "c.toml"
        self.cfg.write_text(f'[paths]\npages_dir = "{self.dir}/pages"\n'
                            '[schedule]\ncollectors = ["jobs", "filesystems"]\n')

    def scan(self, *extra):
        return run("--config", str(self.cfg), "--db", self.db, "scan", *extra)

    def runs(self):
        conn = db.connect(self.db)
        rows = conn.execute("SELECT c.code, s.code, r.gate_result, r.error FROM scan_run r "
                            "JOIN ref_collector c ON c.id = r.collector_id "
                            "JOIN ref_run_status s ON s.id = r.status_id ORDER BY r.id").fetchall()
        conn.close()
        return [tuple(r) for r in rows]


def fake(name, *_):
    return {**payload([job("crontab:a")]), "collector": name, "kinds": ["job"]}


class TestScan(ScanCase):
    def test_one_collector_failing_records_failed_and_continues(self):
        def run_one(conn, cfg, name, measure_all=False):
            if name == "jobs":
                raise RuntimeError("boom")
            return fake(name)
        with mock.patch.object(collect, "run", run_one):
            code, _, err = self.scan()
        self.assertEqual(code, 0, err)
        runs = {r[0]: r for r in self.runs()}
        self.assertEqual(runs["jobs"][1], "failed")
        self.assertIn("boom", runs["jobs"][3])
        self.assertEqual(runs["filesystems"][1], "ok")

    def test_partial_run_exits_zero(self):
        part = {**fake("jobs"), "status": "partial", "errors": ["denied"]}
        with mock.patch.object(collect, "run", lambda c, f, name, m=False: part if name == "jobs" else fake(name)):
            self.assertEqual(self.scan()[0], 0)

    def test_from_json_failures_are_one_line(self):
        bad = self.dir / "bad.json"
        bad.write_text("{nope")
        wrong = self.dir / "wrong.json"
        wrong.write_text("[1, 2]")
        for path in (self.dir / "missing.json", bad, wrong):
            code, _, err = self.scan("--from-json", str(path))
            self.assertEqual(code, 2, path)
            self.assertEqual(sum(x.startswith("error:") for x in err.splitlines()), 1)
            self.assertNotIn("Traceback", err)

    def test_unknown_collector_in_payload_is_one_line(self):
        saved = self.dir / "p.json"
        saved.write_text(json.dumps({"collector": "nope", "items": []}))
        code, _, err = self.scan("--from-json", str(saved))
        self.assertEqual((code, "Traceback" in err), (2, False))
        self.assertIn("error: ref_collector has no code 'nope'", err)

    def test_bad_toml_and_bad_db_path(self):
        self.cfg.write_text("[paths\nx=")
        code, _, err = self.scan()
        self.assertEqual((code, "error:" in err), (2, True))
        blocker = self.dir / "file"
        blocker.write_text("x")
        code, _, err = run("--db", str(blocker / "sub" / "i.db"), "status")
        self.assertEqual((code, "error:" in err), (2, True))
        code, _, err = run("--db", str(self.dir), "status")
        self.assertEqual((code, "error:" in err), (2, True))

    def test_lock_held_skips_and_exits_zero(self):
        with open(f"{self.db}.lock", "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch.object(collect, "run", side_effect=AssertionError("must not run")):
                code, out, _ = self.scan()
        self.assertEqual(code, 0)
        self.assertIn(scan.SKIP_BUSY, out)

    def test_lock_held_records_skip_when_db_exists(self):
        with mock.patch.object(collect, "run", lambda c, f, name, m=False: fake(name)):
            self.scan()
        with open(f"{self.db}.lock", "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.scan()
        self.assertIn(("jobs", "skipped", scan.SKIP_BUSY, None), self.runs())

    def test_first_scan_measures_all_then_rotates(self):
        seen = []

        def run_one(conn, cfg, name, measure_all=False):
            seen.append(measure_all)
            return {**fake("folders"), "kinds": ["job"]}
        self.cfg.write_text(f'[paths]\npages_dir = "{self.dir}/pages"\n[schedule]\ncollectors = ["folders"]\n')
        with mock.patch.object(collect, "run", run_one):
            self.scan()
            self.scan()
            self.scan("--measure-all")
        self.assertEqual(seen, [True, False, True])


class TestReadOnly(ScanCase):
    def test_search_and_status_work_on_a_read_only_file(self):
        with mock.patch.object(collect, "run", lambda c, f, name, m=False: fake(name)):
            self.scan()
        copy = self.dir / "ro" / "copy.db"
        copy.parent.mkdir()
        conn = db.connect(self.db)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        shutil.copy(self.db, copy)
        os.chmod(copy, 0o444)
        for argv in (["search", "crontab"], ["status"]):
            code, _, err = run("--db", str(copy), *argv)
            self.assertEqual(code, 0, err)
        self.assertIn("crontab:a", run("--db", str(copy), "search", "crontab")[1])

    def test_read_does_not_reapply_or_write(self):
        db.init(self.db).close()
        before = os.stat(self.db).st_mtime_ns
        conn = db.open(self.db)
        self.assertTrue(db.is_current(conn))
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("INSERT INTO setting (key, value) VALUES ('x', '1')")
        conn.close()
        self.assertEqual(os.stat(self.db).st_mtime_ns, before)

    def test_init_reapplies_only_when_schema_files_change(self):
        db.init(self.db).close()
        with mock.patch.object(db, "reapply") as reapply:
            db.init(self.db).close()
            reapply.assert_not_called()
        with mock.patch.object(db, "schema_hash", return_value="changed"), mock.patch.object(db, "reapply") as reapply:
            db.init(self.db).close()
            reapply.assert_called_once()
