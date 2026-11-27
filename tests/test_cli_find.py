# SPDX-License-Identifier: MIT
"""CLI: find, tree, projects, folder, describe in-process on a temp database."""
import json
from pathlib import Path

from test_cli_errors import CliCase, run
from test_query import QueryCase


class TestCliFind(QueryCase):
    def setUp(self):
        super().setUp()
        for i in range(30):
            self.add_file(f"report{i}.pdf", title="Line\nbreak")
        self.conn.close()
        self.base = ["--db", str(self.path)]

    def test_json_envelope(self):
        code, out, _ = run(*self.base, "find", "report", "--json")
        data = json.loads(out)
        self.assertEqual((code, data["schema_version"], len(data["results"]), data["more"]), (0, 1, 25, 5))

    def test_human_more_line_and_one_line_each(self):
        code, out, _ = run(*self.base, "find", "report", "--limit", "3")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 4)
        self.assertIn("27 more (narrow the words)", lines[-1])

    def test_other_commands(self):
        for argv in (["tree", "/srv/data"], ["projects"], ["folder", "/srv/data"], ["describe"]):
            code, out, _ = run(*self.base, *argv, "--json")
            self.assertEqual((code, json.loads(out)["schema_version"]), (0, 1))
        code, out, _ = run(*self.base, "describe")
        self.assertIn("find:", out)

    def test_unknown_path_is_one_error_line(self):
        code, out, err = run(*self.base, "folder", "/nope")
        self.assertEqual((code, out, err), (2, "", "error: unknown path\n"))

    def test_changes_documents(self):
        code, out, _ = run(*self.base, "changes", "--documents", "--since", "7d", "--json")
        self.assertEqual((code, json.loads(out)["schema_version"]), (0, 1))


class TestCliMissingDb(CliCase):
    def test_missing_db(self):
        code, out, err = run("--db", self.db, "find", "x")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("error: no database") and err.count("\n") == 1)
        self.assertFalse(Path(self.db).exists())
