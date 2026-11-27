# SPDX-License-Identifier: MIT
"""Single-file (.pyz) launch shim. Inside a zipapp, package files are not on disk, so the SQL, SVG and HTML
files and the collector scripts (run as `python -I <path>`) cannot be reached by path. On first run from a
.pyz the package is extracted once to a per-build cache dir, then imported from there. Normal installs never
take the extraction path: launch() only extracts when this module was loaded from a zip archive."""
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from . import __version__

PKG_NAME = "theindex"
PKG_PREFIX = PKG_NAME + "/"


def archive_path():
    """Path of the .pyz this module was loaded from, or None when running from a normal install."""
    return getattr(globals().get("__loader__"), "archive", None) or None


def cache_root():
    """XDG cache dir on Linux and macOS, %LOCALAPPDATA% on Windows."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "the-index"


def _build_id(zf):
    """Digest of every member name and CRC: a rebuilt .pyz with the same version gets a fresh cache dir."""
    digest = hashlib.sha256()
    for info in zf.infolist():
        digest.update(f"{info.filename}:{info.CRC}\n".encode())
    return digest.hexdigest()[:12]


def _ready(root):
    return (root / PKG_NAME / "__init__.py").is_file()


def _extract_into(zf, dest):
    for info in zf.infolist():
        if info.filename.startswith(PKG_PREFIX) and not info.is_dir():
            zf.extract(info, dest)


def ensure_extracted(archive):
    """Directory holding a real copy of the package for this archive; extracted at most once per build.
    The copy is written into a temp dir and moved into place with os.replace, so readers never see half a tree."""
    with zipfile.ZipFile(archive) as zf:
        target = cache_root() / f"{__version__}-{_build_id(zf)}"
        if _ready(target):
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=target.parent))
        try:
            _extract_into(zf, staging)
            os.replace(staging, target)
        except OSError:
            if not _ready(target):   # another process may have won the race; anything else is a real error
                raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return target


def activate(root):
    """Import the package from `root` from now on: drop the archive's copy from sys.modules, search root first."""
    for name in [n for n in sys.modules if n == PKG_NAME or n.startswith(PKG_PREFIX)]:
        del sys.modules[name]
    sys.path.insert(0, str(root))


def launch():
    """Entry point of the zipapp's __main__.py: extract and switch to the real files when running from a .pyz."""
    archive = archive_path()
    if archive:
        activate(ensure_extracted(archive))
    from theindex.cli import main
    raise SystemExit(main())
