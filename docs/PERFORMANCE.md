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
One machine so far: Linux, 10 CPUs, Python 3.14, SQLite 3.46, synthetic tree on tmpfs (warm, no disk waits), 1 M
files in 49 000 folders. Before and after the speed work (`bench/baselines/host-a_linux_1m_*.json`):

| Metric | Before | After | Target |
|---|---|---|---|
| `find`, in-process / MCP, p95 | 137 ms | 12.5 ms | ≤ 15 ms ✓ |
| `find`, command line, p95 | 232 ms | 51.6 ms | ≤ 60 ms ✓ |
| Rescan, nothing changed | 3.9 s | 4.0 s | ≤ 5 s ✓ |
| Rescan, 1 % of folders changed | 3.4 s | 4.1 s | ≤ 8 s ✓ |
| First scan (incl. 20 000 titles) | 68.6 s | 30.6 s | ≤ 6.3 s (1.5 × the 4.2 s bare walk) ✗ |
| Database size | 192 B/file | 194–206 B/file (with substring search) | ≤ 200 ✓ fresh, ~ after rescans |
| `watch`: new file visible in `find` | — | 0.35 s (small tree), 1.27 s (1 M files) | ≤ 3 s ✓ |

What made the difference, and what did not:

| Change | Effect |
|---|---|
| Large plain searches read the index in order instead of ranking every hit | find 138 → 5 ms |
| Load modules on use, build only the needed subparsers, no argparse colour theme, plain Config class | CLI find 215 → 49 ms |
| Plugins call the query layer in-process | Flow Launcher query 90 → 57 ms; Albert ~5 ms |
| First load drops the search triggers, rebuilds the indexes once | first scan without titles 108 → 31 s |
| Trigram name index (substring search), detail none, no column sizes | +~10 B/file, `mber` in 5 ms |
| VACUUM once after a first load | −12 % size |
| `executemany` batches for new files | no gain, reverted |
| 8-thread walk | 10× slower (GIL contention on 3.14), not adopted |
| Dirty-only size rollups, parallel title reads | not needed: 0.1 s and 5.6 s of the run |

## Strategy (ranked, next)
1. **Measure on real machines.** All numbers above are one Linux box on tmpfs. Run `the-index bench` (or the
   `bench` GitHub Actions matrix) on macOS and Windows, on SSD and spinning disks with a cold cache; the walk,
   not Python, may dominate there, and that decides 2 and 5.
2. **Windows: verify the NTFS MFT listing and add the USN journal to `watch`.** This is how Everything lists a
   whole volume in seconds. The code exists (admin only) but has never run on Windows.
3. **Leaner scan stream.** File records repeat their folder's full path and are JSON-encoded and -decoded (about
   7 s of the 31 s first scan). Dropping the repeated `dir` field and using a compact record would cut that.
4. **Faster `watch` flushes on large indexes.** A flush loads every folder row of the device (~1 s at 49 000
   folders); load only the listed folders and their parents.
5. **Threads only with free-threaded Python.** On standard CPython a threaded walk is slower; re-measure with
   the free-threaded build (3.13t+) on a real disk before using threads.
6. **A compiled helper only if a target stays out of reach** after 1–4, and only as an optional, permissively
   licensed, vendored part (see Dependencies in DESIGN.md). The first-scan target is the only miss today: about
   10 s of it is SQLite inserting a million rows, which no walk speed-up removes.
