# SPDX-License-Identifier: MIT
"""Fleet: members write payload files, the hub drains the inbox. Fake members, a temp inbox, no real hosts."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from helpers import DbCase, job, payload

from theindex import config, identity, inbox, scan

M1, M2 = "1" * 32, "2" * 32


def jobs_file(pid, machine, host):
    return json.dumps({**payload([job("cron:backup")]), "payload_id": pid, "machine": machine, "host": host})


def tree_file(pid, machine, host):
    recs = [{"t": "header", "collector": "filetree", "payload_id": pid, "machine": machine, "host": host,
             "os": "linux", "case_insensitive": False, "full": True, "roots": ["/srv/data"],
             "started_at": "2026-01-01T00:00:00Z"},
            {"t": "dir", "key": "/srv/data", "path": "/srv/data", "parent": None, "mtime_ns": 1, "ctime_ns": 1,
             "size": 10, "files": 1, "cache": False, "agents": []},
            {"t": "file", "dir": "/srv/data", "name": "plan.md", "size": 10, "mtime_ns": 5, "ctime_ns": 5,
             "inode": 1, "title": "Garden plan", "title_src": "md", "title_sig": "10:5"},
            {"t": "trailer", "status": "ok", "finished_at": "2026-01-01T00:00:05Z", "counts": {}, "errors": []}]
    return "".join(json.dumps(r) + "\n" for r in recs)


class InboxCase(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.box = Path(tmp.name) / "inbox"
        self.box.mkdir()

    def put(self, name, text):
        (self.box / name).write_text(text)

    def drain(self):
        return inbox.drain(self.conn, self.box, "host-a")

    def moved(self, folder):
        return [p for p in (self.box / folder).rglob("*") if p.is_file()] if (self.box / folder).exists() else []

    def devices(self):
        return [r[0] for r in self.conn.execute("SELECT name FROM device ORDER BY name")]


class DrainTest(InboxCase):
    def test_two_members_ingested_then_moved(self):
        self.put("m1_jobs_20260101T000000Z.json", jobs_file("p1", M1, "host-b"))
        self.put("m2_filetree_20260101T000000Z.jsonl", tree_file("p2", M2, "host-c"))
        self.assertEqual(self.drain(), {"ingested": 2, "duplicate": 0, "bad": 0})
        self.assertEqual(self.one("SELECT count(*) FROM item i JOIN device d ON d.id = i.device_id "
                                  "WHERE d.name = 'host-b' AND i.key = 'cron:backup'"), 1)
        self.assertEqual(self.one("SELECT title FROM file f JOIN device d ON d.id = f.device_id "
                                  "WHERE d.name = 'host-c'"), "Garden plan")
        self.assertEqual(self.one("SELECT count(*) FROM device d JOIN ref_reach r ON r.id = d.reach_id "
                                  "WHERE r.code = 'inbox'"), 2)
        self.assertEqual(self.one("SELECT machine_hash FROM device WHERE name = 'host-b'"), M1)
        self.assertEqual(self.one("SELECT count(*) FROM inbox_receipt WHERE status = 'ingested'"), 2)
        self.assertEqual(len(self.moved("done")), 2)
        self.assertEqual(list(self.box.glob("*.json*")), [])

    def test_duplicate_payload_id_is_skipped(self):
        self.put("a.json", jobs_file("p1", M1, "host-b"))
        self.drain()
        runs = self.one("SELECT count(*) FROM scan_run")
        self.put("b.json", jobs_file("p1", M1, "host-b"))
        self.assertEqual(self.drain(), {"ingested": 0, "duplicate": 1, "bad": 0})
        self.assertEqual(self.one("SELECT count(*) FROM scan_run"), runs)
        self.assertEqual(len(self.moved("done")), 2)

    def test_malformed_files_go_to_bad_with_a_gap_until_a_clean_drain(self):
        self.put("a.json", "{not json")
        self.put("b.jsonl", json.dumps({"t": "dir"}) + "\n")
        self.put("c.json", json.dumps(payload([job("cron:x")])))                    # no payload_id
        self.put("d.json", json.dumps({"payload_id": "p9", "collector": "nope", "host": "host-b"}))
        self.put("e.json", jobs_file("p1", M1, "host-b"))
        self.assertEqual(self.drain(), {"ingested": 1, "duplicate": 0, "bad": 4})
        self.assertEqual(len(self.moved("bad")), 4)
        gaps = self.conn.execute("SELECT device, target FROM v_gaps_open WHERE kind = 'bad_payload' "
                                 "ORDER BY target").fetchall()
        self.assertEqual([tuple(g) for g in gaps], [("host-a", n) for n in ("a.json", "b.jsonl", "c.json", "d.json")])
        self.assertEqual(self.one("SELECT count(*) FROM inbox_receipt WHERE status = 'bad'"), 4)
        self.assertEqual(self.drain(), {"ingested": 0, "duplicate": 0, "bad": 0})   # clean drain closes them
        self.assertEqual(self.one("SELECT count(*) FROM v_gaps_open WHERE kind = 'bad_payload'"), 0)

    def test_dot_files_and_other_files_are_left_alone(self):
        self.put(".tmp-a.json", "{half")
        self.put("notes.txt", "hello")
        self.assertEqual(self.drain(), {"ingested": 0, "duplicate": 0, "bad": 0})
        self.assertEqual(sorted(p.name for p in self.box.iterdir()), [".tmp-a.json", "notes.txt"])

    def test_corrected_resend_of_a_bad_payload_id_is_ingested(self):
        self.put("a.json", json.dumps({"payload_id": "p1", "collector": "nope", "host": "host-b"}))
        self.drain()
        self.put("b.json", jobs_file("p1", M1, "host-b"))
        self.assertEqual(self.drain()["ingested"], 1)

    def test_out_of_order_names_all_ingest(self):
        for name, pid in (("z_late.json", "p1"), ("a_early.json", "p2"), ("m_mid.json", "p3")):
            self.put(name, jobs_file(pid, M1, "host-b"))
        self.assertEqual(self.drain()["ingested"], 3)

    def test_renamed_host_keeps_one_device(self):
        self.put("a.json", jobs_file("p1", M1, "host-b"))
        self.drain()
        self.put("b.json", jobs_file("p2", M1, "host-b2"))
        self.drain()
        self.assertEqual(self.devices(), ["host-b2"])
        self.assertEqual(self.one("SELECT count(*) FROM scan_run"), 2)

    def test_files_are_moved_never_deleted(self):
        names = ["a.json", "b.json", "c.json", "d.jsonl"]
        self.put("a.json", jobs_file("p1", M1, "host-b"))
        self.put("b.json", jobs_file("p1", M1, "host-b"))
        self.put("c.json", "garbage")
        self.put("d.jsonl", tree_file("p2", M2, "host-c"))
        self.drain()
        self.assertEqual(len(self.moved("done")) + len(self.moved("bad")), len(names))
        self.assertEqual([p for p in self.box.iterdir() if p.is_file()], [])

    def test_missing_inbox_folder_is_an_error(self):
        with self.assertRaises(ValueError):
            inbox.drain(self.conn, self.box / "nope", "host-a")


class IdentityTest(InboxCase):
    def test_machine_hash_is_stable_and_private(self):
        with mock.patch.object(identity, "machine_id", return_value="abc-123"):
            first, second = identity.machine_hash(), identity.machine_hash()
        with mock.patch.object(identity, "machine_id", return_value="other"):
            other = identity.machine_hash()
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first, other)
        self.assertNotIn("abc", first)
        with mock.patch.object(identity, "machine_id", return_value=None):
            self.assertIsNone(identity.machine_hash())

    def test_linux_machine_id_file(self):
        with mock.patch("builtins.open", mock.mock_open(read_data="deadbeef\n")), \
                mock.patch("sys.platform", "linux"):
            self.assertEqual(identity.machine_id(), "deadbeef")

    def test_resolve_device_cases(self):
        self.assertEqual(identity.resolve_device(self.conn, "host-a", M1), "host-a")      # new: ingest creates
        self.conn.execute("INSERT INTO device (name, reach_id, status_id) VALUES ('host-a', 1, 1)")
        self.assertEqual(identity.resolve_device(self.conn, "host-a", M1), "host-a")      # adopts the hash
        self.assertEqual(self.one("SELECT machine_hash FROM device WHERE name = 'host-a'"), M1)
        self.assertEqual(identity.resolve_device(self.conn, "host-z", M1), "host-z")      # renamed
        self.assertEqual(self.devices(), ["host-z"])
        self.assertEqual(identity.resolve_device(self.conn, "host-z", M2), "host-z-222222")   # name clash
        self.assertEqual(identity.resolve_device(self.conn, "host-q", None), "host-q")


class ScanAndConfigTest(InboxCase):
    def cfg(self, role="hub"):
        cfg = config.Config(device_name="host-a")
        cfg.inbox_dir, cfg.inbox_role = self.box, role
        return cfg

    def test_scan_drains_for_hub_only(self):
        self.put("a.json", jobs_file("p1", M1, "host-b"))
        lines = []
        scan._drain_inbox(self.conn, self.cfg("member"), lines.append)
        self.assertEqual(lines, [])
        scan._drain_inbox(self.conn, self.cfg(), lines.append)
        self.assertEqual(lines, ["inbox: 1 ingested, 0 duplicate, 0 bad"])

    def test_role_is_validated(self):
        path = self.box / "c.toml"
        path.write_text('[inbox]\ndir = "/srv/inbox"\nrole = "boss"\n')
        with self.assertRaisesRegex(ValueError, "inbox.role"):
            config.load(path)
        path.write_text('[inbox]\ndir = "/srv/inbox"\nrole = "member"\n')
        cfg = config.load(path)
        self.assertEqual((str(cfg.inbox_dir), cfg.inbox_role), ("/srv/inbox", "member"))
        self.assertEqual(config.Config().inbox_role, "hub")

    def test_network_mount_view_names_the_serving_device(self):
        self.drain_one("a.json", jobs_file("p1", M1, "host-b"))
        gap = {"kind": "network", "target": "/mnt/share", "reason": "nfs host-b:/export"}
        from theindex import ingest
        ingest.ingest(self.conn, {**payload([]), "gaps": [gap, {**gap, "target": "/mnt/x", "reason": "nfs far:/e"}]},
                      "host-a")
        rows = {r["mount_path"]: r for r in self.conn.execute("SELECT * FROM v_network_mounts")}
        self.assertEqual(rows["/mnt/share"]["served_by"], "host-b")
        self.assertEqual(rows["/mnt/share"]["device"], "host-a")
        self.assertIsNone(rows["/mnt/x"]["served_by"])

    def drain_one(self, name, text):
        self.put(name, text)
        self.drain()
