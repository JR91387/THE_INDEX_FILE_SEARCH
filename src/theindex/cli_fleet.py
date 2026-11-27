# SPDX-License-Identifier: MIT
"""CLI for the fleet: `collect --out DIR` (member), `ingest --inbox DIR` and `pull` (hub)."""
from contextlib import closing

from . import db
from .lazy import Lazy

frames, inbox, member, pull, scan = (Lazy(f".{n}") for n in ("frames", "inbox", "member", "pull", "scan"))


def _folder(given, configured, what):
    if given or configured:
        return given or configured
    raise ValueError(f"no {what} given and no [inbox] dir in the config")


def cmd_collect(cfg, args):
    out = _folder(args.out, cfg.inbox_dir, "--out folder")
    if out == "-":
        return frames.stream_collect(cfg, args.collector)
    paths = member.run(cfg, out, args.collector)
    if args.verbose:
        print("\n".join(str(p) for p in paths) or "nothing collected")
    return 0


def cmd_pull(cfg, args):
    folder = _folder(args.inbox, cfg.inbox_dir, "--inbox folder")
    with scan.scan_lock(cfg.db_path) as taken:
        if not taken:
            print(f"skipped: {scan.SKIP_BUSY}")
            return 0
        with closing(db.init(cfg.db_path)) as conn:
            failed = pull.run(conn, cfg, pull.select(cfg, args.hosts), folder)
            db.rebuild_search(conn)
    return 1 if failed else 0


def cmd_ingest(cfg, args):
    folder = _folder(args.inbox, cfg.inbox_dir, "--inbox folder")
    with scan.scan_lock(cfg.db_path) as taken:
        if not taken:
            print(f"skipped: {scan.SKIP_BUSY}")
            return 0
        with closing(db.init(cfg.db_path)) as conn:
            counts = inbox.drain(conn, folder, cfg.device_name)
            db.rebuild_search(conn)
    print(inbox.summary(counts))
    return 0


def add_parsers(sub):
    col = sub.add_parser("collect", help="member: write collector payloads into the shared inbox folder")
    col.add_argument("--out", help="inbox folder (default: [inbox] dir in the config)")
    col.add_argument("--collector", help="run only this collector")
    col.add_argument("--quiet", action="store_true", help="accepted, does nothing (success is silent)")
    col.add_argument("--verbose", action="store_true", help="print the paths written")
    col.set_defaults(verbose=False)
    pl = sub.add_parser("pull", help="hub: fetch payloads from members over ssh, then take the inbox")
    pl.add_argument("hosts", nargs="*", help="ssh destinations (default: the [[pull]] hosts in the config)")
    pl.add_argument("--inbox", help="inbox folder (default: [inbox] dir in the config)")
    ing = sub.add_parser("ingest", help="hub: take the payload files in the inbox folder into the database")
    ing.add_argument("--inbox", help="inbox folder (default: [inbox] dir in the config)")


COMMANDS = {"collect": cmd_collect, "pull": cmd_pull, "ingest": cmd_ingest}
