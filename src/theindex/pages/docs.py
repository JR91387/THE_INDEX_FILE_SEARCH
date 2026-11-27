# SPDX-License-Identifier: MIT
"""Tiny Markdown-to-HTML for the docs/*.md files, used only by `serve`. Text is always escaped."""
import html
import json
import re
from importlib import resources
from pathlib import Path

from . import finder

NAME = re.compile(r"^[A-Z_]+\.md$")
CODE = re.compile(r"`([^`]+)`")
STYLE = ("body{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:0 auto;padding:16px}"
         "pre{background:#8881;padding:8px;overflow-x:auto}table{border-collapse:collapse}"
         "td,th{border:1px solid #8886;padding:3px 8px}")


def docs_dir():
    """The shipped docs folder, else the repo's docs/ next to src/; None when neither exists."""
    for path in (Path(str(resources.files("theindex"))) / "docs", Path(__file__).resolve().parents[3] / "docs"):
        if path.is_dir():
            return path
    return None


def names():
    folder = docs_dir()
    return sorted(p.name for p in folder.glob("*.md") if NAME.match(p.name)) if folder else []


def read(name):
    """Text of one doc, or None for an unknown or unsafe name."""
    folder = docs_dir()
    if folder is None or not NAME.match(name or "") or not (folder / name).is_file():
        return None
    return (folder / name).read_text(encoding="utf-8")


def inline(text):
    return CODE.sub(lambda m: f"<code>{m.group(1)}</code>", html.escape(text, quote=False))


def _table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not re.match(r"^\|?[\s:|-]+$", r)]
    body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in cells)
    return f"<table>{body}</table>"


def convert(text):
    """Headings, lists, code fences, tables and paragraphs; everything else is a paragraph."""
    out, lines, i, in_list = [], text.splitlines(), 0, False
    while i < len(lines):
        line = lines[i]
        i += 1
        if in_list and not line.startswith(("- ", "* ")):
            out.append("</ul>")
            in_list = False
        if line.startswith("```"):
            block = []
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append("<pre>" + html.escape("\n".join(block), quote=False) + "</pre>")
        elif line.startswith("|"):
            rows = [line]
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
        elif m := re.match(r"^(#{1,6})\s+(.*)", line):
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
        elif line.startswith(("- ", "* ")):
            out.append("" if in_list else "<ul>")
            in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    return "\n".join(out + (["</ul>"] if in_list else []))


def page(title, body, token=""):
    home = f"/?t={token}" if token else "/"
    boot = json.dumps({"served": True, "token": token}).replace("<", "\\u003c")
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f'<style>{STYLE}</style></head><body><p><a href="{home}">THE INDEX</a></p>{body}'
            f'<script>{finder.script()}\ntheIndexFinder({boot});</script></body></html>')
