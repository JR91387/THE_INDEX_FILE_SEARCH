# SPDX-License-Identifier: MIT
"""First load of a device skips per-row search triggers, rebuilds the indexes and restores the triggers."""
import test_files_ingest

from theindex import query

TRIGGERS = "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'file_%' ORDER BY name"


class FilesBulkTest(test_files_ingest.FilesIngestTest):
    def test_first_load_is_searchable_and_triggers_come_back(self):
        before = self.conn.execute(TRIGGERS).fetchall()
        self.scan()
        self.assertEqual(self.conn.execute(TRIGGERS).fetchall(), before)
        hits = query.find(self.conn, {"words": ["plan"]})["results"]
        self.assertIn("plan.md", [h["name"] for h in hits])
        self.assertIn("plan.md", [h["name"] for h in query.find(self.conn, {"words": ["lan"]})["results"]])

    def test_later_runs_use_the_triggers(self):
        self.scan()
        (self.root / "docs" / "fresh_notes.txt").write_text("x")
        self.scan(full=True)
        self.assertEqual([h["name"] for h in query.find(self.conn, {"words": ["fresh"]})["results"]],
                         ["fresh_notes.txt"])
