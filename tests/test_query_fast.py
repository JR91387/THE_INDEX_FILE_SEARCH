# SPDX-License-Identifier: MIT
"""find on large match sets: index-order results (folders, then name matches, then title matches), exact counts."""
from unittest import mock

from test_query import QueryCase

from theindex import query, query_fast


class FastFindTest(QueryCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(query_fast, "RANK_ALL", 3)
        patcher.start()
        self.addCleanup(patcher.stop)
        sub = self.add_dir("/srv/data/amber_box", self.root)
        for i in range(4):
            self.add_file(f"amber_{i}.txt", ext=".txt")
        self.add_file("notes.md", ext=".md", title="Amber notes")
        self.retired = self.add_file("amber_gone.txt", ext=".txt")
        self.conn.execute("UPDATE file SET retired_run = ? WHERE id = ?", (self.run, self.retired))
        self.sub = sub

    def test_order_and_count(self):
        out = query.find(self.conn, {"words": ["amber"], "limit": 4})
        self.assertEqual(out["more"], 6 - 4)                  # 1 dir + 4 named + 1 titled; retired not counted
        self.assertEqual(out["results"][0]["type"], "dir")
        self.assertEqual([r["name"] for r in out["results"][1:]], ["amber_3.txt", "amber_2.txt", "amber_1.txt"])

    def test_title_matches_after_name_matches(self):
        out = query.find(self.conn, {"words": ["amber"], "kind": "file", "limit": 10})
        self.assertEqual([r["name"] for r in out["results"]][-1], "notes.md")
        self.assertEqual(out["more"], 0)

    def test_filters_use_ranked_path(self):
        out = query.find(self.conn, {"words": ["amber"], "ext": "md"})
        self.assertEqual([r["name"] for r in out["results"]], ["notes.md"])


class SubstringTest(QueryCase):
    def test_inside_word_match_fills_after_word_matches(self):
        self.add_file("amber_notes.txt", ext=".txt")
        self.add_file("xamberx.txt", ext=".txt")
        self.add_file("ember.txt", ext=".txt")
        out = query.find(self.conn, {"words": ["amber"]})
        self.assertEqual([r["name"] for r in out["results"]], ["amber_notes.txt", "xamberx.txt"])
        self.assertEqual(out["more"], 0)
        names = [r["name"] for r in query.find(self.conn, {"words": ["mber"]})["results"]]
        self.assertEqual(sorted(names), ["amber_notes.txt", "ember.txt", "xamberx.txt"])

    def test_short_words_and_wildcards(self):
        self.add_file("ab_cd.txt", ext=".txt")
        self.add_file("abXcd.txt", ext=".txt")
        self.assertEqual(query.find(self.conn, {"words": ["bx"]})["results"], [])     # under 3 characters
        names = [r["name"] for r in query.find(self.conn, {"words": ["b_c"]})["results"]]
        self.assertEqual(names, ["ab_cd.txt"])                                       # '_' is not a wildcard

    def test_retired_files_are_not_found(self):
        fid = self.add_file("xamberx.txt", ext=".txt")
        self.conn.execute("UPDATE file SET retired_run = ? WHERE id = ?", (self.run, fid))
        self.assertEqual(query.find(self.conn, {"words": ["mber"]})["results"], [])
