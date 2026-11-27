# SPDX-License-Identifier: MIT
"""The Windows bundle builder: layout, ._pth edit, launcher, refusals and the download hash check."""
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import helpers  # puts src/ on the path

sys.path.insert(0, str(helpers.ROOT / "tools"))
import build_windows

PTH = "python312.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n"


def fake_embed(path, files=None):
    files = files or {"python.exe": b"MZ", "python312.zip": b"PK", "python312._pth": PTH}
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return Path(path)


class BuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def build(self, files=None):
        embed = fake_embed(self.tmp / "e.zip", files)
        return build_windows.build(embed, self.tmp / "out", "b")

    def test_layout_and_launcher(self):
        with zipfile.ZipFile(self.build()) as zf:
            names = set(zf.namelist())
            for need in ("b/python/python.exe", "b/lib/theindex/__main__.py", "b/the-index.cmd", "b/README.txt"):
                self.assertIn(need, names)
            self.assertFalse([n for n in names if "__pycache__" in n or "/tests/" in n])
            cmd = zf.read("b/the-index.cmd")
            self.assertTrue(cmd.startswith(b"@echo off\r\n"))
            self.assertIn(b'"%~dp0python\\python.exe" -m theindex %*\r\n', cmd)
            self.assertNotIn(b"\n", cmd.replace(b"\r\n", b""))
            self.assertNotIn(b"\n", zf.read("b/README.txt").replace(b"\r\n", b""))

    def test_pth_edited(self):
        with zipfile.ZipFile(self.build()) as zf:
            pth = zf.read("b/python/python312._pth").decode()
        lines = pth.split("\r\n")
        self.assertEqual(lines[:3], ["python312.zip", ".", "..\\lib"])
        self.assertIn("#import site", lines)
        self.assertNotIn("import site", lines)

    def test_refusals(self):
        with self.assertRaises(build_windows.Refuse):
            self.build({"python312._pth": PTH})
        with self.assertRaises(build_windows.Refuse):
            self.build({"python.exe": b"", "a._pth": "", "b._pth": ""})
        with self.assertRaises(build_windows.Refuse):
            self.build({"python.exe": b""})

    def test_main_exit_2_one_line(self):
        embed = fake_embed(self.tmp / "e.zip", {"x": b""})
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            code = build_windows.main(["--embed-zip", str(embed), "--out", str(self.tmp / "o")])
        self.assertEqual(code, 2)
        self.assertEqual(len(err.getvalue().splitlines()), 1)


class DownloadTest(unittest.TestCase):
    DATA = b"embed-bytes"

    def fake_get(self, spdx_hash):
        sha = hashlib.sha256(self.DATA).hexdigest()
        spdx = {"packages": [{"packageFileName": "python-3.12.8-embed-amd64.zip",
                              "checksums": [{"algorithm": "SHA256", "checksumValue": spdx_hash or sha}]}]}

        def get(url):
            return json.dumps(spdx).encode() if url.endswith(".spdx.json") else self.DATA
        return get

    def run_download(self, get, sha=None):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_windows, "_get", get):
            return build_windows.download("3.12.8", tmp, sha).name

    def test_good_hash(self):
        self.assertEqual(self.run_download(self.fake_get(None)), "python-3.12.8-embed-amd64.zip")

    def test_bad_hash_refuses(self):
        with self.assertRaises(build_windows.Refuse):
            self.run_download(self.fake_get("0" * 64))

    def test_explicit_sha256_overrides_missing_publication(self):
        def get(url):
            if url.endswith(".spdx.json"):
                raise OSError("404")
            return self.DATA
        self.run_download(get, hashlib.sha256(self.DATA).hexdigest())
        with self.assertRaises(build_windows.Refuse):
            self.run_download(get)


if __name__ == "__main__":
    unittest.main()
