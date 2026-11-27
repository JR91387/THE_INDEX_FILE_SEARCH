# SPDX-License-Identifier: MIT
"""Build the Windows bundle (any OS, standard library only): Python's embeddable zip + THE INDEX + the-index.cmd.
Usage: build_windows.py (--embed-zip PATH | --download VERSION [--sha256 HEX]) [--out DIR] [--name NAME]"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FTP = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
TIMEOUT = 60
# The ._pth file already ignores PYTHONPATH, the registry and user site, and keeps the current directory off
# sys.path (https://docs.python.org/3/using/windows.html#finding-modules, and "_pth files" in
# https://docs.python.org/3/library/sys_path_init.html: isolated mode is enabled). So `-I` adds nothing: omitted.
CMD = '@echo off\r\n"%~dp0python\\python.exe" -m theindex %*\r\n'
README = """THE INDEX for Windows\r
\r
Unzip this folder anywhere, then in a terminal:\r
    the-index.cmd scan        build or refresh the catalog\r
    the-index.cmd status      show the front page\r
    the-index.cmd --help      all commands\r
\r
Nothing to install. Python (PSF license) is in python\\, THE INDEX is in lib\\.\r
"""


class Refuse(Exception):
    pass


def _get(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
        return resp.read()


def published_sha256(version):
    """SHA-256 python.org publishes for the embeddable zip: the SPDX file beside it on /ftp/ lists it."""
    url = FTP.format(v=version)
    try:
        doc = json.loads(_get(url + ".spdx.json"))
    except (OSError, ValueError) as exc:
        raise Refuse(f"no published hash for {version} ({exc}); pass --sha256") from None
    fname = url.rsplit("/", 1)[1]
    sums = [c for p in doc.get("packages", []) if p.get("packageFileName") == fname for c in p.get("checksums", [])]
    for entry in sums:
        if entry.get("algorithm") == "SHA256":
            return entry["checksumValue"].lower()
    raise Refuse(f"no SHA-256 published for {version}; pass --sha256")


def download(version, dest_dir, sha256=None):
    """Fetch the embeddable zip into dest_dir; refuse unless its SHA-256 matches. Returns the file path."""
    expected = (sha256 or published_sha256(version)).lower()
    data = _get(FTP.format(v=version))
    got = hashlib.sha256(data).hexdigest()
    if got != expected:
        raise Refuse(f"SHA-256 mismatch for {version}: expected {expected}, got {got}")
    path = Path(dest_dir) / f"python-{version}-embed-amd64.zip"
    path.write_bytes(data)
    return path


def _extract_python(embed_zip, target):
    with zipfile.ZipFile(embed_zip) as zf:
        names = zf.namelist()
        pths = [n for n in names if n.endswith("._pth") and "/" not in n]
        if "python.exe" not in names:
            raise Refuse("not an embeddable Python zip: no python.exe")
        if len(pths) != 1:
            raise Refuse(f"expected exactly one ._pth file, found {len(pths)}")
        zf.extractall(target)
    return target / pths[0]


def edit_pth(pth):
    """Keep the shipped lines (and `import site` as shipped, commented), add ..\\lib; written CRLF."""
    lines = pth.read_text().splitlines()
    if "..\\lib" not in lines:
        at = next((i for i, ln in enumerate(lines) if not ln.strip() or ln.startswith("#")), len(lines))
        lines.insert(at, "..\\lib")
    pth.write_bytes(("\r\n".join(lines) + "\r\n").encode())


def assemble(embed_zip, bundle):
    bundle.mkdir(parents=True)
    pth = _extract_python(embed_zip, bundle / "python")
    edit_pth(pth)
    shutil.copytree(ROOT / "src" / "theindex", bundle / "lib" / "theindex",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
    (bundle / "the-index.cmd").write_bytes(CMD.encode())
    (bundle / "README.txt").write_bytes(README.encode())


def zip_bundle(bundle, out_zip):
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle.rglob("*")):
            zf.write(path, path.relative_to(bundle.parent).as_posix())


def build(embed_zip, out_dir, name):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_zip = out_dir / f"{name}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        bundle = Path(tmp) / name
        assemble(embed_zip, bundle)
        zip_bundle(bundle, out_zip)
    return out_zip


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--embed-zip", help="Python embeddable zip already on disk")
    src.add_argument("--download", metavar="VERSION", help="fetch it from python.org, e.g. 3.12.8")
    ap.add_argument("--sha256", help="expected SHA-256 for --download (default: the one python.org publishes)")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--name", default="the-index-windows")
    args = ap.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            embed = args.embed_zip or download(args.download, tmp, args.sha256)
            print(build(embed, args.out, args.name))
    except (Refuse, OSError, zipfile.BadZipFile) as exc:
        print(f"build_windows: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
