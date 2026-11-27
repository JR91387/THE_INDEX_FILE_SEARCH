# THE INDEX

**A catalog of what exists on your machines, kept up to date for you.**

THE INDEX answers "what is here, who owns it, what runs it, is it backed up, and what changed?"
in seconds. Plain scripts walk each machine on a schedule and record folders, scheduled jobs,
containers and backups in one SQLite file. You read a short front page and open the detail only
when a question needs it.

- **No dependencies.** Python 3.11+ standard library only.
- **No AI tokens spent scanning.** Collectors are plain scripts.
- **Nothing is erased.** Things that disappear are marked retired, so history stays.
- **Planned vs. suspicious change.** Declare a change ahead of time and it shows as expected;
  anything undeclared is flagged for review.
- **Blind spots are listed.** Folders it cannot read and machines it cannot reach are on the front page.
- **Finds folders and documents fast.** `the-index find` matches names, words inside names, document titles
  and front matter (author, tags) in milliseconds, for you or your AI agent (`--json`, MCP).

> Status: pre-alpha. Linux is tested; macOS and Windows code exists but has not been tried on a real machine yet.

## Quick start
```bash
pip install .                       # from a checkout (or run with PYTHONPATH=src)
the-index scan                      # first run creates the database, runs the collectors, writes the pages
the-index schedule        # run the scan daily in the background (systemd/cron, launchd, Task Scheduler)
the-index status          # prints the front page
the-index search disk     # ranked search; add --json for scripts and AI tools
the-index find tax return # folders and documents by name, title or tag
the-index watch           # optional: keep the index current as files change (quiet, low priority)
the-index serve           # review page on 127.0.0.1: open the printed link (Ctrl+C stops)
```
`schedule` writes `the-index.service` and `.timer` under `~/.config/systemd/user/` (daily, low CPU and disk
priority, random delay up to 1h, catches up after downtime); `schedule --remove` undoes it, `--print` only shows
them. Without a systemd user session it prints a crontab line instead. After every `scan` the Markdown pages (`index.md` first) and
`the_index.html` are written to `pages_dir`; you never need to run `pages` by hand. Set
`pages_on_scan = false` to turn that off. See `docs/CONFIG.md` for the config file.

## Use with an AI agent
`the-index mcp` is a read-only MCP server on stdin/stdout (standard library only, nothing extra to install):
```json
{"mcpServers": {"the-index": {"command": "the-index", "args": ["mcp"]}}}
```
Any MCP-capable client works. Tools: `find`, `tree`, `projects`, `folder`, `changes`, `describe`; they match the CLI commands.

## Single file
Build one runnable file (standard library only, no install step): `python3 tools/build_zipapp.py`, then run
`python3 dist/the-index.pyz scan`. On first run it unpacks its code into your cache dir (`~/.cache/the-index/`), then runs from there.

## Windows
Build `the-index-windows.zip` with `python tools/build_windows.py --download 3.12.8` (it checks the SHA-256 python.org
publishes), unzip it anywhere and run `the-index.cmd scan` in a terminal. It carries Python's official embeddable
package, so nothing needs installing.

## Layout
```
src/theindex/  engine: db, config, ingest, classify, declare, cli
src/theindex/schema/      SQL migrations, seeds, views (the rules live in SQL)
src/theindex/icons/       SVG status and content-type icons (loaded into the DB)
src/theindex/collectors/  standalone scripts that print JSON (run locally or over ssh)
examples/      sample config, purposes and links files
docs/          design, config reference, AI guide
tests/         unittest suite
```

## License
MIT. See `LICENSE`. Bundled icons: Tabler Icons (MIT), see `THIRD_PARTY_NOTICES.md`.
