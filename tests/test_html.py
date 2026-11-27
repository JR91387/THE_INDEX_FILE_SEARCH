# SPDX-License-Identifier: MIT
"""The single-file HTML page: written by `pages`, self-contained, data intact and safely embedded, byte-stable."""
import contextlib
import io
import json
import re
from pathlib import Path

from helpers import job, payload
from test_pages import PagesCase

from theindex import cli, ingest
from theindex.pages import html, model


def embedded(text):
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', text, re.DOTALL)
    return json.loads(m.group(1))


class TestHtml(PagesCase):
    def page(self):
        return (self.out / html.NAME).read_text(encoding="utf-8")

    def test_cli_writes_html_next_to_markdown(self):
        self.fill()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--db", str(self.path), "pages", "--out", str(self.out)]), 0)
        self.assertTrue((self.out / "index.md").exists())
        self.assertIn("<title>THE INDEX</title>", self.page())

    def test_self_contained_and_data_matches_model(self):
        self.fill()
        html.write(self.conn, self.out)
        text = self.page()
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        # fetch is allowed only toward this server's own /api/ (the served review control)
        self.assertNotRegex(text, r"""<(link|img|iframe)\b|\bsrc=|@import|import\(|fetch\((?!"/api/)|XMLHttpRequest""")
        data = embedded(text)
        self.assertEqual(data["model"], model.build(self.conn))
        self.assertIn("svg", data["icons"]["health"]["ok"])
        self.assertTrue(data["icons"]["health"]["ok"]["svg"].startswith("<svg"))

    def test_only_builtin_icons_carry_svg(self):
        self.fill()
        self.conn.execute("UPDATE ref_icon SET is_builtin = 0 WHERE code = 'ok'")
        icons = html.icons(self.conn)
        self.assertIsNone(icons["health"]["ok"]["svg"])
        self.assertIn("Content-Security-Policy", html.render(self.conn))

    def test_same_db_same_bytes(self):
        self.fill()
        html.write(self.conn, self.out)
        first = (self.out / html.NAME).read_bytes()
        html.write(self.conn, self.out)
        self.assertEqual(first, (self.out / html.NAME).read_bytes())
        self.assertEqual([p.name for p in Path(self.out).iterdir() if p.name.startswith(".")], [])

    def test_script_tag_in_a_key_cannot_break_out(self):
        evil = "crontab:</script><script>alert(1)</script>"
        ingest.ingest(self.conn, payload([job(evil)]), "host-a")
        html.write(self.conn, self.out)
        text = self.page()
        self.assertEqual(text.count("</script>"), 2)
        self.assertEqual(text.count("<script"), 2)
        keys = [r["key"] for r in embedded(text)["model"]["jobs"]["items"]]
        self.assertEqual(keys, [evil])
