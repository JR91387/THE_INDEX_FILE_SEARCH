# SPDX-License-Identifier: MIT
"""Front matter (author, date, tags, description, lang) from document metadata. Standalone, stdlib only.

Every reader hands raw values to `normalise`: strings are cleaned and cut at 300 characters, tags are a
de-duplicated list of at most 20, and an empty value is simply absent."""
import re

CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
MAX_LEN, MAX_TAGS = 300, 20
ALIASES = {"author": ("author", "authors"), "date": ("date",), "tags": ("tags", "keywords"),
           "description": ("description", "summary"), "lang": ("lang", "language")}
BLOCK_SCALAR = ("|", ">", "|-", ">-", "|+", ">+")
INLINE_ITEM = re.compile(r"""\s*(?:"([^"]*)"|'([^']*)'|([^,"']+))\s*(?:,|$)""")
KEY_LINE = re.compile(r"([A-Za-z_]+):(?:[ \t]+(.*))?$")


def text(value):
    """One cleaned, single-line string of at most 300 characters (empty string for nothing)."""
    if value is None:
        return ""
    return " ".join(CONTROL.sub(" ", str(value)).split())[:MAX_LEN].strip()


def split_words(value):
    return re.split(r"[,;]", value or "")


def normalise(raw):
    """Clean a raw {field: value} dict; keys with no usable value are dropped."""
    out = {}
    for key in ("author", "date", "description", "lang"):
        val = raw.get(key)
        if isinstance(val, (list, tuple)):
            val = ", ".join(t for t in (text(v) for v in val) if t)
        val = text(val)
        if val:
            out[key] = val
    tags = raw.get("tags") or []
    tags = split_words(tags) if isinstance(tags, str) else tags
    seen = []
    for tag in (text(t) for t in tags):
        if tag and tag not in seen:
            seen.append(tag)
    if seen:
        out["tags"] = seen[:MAX_TAGS]
    return out


def unquote(val):
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        return val[1:-1].replace('\\"', '"') if val[0] == '"' else val[1:-1]
    return re.split(r"\s#", val)[0].strip()


def inline_list(val):
    inner = val[1:val.rfind("]")] if "]" in val else val[1:]
    return [m[0] or m[1] or m[2].strip() for m in INLINE_ITEM.findall(inner)]


def yaml_value(val, rest):
    """(value, number of following lines used) for one `key: val` whose next lines are `rest`."""
    val = val.strip()
    if val and val not in BLOCK_SCALAR:
        return (inline_list(val), 0) if val[0] == "[" else (unquote(val), 0)
    body = []
    for line in rest:
        if line.strip() and not line[0].isspace() and not line.startswith("- "):
            break
        body.append(line.strip())
    items = [b[2:].strip() for b in body if b.startswith("- ")]
    if not val and items:
        return [unquote(i) for i in items], len(body)
    return (" ".join(b for b in body if b) if val else ""), len(body)


def fm_meta(block):
    """Meta from the lines between the '---' fences of a Markdown file (a YAML subset)."""
    found, i = {}, 0
    while i < len(block):
        m = KEY_LINE.match(block[i].rstrip())
        i += 1
        if not m:
            continue
        value, used = yaml_value(m.group(2) or "", block[i:])
        i += used
        found.setdefault(m.group(1).lower(), value)
    raw = {}
    for field, names in ALIASES.items():
        for name in names:
            if found.get(name):
                raw[field] = found[name]
                break
    return normalise(raw)


def html_tag(raw, tag, attrs):
    """Collect <meta name content> and <html lang> into `raw`."""
    a = {k.lower(): v for k, v in attrs if v is not None}
    if tag == "html" and a.get("lang"):
        raw.setdefault("lang", a["lang"])
    elif tag == "meta" and "content" in a:
        name = a.get("name", "").lower()
        if name in ("author", "description"):
            raw.setdefault(name, a["content"])
        elif name == "keywords":
            raw.setdefault("tags", split_words(a["content"]))


XML_FIELDS = {
    "ooxml": {"author": ("creator",), "date": ("created",), "tags": ("keywords",),
              "description": ("subject", "description"), "lang": ("language",)},
    "odf": {"author": ("initial-creator", "creator"), "date": ("creation-date",), "tags": ("keyword",),
            "description": ("description",), "lang": ("language",)},
    "epub": {"author": ("creator",), "date": ("date",), "tags": ("subject",),
             "description": ("description",), "lang": ("language",)},
}


def xml_meta(root, kind):
    """Meta from the root element of docProps/core.xml, meta.xml or an OPF package."""
    values = {}
    for el in root.iter():
        if el.text and el.text.strip():
            values.setdefault(el.tag.rsplit("}", 1)[-1], []).append(el.text)
    raw = {}
    for field, names in XML_FIELDS[kind].items():
        for name in names:
            if name in values:
                raw[field] = values[name] if field == "tags" else values[name][0]
                break
    if kind == "ooxml" and "tags" in raw:
        raw["tags"] = [w for v in raw["tags"] for w in split_words(v)]
    return normalise(raw)
