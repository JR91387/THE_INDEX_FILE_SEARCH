# SPDX-License-Identifier: MIT
"""`search`: ranked hits from search_fts, safe for any input, plain and JSON output, one-line errors."""
import contextlib
import gc
import io
import json
from unittest import mock

from test_pages import PagesCase

from theindex import cli, search

KEYS = {"source", "ref_id", "device", "kind", "key", "active", "purpose", "criticality", "primary_content",
        "size_bytes", "snippet"}


class TestSearch(PagesCase):
    def setUp(self):
        super().setUp()
        self.fill()

    def cli(self, *argv):
        gc.collect()   # a connection another test left open must not warn into this stderr
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--db", str(self.path), "search", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_plain_output(self):
        code, out, _ = self.cli("crontab:c")
        self.assertEqual(code, 0)
        self.assertIn("job host-a:crontab:c -- ", out)

    def test_json_keys_and_limit(self):
        code, out, _ = self.cli("crontab", "--json", "--limit", "2")
        hits = json.loads(out)
        self.assertEqual((code, len(hits)), (0, 2))
        self.assertTrue(all(set(h) == KEYS for h in hits))

    def test_changes_command(self):
        def changes(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["--db", str(self.path), "changes", *argv])
            return code, out.getvalue()
        code, out = changes("--since", "3650d", "--json")
        rows = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual({r["key"] for r in rows}, {"crontab:a", "crontab:b", "crontab:c"})
        self.assertIn("host-a:crontab:a", changes("--since", "3650d")[1])
        self.assertEqual(changes("--since", "1s")[1], "")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--db", str(self.path), "changes", "--since", "soon"]), 2)

    def test_special_characters_never_raise(self):
        for term in ['a-b', 'x.y', '/srv/data', 'k:v', '*', '"', 'a"b', 'AND', 'NOT', '(', 'a OR', '^x', '-']:
            self.assertIsInstance(search.run(self.conn, [term]), list, term)

    def test_no_match_and_empty(self):
        self.assertEqual(self.cli("zzzzqq")[1], "")
        code, _, err = self.cli("   ")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error: ") and err.count("\n") == 1)

    def test_bad_query_is_exit_2(self):
        with mock.patch.object(search, "match_expr", return_value='"unterminated'):
            code, out, err = self.cli("x")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("error: ") and err.count("\n") == 1)
