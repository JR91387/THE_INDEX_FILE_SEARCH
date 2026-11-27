# SPDX-License-Identifier: MIT
"""CLI for the query layer: find, tree, projects, folder, describe (and `changes --documents`)."""
import json
import re

from . import db, query
from .units import size

CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _clean(text):
    """One printable line: untrusted names and titles never break the output layout."""
    return CONTROL.sub(" ", "" if text is None else str(text))


def _conn(cfg):
    if not cfg.db_path.exists():
        raise ValueError(f"no database at {cfg.db_path} (run `the-index scan` first)")
    return db.open(cfg.db_path)


def _line_find(r):
    author = (r.get("meta") or {}).get("author")
    bits = " · ".join(_clean(b) for b in (r["title"], author) if b)
    tail = f"  {bits}" if bits else ""
    mark = " [project]" if r["is_project"] else ""
    return f"{r['type']:<4} {r['device']}:{_clean(r['path'])}  {size(r['size_bytes'])}{mark}{tail}"


def _line_tree(r):
    pct = "" if r["pct_of_parent"] is None else f" {r['pct_of_parent']}%"
    return f"{'  ' * (r['depth'] - 1)}{_clean(r['path'])}  {size(r['size_total'])}{pct}"


def _line_project(r):
    return f"{r['device']}:{_clean(r['path'])}  {', '.join(r['agent_files'])}  {size(r['size_total'])}"


def _line_event(r):
    return f"{r['at']} {r['action']} {r['device']}:{_clean(r['name'])} {_clean(r['title'])}".rstrip()


def _lines_folder(r):
    out = [f"{r['device']}:{_clean(r['path'])}  {size(r['size_total'])}  {r['files_total']} files"]
    out += [f"  dir  {_clean(s['path'])}  {size(s['size_total'])}" for s in r["subdirs"]]
    out += [f"  file {_clean(f['name'])}  {size(f['size_bytes'])}  {_clean(f['title'])}".rstrip() for f in r["files"]]
    return out


def emit(out, line, as_json):
    """Print the envelope as JSON, or one short line per result plus the 'more' hint."""
    if as_json:
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if out.get("error"):
        raise ValueError(out["error"])
    for r in out["results"]:
        text = line(r)
        print("\n".join(text) if isinstance(text, list) else text)
    if out["more"]:
        hint = "narrow the words" if out.get("query", {}).get("words") else "raise --limit"
        print(f"… {out['more']} more ({hint})")
    return 0


def _run(cfg, args, params, spec):
    """spec = (query command name, line formatter)."""
    return emit(query.COMMANDS[spec[0]](_conn(cfg), params), spec[1], args.json)


def cmd_find(cfg, args):
    params = {"words": args.words, "kind": args.kind, "ext": args.ext, "device": args.device,
              "documents_only": args.documents, "tag": args.tag, "author": args.author, "limit": args.limit}
    return _run(cfg, args, params, ("find", _line_find))


def cmd_tree(cfg, args):
    params = {"path": args.path, "depth": args.depth, "min_bytes": args.min_size, "limit": args.limit}
    return _run(cfg, args, params, ("tree", _line_tree))


def cmd_projects(cfg, args):
    return _run(cfg, args, {"limit": args.limit}, ("projects", _line_project))


def cmd_folder(cfg, args):
    return _run(cfg, args, {"path": args.path, "limit": args.limit}, ("folder", _lines_folder))


def cmd_describe(cfg, args):
    out = query.describe()
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
        return 0
    for c in out["results"][0]["commands"]:
        print(f"{c['name']}: {c['summary']}  ({', '.join(p['name'] for p in c['params'])})")
    print(out["note"])
    return 0


def cmd_changes_documents(cfg, args):
    return _run(cfg, args, {"since": args.since}, ("changes_files", _line_event))


def add_parsers(sub):
    """Register find, tree, projects, folder and describe on the subparsers object."""
    def common(p, limit=True):
        p.add_argument("--json", action="store_true", help="print the versioned JSON envelope")
        if limit:
            p.add_argument("--limit", type=int, default=query.DEFAULT_LIMIT, help="most results (max 500)")
    fnd = sub.add_parser("find", help="find folders and documents by words in name, title, author, tags or path")
    fnd.add_argument("words", nargs="+")
    fnd.add_argument("--kind", choices=["dir", "file", "any"], default="any")
    fnd.add_argument("--ext", help="extension, with or without the dot")
    fnd.add_argument("--device", help="only this device")
    fnd.add_argument("--documents", action="store_true", help="only documents (files whose title is read)")
    fnd.add_argument("--tag", help="only documents with this tag (whole tag, any case)")
    fnd.add_argument("--author", help="only documents whose author contains this text (any case)")
    common(fnd)
    tre = sub.add_parser("tree", help="folders below PATH by size")
    tre.add_argument("path")
    tre.add_argument("--depth", type=int, default=2, help="levels down (max 6)")
    tre.add_argument("--min-size", type=int, default=0, help="hide folders smaller than this many bytes")
    common(tre)
    common(sub.add_parser("projects", help="folders holding AI-agent files, newest first"))
    common(sub.add_parser("folder", help="one folder: its files and subfolders"))
    sub.choices["folder"].add_argument("path")
    common(sub.add_parser("describe", help="commands, fields and limits for agents"), limit=False)


COMMANDS = {"find": cmd_find, "tree": cmd_tree, "projects": cmd_projects, "folder": cmd_folder,
            "describe": cmd_describe}
