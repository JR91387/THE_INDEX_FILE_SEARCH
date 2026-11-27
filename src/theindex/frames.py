# SPDX-License-Identifier: MIT
"""Framing for `collect --out -`: per payload one line `#the-index-payload <name> <bytes>` then the raw bytes.

The member writes with the normal collect code into a temp folder and streams each file; stdout carries nothing
else. The hub side (`pull.py`) reads the frames back with `read_header`."""
import sys
import tempfile
from pathlib import Path

from . import member

MARK = "#the-index-payload"


def header(name, size):
    return f"{MARK} {name} {size}\n".encode()


def read_header(line):
    """(name, size) from a frame header line (bytes). Raises ValueError."""
    parts = line.decode("utf-8", "replace").rstrip("\r\n").split(" ")
    if len(parts) != 3 or parts[0] != MARK or not parts[2].isdigit():
        raise ValueError("bad frame header")
    return parts[1], int(parts[2])


def stream_collect(cfg, only, out=None):
    """Collect into a temp folder, then write every payload as a frame to `out` (default: binary stdout)."""
    out = out or sys.stdout.buffer
    with tempfile.TemporaryDirectory(prefix="the-index-out-") as tmp:
        for path in member.run(cfg, tmp, only):
            path = Path(path)
            out.write(header(path.name, path.stat().st_size))
            out.write(path.read_bytes())
        out.flush()
    return 0
