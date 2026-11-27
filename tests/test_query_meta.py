# SPDX-License-Identifier: MIT
"""find over front matter: meta words, tag and author filters, meta in results (query layer, CLI and MCP)."""
import json

from test_cli_errors import run
from test_mcp import rpc, serve
from test_query import QueryCase

from theindex import query


class MetaFind(QueryCase):
    def setUp(self):
        super().setUp()
        self.add_file("scan1.pdf", title="Invoice", meta={"author": "Zelda Quimby", "tags": ["Taxes", "q3"],
                                                          "description": "Garden receipts", "lang": "en"})
        self.add_file("scan2.pdf", title="Letter", meta={"author": "Bob", "tags": ["family"]})
        self.add_file("taxes.md", ext=".md")                       # a name hit, no meta
        self.add_dir("/srv/data/taxes", self.root)

    def find(self, **p):
        return query.find(self.conn, p)["results"]

    def names(self, **p):
        return [r["name"] for r in self.find(**p)]

    def test_meta_words_match_and_rank_below_name_and_title(self):
        self.assertEqual(self.names(words=["quimby"]), ["scan1.pdf"])
        self.assertEqual(self.names(words=["garden"]), ["scan1.pdf"])
        self.assertEqual(self.names(words=["taxes"], kind="file"), ["taxes.md", "scan1.pdf"])   # name 10 beats meta 2

    def test_results_carry_meta_or_null(self):
        self.assertEqual(self.find(words=["scan1"])[0]["meta"]["tags"], ["Taxes", "q3"])
        self.assertIsNone(self.find(words=["taxes"], kind="file")[0]["meta"])

    def test_tag_filter_is_whole_tag_and_case_insensitive(self):
        self.assertEqual(self.names(words=["scan"], tag="TAXES"), ["scan1.pdf"])
        self.assertEqual(self.names(words=["scan"], tag="tax"), [])
        self.assertEqual(self.names(words=["scan"], tag="family"), ["scan2.pdf"])

    def test_author_filter_is_partial_and_case_insensitive(self):
        self.assertEqual(self.names(words=["scan"], author="quimby"), ["scan1.pdf"])
        self.assertEqual(self.names(words=["scan"], author="BO"), ["scan2.pdf"])
        self.assertEqual(self.names(words=["scan"], author="nobody"), [])

    def test_filters_leave_out_folders_and_unread_files(self):
        self.assertEqual([r["type"] for r in self.find(words=["taxes"], tag="taxes")], ["file"])
        self.assertEqual(self.names(words=["taxes"], author="x"), [])

    def test_cli_options_and_one_line(self):
        self.conn.close()
        code, out, _ = run("--db", str(self.path), "find", "scan", "--tag", "taxes", "--author", "zelda")
        lines = out.splitlines()
        self.assertEqual((code, len(lines)), (0, 1))
        self.assertTrue(lines[0].endswith("Invoice · Zelda Quimby"), lines[0])
        code, out, _ = run("--db", str(self.path), "find", "scan2")
        self.assertTrue(out.splitlines()[0].endswith("Letter · Bob"))

    def test_describe_lists_the_new_fields(self):
        find = next(c for c in query.describe()["results"][0]["commands"] if c["name"] == "find")
        self.assertTrue({"tag", "author"} <= {p["name"] for p in find["params"]})
        self.assertIn("meta", find["result_fields"])

    def test_mcp_tool_takes_tag_and_author(self):
        self.conn.close()
        calls = [rpc(1, "tools/list"),
                 rpc(2, "tools/call", {"name": "find", "arguments": {"words": ["scan"], "tag": "q3", "author": "zel"}}),
                 rpc(3, "tools/call", {"name": "find", "arguments": {"words": ["scan"], "tag": 5}})]
        out, _ = serve(self.path, calls)
        by_id = {m["id"]: m["result"] for m in out}
        props = by_id[1]["tools"][0]["inputSchema"]["properties"]
        self.assertEqual((props["tag"]["type"], props["author"]["type"]), ("string", "string"))
        hits = by_id[2]["structuredContent"]["results"]
        self.assertEqual([(h["name"], h["meta"]["author"]) for h in hits], [("scan1.pdf", "Zelda Quimby")])
        self.assertTrue(by_id[3]["isError"])
        self.assertEqual(json.loads(by_id[2]["content"][0]["text"])["results"], hits)
