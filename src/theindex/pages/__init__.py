# SPDX-License-Identifier: MIT
"""Pages: one model built from the views, rendered to Markdown and one HTML file (HTML and a local server can follow)."""
from pathlib import Path

from . import html, markdown


def write_all(conn, out_dir):
    """Every page (the Markdown set and the_index.html) into out_dir, from one DB read each. Returns the directory."""
    out = markdown.write(conn, out_dir)
    html.write(conn, out)
    return Path(out)
