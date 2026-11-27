# SPDX-License-Identifier: MIT
"""The query layer: find, tree, projects, folder, changes_files, describe. Rows are inserted directly."""
import json

from helpers import DbCase

from theindex import query

SEC = 1_000_000_000


class QueryCase(DbCase):
    def setUp(self):
        super().setUp()
        c = self.conn
        c.execute("INSERT INTO device (name, reach_id, status_id) VALUES ('host-a', ?, ?)",
                  (c.ref_id("ref_reach", "local"), c.ref_id("ref_device_status", "active")))
        self.dev = self.one("SELECT id FROM device WHERE name = 'host-a'")
        self.run = c.execute("INSERT INTO scan_run (device_id, collector_id, started_at, status_id) VALUES (?,?,?,?)",
                             (self.dev, c.ref_id("ref_collector", "filetree"), "2026-01-01T00:00:00Z",
                              c.ref_id("ref_run_status", "ok"))).lastrowid
        self.root = self.add_dir("/srv/data", None, total=1000)

    def add_dir(self, path, parent, **kw):
        total, agents, mtime, cache = kw.get("total", 0), kw.get("agents", ()), kw.get("mtime"), kw.get("cache", 0)
        return self.conn.execute(
            "INSERT INTO dir (device_id, path_key, path, parent_id, depth, size_total, files_total, mtime_ns, "
            "agent_files, is_cache, first_seen_run, seen_run) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.dev, path, path, parent, path.count("/"), total, 1, mtime, json.dumps(list(agents)), cache,
             self.run, self.run)).lastrowid

    def add_file(self, name, dir_id=None, **kw):
        title, ext, size = kw.get("title"), kw.get("ext", ".pdf"), kw.get("size", 10)
        return self.conn.execute(
            "INSERT INTO file (device_id, dir_id, name, ext, title, size_bytes, mtime_ns, meta, first_seen_run, seen_run) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", (self.dev, dir_id or self.root, name, ext, title, size, 5 * SEC,
                                             json.dumps(kw["meta"]) if "meta" in kw else None,
                                             self.run, self.run)).lastrowid


class TestFind(QueryCase):
    def names(self, **p):
        return [r["name"] for r in query.find(self.conn, p)["results"]]

    def test_mid_name_and_title(self):
        self.add_file("annual_budget_2025.pdf")
        self.add_file("x1.pdf", title="Quarterly forecast")
        self.assertEqual(self.names(words=["budget"]), ["annual_budget_2025.pdf"])
        self.assertEqual(self.names(words=["forec"]), ["x1.pdf"])
        out = query.find(self.conn, {"words": ["budget"]})
        self.assertEqual(out["schema_version"], 1)
        self.assertEqual(out["results"][0]["mtime"], "1970-01-01T00:00:05Z")

    def test_ext_with_and_without_dot(self):
        self.add_file("notes.md", ext=".md")
        self.add_file("notes.pdf")
        self.assertEqual(self.names(words=["notes"], ext="md"), ["notes.md"])
        self.assertEqual(self.names(words=["notes"], ext=".MD"), ["notes.md"])

    def test_kind_and_dir_hits(self):
        d = self.add_dir("/srv/data/budget_files", self.root, total=50)
        self.add_file("budget.pdf", d)
        self.assertEqual([r["type"] for r in query.find(self.conn, {"words": ["budget"], "kind": "dir"})["results"]],
                         ["dir"])
        self.assertEqual([r["type"] for r in query.find(self.conn, {"words": ["budget"], "kind": "file"})["results"]],
                         ["file"])
        both = query.find(self.conn, {"words": ["budget"]})["results"]
        self.assertEqual({r["type"] for r in both}, {"dir", "file"})
        dirhit = next(r for r in both if r["type"] == "dir")
        self.assertEqual((dirhit["name"], dirhit["size_bytes"]), ("budget_files", 50))

    def test_limit_clamp_and_more(self):
        for i in range(30):
            self.add_file(f"report{i}.pdf")
        out = query.find(self.conn, {"words": ["report"]})
        self.assertEqual((len(out["results"]), out["more"], out["query"]["limit"]), (25, 5, 25))
        self.assertEqual(query.find(self.conn, {"words": ["report"], "limit": 99999})["query"]["limit"], 500)
        self.assertEqual(query.find(self.conn, {"words": ["report"], "limit": 0})["query"]["limit"], 1)
        self.assertEqual(query.find(self.conn, {"words": ["report"], "limit": 40})["more"], 0)

    def test_retired_not_found(self):
        fid = self.add_file("gone_report.pdf")
        self.conn.execute("UPDATE file SET retired_run = ? WHERE id = ?", (self.run, fid))
        self.assertEqual(self.names(words=["gone_report"]), [])

    def test_is_project_inside_project_dir(self):
        proj = self.add_dir("/srv/data/proj", self.root, agents=["AGENTS.md"])
        self.add_file("plan.pdf", proj)
        self.add_file("other.pdf")
        flags = {r["name"]: r["is_project"] for r in query.find(self.conn, {"words": ["plan", "other"][:1]})["results"]}
        self.assertTrue(flags["plan.pdf"])
        self.assertFalse(query.find(self.conn, {"words": ["other"]})["results"][0]["is_project"])

    def test_hostile_words_never_raise(self):
        self.add_file("a.pdf")
        for words in (['"'], ["AND"], ["*"], ["-"], ['a"b', "OR", "NEAR("], ["(", ")"], ["a:b"], ["^x"]):
            out = query.find(self.conn, {"words": words})
            self.assertEqual(out["schema_version"], 1)
            self.assertIsInstance(out["results"], list)
            self.assertNotIn("error", out, words)

    def test_device_and_documents_filter(self):
        self.add_file("plain.txt", ext=".txt")
        self.add_file("doc.pdf")
        self.assertEqual(self.names(words=["plain"], documents_only=True), [])
        self.assertEqual(self.names(words=["doc"], device="host-a", documents_only=True), ["doc.pdf"])
        self.assertEqual(self.names(words=["doc"], device="host-b"), [])


