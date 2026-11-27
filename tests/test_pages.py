# SPDX-License-Identifier: MIT
"""Markdown pages: content from a fixture DB, byte-stable output, empty DB, and the CLI command."""
import contextlib
import io
import json
import re
import tempfile
from pathlib import Path
from unittest import mock

from helpers import DbCase, job, payload

from theindex import cli, db, ingest, report
from theindex.pages import finder, html, markdown, model

NAMES = ["index.md"] + [f"{n}.md" for n in markdown.SECTIONS]


def read_all(out):
    return {n: (Path(out) / n).read_bytes() for n in NAMES}


class PagesCase(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name) / "pages"

    def fill(self):
        ingest.ingest(self.conn, payload([job("crontab:a"), job("crontab:b")]), "host-a")
        ingest.ingest(self.conn, payload([job("crontab:a", command="/bin/false"), job("crontab:c")],
                                         gaps=[{"kind": "denied", "target": "/srv/data/x", "reason": "no"}]),
                      "host-a")
        db.rebuild_search(self.conn)


class TestPages(PagesCase):
    def test_fixture_rows_and_headings(self):
        self.fill()
        markdown.write(self.conn, self.out)
        files = {n: b.decode() for n, b in read_all(self.out).items()}
        self.assertIn("# THE INDEX", files["index.md"])
        self.assertIn("[jobs](jobs.md) (2)", files["index.md"])
        self.assertIn("# Jobs", files["jobs.md"])
        self.assertIn("| host-a | crontab:a | 0 1 * * * | alice | /bin/false |", files["jobs.md"])
        self.assertIn("job command or user changed", files["changes.md"])
        self.assertIn("| denied | /srv/data/x |", files["gaps.md"])
        self.assertTrue(all("(index.md)" in files[n] for n in NAMES[1:]))
        self.assertEqual(files["folders.md"].count("Nothing yet."), 1)

    def test_same_db_same_bytes(self):
        self.fill()
        markdown.write(self.conn, self.out)
        first = read_all(self.out)
        markdown.write(self.conn, self.out)
        self.assertEqual(first, read_all(self.out))
        self.assertEqual([p.name for p in self.out.iterdir() if p.name.startswith(".")], [])

    def test_empty_db_every_page_says_nothing_yet(self):
        markdown.write(self.conn, self.out)
        files = {n: b.decode() for n, b in read_all(self.out).items()}
        for name in NAMES[1:]:
            self.assertIn("Nothing yet.", files[name])
        self.assertIn("Last run never", files["index.md"])

    def test_status_uses_the_model(self):
        self.fill()
        m = model.overview(self.conn)
        text = report.front_page(self.conn)
        self.assertIn(f"blind spots: {m['front']['gaps_open']}", text)
        self.assertEqual(len(m["changes"]), 3)

    def test_cli_pages_out(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["--db", str(self.path), "pages", "--out", str(self.out)])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), str(self.out))
        self.assertTrue((self.out / "index.md").exists())


class TestAutoPages(PagesCase):
    def scan(self, pages_on_scan=True, pages_dir=None):
        """Run `scan --from-json` with a temp config; returns (exit code, the 'pages:' stderr lines)."""
        tmp = self.path.parent
        cfg = tmp / "config.toml"
        cfg.write_text(f'[paths]\npages_dir = "{pages_dir or self.out}"\n'
                       f'pages_on_scan = {str(pages_on_scan).lower()}\n')
        saved = tmp / "payload.json"
        saved.write_text(json.dumps(payload([job("crontab:a")])))
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = cli.main(["--config", str(cfg), "--db", str(self.path), "scan", "--from-json", str(saved)])
        return rc, [line for line in err.getvalue().splitlines() if line.startswith("pages:")]

    def test_scan_writes_markdown_and_html(self):
        rc, err = self.scan()
        self.assertEqual((rc, err), (0, []))
        self.assertIn("# THE INDEX", (self.out / "index.md").read_text(encoding="utf-8"))
        self.assertIn("crontab:a", (self.out / "jobs.md").read_text(encoding="utf-8"))
        self.assertTrue((self.out / html.NAME).exists())

    def test_pages_on_scan_false_writes_nothing(self):
        rc, err = self.scan(pages_on_scan=False)
        self.assertEqual((rc, err), (0, []))
        self.assertFalse(self.out.exists())

    def test_unwritable_pages_dir_fails_only_the_pages_step(self):
        blocker = self.path.parent / "blocker"
        blocker.write_text("a regular file, so no directory can live under it")
        rc, err = self.scan(pages_dir=blocker / "pages")
        self.assertEqual(rc, 0)
        self.assertEqual(len(err), 1)
        self.assertTrue(err[0].startswith("pages: not written ("), err)
        self.assertGreater(self.one("SELECT COUNT(*) FROM item"), 0)


