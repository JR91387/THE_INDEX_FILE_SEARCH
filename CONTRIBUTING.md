# Contributing

Thanks for looking. THE INDEX is pre-alpha, so issues describing what you tried and what happened are as
useful as code.

## Setup

```bash
git clone https://github.com/JR91387/THE_INDEX_FILE_SEARCH.git
cd THE_INDEX_FILE_SEARCH
python3 -m unittest discover -s tests     # Python 3.11+, nothing to install
```

Run the code without installing: `PYTHONPATH=src python3 -m theindex --db /tmp/t.db scan`.

## Rules the tests enforce

- **Standard library only.** No third-party dependencies (`dependencies = []` in `pyproject.toml`).
- **Small units.** File ≤ 200 lines, function ≤ 50 lines, ≤ 4 parameters, nesting ≤ 3 (`tests/test_hygiene.py`).
- **License header.** Every `.py` and `.sql` file starts with `SPDX-License-Identifier: MIT`.
- **Nothing is deleted.** Database rows are retired, never removed; `BEFORE DELETE` triggers abort.
- **Generic examples.** Use `host-a`, `/srv/data` and `alice` in code, tests and docs, never a real machine,
  path or person.
- **Lint.** `ruff check .` must be clean.

## Before a pull request

```bash
python3 -m unittest discover -s tests
ruff check .
```

Keep a pull request to one change, say what it fixes or adds, and add a test that fails without it.
Design notes live in `docs/DESIGN.md`; the payload contract for collectors is `src/theindex/collectors/README.md`.

Security problems: please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
