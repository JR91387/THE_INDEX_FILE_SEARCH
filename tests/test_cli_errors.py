# SPDX-License-Identifier: MIT
"""CLI behaviour at the edges: one-line errors, exit codes, declare withdraw, explicit config."""
import contextlib
import io
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import helpers  # noqa: F401  (puts src/ on the path)

from theindex import cli


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = str(self.dir / "i.db")


class TestCliBasics(CliCase):
    def test_withdraw_unknown_or_missing_id(self):
        for extra in (["--id", "999"], []):
            code, out, _ = run("--db", self.db, "declare", "withdraw", "--by", "alice", *extra)
            self.assertEqual((code, out.strip()), (1, "not found or not active"))

    def test_explicit_missing_config_is_an_error(self):
        code, _, err = run("--config", str(self.dir / "nope.toml"), "--db", self.db, "status")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error: config file not found"))
        self.assertEqual(err.count("\n"), 1)

    def test_missing_default_config_is_fine(self):
        with unittest.mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(self.dir / "none")}):
            self.assertEqual(run("--db", self.db, "status")[0], 0)


class TestConfigValidation(CliCase):
    def bad(self, text, needle):
        cfg = self.dir / "c.toml"
        cfg.write_text(text)
        code, _, err = run("--config", str(cfg), "--db", self.db, "status")
        self.assertEqual(code, 2, text)
        self.assertIn(needle, err)
        self.assertEqual(sum(l.startswith("error:") for l in err.splitlines()), 1)

    def test_bad_values_name_the_key(self):
        self.bad('[schedule]\nblackout = ["25:00-04:00"]', "schedule.blackout")
        self.bad('[schedule]\nblackout = ["02:30"]', "schedule.blackout")
        self.bad('[schedule]\nblackout = ["02:60-03:00"]', "schedule.blackout")
        self.bad('[schedule]\nblackout = "02:30-04:45"', "schedule.blackout")
        self.bad("[serve]\nport = 99999", "serve.port")
        self.bad('[serve]\nport = "http"', "serve.port")
        self.bad("[rules]\nfs_warn_pct = 500", "rules.fs_warn_pct")
        self.bad('[rules]\nemergency_after = "soon"', "rules.emergency_after")
        self.bad("[schedule]\ncollectors = 3", "schedule.collectors")

    def test_good_window_loads(self):
        cfg = self.dir / "c.toml"
        cfg.write_text('[schedule]\nblackout = ["23:30-04:45"]\n[serve]\nport = 9000')
        self.assertEqual(run("--config", str(cfg), "--db", self.db, "status")[0], 0)
