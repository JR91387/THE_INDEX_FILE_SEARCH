# SPDX-License-Identifier: MIT
"""CLI: `the-index catalog {import, export, list}`."""
import json
import sys

from . import db
from .lazy import Lazy

catalog, catalog_export = Lazy(".catalog"), Lazy(".catalog_export")


def _writable(cfg):
    return db.open(cfg.db_path, write=True)


def _import(cfg, args):
    result = catalog.import_catalog(_writable(cfg), args.file, args.name, args.format)
    if result["skipped"]:
        print(f"catalog {args.name}: skipped {result['skipped']} bad lines", file=sys.stderr)
    print(f"catalog {args.name}: {result['folders']} folders, {result['files']} files")
    return 0 if result["status"] != "failed" else 1


def _export(cfg, args):
    fmt = args.format or ("jsonl" if str(args.out).lower().endswith((".jsonl", ".json")) else "efu")
    catalog_export.export_catalog(db.open(cfg.db_path), args.out, (args.device, args.path), fmt)
    return 0


def _list(cfg, args):
    rows = catalog_export.list_catalogs(db.open(cfg.db_path))
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        print(f"{r['name']}: {r['folders']} folders, {r['files']} files, last import {r['last_import'] or 'never'}")
    return 0


def cmd_catalog(cfg, args):
    return {"import": _import, "export": _export, "list": _list}[args.catalog_cmd](cfg, args)


def add_parsers(sub):
    cat = sub.add_parser("catalog", help="offline catalogs: unplugged drives and backups from file lists")
    ops = cat.add_subparsers(dest="catalog_cmd", required=True)
    imp = ops.add_parser("import", help="load an Everything file list (EFU) or JSON Lines as an offline device")
    imp.add_argument("file")
    imp.add_argument("--name", required=True, help="device name for this catalog")
    imp.add_argument("--format", choices=["efu", "jsonl"], help="default: by file extension")
    exp = ops.add_parser("export", help="write a catalog from the database")
    exp.add_argument("--device", required=True)
    exp.add_argument("--path", help="only this folder and below")
    exp.add_argument("--out", required=True)
    exp.add_argument("--format", choices=["efu", "jsonl"], help="default: efu, or jsonl for a .jsonl name")
    lst = ops.add_parser("list", help="catalogs (offline devices) with counts and last import")
    lst.add_argument("--json", action="store_true")


COMMANDS = {"catalog": cmd_catalog}
