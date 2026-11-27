# SPDX-License-Identifier: MIT
"""Albert plugin (Python interface 5.0): type `ix <words>` to find folders and documents in THE INDEX.

Written against the `albert.pyi` stub of albert-plugin-python (interface v5.0): a module with md_* metadata and a
class `Plugin(PluginInstance, GeneratorQueryHandler)` whose `items(context)` yields lists of StandardItem.
Not yet tried in a real Albert. Standard library only. It calls the installed `the-index` command, or the command
line in THE_INDEX_CMD (for example `python3 /opt/the-index.pyz --db /srv/data/index.db`). Names and titles are
shown as text, never run."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

from albert import (
    Action,
    GeneratorQueryHandler,
    Icon,
    PluginInstance,
    StandardItem,
    openFile,
    setClipboardText,
)

md_iid = "5.0"
md_version = "0.1"
md_name = "THE INDEX"
md_description = "Find folders and documents"
md_license = "MIT"
md_bin_dependencies = ["the-index"]

LIMIT = 20
TRIGGER = "ix "
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def command():
    """The-index argv prefix, or None when it cannot be found."""
    env = os.environ.get("THE_INDEX_CMD", "").strip()
    if env:
        return shlex.split(env)
    found = shutil.which("the-index")
    return [found] if found else None


def direct():
    """THE INDEX's own query layer when it is importable here (installed, or THE_INDEX_LIB = its src folder or
    .pyz): searches without starting a second process. None when not importable or THE_INDEX_CMD is set."""
    if os.environ.get("THE_INDEX_CMD", "").strip():
        return None
    lib = os.environ.get("THE_INDEX_LIB", "").strip()
    if lib and lib not in sys.path:
        sys.path.insert(0, lib)
    try:
        from theindex import config, db, query
        cfg = config.load(os.environ.get("THE_INDEX_CONFIG") or None)
    except (ImportError, OSError, ValueError):
        return None
    return lambda words: query.find(db.open(cfg.db_path), {"words": words, "limit": LIMIT})


def clean(text):
    return CONTROL.sub(" ", "" if text is None else str(text)).strip()


def size(n):
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def note(key, text, subtext=""):
    """A row that does nothing when chosen (hints, errors)."""
    return StandardItem(id=f"ix-{key}", text=text, subtext=subtext, icon_factory=lambda: Icon.theme("dialog-information"))


def actions(path):
    """Open (only where the path exists on this machine), Open containing folder, Copy path."""
    out = []
    if os.path.exists(path):
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        out += [Action("open", "Open", lambda p=path: openFile(p)),
                Action("folder", "Open containing folder", lambda p=folder: openFile(p))]
    return out + [Action("copy", "Copy path", lambda p=path: setClipboardText(p))]


def item(r):
    """One find result as an Albert row."""
    path = clean(r.get("path"))
    tail = "  [project]" if r.get("is_project") else ("  [offline]" if r.get("offline") else "")
    theme = "folder" if r.get("type") == "dir" else "text-x-generic"
    return StandardItem(id=f"ix:{clean(r.get('device'))}:{path}",
                        text=clean(r.get("title")) or clean(r.get("name")) or path,
                        subtext=f"{clean(r.get('device'))}:{path}  {size(r.get('size_bytes'))}{tail}",
                        icon_factory=lambda t=theme: Icon.theme(t), actions=actions(path))


def _via_cli(words, run):
    cmd = command()
    if cmd is None:
        return None
    try:
        proc = run([*cmd, "find", "--json", "--limit", str(LIMIT), "--", *words], capture_output=True,
                   text=True, encoding="utf-8", timeout=15)
        return json.loads(proc.stdout) if proc.returncode == 0 else {"error": proc.stderr.strip()}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def search(words, run=subprocess.run):
    """Rows for the words: results, or one note row for nothing found, a missing command or an error."""
    fast = direct()
    out = fast(words) if fast else _via_cli(words, run)
    if out is None:
        return [note("missing", "the-index command not found", "Install THE INDEX, or set THE_INDEX_CMD")]
    if out.get("error"):
        return [note("error", "THE INDEX could not search", clean(out["error"])[-200:])]
    rows = [item(r) for r in out.get("results", [])] or [note("none", "Nothing found", "Try fewer or shorter words")]
    if out.get("more"):
        rows.append(note("more", f"{out['more']} more", "Add words to narrow the search"))
    return rows


class Plugin(PluginInstance, GeneratorQueryHandler):
    def __init__(self):
        PluginInstance.__init__(self)
        GeneratorQueryHandler.__init__(self)

    def defaultTrigger(self):
        return TRIGGER

    def synopsis(self, query):
        return "words in a name, title or folder path"

    def items(self, context):
        words = context.query.split()
        if not words:
            yield [note("hint", "Type words to find folders and documents", "Names, titles and folder paths")]
            return
        if not context.isValid:
            return
        yield search(words)
