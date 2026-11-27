# SPDX-License-Identifier: MIT
"""Title readers: every fixture is generated in a temp dir."""
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from helpers import ROOT

COLLECTORS = ROOT / "src" / "theindex" / "collectors"
sys.path.insert(0, str(COLLECTORS))
import titles

DC = 'xmlns:dc="http://purl.org/dc/elements/1.1/"'


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def make(self, name, data):
        path = self.dir / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(path)

    def zipped(self, name, members):
        path = self.dir / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for member, body in members.items():
                zf.writestr(member, body)
        return str(path)

    def title(self, path):
        return titles.process(path)[:2]


class TextTitles(Base):
    def test_front_matter_and_quotes(self):
        self.assertEqual(self.title(self.make("a.md", "---\ntitle: Plain one\n---\n# H\n")), ("Plain one", "md_front"))
        self.assertEqual(self.title(self.make("b.md", "---\ntitle: 'Quoted: yes'\n---\n")), ("Quoted: yes", "md_front"))
        self.assertEqual(self.title(self.make("c.md", '---\ntitle: "Dq"\n---\n')), ("Dq", "md_front"))

    def test_heading_after_code_fence(self):
        body = "intro\n```\n# not this\n```\n# Real title ##\n## sub\n"
        self.assertEqual(self.title(self.make("d.md", body)), ("Real title", "md_heading"))

    def test_no_title_and_bom(self):
        self.assertEqual(self.title(self.make("e.md", "just words\n#hashtag\n")), (None, None))
        self.assertEqual(self.title(self.make("f.md", b"\xef\xbb\xbf# With BOM\n")), ("With BOM", "md_heading"))

    def test_non_scalar_front_matter_falls_back_to_heading(self):
        body = "---\ntitle: [a, b]\n---\n# Fallback\n"
        self.assertEqual(self.title(self.make("g.md", body)), ("Fallback", "md_heading"))

    def test_html_entities_and_whitespace(self):
        page = "<html><head><title>\n  Tom &amp; Jerry\n   &#169; 2026 </title></head><body>x</body></html>"
        self.assertEqual(self.title(self.make("p.html", page)), ("Tom & Jerry © 2026", "html"))


class ZipTitles(Base):
    def test_docx_odt_epub(self):
        core = f'<cp:coreProperties {DC} xmlns:cp="x"><dc:title>Quarterly plan</dc:title></cp:coreProperties>'
        self.assertEqual(self.title(self.zipped("a.docx", {"docProps/core.xml": core})), ("Quarterly plan", "ooxml"))
        meta = f'<office:document-meta xmlns:office="o" {DC}><office:meta><dc:title>Notes</dc:title></office:meta></office:document-meta>'
        self.assertEqual(self.title(self.zipped("a.odt", {"meta.xml": meta})), ("Notes", "odf"))
        container = '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>'
        opf = f'<package {DC}><metadata><dc:title>A Book</dc:title></metadata></package>'
        members = {"META-INF/container.xml": container, "OEBPS/c.opf": opf}
        self.assertEqual(self.title(self.zipped("a.epub", members)), ("A Book", "epub"))

    def test_huge_member_is_skipped(self):
        core = f'<cp:coreProperties {DC} xmlns:cp="x"><dc:title>Bomb</dc:title></cp:coreProperties>' + " " * 2_000_000
        result = titles.process(self.zipped("bomb.docx", {"docProps/core.xml": core}))
        self.assertEqual(result, (None, None, False))

    def test_corrupt_zip_is_an_error_not_a_raise(self):
        self.assertEqual(titles.process(self.make("bad.docx", b"PK\x03\x04 not really")), (None, None, True))

    def test_entity_declarations_refused(self):
        core = f'<!DOCTYPE x [<!ENTITY a "b">]><cp {DC}><dc:title>&a;</dc:title></cp>'
        self.assertEqual(self.title(self.zipped("e.docx", {"docProps/core.xml": core})), (None, None))


