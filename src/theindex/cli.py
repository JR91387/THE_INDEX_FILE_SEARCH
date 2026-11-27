# SPDX-License-Identifier: MIT
"""Command line: the-index {init, scan, watch, collect, ingest, schedule, status, pages, declare, review, search, serve, mcp}. See `the-index <command> -h`."""
import json
import sqlite3
import sys
import tomllib
from pathlib import Path

from . import cli_catalog, cli_find, cli_fleet, config, db
from .cli_parser import Parser
from .lazy import Lazy, command

declare, pages, report, scan, schedule, search, watch = (Lazy(f".{n}") for n in
                                                        ("declare", "pages", "report", "scan", "schedule", "search", "watch"))
model, serve = Lazy(".pages.model"), Lazy(".pages.serve")


def cmd_bench(cfg, args):
    from . import bench
    return bench.cmd_bench(cfg, args)


def bench_parser(sub):
    p = sub.add_parser("bench", help="time scans and searches on a synthetic tree (nothing is sent anywhere)")
    p.add_argument("--files", type=int, default=100_000, help="size of the synthetic tree (default 100000)")
    p.add_argument("--root", help="folder to build in (default: a new temporary folder)")
    p.add_argument("--keep", action="store_true", help="keep the tree and database afterwards")
    p.add_argument("--out", help="also write the result as JSON to this file")


def cmd_mcp(cfg, args):
    from . import mcp
    return mcp.serve(cfg)


