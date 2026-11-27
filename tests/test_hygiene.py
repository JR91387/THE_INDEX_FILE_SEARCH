# SPDX-License-Identifier: MIT
"""Repo hygiene: no environment-specific strings (generic patterns, plus an optional private denylist) and
the project's code-size limits: file <= 200 lines, function <= 50 lines, <= 4 params, nesting <= 3."""
import ast
import ipaddress
import os
import re
import subprocess
import unittest
from pathlib import Path

from helpers import ROOT

# Optional private list, one string per line, kept OUTSIDE the repo. Unset = only the generic checks run;
# set to a missing file = failure (a typo must not silently disable the check).
DENYLIST_ENV = os.environ.get("THE_INDEX_DENYLIST")
DENYLIST = Path(DENYLIST_ENV) if DENYLIST_ENV else ROOT / ".local_denylist"
SKIP_DIRS = {".git", "__pycache__", "build", "dist", ".claude", ".ruff_cache", ".venv", "node_modules"}
CODE = {".py", ".sql"}
SPDX = "SPDX-License-Identifier: MIT"
# Files exempt from the strict structure checks (name -> why). Keep this empty if you can.
STRUCTURE_SKIP = {}

IPV4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.]*\w)(?!\.\d)")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
HOME = re.compile(r"/home/([A-Za-z0-9_][\w.-]*)")
DOC_NETS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",
                                              "0.0.0.0/32")]
MAIL_OK = {"example.com", "example.org"}
MAIL_EXACT = {"noreply@anthropic.com"}


def repo_files():
    """Tracked plus untracked-not-ignored files (git), else a walk; only readable text files."""
    try:
        names = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                               capture_output=True, text=True, check=True, timeout=30).stdout.split("\n")
        paths = [ROOT / n for n in names if n]
    except (OSError, subprocess.SubprocessError):
        paths = [p for p in ROOT.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]
    return [p for p in paths if p.is_file() and not SKIP_DIRS & set(p.relative_to(ROOT).parts)]


def read_text(path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def leaks(text):
    """Strings that look like a real environment: public/private IPv4, a real e-mail, someone's /home folder."""
    found = []
    for m in IPV4.finditer(text):
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if not any(ip in net for net in DOC_NETS):
            found.append(m.group(1))
    for m in EMAIL.finditer(text):
        if m.group(1).lower() not in MAIL_OK and m.group(0).lower() not in MAIL_EXACT:
            found.append(m.group(0))
    found += [m.group(0) for m in HOME.finditer(text) if m.group(1) != "alice"]
    return found


def nesting(node, level=0):
    """Deepest chain of control statements below node (elif does not nest; nested defs are measured alone)."""
    deepest = level
    control = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)
    elif_of = node.orelse[0] if isinstance(node, ast.If) and len(node.orelse) == 1 else None
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(child, control) or hasattr(ast, "TryStar") and isinstance(child, ast.TryStar):
            deepest = max(deepest, nesting(child, level if child is elif_of else level + 1))
        else:
            deepest = max(deepest, nesting(child, level))
    return deepest


def param_count(fn):
    a = fn.args
    names = [x.arg for x in a.posonlyargs + a.args]
    count = len(names) - (1 if names and names[0] in {"self", "cls"} else 0)
    return count + len(a.kwonlyargs) + (a.vararg is not None) + (a.kwarg is not None)


def functions(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


class TestHygiene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = [(p, t) for p in repo_files() if (t := read_text(p)) is not None]
        cls.code = [p for p, _ in cls.files if p.suffix in CODE]

    def rel(self, path):
        return str(path.relative_to(ROOT))

    def test_denylist_if_configured(self):
        if DENYLIST_ENV and not DENYLIST.is_file():
            self.fail(f"THE_INDEX_DENYLIST points to a missing file: {DENYLIST}")
        if not DENYLIST.is_file():
            self.skipTest("no private denylist configured (the generic leak test still runs)")
        words = [w.strip().lower() for w in DENYLIST.read_text().splitlines() if w.strip() and not w.startswith("#")]
        hits = [(self.rel(p), w) for p, t in self.files if p != DENYLIST for w in words if w in t.lower()]
        self.assertEqual(hits, [])

    def test_no_generic_leaks(self):
        hits = [(self.rel(p), x) for p, t in self.files if p.name != "test_hygiene.py" for x in leaks(t)]
        self.assertEqual(hits, [])

    def test_leak_detector_catches_samples(self):
        bad = "host 10.1." + "2.3 bob@" + "corp.net /home/" + "bob/x"
        self.assertEqual(len(leaks(bad)), 3)
        good = "127.0.0.1 192.0.2.7 0.0.0.0 alice@example.com noreply@anthropic.com /home/alice/x v1.2.3 1.2.3.4.5"
        self.assertEqual(leaks(good), [])

    def test_file_length(self):
        long = [(self.rel(p), n) for p in self.code if (n := len(p.read_text(encoding="utf-8").splitlines())) > 200]
        self.assertEqual(long, [])

    def test_function_length_params_and_nesting(self):
        bad = []
        for path in (p for p in self.code if p.suffix == ".py" and self.rel(p) not in STRUCTURE_SKIP):
            for fn in functions(path):
                lines, params, depth = fn.end_lineno - fn.lineno + 1, param_count(fn), nesting(fn)
                if lines > 50 or params > 4 or depth > 3:
                    bad.append(f"{self.rel(path)}:{fn.name} lines={lines} params={params} nesting={depth}")
        self.assertEqual(bad, [])

    def test_spdx_header(self):
        missing = [self.rel(p) for p, t in self.files if p.suffix in CODE | {".sh"} and SPDX not in t[:300]]
        self.assertEqual(missing, [])

    def test_no_dependencies(self):
        import tomllib
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project.get("dependencies"), [])
