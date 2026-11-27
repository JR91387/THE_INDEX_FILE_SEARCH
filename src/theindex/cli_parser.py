# SPDX-License-Identifier: MIT
"""argparse with a quicker start: on Python 3.14 every parser builds a help formatter, which imports the colour
theme (`_colorize`, ~13 ms with `dataclasses` and `inspect`) and `shutil` (~4 ms) even when no help is printed.
Here help is plain text and neither is imported. Output is the same, without colour."""
import argparse
import os
import sys


def _width():
    try:
        return int(os.environ.get("COLUMNS") or os.get_terminal_size(sys.stdout.fileno()).columns) - 2
    except (OSError, ValueError):
        return 78


class QuickFormatter(argparse.HelpFormatter):
    def __init__(self, prog, **kw):
        kw["width"] = kw.get("width") or _width()
        super().__init__(prog, **kw)

    def _set_color(self, color):
        self._theme, self._decolor = _NoColor(), str         # plain text, without importing the theme module


class _NoColor:
    """Stands in for argparse's colour theme: every colour code is the empty string."""

    def __getattr__(self, name):
        return ""


class Parser(argparse.ArgumentParser):
    """Subparsers inherit this class (argparse uses type(self)), so they get the quick formatter too."""

    def __init__(self, *args, **kw):
        kw.setdefault("formatter_class", QuickFormatter)
        if sys.version_info >= (3, 14):
            kw.setdefault("color", False)
        super().__init__(*args, **kw)
