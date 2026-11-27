# SPDX-License-Identifier: MIT
"""bench: the synthetic tree is the same for the same seed, and a small run reports every metric."""
import os
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts src/ on the path)

from theindex import bench, bench_tree


def listing(root):
    return sorted((os.path.relpath(p, root), tuple(sorted(f))) for p, _, f in os.walk(root))


class BenchTest(unittest.TestCase):
    def test_tree_is_deterministic(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(bench_tree.make(Path(a) / "t", 3000), bench_tree.make(Path(b) / "t", 3000))
            self.assertEqual(listing(Path(a) / "t"), listing(Path(b) / "t"))
            files, _ = bench_tree.make(Path(a) / "u", 3000)
            self.assertEqual(bench_tree.reference_walk(Path(a) / "u"), files)

    def test_small_run_reports_every_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = bench.run(2000, Path(tmp) / "b")
        for key in ("reference_walk_s", "first_scan_s", "rescan_unchanged_s", "rescan_1pct_s",
                    "find_inproc_p95_ms", "find_cli_p95_ms", "db_bytes_per_file"):
            self.assertIn(key, result)
        self.assertGreater(result["titles_read"], 0)
        self.assertIn("SQLite", bench.table(result))
