# Performance

The bar is Everything (voidtools): results while you type, and an index that stays current without re-reading the
disk. THE INDEX is Python with SQLite, so it gets there by doing less work, not by doing work faster.

## Targets
Measured on the synthetic 1 M-file tree (`the-index bench --files 1000000`), warm cache. Each machine records its own
numbers; a slower machine is compared with its own bare-walk reference, not with these absolutes.

| Metric | Target |
|---|---|
| `find` from the command line, p95 | ≤ 60 ms |
| `find` in-process or over MCP, p95 | ≤ 15 ms |
| Rescan, nothing changed | ≤ 5 s |
| Rescan, 1 % of folders changed | ≤ 8 s |
| First scan | ≤ 1.5 × a bare `os.scandir` walk of the same tree |
| Database size | ≤ 200 bytes per file |
| `watch`: change visible in `find` | ≤ 3 s |

## Method
`the-index bench` builds a seeded synthetic tree in a temporary folder (or `--root`), runs each scenario, prints one
table and writes JSON. Nothing is sent anywhere. `THE_INDEX_PERF=1` runs `tests/test_perf_budget.py`, a 20 000-file
version whose limits scale with the bare walk on the same machine. A change to speed is kept only when it gains at
least 10 % on its own metric and loses nothing elsewhere.

## Results
(filled in by the measurement run)

## Strategy
(ranked, filled in by the measurement run)
