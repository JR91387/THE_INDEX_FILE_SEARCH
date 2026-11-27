# SPDX-License-Identifier: MIT
"""The Ctrl-K finder: the small search index embedded in a page that is opened as a file, and the script itself."""
import json
from importlib import resources

FOLDERS, PROJECTS, FILES = 2000, 500, 2500
MAX_ROWS, MAX_BYTES, MAX_TITLE = 5000, 600_000, 120
PROJECT_SQL = f"SELECT device, path FROM v_projects ORDER BY mtime_ns IS NULL, mtime_ns DESC, path LIMIT {PROJECTS}"
FOLDER_SQL = f"SELECT device, path FROM v_dirs ORDER BY coalesce(size_total, -1) DESC, path LIMIT {FOLDERS}"
FILE_SQL = ("SELECT device, path, name, title FROM v_files WHERE coalesce(title, '') <> '' "
            f"ORDER BY mtime_ns IS NULL, mtime_ns DESC, path LIMIT {FILES}")


def script():
    """The finder JavaScript: defines theIndexFinder(data), which wires the keys and the overlay."""
    return resources.files("theindex.pages").joinpath("finder.js").read_text(encoding="utf-8")


def _base(path):
    return path.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or path


def _cost(row):
    """Bytes the row takes in the page (every '<' becomes six characters when embedded)."""
    text = json.dumps(row, ensure_ascii=False)
    return len(text.encode()) + 1 + 5 * text.count("<")


def index(conn):
    """Rows [type, device, path, name, title]: type p(roject), d(ir) or f(ile); projects first, then the biggest
    folders, then the newest titled documents. Capped at MAX_ROWS rows and MAX_BYTES bytes (documents go first)."""
    rows, seen, used = [], set(), 2
    sources = ((PROJECT_SQL, "p"), (FOLDER_SQL, "d"), (FILE_SQL, "f"))
    for sql, kind in sources:
        for r in conn.execute(sql).fetchall():
            if (kind != "f" and (r["device"], r["path"]) in seen) or len(rows) >= MAX_ROWS:
                continue
            row = [kind, r["device"], r["path"], r["name"] if kind == "f" else _base(r["path"]),
                   (r["title"] or "")[:MAX_TITLE] if kind == "f" else ""]
            used += _cost(row)
            if used > MAX_BYTES:
                return rows
            seen.add((r["device"], r["path"]))
            rows.append(row)
    return rows