def pdf(info, extra=b""):
    return b"%PDF-1.4\n1 0 obj\n<< /Producer (t) " + info + b" >>\nendobj\n" + extra + b"%%EOF\n"


class PdfTitles(Base):
    def test_literal_escapes_and_nested_parens(self):
        raw = rb"/Title (Plan \(draft\) (v2) a\\b\101\n\ttab)"
        self.assertEqual(self.title(self.make("a.pdf", pdf(raw))), ("Plan (draft) (v2) a\\bA tab", "pdf_info"))

    def test_hex_utf16be(self):
        hexed = ("﻿Café ☕").encode("utf-16-be").hex().encode()
        self.assertEqual(self.title(self.make("b.pdf", pdf(b"/Title <" + hexed + b">"))), ("Café ☕", "pdf_info"))

    def test_xmp_title_wins(self):
        xmp = b'<x:xmpmeta><dc:title><rdf:Alt><rdf:li xml:lang="x-default">XMP &amp; Co</rdf:li></rdf:Alt></dc:title></x:xmpmeta>'
        data = pdf(b"/Title (Info one)", xmp)
        self.assertEqual(self.title(self.make("c.pdf", data)), ("XMP & Co", "pdf_xmp"))

    def test_flate_compressed_object(self):
        packed = zlib.compress(b"<< /Producer (t) /Title (Inside stream) >>")
        extra = b"2 0 obj\n<< /Filter /FlateDecode >>\nstream\n" + packed + b"\nendstream\nendobj\n"
        self.assertEqual(self.title(self.make("d.pdf", b"%PDF-1.5\n" + extra + b"%%EOF")), ("Inside stream", "pdf_info"))

    def test_title_beyond_head_window_is_found_in_tail(self):
        data = b"%PDF-1.4\n" + b"x" * 200_000 + b"\n" + pdf(b"/Title (From the tail)")
        self.assertEqual(self.title(self.make("t.pdf", data)), ("From the tail", "pdf_info"))

    def test_cleaning(self):
        self.assertEqual(self.title(self.make("e.pdf", pdf(b"/Title (Microsoft Word - Budget)"))), ("Budget", "pdf_info"))
        self.assertEqual(self.title(self.make("report.pdf", pdf(b"/Title (report)"))), (None, None))
        self.assertEqual(self.title(self.make("f.pdf", pdf(b"/Title (Untitled)"))), (None, None))

    def test_empty_file(self):
        self.assertEqual(titles.process(self.make("z.pdf", b"")), (None, None, False))


class Cli(Base):
    def run_cli(self, paths, opts):
        work = self.dir / "work.jsonl"
        work.write_text("".join(json.dumps({"id": i, "path": p}) + "\n" for i, p in enumerate(paths, 1)))
        out = subprocess.run([sys.executable, str(COLLECTORS / "titles.py"), "--worklist", str(work), json.dumps(opts)],
                             capture_output=True, text=True, timeout=60, check=True).stdout
        return [json.loads(line) for line in out.splitlines()]

    def test_max_files_stops_cleanly(self):
        paths = [self.make(f"{n}.md", f"# T{n}\n") for n in "abc"]
        rows = self.run_cli(paths, {"max_files": 2})
        self.assertEqual(rows[:2], [{"id": 1, "title": "Ta", "src": "md_heading"}, {"id": 2, "title": "Tb", "src": "md_heading"}])
        self.assertEqual(rows[2], {"t": "trailer", "done": 2, "errors": 0, "stopped": "max_files"})

    def test_missing_file_counts_an_error(self):
        rows = self.run_cli([str(self.dir / "gone.md")], {})
        self.assertEqual(rows[0], {"id": 1, "title": None, "src": None})
        self.assertEqual(rows[1], {"t": "trailer", "done": 1, "errors": 1, "stopped": None})

    def test_zero_budget_stops(self):
        rows = self.run_cli([self.make("a.md", "# A\n")], {"budget_s": 0})
        self.assertEqual(rows, [{"t": "trailer", "done": 0, "errors": 0, "stopped": "budget"}])


if __name__ == "__main__":
    unittest.main()
