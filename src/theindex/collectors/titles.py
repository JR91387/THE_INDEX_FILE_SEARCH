# SPDX-License-Identifier: MIT
"""Title collector: `titles.py --worklist FILE '<options JSON>'` prints one JSON line per file.

Standalone apart from two sibling modules in the same directory. Reads at most 64 KB per file, never
stores body text, and never raises for a bad file (title null, counted in the trailer).
"""
import html.parser
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import titles_meta
import titles_pdf
import titles_zip

READ_BYTES = 65536
READERS = {".md": "md", ".markdown": "md", ".html": "html", ".htm": "html", ".docx": "ooxml",
           ".xlsx": "ooxml", ".pptx": "ooxml", ".odt": "odf", ".ods": "odf", ".odp": "odf",
           ".epub": "epub", ".pdf": "pdf"}
JUNK = re.compile(r"^Microsoft (Word|Excel|PowerPoint) - ", re.IGNORECASE)
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)\s*$")


def clean(title, path):
    """Normalise a raw title; None when empty, 'untitled' or just the file name."""
    if not title:
        return None
    text = " ".join(CONTROL.sub(" ", title).split())
    text = JUNK.sub("", text).strip()[:300].strip()
    name = os.path.basename(path).lower()
    if not text or text.lower() == "untitled" or text.lower() in (name, os.path.splitext(name)[0]):
        return None
    return text


def read_head(path):
    with open(path, "rb") as fh:
        return fh.read(READ_BYTES).decode("utf-8", "replace").lstrip("﻿")


def split_front(lines):
    """(front matter lines or None, index of the first body line) for a document that may start with '---'."""
    if not lines or lines[0].rstrip() != "---":
        return None, 0
    for i, line in enumerate(lines[1:], 1):
        if line.rstrip() in ("---", "..."):
            return lines[1:i], i + 1
    return None, 0


def front_matter(lines):
    """(title or None, index of the first body line) for a document that may start with '---'."""
    block, start = split_front(lines)
    return (fm_title(block) if block is not None else None), start


def fm_title(lines):
    for line in lines:
        m = re.match(r"title:[ \t]*(.*)$", line.rstrip())
        if not m:
            continue
        val = m.group(1).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            return val[1:-1].replace('\\"', '"') if val[0] == '"' else val[1:-1]
        val = re.split(r"\s#", val)[0].strip()
        return val if val and val[0] not in "|>[{&*!" else None
    return None


def first_heading(lines):
    fence = None
    for line in lines:
        mark = line.lstrip()[:3]
        if mark in ("```", "~~~"):
            fence = None if fence == mark else (fence or mark)
            continue
        m = None if fence else HEADING.match(line)
        if m:
            return re.sub(r"\s+#+$", "", m.group(1))
    return None


def md_title(path):
    """(title, src, meta)."""
    lines = read_head(path).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    block, start = split_front(lines)
    meta = titles_meta.fm_meta(block) if block is not None else {}
    title = fm_title(block) if block is not None else None
    if title:
        return title, "md_front", meta
    heading = first_heading(lines[start:])
    return (heading, "md_heading", meta) if heading else (None, None, meta)


class TitleParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside, self.done, self.parts, self.raw = False, False, [], {}

    def handle_starttag(self, tag, attrs):
        titles_meta.html_tag(self.raw, tag, attrs)
        self.inside = tag == "title" and not self.done

    def handle_endtag(self, tag):
        if tag == "title" and self.inside:
            self.inside, self.done = False, True

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def html_title(path):
    parser = TitleParser()
    parser.feed(read_head(path))
    text = "".join(parser.parts)
    meta = titles_meta.normalise(parser.raw)
    return (text, "html", meta) if text.strip() else (None, None, meta)


def read_title(path):
    """(raw title, src, meta) chosen by extension; may raise on a damaged file."""
    kind = READERS.get(os.path.splitext(path)[1].lower())
    if kind == "md":
        return md_title(path)
    if kind == "html":
        return html_title(path)
    if kind == "pdf":
        return titles_pdf.pdf_read(path)
    if kind:
        title, meta = titles_zip.zip_read(path, kind)
        return title, kind, meta
    return None, None, {}


def read_all(path):
    """(title, src, meta, errored): never raises."""
    try:
        raw, src, meta = read_title(path)
    except Exception:  # noqa: BLE001 - a bad file must never stop a run
        return None, None, {}, True
    title = clean(raw, path)
    return title, (src if title else None), meta, False


def process(path):
    """(title, src, errored): never raises."""
    title, src, _meta, bad = read_all(path)
    return title, src, bad


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")


def run(lines, opts):
    deadline = time.monotonic() + float(opts.get("budget_s", 600))
    limit = int(opts.get("max_files", 20000))
    done = errors = 0
    stopped = None
    for line in lines:
        if done >= limit or time.monotonic() >= deadline:
            stopped = "max_files" if done >= limit else "budget"
            break
        try:
            item = json.loads(line)
            ident, path = item["id"], item["path"]
        except (ValueError, KeyError, TypeError):
            continue
        title, src, meta, bad = read_all(path)
        emit({"id": ident, "title": title, "src": src, **({"meta": meta} if meta else {})})
        done, errors = done + 1, errors + bad
    emit({"t": "trailer", "done": done, "errors": errors, "stopped": stopped})


def main(argv):
    try:
        args = argv[argv.index("--worklist") + 1:]
        opts = json.loads(args[1]) if len(args) > 1 else {}
        with open(args[0], encoding="utf-8", errors="replace") as fh:
            run(fh, opts if isinstance(opts, dict) else {})
    except (ValueError, IndexError, OSError, TypeError):
        emit({"t": "trailer", "done": 0, "errors": 1, "stopped": None})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
