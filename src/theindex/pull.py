# SPDX-License-Identifier: MIT
"""Hub side of `the-index pull`: fetch framed payloads from members over ssh into the inbox, then drain it.

Per host: `ssh -o BatchMode=yes -o ConnectTimeout=10 [ssh_options] HOST COMMAND collect --out -`. Each complete
frame is written to `.<name>.part` and renamed into the inbox. A truncated frame goes to `bad/` (moved, never
deleted). A host that fails (exit code, timeout, bad or short frame) is one `no_route` gap on the hub and one
stderr line; the other hosts carry on."""
import os
import shlex
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from . import frames, gaps, inbox, ingest

CHUNK = 1 << 20


def select(cfg, hosts):
    """Pull tables to use: the named hosts (config settings when listed there) or every configured one."""
    if not hosts:
        return list(cfg.pulls)
    known = {p["host"]: p for p in cfg.pulls}
    default = {"ssh_options": [], "timeout_s": 900, "command": "the-index"}
    return [known.get(h) or {"host": h, **default} for h in hosts]


def argv(spec):
    remote = " ".join(shlex.quote(w) for w in (*shlex.split(spec["command"]), "collect", "--out", "-"))
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", *spec["ssh_options"], spec["host"], remote]


def safe_name(name):
    return bool(name) and "/" not in name and "\\" not in name and not name.startswith(".") and "\0" not in name


def _frame(stream, box):
    """Read one frame into the inbox. Returns False at a clean end; raises ValueError on a damaged stream."""
    line = stream.readline()
    if not line:
        return False
    name, size = frames.read_header(line)
    part = box / f".{name}.part" if safe_name(name) else None
    left = size
    with open(part or os.devnull, "wb") as sink:      # a refused name is read and thrown away
        while left:
            data = stream.read(min(CHUNK, left))
            if not data:
                break
            left -= len(data)
            sink.write(data)
    if part is None:
        raise ValueError(f"refused payload name {name!r}")
    if left:
        inbox._move(part, box / "bad")
        raise ValueError(f"truncated frame {name}: {size - left} of {size} bytes")
    os.replace(part, box / name)
    return True


def _read_all(proc, box):
    """Read frames until the stream ends. Returns the problem text, or None."""
    try:
        while _frame(proc.stdout, box):
            pass
    except (ValueError, OSError) as exc:
        proc.kill()
        return str(exc)
    return None


def fetch(spec, box):
    """Pull one host. Returns an error text, or None on success. Complete frames are kept either way."""
    box.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as err:
        return _fetch(spec, box, err)


def _fetch(spec, box, err):
    try:
        proc = subprocess.Popen(argv(spec), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err)
    except OSError as exc:
        return f"cannot run ssh ({exc})"
    fired = threading.Event()
    timer = threading.Timer(spec["timeout_s"], lambda: (fired.set(), proc.kill()))
    timer.start()
    try:
        problem = _read_all(proc, box)
    finally:
        timer.cancel()
        proc.stdout.close()
        code = proc.wait()
    if fired.is_set():
        return f"timed out after {spec['timeout_s']}s"
    if problem is None and code == 0:
        return None
    err.seek(0)
    tail = err.read().decode("utf-8", "replace").strip().splitlines()[-1:] or [f"exit {code}"]
    return problem or f"ssh exit {code}: {tail[0]}"[:300]


def record_gaps(conn, hub, failed):
    """One gap per failed host on the hub; gaps of hosts that now answer are closed (this collector's only)."""
    open_gaps = conn.execute("SELECT 1 FROM gap g JOIN ref_collector c ON c.id = g.collector_id JOIN device d "
                             "ON d.id = g.device_id WHERE c.code = 'pull' AND g.closed_run IS NULL "
                             "AND d.name = ?", (hub,)).fetchone()
    if not failed and not open_gaps:
        return
    conn.execute("BEGIN")
    ctx = ingest.start_run(conn, ingest.ensure_device(conn, hub), {"collector": "pull"})
    gaps.sync(conn, ctx, [{"kind": "no_route", "target": h, "reason": r} for h, r in failed], True)
    ingest.finish_run(conn, ctx, {"items": [], "errors": []}, "ok")
    conn.execute("COMMIT")


def fetch_all(specs, folder):
    """Fetch every spec into `folder`. Returns [(host, error)] for hosts that failed (one stderr line each)."""
    box, failed = Path(folder).expanduser(), []
    for spec in specs:
        error = fetch(spec, box)
        if error:
            failed.append((spec["host"], error))
            print(f"pull: {spec['host']}: {error}", file=sys.stderr)
    return failed


def run(conn, cfg, specs, folder):
    """Fetch, drain the inbox, record gaps. Returns the failed [(host, error)]."""
    failed = fetch_all(specs, folder)
    if specs:
        inbox.drain(conn, Path(folder).expanduser(), cfg.device_name)
        record_gaps(conn, cfg.device_name, failed)
    return failed
