# SPDX-License-Identifier: MIT
"""`pull`: a stub `ssh` on PATH prints framed payloads chosen by host name. No real hosts."""
import io
import os
import stat
import tempfile
from pathlib import Path
from unittest import mock

import test_inbox
from test_inbox import M1, M2, jobs_file

from theindex import config, config_inbox, frames, identity, member, pull

STUB = """#!/bin/sh
echo "$@" >> "$FIX/calls.log"
for a in "$@"; do before=$last; last=$a; done
host=$before
[ -f "$FIX/$host.bin" ] && cat "$FIX/$host.bin"
exit "$(cat "$FIX/$host.rc" 2>/dev/null || echo 0)"
"""


def frame(name, data):
    return frames.header(name, len(data)) + data


class PullCase(test_inbox.InboxCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fix = Path(tmp.name)
        bindir = self.fix / "bin"
        bindir.mkdir()
        ssh = bindir / "ssh"
        ssh.write_text(STUB)
        ssh.chmod(ssh.stat().st_mode | stat.S_IXUSR)
        env = mock.patch.dict(os.environ, {"PATH": f"{bindir}:/usr/bin:/bin", "FIX": str(self.fix)})
        env.start()
        self.addCleanup(env.stop)
        self.cfg = config.Config(device_name="host-a")

    def host(self, name, data=b"", rc=0):
        (self.fix / f"{name}.bin").write_bytes(data)
        (self.fix / f"{name}.rc").write_text(str(rc))

    def specs(self, *hosts):
        return pull.select(self.cfg, list(hosts))

    def pull(self, *hosts):
        return pull.run(self.conn, self.cfg, self.specs(*hosts), self.box)

    def gaps(self):
        return [tuple(r) for r in self.conn.execute(
            "SELECT device, target FROM v_gaps_open WHERE kind = 'no_route' ORDER BY target")]


class PullTest(PullCase):
    def test_good_host_is_ingested_and_silent(self):
        self.host("host-b", frame("m1_jobs_1.json", jobs_file("p1", M1, "host-b").encode())
                  + frame("m1_jobs_2.json", jobs_file("p2", M1, "host-b").encode()))
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(self.pull("host-b"), [])
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(self.one("SELECT count(*) FROM inbox_receipt WHERE status = 'ingested'"), 2)
        self.assertEqual(len(self.moved("done")), 2)
        self.assertEqual(self.gaps(), [])
        calls = (self.fix / "calls.log").read_text()
        self.assertIn("-o BatchMode=yes -o ConnectTimeout=10 host-b the-index collect --out -", calls)

    def test_down_host_is_one_gap_and_others_continue(self):
        self.host("host-b", rc=255)
        self.host("host-a2", frame("x.json", jobs_file("p1", M1, "host-a2").encode()))
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            failed = self.pull("host-b", "host-a2")
        self.assertEqual([h for h, _ in failed], ["host-b"])
        self.assertEqual(err.getvalue().count("\n"), 1)
        self.assertEqual(self.gaps(), [("host-a", "host-b")])
        self.assertEqual(self.one("SELECT count(*) FROM inbox_receipt WHERE status = 'ingested'"), 1)
        self.host("host-b")                                           # comes back: the gap closes
        self.assertEqual(self.pull("host-b"), [])
        self.assertEqual(self.gaps(), [])

    def test_truncated_frame_goes_to_bad_and_good_frames_are_kept(self):
        good = frame("m2_jobs_1.json", jobs_file("p3", M2, "host-c").encode())
        self.host("host-c", good + frames.header("m2_jobs_2.json", 500) + b'{"half":')
        with mock.patch("sys.stderr", new=io.StringIO()):
            failed = self.pull("host-c")
        self.assertIn("truncated", failed[0][1])
        self.assertEqual([p.read_bytes() for p in self.moved("bad")], [b'{"half":'])
        self.assertEqual(self.one("SELECT count(*) FROM inbox_receipt WHERE status = 'ingested'"), 1)
        self.assertEqual(self.gaps(), [("host-a", "host-c")])
        self.assertEqual([p.name for p in self.box.iterdir() if p.name.startswith(".")], [])

    def test_unsafe_names_refused_but_stream_stays_in_step(self):
        data = (frame("../evil.json", b"{}") + frame(".hidden.json", b"{}") + frame("a\\b.json", b"{}")
                + frame("ok.json", jobs_file("p4", M1, "host-b").encode()))
        self.host("host-b", data)
        with mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(len(self.pull("host-b")), 1)
        self.assertFalse((self.box.parent / "evil.json").exists())
        self.assertEqual(self.one("SELECT count(*) FROM inbox_receipt WHERE status = 'ingested'"), 0)

    def test_repulled_payload_is_a_duplicate(self):
        self.host("host-b", frame("m1_jobs_1.json", jobs_file("p1", M1, "host-b").encode()))
        self.pull("host-b")
        self.pull("host-b")
        self.assertEqual(self.one("SELECT count(*) FROM inbox_receipt WHERE status = 'ingested'"), 1)
        self.assertEqual(len(self.moved("done")), 2)

    def test_config_hosts_and_options(self):
        cfg = config.Config()
        cfg.pulls = config_inbox.pulls([{"host": "alice@host-b", "ssh_options": ["-p", "2222"], "command": "my idx"}])
        spec = pull.select(cfg, [])[0]
        self.assertEqual(spec["timeout_s"], 900)
        self.assertEqual(pull.argv(spec), ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-p", "2222",
                                          "alice@host-b", "my idx collect --out -"])
        for bad in ([{}], [{"host": "h", "ssh_options": "x"}], [{"host": "h", "timeout_s": 0}]):
            with self.assertRaises(ValueError):
                config_inbox.pulls(bad)

    def test_timeout_kills_a_hung_host(self):
        slow = self.fix / "bin" / "ssh"
        slow.write_text("#!/bin/sh\nexec sleep 30\n")
        spec = {**self.specs("host-b")[0], "timeout_s": 1}
        with mock.patch("sys.stderr", new=io.StringIO()):
            failed = pull.fetch_all([spec], self.box)
        self.assertIn("timed out", failed[0][1])


