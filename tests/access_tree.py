# SPDX-License-Identifier: MIT
"""A reusable tree of awkward things to index: documents that work, documents that are broken or lie about their
type, odd names, links and pipes, and things we are not allowed to read. Everything is generated (git cannot hold
permissions, pipes or non-UTF-8 names), seeded, and generic. Each case says what a scan must record for it.

    python3 tests/access_tree.py OUT_DIR      # build it to look at or scan by hand (prints the cases)

Add a case: one CASES line (relative path, maker, expectation, needs). Expectation: Want(listed, title), where
title ANY means "any title or none, as long as nothing breaks". Remove the tree with `chmod -R u+rwx` first."""
import os
import random
import stat
import sys
import zipfile
from pathlib import Path
from typing import NamedTuple

ANY = object()
DC = 'xmlns:dc="http://purl.org/dc/elements/1.1/"'
CORE = f'<cp:coreProperties {DC} xmlns:cp="x"><dc:title>{{}}</dc:title><dc:creator>Alice</dc:creator></cp:coreProperties>'
ODF = f'<office:document-meta xmlns:office="o" {DC}><office:meta><dc:title>{{}}</dc:title></office:meta></office:document-meta>'
CONTAINER = '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>'
OPF = f'<package {DC}><metadata><dc:title>{{}}</dc:title></metadata></package>'


class Want(NamedTuple):
    listed: bool
    title: object = None


class Case(NamedTuple):
    rel: str            # path below the root, as the index should store it
    make: object        # make(path)
    want: Want
    needs: str = ""     # "posix" (permissions, pipes), "bytes" (non-UTF-8 names), "" (anywhere)


def text(body, encoding="utf-8"):
    return lambda p: p.write_bytes(body.encode(encoding) if isinstance(body, str) else body)


def zipped(members):
    def make(p):
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, body in members.items():
                zf.writestr(name, body)
    return make


