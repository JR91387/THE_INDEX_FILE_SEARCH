# SPDX-License-Identifier: MIT
"""PDF title reader: XMP dc:title, else Info /Title, also inside Flate streams of the tail. Bounded."""
import html
import re
import zlib

import titles_meta

CHUNK = 65536
FLATE_CAP = 262144
MAX_STREAMS = 40
INFO_KEYS = {"author": b"/Author", "date": b"/CreationDate", "tags": b"/Keywords", "description": b"/Subject"}
XMP = re.compile(rb"<dc:title>.*?<rdf:li[^>]*>(.*?)</rdf:li>", re.DOTALL)
TITLE = re.compile(rb"/Title\s*(?=[(<])(?!<<)")
STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.DOTALL)
ESCAPES = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12, 0x28: 40, 0x29: 41, 0x5C: 92}


def escape(buf, i, out):
    """Handle the escape at buf[i] (a backslash): append the byte it denotes, return the next index."""
    nxt = buf[i + 1:i + 2]
    octal = re.match(rb"[0-7]{1,3}", buf[i + 1:i + 4])
    if octal:
        out.append(int(octal.group(), 8) & 255)
        return i + 1 + len(octal.group())
    if nxt in (b"\n", b"\r"):
        return i + (3 if buf[i + 1:i + 3] == b"\r\n" else 2)
    if nxt:
        out.append(ESCAPES.get(nxt[0], nxt[0]))
    return i + 2


def literal(buf, i):
    """Bytes of the literal string whose '(' is at buf[i]; balanced nested parentheses allowed."""
    out, depth, i = bytearray(), 1, i + 1
    end = min(len(buf), i + 4000)
    while i < end:
        c = buf[i]
        if c == 0x5C:
            i = escape(buf, i, out)
            continue
        depth += (c == 0x28) - (c == 0x29)
        if depth == 0:
            return bytes(out)
        out.append(c)
        i += 1
    return None


def hex_string(buf, i):
    j = buf.find(b">", i, i + 8000)
    if j < 0:
        return None
    digits = re.sub(rb"\s", b"", buf[i + 1:j])
    try:
        return bytes.fromhex((digits + (b"0" if len(digits) % 2 else b"")).decode("ascii"))
    except ValueError:
        return None


def decode_text(raw):
    if raw[:2] == b"\xfe\xff":
        return raw[2:].decode("utf-16-be", "replace")
    if raw[:2] == b"\xff\xfe":
        return raw[2:].decode("utf-16-le", "replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", "replace")
    return raw.decode("latin-1")


def info_title(buf):
    """First usable /Title string, preferring one near Info-dictionary keys (outline entries have /Title too)."""
    first = None
    for m in TITLE.finditer(buf):
        raw = literal(buf, m.end()) if buf[m.end()] == 0x28 else hex_string(buf, m.end())
        text = decode_text(raw).strip() if raw else ""
        if not text:
            continue
        near = buf[max(0, m.start() - 400):m.end() + 800]
        if b"/Producer" in near or b"/Creator" in near or b"/CreationDate" in near:
            return text
        first = first or text
    return first


def inflated(tail):
    """Decompressed content of the first Flate streams of the tail."""
    for k, m in enumerate(STREAM.finditer(tail)):
        if k >= MAX_STREAMS:
            break
        try:
            yield zlib.decompressobj().decompress(m.group(1), FLATE_CAP)
        except zlib.error:
            continue


def flate_title(tail):
    for out in inflated(tail):
        text = info_title(out)
        if text:
            return text
    return None


def info_value(buf, key):
    """First non-empty string value of an Info key such as b'/Author'."""
    for m in re.finditer(re.escape(key) + rb"\s*(?=[(<])(?!<<)", buf):
        raw = literal(buf, m.end()) if buf[m.end()] == 0x28 else hex_string(buf, m.end())
        text = decode_text(raw).strip() if raw else ""
        if text:
            return text
    return None


def pdf_date(value):
    """'D:20240503101500Z' -> '2024-05-03' (shorter forms keep what they have)."""
    m = re.match(r"D?:?(\d{4})(\d{2})?(\d{2})?", value or "")
    return "-".join(g for g in m.groups() if g) if m else None


def info_meta(buf, tail):
    """Meta from the Info dictionary: in the visible text, else inside the tail's Flate streams."""
    for source in [buf, *inflated(tail)]:
        if any(info_value(source, k) for k in INFO_KEYS.values()):
            raw = {f: info_value(source, k) for f, k in INFO_KEYS.items()}
            raw["date"] = pdf_date(raw["date"])
            raw["tags"] = titles_meta.split_words(raw["tags"])
            return raw
    return {}


def xmp_list(xmp, tag):
    m = re.search(rb"<" + tag + rb"\b[^>]*>(.*?)</" + tag + rb">", xmp, re.DOTALL)
    items = re.findall(rb"<rdf:li[^>]*>(.*?)</rdf:li>", m.group(1), re.DOTALL) if m else []
    return [re.sub(r"<[^>]+>", "", html.unescape(i.decode("utf-8", "replace"))).strip() for i in items]


def xmp_meta(buf):
    m = re.search(rb"<x:xmpmeta.*?</x:xmpmeta>", buf, re.DOTALL)
    if not m:
        return {}
    xmp = m.group()
    date = re.search(rb"xmp:CreateDate(?:=\"|>)([^\"<]+)", xmp)
    return {"author": xmp_list(xmp, b"dc:creator"), "tags": xmp_list(xmp, b"dc:subject"),
            "description": xmp_list(xmp, b"dc:description")[:1],
            "date": date.group(1).decode("ascii", "replace") if date else None}


def head_tail(path):
    with open(path, "rb") as fh:
        head = fh.read(CHUNK)
        if len(head) < CHUNK:
            return head, head
        fh.seek(0, 2)
        fh.seek(max(CHUNK, fh.tell() - CHUNK))
        return head, fh.read(CHUNK)


def pdf_read(path):
    """(title, src, meta) from the first and last 64 KB of a PDF; (None, None, meta) when no title is found."""
    head, tail = head_tail(path)
    buf = head if head is tail else head + b"\n" + tail
    meta = titles_meta.normalise({**info_meta(buf, tail), **{k: v for k, v in xmp_meta(buf).items() if v}})
    m = XMP.search(buf)
    if m:
        text = re.sub(r"<[^>]+>", "", html.unescape(m.group(1).decode("utf-8", "replace"))).strip()
        if text:
            return text, "pdf_xmp", meta
    text = info_title(buf) or flate_title(tail)
    return (text, "pdf_info", meta) if text else (None, None, meta)


def pdf_title(path):
    """(title, src) from the first and last 64 KB of a PDF; (None, None) when nothing is found."""
    return pdf_read(path)[:2]
