# SPDX-License-Identifier: MIT
"""Member side: write one `filetree` stream as an inbox file (JSON Lines).

Pass 1 runs filetree.py, adds `payload_id`/`machine`/`host` to the header, spools the records, rewrites the state
file from the stream's dir and skip records, and lists the documents whose title must be read. Then the titles are
read (see member_titles). Pass 2 copies the spool to `.tmp-<name>` adding title fields from the cache, and
renames it into place: the hub never sees a half-written file."""
import json
import os
import sys

from . import files_run, member_titles

SEP = (",", ":")


def tmp_path(final):
    return final.with_name(".tmp-" + final.name)


def ext_of(name):
    return ("." + name.rsplit(".", 1)[1].lower()) if "." in name.strip(".") else ""


def sig_of(rec):
    return f"{rec.get('size', 0)}:{rec.get('mtime_ns') if rec.get('mtime_ns') is not None else ''}"


class Spool:
    """Pass 1: spool records, write state rows, collect the title worklist."""

    def __init__(self, ident, exts, cache):
        self.ident, self.exts, self.cache = ident, exts, cache[0]
        self.with_meta = cache[1]
        self.wanted, self.cur, self.finished = [], "", False

    def feed(self, rec, spool, state):
        kind = rec.get("t")
        if kind == "header":
            rec.update(self.ident)
        elif kind in ("dir", "skip"):
            if kind == "dir":
                self.cur = rec["path"]
            state.write(f"{rec['key']}\t{rec.get('mtime_ns')}\t{rec.get('ctime_ns')}\n")
        elif kind == "trailer":
            self.finished = True
        elif kind == "file" and ext_of(rec["name"]) in self.exts:
            self.want(rec)
        spool.write(json.dumps(rec, separators=SEP) + "\n")

    def want(self, rec):
        key, sig = f"{rec['dir']}/{rec['name']}", sig_of(rec)
        if member_titles.lookup(self.cache, key, sig, self.with_meta) is None:
            self.wanted.append((rec.get("mtime_ns"), key, os.path.join(self.cur, rec["name"]), sig))


def _pass_one(lines, work, files):
    spool_fh, state_fh = files
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            work.feed(rec, spool_fh, state_fh)
    return work


def _decorate(rec, cache):
    """Add the cached title (when its sig still matches) to a document's file record."""
    if rec.get("t") != "file" or ext_of(rec["name"]) not in cache["exts"]:
        return
    sig = sig_of(rec)
    hit = member_titles.lookup(cache["db"], f"{rec['dir']}/{rec['name']}", sig, cache["meta"])
    if hit is not None:
        rec.update(title=hit[0], title_src=hit[1], title_sig=sig)
        if cache["meta"] and hit[2] is not None:
            rec["meta"] = json.loads(hit[2])


def _pass_two(spool_path, out, cache):
    with open(spool_path, encoding="utf-8") as src:
        for line in src:
            rec = json.loads(line)
            _decorate(rec, cache)
            out.write(json.dumps(rec, separators=SEP) + "\n")


def run(cfg, scratch, job):
    """job = (identity dict, final path, scratch dir). Writes the inbox file; returns its path."""
    ident, final, tmp = job
    s = files_run.settings(cfg)
    exts = {r[0] for r in scratch.execute("SELECT code FROM ref_title_type WHERE retired_at IS NULL")} \
        if s["titles"] else set()
    state = member_titles.data_dir() / "member-state.tsv"
    cache = member_titles.open_cache()
    try:
        runs = member_titles.bump_runs(cache)
        full = not state.exists() or runs % max(1, int(s["full_every"])) == 0
        argv = [sys.executable, "-I", str(files_run.HERE / "filetree.py"),
                json.dumps(files_run.options(scratch, cfg, full)), "--state", str(state)]
        spool, new_state = os.path.join(tmp, "spool.jsonl"), state.with_name(".member-state.tmp")
        with open(spool, "w", encoding="utf-8") as sp, open(new_state, "w", encoding="utf-8") as st:
            work = files_run.stream(argv, float(s["budget_s"]) + 300,
                                    lambda lines: _pass_one(lines, Spool(ident, exts, (cache, s["meta"])), (sp, st)))
        member_titles.read_titles(cache, work.wanted, (s, tmp))
        _publish(spool, final, {"exts": exts, "db": cache, "meta": s["meta"]})
        if work.finished:
            os.replace(new_state, state)
    finally:
        cache.close()
    return final


def _publish(spool, final, cache):
    part = tmp_path(final)
    try:
        with open(part, "w", encoding="utf-8") as out:
            _pass_two(spool, out, cache)
        os.replace(part, final)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