class FramingTest(test_inbox.InboxCase):
    def test_collect_out_dash_frames_every_payload(self):
        cfg = config.Config(device_name="host-m", collectors=["filesystems"])
        buf = io.BytesIO()
        with mock.patch.object(identity, "machine_id", return_value="member-one"):
            self.assertEqual(frames.stream_collect(cfg, None, buf), 0)
            written = member.run(cfg, self.box)
        data, seen = buf.getvalue(), []
        while data:
            line, data = data.split(b"\n", 1)
            name, size = frames.read_header(line)
            seen.append((name, data[:size]))
            data = data[size:]
        self.assertEqual(len(seen), len(written))
        self.assertTrue(seen[0][0].endswith(".json") and seen[0][1].startswith(b"{"))


class CollectCliTest(test_inbox.InboxCase):
    def test_silent_by_default_verbose_prints_paths_quiet_accepted(self):
        from test_cli_errors import run
        cfg = self.box.parent / "c.toml"
        cfg.write_text('[schedule]\ncollectors = ["filesystems"]\n')
        with mock.patch.object(identity, "machine_id", return_value="member-one"):
            base = ("--config", str(cfg), "--db", str(self.box.parent / "i.db"), "collect", "--out", str(self.box))
            self.assertEqual(run(*base)[:2], (0, ""))
            self.assertEqual(run(*base, "--quiet")[:2], (0, ""))
            code, out, _ = run(*base, "--verbose")
        self.assertEqual(code, 0)
        self.assertTrue(out.strip() and all(Path(l).exists() for l in out.split()))
