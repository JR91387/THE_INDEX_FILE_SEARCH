# SPDX-License-Identifier: MIT
"""Speed budgets on a 20 000-file synthetic tree, scaled to a bare walk on the same machine so slow machines
do not fail. Off by default (timing tests are noisy): run with THE_INDEX_PERF=1. Tighten as speed-ups land."""
import os
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401

from theindex import bench

BUDGET = {"first_scan_s": (25, 1.0), "rescan_unchanged_s": (3, 0.5), "rescan_1pct_s": (4, 0.5)}  # (x walk, + s)
FIND_P95_MS = 50


@unittest.skipUnless(os.environ.get("THE_INDEX_PERF") == "1", "set THE_INDEX_PERF=1 to run speed budgets")
class PerfBudgetTest(unittest.TestCase):
    def test_budgets(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = bench.run(20000, Path(tmp) / "b")
        walk = r["reference_walk_s"]
        for key, (times, plus) in BUDGET.items():
            self.assertLessEqual(r[key], walk * times + plus, f"{key} {r[key]} s vs walk {walk} s")
        self.assertLessEqual(r["find_inproc_p95_ms"], FIND_P95_MS)
