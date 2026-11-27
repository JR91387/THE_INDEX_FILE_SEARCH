# SPDX-License-Identifier: MIT
"""Render the page model to ONE self-contained the_index.html: inline CSS, JS and SVG, data as embedded JSON."""
import json
import re
from importlib import resources

from . import finder, markdown, model

NAME = "the_index.html"
ICON_TABLES = ("health", "change_class", "item_kind", "gap_kind")
XMLNS = re.compile(r'\s+xmlns="[^"]*"')
SLOT = "/*THE_INDEX_DATA*/"
FINDER_SLOT = "/*THE_INDEX_FINDER*/"


def icons(conn):
    """{table: {code: {svg, emoji}}} from v_ref_all. The xmlns attribute is dropped: inline SVG needs none.
    Only built-in icons (shipped, reset at every init) keep their svg; any other row falls back to its emoji,
    so a hand-edited icon can never put markup into the page."""
    builtin = {r[0] for r in conn.execute("SELECT code FROM ref_icon WHERE is_builtin = 1")}
    out = {t: {} for t in ICON_TABLES}
    marks = ",".join("?" * len(ICON_TABLES))
    sql = f"SELECT tbl, code, icon, svg, emoji FROM v_ref_all WHERE tbl IN ({marks}) ORDER BY tbl, code"
    for r in conn.execute(sql, ICON_TABLES).fetchall():
        svg = XMLNS.sub("", r["svg"]) if r["svg"] and r["icon"] in builtin else None
        out[r["tbl"]][r["code"]] = {"svg": svg, "emoji": r["emoji"]}
    return out


def embed(data):
    """JSON safe inside a script element: '<' can never open a tag or close the block."""
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render(conn, served=False, token=None):
    """The page. served=True (live server only) adds a flag that turns on the review control and docs links;
    token is the live server's API token (embedded so the page can send it back)."""
    template = resources.files("theindex.pages").joinpath("template.html").read_text(encoding="utf-8")
    data = {"model": markdown.redacted(model.build(conn)), "icons": icons(conn)}
    if served:
        data["served"] = True
        data["token"] = token
    else:
        data["finder"] = finder.index(conn)      # no server to ask: the page carries a small index of its own
    return template.replace(FINDER_SLOT, finder.script()).replace(SLOT, embed(data))


def write(conn, out_dir):
    """Write the_index.html into out_dir (created if needed); returns the file path."""
    path = markdown.private_dir(out_dir) / NAME
    markdown.write_atomic(path, render(conn))
    return path
