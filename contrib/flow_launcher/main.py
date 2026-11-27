# SPDX-License-Identifier: MIT
"""Flow Launcher plugin: type `ix <words>` to find folders and documents in THE INDEX.

Flow runs this file with one JSON-RPC request in argv[1] and reads one JSON reply on stdout. Standard library
only. It calls the installed `the-index` command, or the command line in THE_INDEX_CMD (for example
`py C:\\Tools\\the-index.pyz --db D:\\index.db`). Names and titles are shown as text, never run."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

ICON = "icon.png"
LIMIT = 20
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def command():
    """The-index argv prefix, or None when it cannot be found."""
    env = os.environ.get("THE_INDEX_CMD", "").strip()
    if env:
        return shlex.split(env, posix=os.name != "nt")
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


def note(title, sub=""):
    return {"Title": title, "SubTitle": sub, "IcoPath": ICON}


def item(r):
    """One find result as a Flow row. Enter opens it only when the path exists on this machine."""
    path = clean(r.get("path"))
    where = f"{clean(r.get('device'))}:{path}"
    tail = "  [project]" if r.get("is_project") else ("  [offline]" if r.get("offline") else "")
    row = note(clean(r.get("title")) or clean(r.get("name")) or path, f"{where}  {size(r.get('size_bytes'))}{tail}")
    if path and os.path.exists(path):
        row["JsonRPCAction"] = {"method": "open", "parameters": [path]}
        row["ContextData"] = path
    return row


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


def query(text, run=subprocess.run):
    words = text.split()
    if not words:
        return [note("Type words to find folders and documents", "Names, titles and folder paths")]
    fast = direct()
    out = fast(words) if fast else _via_cli(words, run)
    if out is None:
        return [note("the-index command not found", "Install THE INDEX, or set THE_INDEX_CMD")]
    if out.get("error"):
        return [note("THE INDEX could not search", clean(out["error"])[-200:])]
    rows = [item(r) for r in out.get("results", [])] or [note("Nothing found", "Try fewer or shorter words")]
    if out.get("more"):
        rows.append(note(f"{out['more']} more", "Add words to narrow the search"))
    return rows


def context_menu(path):
    if not path:
        return []
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    return [{**note("Open containing folder", folder), "JsonRPCAction": {"method": "open", "parameters": [folder]}}]


def open_path(path):
    if hasattr(os, "startfile"):
        os.startfile(path)                   # Windows: the file's default app, or Explorer for a folder
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


def main(argv, run=subprocess.run):
    """Handle one request; returns the reply dict (query, context_menu) or None (open)."""
    req = json.loads(argv[1]) if len(argv) > 1 else {"method": "query", "parameters": [""]}
    method, params = req.get("method", "query"), req.get("parameters") or [""]
    if method == "query":
        return {"result": query(str(params[0]), run)}
    if method == "context_menu":
        return {"result": context_menu(params[0] if params else "")}
    if method == "open":
        open_path(params[0])
    return None


if __name__ == "__main__":
    reply = main(sys.argv)
    if reply is not None:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(reply, ensure_ascii=False))
