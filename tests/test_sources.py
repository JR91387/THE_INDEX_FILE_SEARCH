# SPDX-License-Identifier: MIT
"""sources.py collector: the stream built from fake plocate, Spotlight (mdfind + mdls) and Everything (es)."""
import json
from pathlib import Path

from sources_fixture import NativeCase, fake_tool, nul_list

from theindex import files_ingest


class SourcesStreamTest(NativeCase):
    def kinds(self, records, kind):
        return [r for r in records if r["t"] == kind]

    def test_plocate_stream(self):
        elsewhere = self.tmp / "outside.txt"
        elsewhere.write_text("o")
        self.fake_plocate([*self.listing(), elsewhere, self.root / "gone.txt"])
        recs = self.run_sources()
        head, tail = recs[0], recs[-1]
        self.assertEqual((head["t"], head["source"], head["no_retire"], head["full"]), ("header", "plocate", True, False))
        self.assertEqual((tail["t"], tail["status"], tail["errors"]), ("trailer", "ok", []))
        self.assertFalse(self.kinds(recs, "skip") or self.kinds(recs, "gap"))
        names = {(Path(r["dir"]).name, r["name"]) for r in self.kinds(recs, "file")}
        self.assertEqual(names, {("data", "top.txt"), ("data", "AGENTS.md"), ("docs", "a.md"), ("docs", "a.pdf"),
                                 ("sub", "b.txt")})
        dirs = {r["path"]: r for r in self.kinds(recs, "dir")}
        self.assertEqual(dirs[str(self.root)]["parent"], None)
        self.assertEqual(dirs[str(self.root)]["agents"], ["AGENTS.md"])
        self.assertEqual(dirs[str(self.root / "docs" / "sub")]["parent"], dirs[str(self.root / "docs")]["key"])
        cache = dirs[str(self.root / "node_modules")]
        self.assertEqual((cache["cache"], cache["size"], cache["files"]), (True, 10, 2))
        self.assertNotIn(str(self.root / "node_modules" / "pkg"), dirs)
        self.assertEqual(recs.index(dirs[str(self.root)]), 1)          # parents come before children

    def test_count_only_prints_files_per_root(self):
        self.fake_plocate()
        recs = self.run_sources(count_only=True)
        self.assertEqual([r["t"] for r in recs], ["header", "trailer"])
        self.assertEqual(recs[-1]["counts"]["roots"], {str(self.root): 7})

    def test_stale_or_absent_tool_gives_partial_with_error(self):
        self.fake_plocate()
        self.stale()
        tail = self.run_sources()[-1]
        self.assertEqual(tail["status"], "partial")
        self.assertIn("older than 2 days", tail["errors"][0])
        (self.bin / "plocate").unlink()
        self.assertIn("not found", self.run_sources()[-1]["errors"][0])

    def test_tool_failure_is_partial(self):
        self.fake_plocate(code=3)
        tail = self.run_sources()[-1]
        self.assertEqual((tail["status"], tail["errors"][0]), ("partial", "RuntimeError: locate exited 3"))

    def test_spotlight_titles_are_native(self):
        fake_tool(self.bin, "mdfind", nul_list(self.listing()))
        fake_tool(self.bin, "mdls", 'shift 3\nfor f in "$@"; do case "$f" in *.pdf) printf "Annual report\\0";; '
                  '*) printf "(null)\\0";; esac; done')
        recs = self.run_sources(platform="darwin", title_exts=[".pdf", ".md"])
        self.assertEqual(recs[0]["source"], "spotlight")
        by_name = {r["name"]: r for r in self.kinds(recs, "file")}
        self.assertEqual((by_name["a.pdf"]["title"], by_name["a.pdf"]["title_src"]), ("Annual report", "native"))
        self.assertEqual(by_name["a.pdf"]["title_sig"], "20:" + str(by_name["a.pdf"]["mtime_ns"]))
        self.assertNotIn("title", by_name["a.md"])

    def test_everything_csv(self):
        rows = ["Filename,Size,Date Modified"] + [f'"{p}",1,2026-01-01' for p in self.listing()] + ["junk"]
        fake_tool(self.bin, "es", "/bin/cat <<'EOF'\n" + "\n".join(rows) + "\nEOF")
        recs = self.run_sources(platform="win32")
        self.assertEqual((recs[0]["source"], recs[0]["os"], recs[-1]["status"]), ("everything", "windows", "ok"))
        self.assertEqual(len(self.kinds(recs, "file")), 5)

    def test_titles_reach_the_database(self):
        fake_tool(self.bin, "mdfind", nul_list(self.listing()))
        fake_tool(self.bin, "mdls", 'shift 3\nfor f in "$@"; do printf "Annual report\\0"; done')
        lines = [json.dumps(r) for r in self.run_sources(platform="darwin", title_exts=[".pdf"])]
        files_ingest.ingest_stream(self.conn, lines, "host-a")
        row = self.conn.execute("SELECT title, title_src FROM file WHERE name = 'a.pdf'").fetchone()
        self.assertEqual(tuple(row), ("Annual report", "native"))
        self.assertIsNone(self.one("SELECT title FROM file WHERE name = 'a.md'"))