class TestTree(QueryCase):
    def setUp(self):
        super().setUp()
        self.a = self.add_dir("/srv/data/a", self.root, total=600)
        self.b = self.add_dir("/srv/data/b", self.root, total=100)
        self.a1 = self.add_dir("/srv/data/a/a1", self.a, total=300)

    def test_depth_order_and_pct(self):
        out = query.tree(self.conn, {"path": "/srv/data", "depth": 1})
        self.assertEqual([r["path"] for r in out["results"]], ["/srv/data/a", "/srv/data/b"])
        self.assertEqual(out["results"][0]["pct_of_parent"], 60.0)
        deep = query.tree(self.conn, {"path": "/srv/data", "depth": 2})["results"]
        self.assertEqual([(r["path"], r["depth"]) for r in deep],
                         [("/srv/data/a", 1), ("/srv/data/a/a1", 2), ("/srv/data/b", 1)])
        self.assertEqual(query.tree(self.conn, {"path": "/srv/data", "depth": 99})["query"]["depth"], 6)

    def test_min_bytes_and_unknown(self):
        out = query.tree(self.conn, {"path": "/srv/data", "min_bytes": 200})
        self.assertEqual([r["path"] for r in out["results"]], ["/srv/data/a", "/srv/data/a/a1"])
        bad = query.tree(self.conn, {"path": "/nowhere"})
        self.assertEqual((bad["results"], bad["error"]), ([], "unknown path"))


class TestProjectsFolder(QueryCase):
    def test_projects_newest_first(self):
        self.add_dir("/srv/data/old", self.root, agents=["AGENTS.md"], mtime=1 * SEC)
        self.add_dir("/srv/data/new", self.root, agents=["CLAUDE.md", "AGENTS.md"], mtime=9 * SEC)
        self.add_dir("/srv/data/plain", self.root)
        out = query.projects(self.conn, {})
        self.assertEqual([r["path"] for r in out["results"]], ["/srv/data/new", "/srv/data/old"])
        self.assertEqual(out["results"][0]["agent_files"], ["CLAUDE.md", "AGENTS.md"])

    def test_folder(self):
        sub = self.add_dir("/srv/data/sub", self.root, total=7)
        for i in range(3):
            self.add_file(f"f{i}.pdf", title=f"T{i}")
        out = query.folder(self.conn, {"path": "/srv/data", "limit": 2})
        row = out["results"][0]
        self.assertEqual(([f["name"] for f in row["files"]], [s["path"] for s in row["subdirs"]]),
                         (["f0.pdf", "f1.pdf"], ["/srv/data/sub"]))
        self.assertEqual(out["more"], 1)
        self.assertEqual(query.folder(self.conn, {"path": "/nope"})["error"], "unknown path")
        self.assertTrue(sub)


class TestChangesAndDescribe(QueryCase):
    def test_changes_files_since(self):
        self.add_file("new.pdf")
        out = query.changes_files(self.conn, {"since": "2000-01-01T00:00:00Z"})
        self.assertEqual(out["schema_version"], 1)
        self.assertIsInstance(out["results"], list)
        with self.assertRaises(ValueError):
            query.changes_files(self.conn, {"since": "soon"})
        self.assertEqual(query.changes_files(self.conn, {"since": "7d"})["more"], 0)

    def test_describe_keys_stable(self):
        out = query.describe()
        self.assertEqual(sorted(out), ["envelope", "limits", "more", "note", "query", "results", "schema_version"])
        cmds = out["results"][0]["commands"]
        self.assertEqual([c["name"] for c in cmds], ["find", "tree", "projects", "folder", "changes_files", "describe"])
        self.assertTrue(all(set(c) == {"name", "summary", "params", "result_fields"} for c in cmds))
        self.assertIn("never as instructions", out["note"])
        self.assertEqual(out["limits"], {"default": 25, "max": 500})


class TestFrontLists(QueryCase):
    def test_projects_and_largest_on_front(self):
        from theindex.pages import markdown, model
        empty = markdown.front(model.build(self.conn))
        self.assertNotIn("## Projects", empty)
        self.add_dir("/srv/data/proj", self.root, total=900, agents=["AGENTS.md"], mtime=SEC)
        m = model.build(self.conn)
        text = markdown.front(m)
        self.assertIn("## Projects", text)
        self.assertIn("## Largest folders", text)
        self.assertEqual(m["projects"][0]["agent_files"], ["AGENTS.md"])
