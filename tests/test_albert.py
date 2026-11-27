# SPDX-License-Identifier: MIT
"""contrib/albert: the plugin against a stand-in `albert` module that mimics the documented v5.0 surface
(albert.pyi of albert-plugin-python). Not yet tried in a real Albert."""
import importlib.util
import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT

PLUGIN = ROOT / "contrib" / "albert" / "__init__.py"
CALLS = []


def stub():
    """The part of albert.pyi the plugin uses: signatures as documented, behaviour recorded."""
    m = types.ModuleType("albert")

    class Action:
        def __init__(self, id, text, callable):
            self.id, self.text, self.callable = id, text, callable

    class StandardItem:
        FIELDS = ("id", "text", "subtext", "icon_factory", "actions", "input_action_text")    # as in albert.pyi

        def __init__(self, **kw):
            assert set(kw) <= set(self.FIELDS), kw
            for name in self.FIELDS:
                setattr(self, name, kw.get(name))
            self.actions = self.actions or []

    class Icon:
        theme = staticmethod(lambda name: ("theme", name))

    class PluginInstance:
        def __init__(self):
            pass

    class GeneratorQueryHandler:
        def __init__(self):
            pass

    m.Action, m.StandardItem, m.Icon = Action, StandardItem, Icon
    m.PluginInstance, m.GeneratorQueryHandler = PluginInstance, GeneratorQueryHandler
    m.openFile = lambda path: CALLS.append(("open", path))
    m.setClipboardText = lambda text: CALLS.append(("copy", text))
    return m


def load():
    with mock.patch.dict(sys.modules, {"albert": stub()}):
        spec = importlib.util.spec_from_file_location("albert_plugin", PLUGIN)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


plugin = load()


class Ctx:
    def __init__(self, query, valid=True):
        self.query, self.isValid, self.trigger = query, valid, "ix "


def recorded(results, more=0, code=0, err=""):
    out = json.dumps({"schema_version": 1, "query": {"words": ["x"]}, "results": results, "more": more})
    return lambda argv, **kw: subprocess.CompletedProcess(argv, code, out if code == 0 else "", err)


class AlbertPluginTest(unittest.TestCase):
    def setUp(self):
        CALLS.clear()
        patcher = mock.patch.dict(os.environ, {"THE_INDEX_CMD": "the-index"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_metadata_and_class_shape(self):
        self.assertEqual((plugin.md_iid, plugin.md_name), ("5.0", "THE INDEX"))
        self.assertTrue(plugin.md_version and plugin.md_description)
        p = plugin.Plugin()
        self.assertEqual(p.defaultTrigger(), "ix ")
        self.assertEqual([b.__name__ for b in plugin.Plugin.__bases__], ["PluginInstance", "GeneratorQueryHandler"])

    def test_local_result_has_open_folder_copy_remote_only_copy(self):
        here = str(PLUGIN)
        hits = [{"type": "file", "device": "host-a", "path": here, "name": "__init__.py", "title": "Garden\nplan",
                 "size_bytes": 2048, "is_project": False, "offline": False},
                {"type": "dir", "device": "host-b", "path": "/srv/data/gone", "name": "gone", "title": None,
                 "size_bytes": 10, "is_project": False, "offline": True}]
        rows = plugin.search(["garden"], recorded(hits, more=3))
        self.assertEqual(rows[0].text, "Garden plan")                    # control characters never reach Albert
        self.assertIn("2.0 KB", rows[0].subtext)
        self.assertEqual([a.id for a in rows[0].actions], ["open", "folder", "copy"])
        for a in rows[0].actions:
            a.callable()
        self.assertEqual(CALLS, [("open", here), ("open", str(PLUGIN.parent)), ("copy", here)])
        self.assertEqual([a.id for a in rows[1].actions], ["copy"])
        self.assertIn("[offline]", rows[1].subtext)
        self.assertEqual(rows[1].icon_factory(), ("theme", "folder"))
        self.assertEqual(rows[2].text, "3 more")

    def test_words_are_passed_after_double_dash(self):
        seen = []
        run = recorded([])
        plugin.search(["--json", "x"], lambda argv, **kw: seen.append(argv) or run(argv, **kw))
        self.assertEqual(seen[0], ["the-index", "find", "--json", "--limit", "20", "--", "--json", "x"])

    def test_nothing_failed_and_missing_command(self):
        self.assertEqual(plugin.search(["x"], recorded([]))[0].text, "Nothing found")
        rows = plugin.search(["x"], recorded([], code=2, err="no database at /x"))
        self.assertEqual(rows[0].subtext, "no database at /x")
        with mock.patch.dict(os.environ, {"THE_INDEX_CMD": ""}), mock.patch.object(plugin.shutil, "which",
                                                                                     return_value=None), \
                mock.patch.object(plugin, "direct", return_value=None):
            self.assertIn("not found", plugin.search(["x"])[0].text)

    def test_items_generator(self):
        p = plugin.Plugin()
        self.assertIn("Type words", next(p.items(Ctx("  ")))[0].text)
        self.assertEqual(list(p.items(Ctx("x", valid=False))), [])
        with mock.patch.object(plugin, "search", return_value=["row"]) as s:
            self.assertEqual(next(p.items(Ctx("a  b"))), ["row"])
        s.assert_called_once_with(["a", "b"])

    def test_real_cli_round_trip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"
            env = {"PYTHONPATH": str(ROOT / "src"), "THE_INDEX_CMD": f"{sys.executable} -m theindex --db {db}"}
            subprocess.run([sys.executable, "-m", "theindex", "--db", str(db), "status"],
                           env={**os.environ, **env}, capture_output=True, check=False)
            with mock.patch.dict(os.environ, env):
                rows = plugin.search(["zzz"])
        self.assertEqual(rows[0].text, "Nothing found")
