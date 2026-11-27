# SPDX-License-Identifier: MIT
"""Shared test helpers: a temp database and synthetic collector payloads (no real hosts or paths)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from theindex import db


class DbCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "index.db"
        self.conn = db.init(self.path)
        self.addCleanup(self.conn.close)

    def one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()[0]


def job(key, command="/usr/bin/true", **metrics):
    return {"kind": "job", "key": key, "attrs": {"command": command, "run_as": "alice", "schedule": "0 1 * * *"},
            "metrics": metrics}


def payload(items, status="ok", coverage=("crontab:",), gaps=()):
    return {"collector": "jobs", "kinds": ["job"], "status": status, "items": list(items),
            "coverage": list(coverage), "gaps": list(gaps), "errors": [],
            "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:00:05Z"}
