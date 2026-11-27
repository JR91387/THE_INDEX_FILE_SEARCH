# SPDX-License-Identifier: MIT
"""Offline catalogs: EFU and JSON Lines import, export round trip, retire on re-import, bad rows skipped."""
import contextlib
import io
import json
import tempfile
from pathlib import Path

from helpers import DbCase

from theindex import catalog, catalog_export, cli, query

FT = 133000000000000000          # a FILETIME; Unix ns = (FT - 116444736000000000) * 100
HEADER = "Filename,Size,Date Modified,Date Created,Attributes\r\n"
EFU = (HEADER +
       f'"E:\\Photos",,{FT},{FT},16\r\n'
       f'"E:\\Photos\\2020\\",,,,\r\n'
       f'"E:\\Photos\\2020\\caf\u00e9 menu.pdf",1234,{FT},{FT},32\r\n'
       f'"E:\\Photos\\2020\\empty.txt",,{FT},,32\r\n'
       f'"E:\\Photos\\top.jpg",500,{FT},,32\r\n')


class CatalogTest(DbCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def load(self, text=EFU, name="usb1", file="a.efu"):
        return catalog.import_catalog(self.conn, self.write(file, text), name)

    def test_filetime_conversion(self):
        self.assertEqual(catalog.filetime_to_ns(str(FT)), (FT - 116444736000000000) * 100)
        self.assertEqual(catalog.filetime_to_ns("116444736000000000"), 0)       # the Unix epoch
        self.assertIsNone(catalog.filetime_to_ns(""))
        self.assertEqual(catalog.ns_to_filetime(catalog.filetime_to_ns(str(FT))), FT)
        with self.assertRaises(ValueError):
            catalog.filetime_to_ns("soon")

    def test_efu_import_folders_files_unicode_and_empty_size(self):
        result = self.load()
        self.assertEqual((result["folders"], result["files"], result["skipped"]), (3, 3, 0))
        self.assertEqual(self.one("SELECT size_bytes FROM file WHERE name = 'empty.txt'"), 0)
        self.assertEqual(self.one("SELECT size_bytes FROM file WHERE name = 'caf\u00e9 menu.pdf'"), 1234)
        self.assertEqual(self.one("SELECT mtime_ns FROM file WHERE name = 'top.jpg'"),
                         (FT - 116444736000000000) * 100)
        self.assertEqual(self.one("SELECT r.code FROM device d JOIN ref_reach r ON r.id = d.reach_id"), "offline")
        self.assertEqual(self.one("SELECT size_total FROM dir WHERE path = 'E:\\Photos'"), 1734)

    def test_missing_columns_and_forward_slashes(self):
        result = self.load("filename\n/mnt/old/a.txt\n/mnt/old/sub/b.txt\n", name="old")
        self.assertEqual((result["folders"], result["files"]), (3, 2))     # /mnt, /mnt/old, /mnt/old/sub

    def test_find_marks_catalog_results_offline(self):
        self.load()
        out = query.find(self.conn, {"words": ["menu"]})
        hit = out["results"][0]
        self.assertTrue(hit["offline"])
        self.assertEqual(hit["device"], "usb1")

    def test_reimport_retires_removed_file(self):
        self.load()
        self.load(EFU.replace('"E:\\Photos\\top.jpg",500,' + str(FT) + ",,32\r\n", ""))
        self.assertIsNotNone(self.one("SELECT retired_run FROM file WHERE name = 'top.jpg'"))
        self.assertEqual(self.catalog_counts(), (3, 2))

    def catalog_counts(self):
        return catalog.counts(self.conn, "usb1")

    def test_export_efu_round_trip(self):
        self.load()
        out = self.dir / "out.efu"
        self.assertEqual(catalog_export.export_catalog(self.conn, out, ("usb1", None)), (3, 3))
        text = out.read_bytes().decode("utf-8")
        self.assertTrue(text.startswith(HEADER))
        self.assertIn(",16\r\n", text)
        self.assertEqual(len([n for n in self.dir.iterdir() if n.suffix == ".tmp"]), 0)
        again = catalog.import_catalog(self.conn, out, "usb2")
        self.assertEqual((again["folders"], again["files"]), (3, 3))

    def test_export_path_prefix(self):
        self.load()
        out = self.dir / "sub.efu"
        self.assertEqual(catalog_export.export_catalog(self.conn, out, ("usb1", "E:\\Photos\\2020")), (1, 2))

    def test_jsonl_import_and_export_round_trip(self):
        self.load()
        out = self.dir / "c.jsonl"
        catalog_export.export_catalog(self.conn, out, ("usb1", None), "jsonl")
        result = catalog.import_catalog(self.conn, out, "usb3")
        self.assertEqual((result["folders"], result["files"], result["skipped"]), (3, 3, 0))
        self.assertEqual(self.one("SELECT r.code FROM device d JOIN ref_reach r ON r.id = d.reach_id "
                                  "WHERE d.name = 'usb3'"), "offline")

    def test_jsonl_forces_catalog_collector_and_skips_garbage(self):
        lines = [{"t": "header", "collector": "filetree", "roots": ["/b"]},
                 {"t": "dir", "key": "/b", "path": "/b", "parent": None},
                 {"t": "file", "dir": "/b", "name": "x.txt", "size": 3}, {"t": "file", "name": "nodir"}]
        text = "\n".join(json.dumps(r) for r in lines[:3]) + "\nnot json\n" + json.dumps(lines[3]) + "\n"
        text += json.dumps({"t": "trailer", "status": "ok"}) + "\n"
        result = self.load(text, name="bk", file="s.jsonl")
        self.assertEqual((result["folders"], result["files"], result["skipped"]), (1, 1, 2))
        self.assertEqual(self.one("SELECT c.code FROM scan_run r JOIN ref_collector c ON c.id = r.collector_id"),
                         "catalog")

    def test_malformed_efu_rows_are_skipped_and_counted(self):
        bad = EFU + 'too,many,fields,here,32,extra\r\n,5,,,32\r\n"E:\\Photos\\x.bin",abc,,,32\r\n"E:\\Photos\\y.bin",1,zz,,32\r\n'
        result = self.load(bad)
        self.assertEqual((result["files"], result["skipped"]), (3, 4))

    def test_no_filename_column_is_an_error(self):
        with self.assertRaises(ValueError):
            self.load("Size,Attributes\n1,32\n")

    def test_cannot_hijack_a_scanned_device(self):
        from theindex import ingest
        ingest.ensure_device(self.conn, "host-a")
        self.conn.execute("INSERT INTO scan_run (device_id, collector_id, started_at, status_id) VALUES "
                          "((SELECT id FROM device), ?, 't', ?)",
                          (self.conn.ref_id("ref_collector", "jobs"), self.conn.ref_id("ref_run_status", "ok")))
        with self.assertRaises(ValueError):
            self.load(name="host-a")

    def test_list_and_cli_one_line(self):
        src = self.write("a.efu", EFU)
        db = str(self.dir / "cli.db")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--db", db, "catalog", "import", str(src), "--name", "usb9"])
        self.assertEqual((code, out.getvalue()), (0, "catalog usb9: 3 folders, 3 files\n"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--db", db, "catalog", "list", "--json"])
        rows = json.loads(out.getvalue())
        self.assertEqual((rows[0]["name"], rows[0]["folders"], rows[0]["files"]), ("usb9", 3, 3))
        self.assertTrue(rows[0]["last_import"])
