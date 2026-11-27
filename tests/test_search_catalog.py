# SPDX-License-Identifier: MIT
"""Search over folders: mid-path words, active-only, hit fields, purpose text, content mix, filters."""
from helpers import DbCase

from theindex import db, ingest, search

HOST = "host-a"


def folder(key, size=None, content=None, **attrs):
    item = {"kind": "folder", "key": key, "attrs": {"owner": "alice", "group": "alice", "mode": "0o755", **attrs},
            "metrics": {} if size is None else {"size_bytes": size}}
    if content:
        item["content"] = content
    return item


def folders_payload(items, run=1):
    return {"collector": "folders", "kinds": ["folder"], "status": "ok", "items": list(items),
            "coverage": ["/srv/", "/var/"], "gaps": [], "errors": [],
            "started_at": f"2026-01-0{run}T00:00:00Z", "finished_at": f"2026-01-0{run}T00:00:05Z"}


class SearchCase(DbCase):
    def load(self, items, run=1):
        ingest.ingest(self.conn, folders_payload(items, run), HOST)
        db.rebuild_search(self.conn)

    def keys(self, *terms, **kw):
        return [h["key"] for h in search.run(self.conn, terms, narrow=kw)]


class TestActiveOnly(SearchCase):
    def test_retired_item_is_not_indexed(self):
        self.load([folder("/srv/data/old"), folder("/srv/data/new")])
        self.load([folder("/srv/data/new")], run=2)
        self.assertEqual(self.keys("old"), [])
        self.assertEqual(self.keys("new"), ["/srv/data/new"])


class TestBody(SearchCase):
    def test_non_ascii_attr_matches_and_key_outranks_body(self):
        self.load([folder("/srv/data/a", city="München"), folder("/srv/data/munchen-notes", city="x")])
        self.assertEqual(self.keys("münchen")[0], "/srv/data/munchen-notes")
        self.assertIn("/srv/data/a", self.keys("münchen"))
        self.assertIn("/srv/data/a", self.keys("munchen"))


class TestFolderHit(SearchCase):
    def test_folder_hit_carries_purpose_criticality_content_size(self):
        self.load([folder("/srv/data/pics", size=4096, primary_content="photos")])
        self.conn.execute("INSERT INTO purpose (device_id, path_glob, criticality_id, description) VALUES (?,?,?,?)",
                          (None, "/srv/data/pics*", self.conn.ref_id("ref_criticality", "irreplaceable"),
                           "family photos"))
        self.conn.execute("INSERT INTO purpose (device_id, path_glob, criticality_id, description) VALUES (?,?,?,?)",
                          (None, "/srv/*", self.conn.ref_id("ref_criticality", "scratch"), "general"))
        db.rebuild_search(self.conn)
        hit = next(h for h in search.run(self.conn, ["family", "photos"]) if h["source"] == "item")
        self.assertEqual((hit["key"], hit["purpose"], hit["criticality"], hit["primary_content"],
                          hit["size_bytes"], hit["active"]),
                         ("/srv/data/pics", "family photos", "irreplaceable", "photos", 4096, True))


class TestContentMix(SearchCase):
    def test_types_at_ten_percent_or_more_become_words(self):
        mix = [{"type": "photos", "files": 3, "bytes": 900}, {"type": "video", "files": 2, "bytes": 50},
               {"type": "logs", "files": 1, "bytes": 50}]
        self.load([folder("/srv/data/mix", content=mix)])
        rows = self.conn.execute("SELECT content_type, pct FROM v_folder_content ORDER BY bytes DESC").fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [("photos", 90.0), ("video", 5.0), ("logs", 5.0)])
        self.assertEqual(self.keys("photos"), ["/srv/data/mix"])
        self.assertEqual(self.keys("video"), [])


class TestFilters(SearchCase):
    def test_kind_and_device_filters(self):
        self.load([folder("/srv/data/shared")])
        ingest.ingest(self.conn, {**folders_payload([folder("/srv/data/shared")]), "collector": "folders"}, "host-b")
        db.rebuild_search(self.conn)
        self.assertEqual(len(search.run(self.conn, ["shared"])), 2)
        self.assertEqual([h["device"] for h in search.run(self.conn, ["shared"], narrow={"device": "host-b"})], ["host-b"])
        self.assertEqual(search.run(self.conn, ["shared"], narrow={"kind": "job"}), [])
        self.assertEqual(len(search.run(self.conn, ["shared"], narrow={"kind": "folder"})), 2)
        self.assertEqual(search.run(self.conn, ["shared"], narrow={"kind": "folder", "device": "x'; DROP TABLE item;--"}), [])


class TestLinksAndChanges(SearchCase):
    def test_link_and_recent_change_rows_are_searchable(self):
        from test_links import MOUNT, item, run
        self.load([folder("/srv/app")])
        mount = {**MOUNT, "from": ["container", "web"]}
        run(self.conn, ("containers", "container"), [item("container", "web")], [mount])
        run(self.conn, ("containers", "container"), [item("container", "web", image="nginx:2")], [mount])
        db.rebuild_search(self.conn)
        links = search.run(self.conn, ["web", "mounts"], narrow={"kind": "link"})
        self.assertEqual([h["key"] for h in links], ["web mounts /srv/app"])
        self.assertEqual(len(search.run(self.conn, ["web"], narrow={"kind": "change"})), 1)
        self.assertEqual(self.one("SELECT count(*) FROM v_changes_recent"), 1)   # baseline sightings are left out


class TestPurposeKey(SearchCase):
    def test_purpose_hit_key_is_device_and_glob_without_ref_id(self):
        self.load([folder("/srv/data/x")])
        dev = self.one("SELECT id FROM device WHERE name = ?", (HOST,))
        self.conn.execute("INSERT INTO purpose (device_id, path_glob, criticality_id, description) VALUES (?,?,?,?)",
                          (dev, "/srv/data/x*", self.conn.ref_id("ref_criticality", "irreplaceable"), "family photos"))
        db.rebuild_search(self.conn)
        hit = next(h for h in search.run(self.conn, ["family"]) if h["kind"] == "purpose")
        self.assertEqual((hit["key"], hit["ref_id"]), ("host-a:/srv/data/x*", None))


class TestMidPath(SearchCase):
    def test_middle_segment_and_underscore_name(self):
        self.load([folder("/srv/data/02_Media/photos"), folder("/var/lib/docker/volumes")])
        self.assertIn("/srv/data/02_Media/photos", self.keys("02_Media"))
        self.assertIn("/srv/data/02_Media/photos", self.keys("Media"))       # a word inside an underscore name
        self.assertIn("/var/lib/docker/volumes", self.keys("docker"))
        self.assertIn("/var/lib/docker/volumes", self.keys("/var/lib/dock"))
