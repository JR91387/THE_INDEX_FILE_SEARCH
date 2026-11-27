# SPDX-License-Identifier: MIT
"""Load one `filetree` JSON Lines stream (see collectors/README.md) into `dir` and `file`, updated in place.

Rules: a listed dir's files are upserted; a `skip` dir keeps its rows; on an `ok` run, files missing from a
listed dir and dirs under a root that were neither listed nor skipped are retired (never under a gap target);
anything seen again is revived. Totals roll up deepest first. One transaction per run."""
import json
import unicodedata

from . import files_bulk, gaps, ingest


class Loader:
    def __init__(self, conn, ctx):
        self.conn, self.ctx, self.run = conn, ctx, ctx["run_id"]
        self.dirs = {k: (i, r) for i, k, r in conn.execute(
            "SELECT id, path_key, retired_run FROM dir WHERE device_id = ?", (ctx["device_id"],))}
        self.seen, self.gaps, self.unseen_files = set(), [], []
        self.files = {}           # name -> (id, retired_run) for the dir being listed
        self.counts = {"dirs": 0, "files": 0}
        self.current = None
        self.titles = []

    def dir_row(self, rec, listed):
        """Insert or refresh one dir (listed or skipped); returns its id."""
        parent = self.dirs.get(rec.get("parent"), (None, None))[0]
        known = self.dirs.get(rec["key"])
        cols = (rec["path"], parent, rec["key"].count("/"), rec.get("mtime_ns"), rec.get("ctime_ns"))
        if known and not listed and known[1] is None:
            self.seen.add(known[0])           # unchanged dir, still active: nothing to write
            self.counts["dirs"] += 1
            return known[0]
        if known:
            self.conn.execute("UPDATE dir SET parent_id=?, depth=?, mtime_ns=?, ctime_ns=?, seen_run=? WHERE id=?",
                              (*cols[1:], self.run, known[0]))
            if known[1] is not None or self.conn.execute("SELECT path FROM dir WHERE id=?", (known[0],)).fetchone()[0] != rec["path"]:
                self.conn.execute("UPDATE dir SET path=?, retired_run=NULL WHERE id=?", (rec["path"], known[0]))
            dir_id = known[0]
        else:
            dir_id = self.conn.execute(
                "INSERT INTO dir (device_id, path_key, path, parent_id, depth, mtime_ns, ctime_ns, first_seen_run, "
                "seen_run) VALUES (?,?,?,?,?,?,?,?,?)",
                (self.ctx["device_id"], rec["key"], *cols, self.run, self.run)).lastrowid
        if listed:
            self.conn.execute("UPDATE dir SET size_bytes=?, file_count=?, is_cache=?, agent_files=? WHERE id=?",
                              (rec.get("size", 0), rec.get("files", 0), int(bool(rec.get("cache"))),
                               json.dumps(sorted(rec.get("agents") or [])), dir_id))
        self.dirs[rec["key"]] = (dir_id, None)
        self.seen.add(dir_id)
        self.counts["dirs"] += 1
        return dir_id

    def open_dir(self, rec):
        """A listed dir: its stored files become candidates for retirement until seen in this stream."""
        self.close_dir()
        self.current = self.dir_row(rec, listed=True)
        self.files = {} if rec.get("cache") else {row[1]: row for row in self.conn.execute(
            "SELECT id, name, retired_run, size_bytes, mtime_ns, ctime_ns FROM file WHERE dir_id = ?", (self.current,))}

    def close_dir(self):
        self.unseen_files += [row[0] for row in self.files.values() if row[2] is None]
        self.files = {}

    def file_row(self, rec):
        name = rec["name"]
        ext = ("." + name.rsplit(".", 1)[1].lower()) if "." in name.strip(".") else ""
        vals = (ext, rec.get("size", 0), rec.get("mtime_ns"), rec.get("ctime_ns"), rec.get("inode"))
        known = self.files.pop(name, None)
        if known and known[2] is None and known[3:] == vals[1:4]:
            pass                                  # unchanged and active: nothing to write
        elif known:
            self.conn.execute("UPDATE file SET ext=?, size_bytes=?, mtime_ns=?, ctime_ns=?, inode=?, seen_run=? "
                              "WHERE id=?", (*vals, self.run, known[0]))
            if known[2] is not None:
                self.conn.execute("UPDATE file SET retired_run = NULL WHERE id = ?", (known[0],))
        else:
            self.conn.execute(
                "INSERT INTO file (device_id, dir_id, name, ext, size_bytes, mtime_ns, ctime_ns, inode, "
                "first_seen_run, seen_run) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self.ctx["device_id"], self.current, name, *vals, self.run, self.run))
        if "title_sig" in rec:                    # titles read on the sending machine (inbox members, catalogs)
            meta = json.dumps(rec["meta"], sort_keys=True, ensure_ascii=False, separators=(",", ":")) \
                if isinstance(rec.get("meta"), dict) else None      # no meta key: unknown, not "none found"
            self.titles.append((rec.get("title"), rec.get("title_src"), rec["title_sig"], self.current, name, meta))
        self.counts["files"] += 1

    def feed(self, rec):
        kind = rec.get("t")
        if kind == "dir":
            self.open_dir(rec)
        elif kind == "file" and self.dirs.get(rec.get("dir"), (None,))[0] == getattr(self, "current", None):
            self.file_row(rec)
        elif kind == "skip":
            self.close_dir()
            self.dir_row(rec, listed=False)
        elif kind == "gap":
            self.gaps.append(rec)

    def retire(self, roots):
        """OK runs only: unseen files of listed dirs, and unseen dirs under a root but not under a gap."""
        self.close_dir()
        self.conn.executemany("UPDATE file SET retired_run=? WHERE id=?", [(self.run, i) for i in self.unseen_files])
        blind = tuple(g["target"].rstrip("/") + "/" for g in self.gaps if g.get("target"))
        for key, (dir_id, retired) in self.dirs.items():
            if retired is None and dir_id not in self.seen and under(key, roots) and not under(key, blind):
                self.conn.execute("UPDATE dir SET retired_run=? WHERE id=?", (self.run, dir_id))
                self.conn.execute("UPDATE file SET retired_run=? WHERE dir_id=? AND retired_run IS NULL",
                                  (self.run, dir_id))


def root_key(path, case_insensitive):
    """The collector's path_key rule (NFC, '/' separators, case-folded on case-insensitive volumes)."""
    key = unicodedata.normalize("NFC", path).replace("\\", "/")
    key = key.rstrip("/") or "/"
    return key.casefold() if case_insensitive else key


def under(key, prefixes):
    return any(key == p.rstrip("/") or key.startswith(p.rstrip("/") + "/") for p in prefixes)


def store_titles(conn, run_id, titles):
    """Titles (and meta JSON, when sent) that came inside the stream; title_run marks a real change.
    A record repeating the stored sig only fills a missing meta."""
    conn.executemany(
        "UPDATE file SET title_run = CASE WHEN coalesce(title_sig, '') = ?3 THEN title_run "
        "WHEN coalesce(title, '') <> coalesce(?1, '') THEN ?7 ELSE title_run END, "
        "title = CASE WHEN coalesce(title_sig, '') = ?3 THEN title ELSE ?1 END, "
        "title_src = CASE WHEN coalesce(title_sig, '') = ?3 THEN title_src ELSE ?2 END, title_sig = ?3, "
        "meta = coalesce(?6, meta) WHERE dir_id = ?4 AND name = ?5 "
        "AND (coalesce(title_sig, '') <> ?3 OR (?6 IS NOT NULL AND meta IS NULL))", [(*row, run_id) for row in titles])


def rollup(conn, device_id):
    """size_total / files_total = own + children's totals, computed deepest level first."""
    depths = [r[0] for r in conn.execute("SELECT DISTINCT depth FROM dir WHERE device_id=? AND retired_run IS NULL "
                                         "ORDER BY depth DESC", (device_id,))]
    for depth in depths:
        conn.execute(
            "UPDATE dir SET size_total = size_bytes + coalesce((SELECT sum(c.size_total) FROM dir c "
            "WHERE c.parent_id = dir.id AND c.retired_run IS NULL), 0), files_total = file_count + "
            "coalesce((SELECT sum(c.files_total) FROM dir c WHERE c.parent_id = dir.id AND c.retired_run IS NULL), 0) "
            "WHERE device_id = ? AND depth = ? AND retired_run IS NULL", (device_id, depth))


def ingest_stream(conn, lines, device_name):
    """Record one filetree run from an iterable of JSON lines. Returns ingest-style result."""
    records = (json.loads(line) for line in lines if line.strip())
    header = next(records, None)
    if not header or header.get("t") != "header":
        return ingest.ingest(conn, {"collector": "filetree", "status": "failed", "items": [],
                                    "errors": ["filetree: no header line"]}, device_name)
    conn.execute("BEGIN")
    try:
        result = _load(conn, header, records, device_name)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


def _load(conn, header, records, device_name):
    collector = header.get("collector") if header.get("collector") in ("filetree", "catalog") else "filetree"
    ctx = ingest.start_run(conn, ingest.ensure_device(conn, device_name), {**header, "collector": collector})
    loader, trailer, bulk = Loader(conn, ctx), {}, files_bulk.begin(conn, ctx["device_id"])
    for rec in records:
        if rec.get("t") == "trailer":
            trailer = rec
            break
        loader.feed(rec)
    status = trailer.get("status") if trailer.get("status") in ("ok", "partial") else "partial"
    errors = list(trailer.get("errors") or ([] if trailer else ["filetree: stream ended without a trailer"]))
    no_retire = bool(header.get("no_retire"))     # a native index listing: complete per root, but only the walk retires
    if status == "ok" and not no_retire:
        loader.retire([root_key(r, header.get("case_insensitive")) for r in header.get("roots") or []])
    loader.close_dir()
    files_bulk.end(conn, bulk)
    store_titles(conn, ctx["run_id"], loader.titles)
    rollup(conn, ctx["device_id"])
    gaps.sync(conn, ctx, [{"kind": g["kind"], "target": g["target"], "reason": g.get("reason")}
                          for g in loader.gaps], status == "ok" and not no_retire)
    payload = {"finished_at": trailer.get("finished_at"), "errors": errors, "items": []}
    ingest.finish_run(conn, ctx, payload, status)
    conn.execute("UPDATE scan_run SET items_seen=? WHERE id=?", (loader.counts["files"], ctx["run_id"]))
    return {"run_id": ctx["run_id"], "status": status, "items": loader.counts["dirs"] + loader.counts["files"],
            "changes": 0, "baseline": ctx["baseline"], "device_id": ctx["device_id"], "bulk": bulk is not None}
