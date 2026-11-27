# SPDX-License-Identifier: MIT
"""Member side: `collect --out` on a small temp tree, its inbox files, the title cache, mount sources."""
import json
import os
import re
import tempfile
from pathlib import Path
from unittest import mock

import test_inbox

from theindex import config, identity, inbox, member, member_titles


class CollectOutTest(test_inbox.InboxCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.root = base / "data"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "plan.md").write_text("---\ntitle: Garden plan\n---\nbody\n")
        (self.root / "top.bin").write_bytes(b"t" * 20)
        env = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(base / "share")})
        env.start()
        self.addCleanup(env.stop)
        patch = mock.patch.object(identity, "machine_id", return_value="member-one")
        patch.start()
        self.addCleanup(patch.stop)
        self.cfg = config.Config(device_name="host-m", collectors=["filesystems", "filetree"])
        self.cfg.filetree = {"roots": [str(self.root)]}
        self.out = base / "out"

    def test_member_sends_meta_and_rereads_cache_rows_without_it(self):
        (self.root / "docs" / "post.md").write_text("---\nauthor: Alice\ntags: [a]\n---\n# Post\n")

        def records(paths):
            tree = next(p for p in paths if p.suffix == ".jsonl")
            return {r["name"]: r for r in map(json.loads, tree.read_text().splitlines()) if r.get("t") == "file"}

        self.cfg.filetree["full_every"] = 1                                # every run lists every file
        first = records(member.run(self.cfg, self.out))
        self.assertEqual(first["post.md"]["meta"], {"author": "Alice", "tags": ["a"]})
        self.assertEqual(first["plan.md"]["meta"], {})
        cache = member_titles.open_cache()
        cache.execute("UPDATE titles SET meta = NULL")                     # a cache written before front matter existed
        cache.close()
        self.assertEqual(records(member.run(self.cfg, self.out))["post.md"]["meta"], {"author": "Alice", "tags": ["a"]})

    def test_collect_writes_named_atomic_files_and_the_hub_ingests_them(self):
        paths = member.run(self.cfg, self.out)
        names = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(names, sorted(p.name for p in paths))
        pattern = r"^[0-9a-f]{32}_(filesystems_\d{8}T\d{6}Z\.json|filetree_\d{8}T\d{6}Z\.jsonl)$"
        self.assertTrue(all(re.match(pattern, n) for n in names), names)
        self.assertEqual(len(names), 2)                                  # no .tmp- leftovers
        tree = next(p for p in paths if p.suffix == ".jsonl")
        records = [json.loads(line) for line in tree.read_text().splitlines()]
        self.assertEqual(records[0]["host"], "host-m")
        self.assertEqual(records[0]["machine"], identity.machine_hash())
        self.assertRegex(records[0]["payload_id"], r"^[0-9a-f]{32}$")
        plan = next(r for r in records if r.get("name") == "plan.md")
        self.assertEqual((plan["title"], plan["title_sig"]), ("Garden plan", f"{plan['size']}:{plan['mtime_ns']}"))
        self.assertEqual(inbox.drain(self.conn, self.out, "host-a")["ingested"], 2)
        self.assertEqual(self.one("SELECT title FROM v_files WHERE device = 'host-m' AND name = 'plan.md'"),
                         "Garden plan")
        self.assertEqual(self.devices().count("host-m"), 1)

    def test_second_run_skips_unchanged_dirs_and_reuses_titles(self):
        member.run(self.cfg, self.out, "filetree")
        with mock.patch("theindex.member_titles.files_run.stream", wraps=member.member_files.files_run.stream) as s:
            second = member.run(self.cfg, self.out, "filetree")
        self.assertEqual(len(s.call_args_list), 1)                       # filetree only: no titles.py run
        records = [json.loads(line) for line in second[0].read_text().splitlines()]
        self.assertTrue(any(r["t"] == "skip" for r in records))
        self.assertTrue((Path(os.environ["XDG_DATA_HOME"]) / "the-index" / "member-state.tsv").exists())

    def test_unknown_collector_is_an_error(self):
        with self.assertRaises(KeyError):
            member.run(self.cfg, self.out, "nope")

    def test_runs_in_the_same_second_never_overwrite(self):
        first = member.run(self.cfg, self.out, "filesystems")
        second = member.run(self.cfg, self.out, "filesystems")
        self.assertNotEqual(first[0], second[0])
        self.assertEqual(len(list(self.out.iterdir())), 2)

    def test_new_document_title_is_read_once_and_cached(self):
        member.run(self.cfg, self.out, "filetree")
        (self.root / "b.md").write_text("# Second note\n")
        third = member.run(self.cfg, self.out, "filetree")
        records = [json.loads(line) for line in third[0].read_text().splitlines()]
        note = next(r for r in records if r.get("name") == "b.md")
        self.assertEqual(note["title"], "Second note")
        cache = member.member_files.member_titles.open_cache()
        self.addCleanup(cache.close)
        self.assertEqual(cache.execute("SELECT title FROM titles WHERE path_key LIKE '%/b.md'").fetchone()[0],
                         "Second note")


class MountSourceTest(test_inbox.InboxCase):
    def test_linux_sources_carry_fstype_and_source(self):
        from theindex.collectors import filetree_net as net
        text = "host-b:/export /mnt/a nfs4 rw 0 0\n//host-b/s /mnt/b cifs rw 0 0\n/dev/sda1 / ext4 rw 0 0\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=text)):
            found = net.linux_sources()
        self.assertEqual(found, {"/mnt/a": "nfs4 host-b:/export", "/mnt/b": "cifs //host-b/s"})
