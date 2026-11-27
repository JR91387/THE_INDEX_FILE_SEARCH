# SPDX-License-Identifier: MIT
"""Build the single-file program dist/the-index.pyz (standard library only).
Usage: python3 tools/build_zipapp.py [output.pyz]. Run it as: python3 dist/the-index.pyz scan"""
import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTERPRETER = "/usr/bin/env python3"
MAIN = "from theindex._zipapp import launch\n\nlaunch()\n"
DEFAULT_OUT = ROOT / "dist" / "the-index.pyz"


def stage(staging):
    """Copy the package and write the archive's __main__.py into the staging dir."""
    shutil.copytree(ROOT / "src" / "theindex", staging / "theindex",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (staging / "__main__.py").write_text(MAIN)


def build(out=DEFAULT_OUT):
    """Write the .pyz to `out` (parent dirs created) and return its path."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "app"
        staging.mkdir()
        stage(staging)
        zipapp.create_archive(staging, out, interpreter=INTERPRETER, compressed=True)
    return out


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    print(build(args[0] if args else DEFAULT_OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
