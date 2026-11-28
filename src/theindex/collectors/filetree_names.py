# SPDX-License-Identifier: MIT
"""Names and output lines for the filetree walker and the native sources. Standalone, stdlib only.
A name that is not valid text (bytes that are not UTF-8 on Linux/macOS, an unpaired surrogate on Windows) must
never stop a run: it is written with U+FFFD in place of the bad part, so the file is still listed by name."""
import json
import sys
import time
import unicodedata
from datetime import UTC, datetime


def utc(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def case_insensitive():
    return sys.platform in ("win32", "darwin")


def path_key(path, ci):
    key = unicodedata.normalize("NFC", path).replace("\\", "/")
    return key.casefold() if ci else key


def text(value):
    """value with any undecodable part replaced by U+FFFD (valid strings come back unchanged)."""
    try:
        value.encode("utf-8")
        return value
    except UnicodeEncodeError:
        pass
    try:
        raw = value.encode("utf-8", "surrogateescape")      # Linux/macOS: the original bytes
    except UnicodeEncodeError:
        raw = value.encode("utf-8", "surrogatepass")        # Windows: an unpaired UTF-16 half
    return raw.decode("utf-8", "replace")


def _clean(obj):
    if isinstance(obj, str):
        return text(obj)
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def json_line(record):
    """One JSON line; a record holding a bad name is cleaned first (rare, so the common path stays one dumps)."""
    line = json.dumps(record, separators=(",", ":"))
    return json.dumps(_clean(record), separators=(",", ":")) if "\\ud" in line else line