def truncated(members):
    def make(p):
        zipped(members)(p)
        p.write_bytes(p.read_bytes()[: p.stat().st_size // 2])
    return make


def noise(size, seed):
    return text(random.Random(seed).randbytes(size))


def pdf(info):
    return text(b"%PDF-1.4\n1 0 obj\n<< /Producer (t) " + info + b" >>\nendobj\n%%EOF\n")


def chmod(maker, mode):
    def make(p):
        maker(p)
        p.chmod(mode)
    return make


def link(target):
    return lambda p: p.symlink_to(target)


def fifo(p):
    os.mkfifo(p)


def folder(mode, inside):
    def make(p):
        p.mkdir()
        (p / inside).write_text("# Inside\n")
        p.chmod(mode)
    return make


def bytes_name(p):
    raw = os.path.join(os.fsencode(p.parent), b"bad\xffname.md")
    with open(raw, "wb") as fh:
        fh.write(b"# Odd name\n")


DOCX = {"docProps/core.xml": CORE.format("Quarterly report")}
CASES = [
    # works: real documents, each with a title the index should find
    Case("works/note.md", text("# Garden notes\nbody\n"), Want(True, "Garden notes")),
    Case("works/front.md", text("---\ntitle: Seed plan\nauthor: Alice\ntags: [seeds, spring]\n---\nx\n"),
         Want(True, "Seed plan")),
    Case("works/page.html", text("<html lang=en><head><title>Tool shed</title></head></html>"), Want(True, "Tool shed")),
    Case("works/report.docx", zipped(DOCX), Want(True, "Quarterly report")),
    Case("works/budget.xlsx", zipped({"docProps/core.xml": CORE.format("Garden budget")}), Want(True, "Garden budget")),
    Case("works/minutes.odt", zipped({"meta.xml": ODF.format("Club minutes")}), Want(True, "Club minutes")),
    Case("works/book.epub", zipped({"META-INF/container.xml": CONTAINER, "OEBPS/c.opf": OPF.format("Sea book")}),
         Want(True, "Sea book")),
    Case("works/paper.pdf", pdf(b"/Title (Soil paper) /Author (Alice)"), Want(True, "Soil paper")),
    Case("works/bom.md", text(b"\xef\xbb\xbf# With BOM\n"), Want(True, "With BOM")),
    Case("works/plain.txt", text("just text\n"), Want(True)),
    Case("works/photo.jpg", text(b"\xff\xd8\xff\xe0" + bytes(60)), Want(True)),
    Case("works/empty.md", text(b""), Want(True)),
    # broken: damaged, empty or mislabelled documents; listed by name, never stop the run
    Case("broken/truncated.docx", truncated(DOCX), Want(True)),
    Case("broken/not_a_zip.docx", text(b"PK\x03\x04 not really a zip"), Want(True)),
    Case("broken/no_core.docx", zipped({"word/document.xml": "<w/>"}), Want(True)),
    Case("broken/bad_xml.docx", zipped({"docProps/core.xml": "<cp:coreProperties><dc:title>Cut"}), Want(True)),
    Case("broken/entities.docx", zipped({"docProps/core.xml": f'<!DOCTYPE x [<!ENTITY a "b">]><cp {DC}>'
                                         "<dc:title>&a;</dc:title></cp>"}), Want(True)),
    Case("broken/epub_no_opf.epub", zipped({"META-INF/container.xml": CONTAINER}), Want(True)),
    Case("broken/random.epub", noise(300, 1), Want(True)),
    Case("broken/garbage.pdf", text(b"%PDF-1.4 garbage"), Want(True)),
    Case("broken/cut.pdf", text(b"%PDF-1.4\n1 0 obj\n<< /Title (Cut sho"), Want(True, ANY)),
    Case("broken/binary.md", noise(500, 2), Want(True, ANY)),
    Case("broken/utf16.md", text("# Wide text\n", "utf-16"), Want(True, ANY)),
    Case("broken/docx_named.pdf", zipped(DOCX), Want(True)),
    Case("broken/zero.docx", text(b""), Want(True)),
    # names: unusual but legal names, each listed as it is
    Case("names/café ☕ notes.md", text("# Coffee\n"), Want(True, "Coffee")),
    Case("names/with space (1).txt", text("x"), Want(True)),
    Case("names/-leading-dash.md", text("# Dash\n"), Want(True, "Dash")),
    Case("names/.hidden.md", text("# Hidden dot\n"), Want(True, "Hidden dot")),
    Case("names/" + "long_" * 49 + "end.txt", text("x"), Want(True)),
    Case("names/new\nline.md", text("# Newline\n"), Want(True, "Newline"), "posix"),
    Case("names/bad�name.md", bytes_name, Want(True), "bytes"),   # stored name is not the real one: so no title
    # special: entries that are not plain files; skipped quietly
    Case("special/broken_link.md", link("/nonexistent/target.md"), Want(False), "posix"),
    Case("special/link_to_note.md", link("../works/note.md"), Want(False), "posix"),
    Case("special/loop", link(".."), Want(False), "posix"),
    Case("special/pipe.md", fifo, Want(False), "posix"),
    # access: what we may not read; listed by name where the name is visible
    Case("access/locked_file.md", chmod(text("# Locked\n"), 0), Want(True), "posix"),
    Case("access/locked_doc.docx", chmod(zipped(DOCX), 0), Want(True), "posix"),
    Case("access/write_only.md", chmod(text("# Write only\n"), stat.S_IWUSR), Want(True), "posix"),
    Case("access/names_only", folder(stat.S_IRUSR, "seen.md"), Want(True), "posix"),
    Case("access/names_only/seen.md", None, Want(True), "posix"),
    Case("access/no_list", folder(stat.S_IWUSR | stat.S_IXUSR, "unseen.md"), Want(False), "posix"),
    Case("access/no_list/unseen.md", None, Want(False), "posix"),
    Case("access/locked_dir", folder(0, "unseen.txt"), Want(False), "posix"),
    Case("access/locked_dir/unseen.txt", None, Want(False), "posix"),
]


def supported(needs):
    posix = sys.platform != "win32" and os.geteuid() != 0
    return {"": True, "posix": posix, "bytes": posix and sys.platform != "darwin"}[needs]


def build(root):
    """Make every supported case below root; returns the cases made (folder contents included)."""
    root, made = Path(root), []
    for case in (c for c in CASES if supported(c.needs)):
        path = root / case.rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if case.make:
            case.make(path)
        made.append(case)
    return made


def unlock(root):
    """Give the owner back every permission, so the tree can be deleted."""
    for dirpath, dirs, files in os.walk(root, topdown=True, onerror=None):
        for name in dirs + files:
            path = os.path.join(dirpath, name)
            if not os.path.islink(path):
                os.chmod(path, 0o700)


if __name__ == "__main__":
    if len(sys.argv) != 2 or (Path(sys.argv[1]).exists() and any(Path(sys.argv[1]).iterdir())):
        sys.exit("usage: access_tree.py OUT_DIR   (a new or empty folder)")
    for c in build(sys.argv[1]):
        print(f"{'listed' if c.want.listed else 'hidden'}  {c.rel!r}")
