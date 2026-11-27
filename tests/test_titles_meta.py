# SPDX-License-Identifier: MIT
"""Front matter (author, date, tags, description, lang) read together with the title."""
import json
import sys
import zipfile
from pathlib import Path

from helpers import ROOT
from test_titles import Base, pdf

sys.path.insert(0, str(ROOT / "src" / "theindex" / "collectors"))
import titles
import titles_meta

NS = ('xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:cp="http://x/cp" xmlns:dcterms="http://x/t" '
      'xmlns:meta="urn:meta" xmlns:office="urn:office"')


class Meta(Base):
    def meta(self, path):
        return titles.read_all(path)[2]

    def test_md_scalars_and_quotes(self):
        text = ('---\ntitle: T\nauthor: "Alice B."\ndate: 2024-05-03\ndescription: \'A note # kept\'  \n'
                'lang: en  # comment\n---\nbody\n')
        self.assertEqual(self.meta(self.make("a.md", text)), {
            "author": "Alice B.", "date": "2024-05-03", "description": "A note # kept", "lang": "en"})

    def test_md_list_forms_and_aliases(self):
        inline = '---\nauthors: [Alice, "Bob, Jr."]\ntags: [a, "b c", a]\n---\n'
        self.assertEqual(self.meta(self.make("b.md", inline)), {"author": "Alice, Bob, Jr.", "tags": ["a", "b c"]})
        block = "---\nkeywords:\n  - x\n  - y\nsummary: >\n  folded\n  text\nlanguage: de\n---\n"
        self.assertEqual(self.meta(self.make("c.md", block)),
                         {"tags": ["x", "y"], "description": "folded text", "lang": "de"})
        self.assertEqual(self.meta(self.make("d.md", "---\ntags: one, two\n---\n")), {"tags": ["one", "two"]})
        self.assertEqual(self.meta(self.make("e.md", "# only a heading\n")), {})

    def test_meta_comes_with_heading_title(self):
        title, src, meta, bad = titles.read_all(self.make("f.md", "---\nauthor: Al\n---\n# Heading\n"))
        self.assertEqual((title, src, meta, bad), ("Heading", "md_heading", {"author": "Al"}, False))

    def test_html(self):
        page = ('<html lang="fr"><head><title>T</title><meta name="Author" content="Al">'
                '<meta name="description" content="Desc"><meta name="keywords" content="a, b ,c"></head></html>')
        self.assertEqual(self.meta(self.make("a.html", page)),
                         {"author": "Al", "description": "Desc", "tags": ["a", "b", "c"], "lang": "fr"})

    def test_ooxml(self):
        core = (f'<cp:coreProperties {NS}><dc:title>T</dc:title><dc:creator>Zed</dc:creator>'
                '<dcterms:created>2024-01-02T03:04:05Z</dcterms:created><cp:keywords>x; y, z</cp:keywords>'
                '<dc:description>Comments</dc:description><dc:language>en-US</dc:language></cp:coreProperties>')
        self.assertEqual(self.meta(self.zipped("a.docx", {"docProps/core.xml": core})), {
            "author": "Zed", "date": "2024-01-02T03:04:05Z", "tags": ["x", "y", "z"],
            "description": "Comments", "lang": "en-US"})
        subject = core.replace("</cp:coreProperties>", "<dc:subject>Subj</dc:subject></cp:coreProperties>")
        self.assertEqual(self.meta(self.zipped("b.docx", {"docProps/core.xml": subject}))["description"], "Subj")

    def test_odf(self):
        xml = (f'<office:document-meta {NS}><meta:initial-creator>Ini</meta:initial-creator><dc:creator>Ed</dc:creator>'
               '<meta:creation-date>2023-09-09T10:00:00</meta:creation-date><meta:keyword>k1</meta:keyword>'
               '<meta:keyword>k2</meta:keyword><dc:description>D</dc:description><dc:language>nl</dc:language>'
               '</office:document-meta>')
        self.assertEqual(self.meta(self.zipped("a.odt", {"meta.xml": xml})), {
            "author": "Ini", "date": "2023-09-09T10:00:00", "tags": ["k1", "k2"], "description": "D", "lang": "nl"})

    def test_epub(self):
        container = '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>'
        opf = (f'<package {NS}><metadata><dc:title>Book</dc:title><dc:creator>Writer</dc:creator><dc:date>2020</dc:date>'
               '<dc:subject>Fiction</dc:subject><dc:subject>Sea</dc:subject><dc:description>Blurb</dc:description>'
               '<dc:language>en</dc:language></metadata></package>')
        path = self.zipped("a.epub", {"META-INF/container.xml": container, "OEBPS/c.opf": opf})
        self.assertEqual(titles.read_all(path)[:3], ("Book", "epub", {
            "author": "Writer", "date": "2020", "tags": ["Fiction", "Sea"], "description": "Blurb", "lang": "en"}))

    def test_pdf_info_and_date(self):
        info = b"/Title (T) /Author (Alice) /CreationDate (D:20240503101500+02'00') /Keywords (k1, k2) /Subject (About)"
        self.assertEqual(self.meta(self.make("a.pdf", pdf(info))), {
            "author": "Alice", "date": "2024-05-03", "tags": ["k1", "k2"], "description": "About"})
        self.assertEqual(titles_meta.normalise({"date": None}), {})

    def test_pdf_xmp_wins_over_info(self):
        xmp = (b'<x:xmpmeta xmlns:xmp="x"><dc:title><rdf:Alt><rdf:li>X</rdf:li></rdf:Alt></dc:title>'
               b'<dc:creator><rdf:Seq><rdf:li>Xena</rdf:li></rdf:Seq></dc:creator>'
               b'<dc:subject><rdf:Bag><rdf:li>t1</rdf:li><rdf:li>t2</rdf:li></rdf:Bag></dc:subject>'
               b'<dc:description><rdf:Alt><rdf:li>Desc</rdf:li></rdf:Alt></dc:description>'
               b'<xmp:CreateDate>2022-02-03T00:00:00Z</xmp:CreateDate></x:xmpmeta>')
        meta = self.meta(self.make("b.pdf", pdf(b"/Author (Info) /CreationDate (D:20010101)", xmp)))
        self.assertEqual(meta, {"author": "Xena", "date": "2022-02-03T00:00:00Z", "tags": ["t1", "t2"],
                                "description": "Desc"})

    def test_caps_and_control_characters(self):
        tags = [f"t{i}" for i in range(30)]
        page = f'<meta name="author" content="{"a" * 400}"><meta name="description" content="x\x01y\n z">'
        meta = self.meta(self.make("c.html", page + f'<meta name="keywords" content="{",".join(tags)}">'))
        self.assertEqual(len(meta["author"]), 300)
        self.assertEqual(meta["description"], "x y z")
        self.assertEqual(meta["tags"], tags[:20])

    def test_cli_record_has_meta_only_when_found(self):
        work = self.dir / "w.jsonl"
        paths = [self.make("a.md", "---\nauthor: Al\n---\n# T\n"), self.make("b.md", "# T\n")]
        work.write_text("".join(json.dumps({"id": i, "path": p}) + "\n" for i, p in enumerate(paths)))
        import subprocess
        out = subprocess.run([sys.executable, str(Path(titles.__file__)), "--worklist", str(work), "{}"],
                             capture_output=True, text=True, timeout=60, check=True).stdout
        recs = [json.loads(line) for line in out.splitlines()]
        self.assertEqual(recs[0]["meta"], {"author": "Al"})
        self.assertNotIn("meta", recs[1])

    def test_corrupt_zip_has_empty_meta(self):
        self.assertEqual(titles.read_all(self.make("bad.docx", b"PK\x03\x04 nope")), (None, None, {}, True))
        self.assertTrue(zipfile.is_zipfile(self.zipped("ok.odt", {"meta.xml": "<a/>"})))