HOSTILE = "</script><img src=x onerror=alert(1)>"


def seed_files(conn, count=3, hostile=True):
    """host-a with a project folder, a plain folder and `count` titled documents (one hostile name)."""
    conn.execute("INSERT OR IGNORE INTO device (name, reach_id, status_id) VALUES ('host-a', ?, ?)",
                 (conn.ref_id("ref_reach", "local"), conn.ref_id("ref_device_status", "active")))
    dev = conn.execute("SELECT id FROM device WHERE name = 'host-a'").fetchone()[0]
    run = conn.execute("INSERT INTO scan_run (device_id, collector_id, started_at, status_id) VALUES (?,?,?,?)",
                       (dev, conn.ref_id("ref_collector", "filetree"), "2026-01-01T00:00:00Z",
                        conn.ref_id("ref_run_status", "ok"))).lastrowid
    dirs = {}
    for path, agents, total in (("/srv/data/garden", '["CLAUDE.md"]', 900), ("/srv/data/misc", "[]", 50)):
        dirs[path] = conn.execute(
            "INSERT INTO dir (device_id, path_key, path, depth, size_total, files_total, agent_files, "
            "first_seen_run, seen_run) VALUES (?,?,?,2,?,1,?,?,?)", (dev, path, path, total, agents, run, run)
        ).lastrowid
    names = [(f"plan{i}.pdf", f"Tomato plan {i}") for i in range(count)]
    names += [(HOSTILE + ".pdf", HOSTILE)] if hostile else []
    for name, title in names:
        conn.execute("INSERT INTO file (device_id, dir_id, name, ext, title, size_bytes, mtime_ns, first_seen_run, "
                     "seen_run) VALUES (?,?,?,'.pdf',?,10,5,?,?)",
                     (dev, dirs["/srv/data/garden"], name, title, run, run))
    db.rebuild_search(conn)


def embedded(text):
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', text, re.DOTALL)
    return json.loads(m.group(1))


class TestFinderIndex(PagesCase):
    def page(self):
        html.write(self.conn, self.out)
        return (self.out / html.NAME).read_text(encoding="utf-8")

    def test_file_page_embeds_index_and_served_page_does_not(self):
        seed_files(self.conn)
        data = embedded(self.page())
        self.assertEqual({r[0] for r in data["finder"]}, {"p", "d", "f"})
        self.assertEqual(data["finder"][0][:3], ["p", "host-a", "/srv/data/garden"])   # projects first
        self.assertEqual(sum(1 for r in data["finder"] if r[2] == "/srv/data/garden"), 1)   # no project/dir twin
        self.assertNotIn("finder", embedded(html.render(self.conn, served=True, token="t")))
        self.assertIn("theIndexFinder(D)", self.page())

    def test_hostile_name_is_escaped_in_the_page(self):
        seed_files(self.conn)
        text = self.page()
        self.assertEqual(text.count("</script>"), 2)
        self.assertNotIn("<img src=x", text)
        self.assertIn(HOSTILE + ".pdf", [r[3] for r in embedded(text)["finder"]])   # data, never markup
        self.assertNotIn("innerHTML", finder.script())

    def test_rows_and_bytes_are_capped(self):
        seed_files(self.conn, count=40, hostile=False)
        self.assertEqual(len(finder.index(self.conn)), 42)
        with mock.patch.object(finder, "MAX_ROWS", 10):
            self.assertEqual(len(finder.index(self.conn)), 10)
        with mock.patch.object(finder, "MAX_BYTES", 400):
            rows = finder.index(self.conn)
            self.assertTrue(0 < len(rows) < 42)
            self.assertLessEqual(sum(len(json.dumps(r)) + 1 for r in rows), 400)

    def test_title_is_cut(self):
        seed_files(self.conn, count=1, hostile=False)
        self.conn.execute("UPDATE file SET title = ?", ("x" * 500,))
        titles = [len(r[4]) for r in finder.index(self.conn) if r[0] == "f"]
        self.assertEqual(titles, [finder.MAX_TITLE])
