# SPDX-License-Identifier: MIT
"""Zip-based title readers (OOXML, ODF, EPUB). Bounded reads, nothing is ever extracted."""
import xml.etree.ElementTree as ET
import zipfile

import titles_meta

MAX_MEMBER = 1 << 20
DC_TITLE = "{http://purl.org/dc/elements/1.1/}title"
MEMBERS = {"ooxml": "docProps/core.xml", "odf": "meta.xml", "epub": "META-INF/container.xml"}


def read_member(zf, name):
    """Bytes of one member, or None when absent or claiming more than 1 MB uncompressed."""
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_MEMBER:
        return None
    with zf.open(info) as fh:
        return fh.read(MAX_MEMBER)


def parse(data):
    """Root element of an XML document; entity declarations are refused (None)."""
    if not data or b"<!ENTITY" in data:
        return None
    return ET.fromstring(data)


def dc_title(root):
    """First dc:title text under a parsed XML root."""
    if root is None:
        return None
    for el in root.iter(DC_TITLE):
        if el.text and el.text.strip():
            return el.text
    return None


def opf_path(container):
    if not container or b"<!ENTITY" in container:
        return None
    for el in ET.fromstring(container).iter():
        if el.tag.endswith("rootfile") and el.get("full-path"):
            return el.get("full-path")
    return None


def zip_read(path, kind):
    """(title, meta) from a zip-based document of the given kind. Errors propagate to the caller."""
    with zipfile.ZipFile(path) as zf:
        data = read_member(zf, MEMBERS[kind])
        if kind == "epub":
            opf = opf_path(data)
            data = read_member(zf, opf) if opf else None
        root = parse(data)
        return dc_title(root), (titles_meta.xml_meta(root, kind) if root is not None else {})


def zip_title(path, kind):
    """Title from a zip-based document of the given kind, or None."""
    return zip_read(path, kind)[0]
