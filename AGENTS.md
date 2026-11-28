# AGENTS.md

Instructions for AI coding agents working on this repository. Using THE INDEX *from* an agent (MCP, `--json`)
is a different topic: see `docs/AI_GUIDE.md`.

## What this is

A self-updating catalog of what exists on a machine (folders, files, scheduled jobs, containers, filesystems,
backups) and what changed. Pipeline: **collector script → JSON payload → ingest → SQLite → views → pages, CLI, MCP.**

## Hard rules

- Python ≥ 3.11, standard library only. Never add a dependency.
- File ≤ 200 lines, function ≤ 50, parameters ≤ 4, nesting ≤ 3; `SPDX-License-Identifier: MIT` on every
  `.py` and `.sql`. `tests/test_hygiene.py` enforces all of this.
- Never DELETE rows: retire them. `BEFORE DELETE` triggers abort.
- Use generic names in code, tests and docs (`host-a`, `/srv/data`, `alice`). Never write a real hostname,
  IP, username, path or secret.
- Collectors (`src/theindex/collectors/*.py`) are standalone scripts with no package imports, so they can run
  over `ssh host python3 - < script.py`. Keep them that way.

## Commands (run from the repo root)

```bash
python3 -m unittest discover -s tests                         # full suite
python3 -m unittest discover -s tests -p test_ingest.py       # one file
python3 -m unittest discover -s tests -k test_gone_then_back  # one test
ruff check .                                                  # lint (must be clean)
PYTHONPATH=src python3 -m theindex --db /tmp/t.db scan --measure-all
```

Tests import `helpers` as a top-level module, so always use `-s tests`; `python3 -m unittest tests.test_x` fails.

## Where things are

- `src/theindex/schema/`: numbered migrations run once; `seed_*.sql`, `views*.sql` and `search.sql` are
  re-applied on every open and must stay idempotent.
- `ingest.py`: records one run atomically; only `ok` runs retire items, and only under the payload's coverage.
- `classify.py`: declared change → expected; first scan → routine; rule hit → suspicious; else unreviewed.
- SQLite: always open through `db.connect()` (foreign keys on); connections use `isolation_level=None`.
- Design: `docs/DESIGN.md`. Config: `docs/CONFIG.md`. Payload contract: `src/theindex/collectors/README.md`.