def cmd_init(cfg, args):
    conn = db.init(cfg.db_path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    print(f"database ready: {cfg.db_path} (schema {version})")
    return 0


def cmd_status(cfg, args):
    print(report.front_page(db.open(cfg.db_path)))
    return 0


def cmd_pages(cfg, args):
    print(pages.write_all(db.open(cfg.db_path), args.out or cfg.pages_dir))
    return 0


def cmd_declare(cfg, args):
    conn = db.init(cfg.db_path)
    if args.action == "list":
        for r in declare.active(conn):
            print(f"#{r['id']} {r['action']} {r['device']}/{r['kind']} {r['key_glob']} until {r['expires_at']} "
                  f"-- {r['reason']} ({r['declared_by']})")
        return 0
    if args.action == "withdraw":
        ok = args.id is not None and declare.withdraw(conn, args.id, args.by)
        print("withdrawn" if ok else "not found or not active")
        return 0 if ok else 1
    print(f"declared #{declare.add(conn, declare.from_fields(vars(args)))}")
    return 0


def cmd_review(cfg, args):
    ok = declare.review(db.init(cfg.db_path), args.change_id, args.by, args.note)
    print("reviewed" if ok else "not found or already reviewed")
    return 0 if ok else 1


def cmd_search(cfg, args):
    hits = search.run(db.open(cfg.db_path), args.terms, args.limit,
                      {"kind": args.kind, "device": args.device})
    if args.json:
        print(json.dumps(hits, indent=2, ensure_ascii=False))
        return 0
    for h in hits:
        print(f"{h['kind']} {h['device']}:{h['key']} -- {h['snippet']}")
    return 0


def cmd_changes(cfg, args):
    if args.documents:
        return cli_find.cmd_changes_documents(cfg, args)
    rows = model.changes_since(db.open(cfg.db_path), config.parse_duration(args.since))
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    for r in rows:
        print(f"#{r['id']} {r['started_at']} {r['class']} {r['action']} {r['kind']} {r['device']}:{r['key']}"
              f"  {r['reason'] or ''}".rstrip())
    return 0


def cmd_serve(cfg, args):
    db.open(cfg.db_path).close()
    return serve.run(cfg.db_path, args.port if args.port is not None else cfg.serve_port)


def _command_name(argv):
    """The command word in argv (after --config/--db), or None."""
    words = iter(argv)
    for word in words:
        if word in ("--config", "--db"):
            next(words, None)
        elif not word.startswith("-"):
            return word
    return None


def parser(argv=None):
    """The full parser, or for the quick query commands only their own subparsers (building all ~25 costs ~12 ms)."""
    p = Parser(prog="the-index", description=__doc__)
    p.add_argument("--config", help="config file (default: XDG config dir)")
    p.add_argument("--db", help="database path (overrides config)")
    sub = p.add_subparsers(dest="command", required=True)
    if _command_name(sys.argv[1:] if argv is None else argv) in cli_find.COMMANDS:
        cli_find.add_parsers(sub)
        return p
    _all_parsers(sub)
    return p


def _all_parsers(sub):
    sub.add_parser("init", help="create or upgrade the database (optional; every command initialises)")
    scan = sub.add_parser("scan", help="run collectors and record what changed")
    scan.add_argument("--collector", help="run only this collector")
    scan.add_argument("--from-json", help="ingest a saved collector payload instead of running one")
    scan.add_argument("--measure-all", action="store_true", help="measure every folder now (no rotation)")
    scan.add_argument("--quiet", action="store_true", help="print nothing on success (used by `schedule`)")
    sch = sub.add_parser("schedule", help="run `scan` (hub) or `collect` (member) daily in the background")
    sch.add_argument("--role", choices=["hub", "member"], help="what to schedule (default: [inbox] role in the config)")
    sch.add_argument("--remove", action="store_true", help="stop and delete the schedule")
    sch.add_argument("--print", action="store_true", help="show what would be installed; change nothing")
    sch.add_argument("--watch", action="store_true", help="also run `watch` as a user service ([watch] enabled)")
    wat = sub.add_parser("watch", help="keep the file index current from the OS change feed (prints nothing)")
    wat.add_argument("--debounce", type=float, help="seconds of quiet before listing (default: [watch] debounce_s)")
    sub.add_parser("status", help="print the front page")
    pg = sub.add_parser("pages", help="write the Markdown pages and the_index.html")
    pg.add_argument("--out", help="output directory (default: pages_dir from config)")
    dec = sub.add_parser("declare", help="declare, list or withdraw planned changes")
    dec.add_argument("action", choices=["add", "list", "withdraw"])
    for flag in ("--key", "--reason", "--by", "--device", "--kind"):
        dec.add_argument(flag)
    dec.add_argument("--change", choices=["new", "gone", "modified", "any"], default="any")
    dec.add_argument("--expires", default="7d", help="duration (7d, 12h) or ISO time")
    dec.add_argument("--id", type=int, help="declaration id (withdraw)")
    rev = sub.add_parser("review", help="mark a change reviewed")
    rev.add_argument("change_id", type=int)
    rev.add_argument("--by", required=True)
    rev.add_argument("--note")
    sea = sub.add_parser("search", help="search the catalog (ranked); --json for scripts and AI")
    sea.add_argument("terms", nargs="+")
    sea.add_argument("--json", action="store_true")
    sea.add_argument("--limit", type=int, default=20)
    sea.add_argument("--kind", help="only this kind (folder, job, container, backup, filesystem, link, change, ...)")
    sea.add_argument("--device", help="only this device")
    chg = sub.add_parser("changes", help="what changed recently (first-scan sightings left out)")
    chg.add_argument("--since", default="7d", help="how far back: 7d, 12h, 30m (default 7d)")
    chg.add_argument("--json", action="store_true")
    chg.add_argument("--documents", action="store_true", help="document events (new, retitled, gone) instead")
    srv = sub.add_parser("serve", help="local page on 127.0.0.1 with search and review (Ctrl+C stops)")
    srv.add_argument("--port", type=int, help="port (default: serve.port in config, 8765)")
    sub.add_parser("mcp", help="MCP server on stdin/stdout for AI agents (read-only)")
    cli_find.add_parsers(sub)
    cli_catalog.add_parsers(sub)
    cli_fleet.add_parsers(sub)
    bench_parser(sub)


COMMANDS = {"init": cmd_init, "scan": command(scan, "cmd_scan"), "schedule": command(schedule, "cmd_schedule"), "status": cmd_status,
            "pages": cmd_pages, "declare": cmd_declare, "review": cmd_review, "search": cmd_search,
            "changes": cmd_changes, "serve": cmd_serve, "mcp": cmd_mcp, "bench": cmd_bench, "watch": command(watch, "cmd_watch"), **cli_find.COMMANDS, **cli_catalog.COMMANDS,
            **cli_fleet.COMMANDS}


def _fail(message):
    """One line on stderr, never a traceback."""
    print(f"error: {message}", file=sys.stderr)
    return 2


def main(argv=None):
    args = parser(argv).parse_args(argv)
    try:
        cfg = config.load(args.config)
        if args.db:
            cfg.db_path = Path(args.db).expanduser()
        return COMMANDS[args.command](cfg, args)
    except KeyError as exc:
        return _fail(exc.args[0] if exc.args else exc)
    except (ValueError, OSError, sqlite3.Error, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        return _fail(exc)
