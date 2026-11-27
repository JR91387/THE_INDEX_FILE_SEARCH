# SPDX-License-Identifier: MIT
"""contrib/flow_launcher: Flow Launcher JSON-RPC replies, from recorded `find --json` output and one real run."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT

PLUGIN = ROOT / "contrib" / "flow_launcher"
spec = importlib.util.spec_from_file_location("flow_main", PLUGIN / "main.py")
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)


def recorded(results, more=0, code=0, err=""):
    out = json.dumps({"schema_version": 1, "query": {"words": ["x"]}, "results": results, "more": more})
    return lambda argv, **kw: subprocess.CompletedProcess(argv, code, out if code == 0 else "", err)


def request(method, *params):
    return ["main.py", json.dumps({"method": method, "parameters": list(params)})]


class FlowLauncherTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"THE_INDEX_CMD": "the-index"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_manifest(self):
        m = json.loads((PLUGIN / "plugin.json").read_text())
        self.assertEqual((m["Language"], m["ExecuteFileName"], m["ActionKeyword"]), ("python", "main.py", "ix"))
        self.assertEqual(len(m["ID"]), 32)
        self.assertTrue((PLUGIN / m["IcoPath"]).read_bytes().startswith(b"\x89PNG"))

    def test_local_result_opens_remote_does_not(self):
        here = str(PLUGIN / "main.py")
        hits = [{"type": "file", "device": "host-a", "path": here, "name": "main.py", "title": "Garden\nplan",
                 "size_bytes": 2048, "is_project": False, "offline": False},
                {"type": "file", "device": "host-b", "path": "/srv/data/gone.pdf", "name": "gone.pdf",
                 "title": None, "size_bytes": 10, "is_project": False, "offline": True}]
        rows = flow.main(request("query", "garden plan"), recorded(hits, more=3))["result"]
        self.assertEqual(rows[0]["Title"], "Garden plan")             # control characters never reach Flow
        self.assertEqual(rows[0]["JsonRPCAction"], {"method": "open", "parameters": [here]})
        self.assertIn("2.0 KB", rows[0]["SubTitle"])
        self.assertNotIn("JsonRPCAction", rows[1])
        self.assertIn("[offline]", rows[1]["SubTitle"])
        self.assertEqual(rows[2]["Title"], "3 more")

    def test_words_are_passed_after_double_dash(self):
        seen = []
        run = recorded([])
        flow.query("--json x", lambda argv, **kw: seen.append(argv) or run(argv, **kw))
        self.assertEqual(seen[0][-3:], ["--", "--json", "x"])

    def test_empty_missing_failed_and_nothing(self):
        self.assertIn("Type words", flow.query("  ")[0]["Title"])
        self.assertEqual(flow.query("x", recorded([], code=2, err="no database at /x"))[0]["SubTitle"],
                         "no database at /x")
        self.assertEqual(flow.query("x", recorded([]))[0]["Title"], "Nothing found")
        with mock.patch.dict(os.environ, {"THE_INDEX_CMD": ""}), mock.patch.object(flow.shutil, "which",
                                                                                     return_value=None), \
                mock.patch.object(flow, "direct", return_value=None):
            self.assertIn("not found", flow.query("x")[0]["Title"])

    def test_context_menu_and_open(self):
        menu = flow.main(request("context_menu", str(PLUGIN / "main.py")))["result"]
        self.assertEqual(menu[0]["JsonRPCAction"]["parameters"], [str(PLUGIN)])
        self.assertEqual(flow.main(request("context_menu", "")), {"result": []})
        with mock.patch.object(flow, "open_path") as opened:
            self.assertIsNone(flow.main(request("open", "/srv/data")))
        opened.assert_called_once_with("/srv/data")

    def test_real_cli_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
                   "THE_INDEX_CMD": f"{sys.executable} -m theindex --db {db}"}
            subprocess.run([sys.executable, "-m", "theindex", "--db", str(db), "status"], env=env,
                           capture_output=True, check=False)
            out = subprocess.run([sys.executable, "-I", str(PLUGIN / "main.py"), request("query", "zzz")[1]],
                                 env=env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout)["result"][0]["Title"], "Nothing found")


class DirectTest(unittest.TestCase):
    def test_in_process_search_when_importable(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
                "THE_INDEX_CMD": "", "THE_INDEX_LIB": str(ROOT / "src"), "XDG_DATA_HOME": tmp,
                "XDG_CONFIG_HOME": tmp}):
            fast = flow.direct()
            self.assertIsNotNone(fast)
            self.assertEqual(flow.query("zzz", run=None)[0]["Title"], "Nothing found")   # run=None: no process

    def test_cmd_wins_over_direct(self):
        with mock.patch.dict(os.environ, {"THE_INDEX_CMD": "the-index"}):
            self.assertIsNone(flow.direct())
