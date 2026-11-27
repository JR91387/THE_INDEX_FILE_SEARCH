# SPDX-License-Identifier: MIT
"""Render-time secret masking and private page permissions."""
import os
import stat
import tempfile
import unittest
from pathlib import Path

from helpers import job, payload
from test_pages import PagesCase

from theindex import ingest
from theindex.pages import html, markdown


class TestRedact(unittest.TestCase):
    def test_masks_values(self):
        cases = {
            "run --password hunter2 --x": "run --password *** --x",
            "run --token=abc123": "run --token=***",
            "run --api-key 'a b' go": "run --api-key *** go",
            "db password=pw1 user=x": "db password=*** user=x",
            "MY_API_TOKEN=zzz /bin/job": "MY_API_TOKEN=*** /bin/job",
            'X_SECRET="a b" y': "X_SECRET=*** y",
            "DB_PASSWORD=p run": "DB_PASSWORD=*** run",
            "S3_KEY=k run": "S3_KEY=*** run",
        }
        for raw, want in cases.items():
            self.assertEqual(markdown.redact(raw), want)

    def test_leaves_normal_commands_alone(self):
        for text in ("/usr/bin/backup --keep 7 -p 5432", "tar czf x.tgz /srv/data", "monkey=1 run", None):
            self.assertEqual(markdown.redact(text), text)


def fake_model(n):
    folders = [{"device": "host-a", "key": f"/srv/data/d{i:03d}", "size_bytes": i, "file_count": 1,
                "primary_content": "unknown", "purpose": None, "criticality": None} for i in range(n)]
    names = ["backups_emergency", "backups_warn", "changes_24h", "runs_bad_24h", "runs_skipped_24h",
             "containers_stopped", "containers_down", "filesystems_full", "folders_no_purpose",
             "unbacked_irreplaceable", "changes_suspicious", "changes_unreviewed", "gaps_open"]
    return {"folders": folders, "jobs": {"items": [], "collisions": []}, "containers": {"items": []},
            "filesystems": [], "backups": [], "changes": [], "gaps": [],
            "front": {**dict.fromkeys(names, 0), "scan_stale": 0, "last_run": None, "last_ok_run": None}}


class TestFolderCap(unittest.TestCase):
    def test_cap_and_more_line(self):
        files = markdown.render(fake_model(130))
        rows = [x for x in files["folders.md"].splitlines() if x.startswith("| host-a")]
        self.assertEqual(len(rows), 100)
        self.assertIn("30 more folders: use `the-index search`", files["folders.md"])
        self.assertIn("folders](folders.md) (130)", files["index.md"])
        self.assertNotIn("more folders", markdown.render(fake_model(100))["folders.md"])


class TestPrivatePages(PagesCase):
    def test_modes_and_render_redaction(self):
        ingest.ingest(self.conn, payload([job("crontab:s", command="run --password hunter2")]), "host-a")
        out = Path(tempfile.mkdtemp()) / "pages"
        markdown.write(self.conn, out)
        html.write(self.conn, out)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
        for p in out.iterdir():
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600, p.name)
            self.assertNotIn("hunter2", p.read_text(encoding="utf-8"))
        stored = self.conn.execute("SELECT attrs FROM v_item WHERE key = 'crontab:s'").fetchone()[0]
        self.assertIn("hunter2", stored)

    def test_existing_dir_not_loosened(self):
        out = Path(tempfile.mkdtemp()) / "keep"
        out.mkdir(mode=0o750)
        os.chmod(out, 0o750)
        markdown.write(self.conn, out)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o750)
