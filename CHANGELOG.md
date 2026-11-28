# Changelog

THE INDEX is pre-alpha. Versions are not tagged yet; each entry is one public snapshot of `main`.

## Unreleased

- README rebuilt as a short hub with a logo, screenshots and a how-it-works diagram; depth moved to the wiki.
- New root files: `CHANGELOG.md`, `CONTRIBUTING.md`, `AGENTS.md`, `SECURITY.md`, `PRIVACY.md`.
- Files we may not read never stop a scan and never look deleted: names-only folders list their files,
  locked folders are recorded as blind spots, and names that are not valid text are kept.
- A reusable test tree of awkward things to index (`tests/access_tree.py`): documents that work, broken ones,
  odd names, links, pipes and no-access cases.

## 2026-11-26: live updates, faster search and scans

- `the-index watch`: optional, quiet live updates (inotify on Linux; FSEvents and ReadDirectoryChangesW
  written but not yet tried on real machines).
- Substring matches inside names, faster `find` on large result sets, quicker CLI start.
- First scans rebuild the search index once; the database is compacted after a first scan.
- Windows: NTFS MFT listing when run as admin (not yet tried on a real machine).
- `docs/PERFORMANCE.md`: targets, measured results and ranked next steps; `the-index bench` reproduces them.

## 2026-11-26: first public release

- Collectors for folders, files, scheduled jobs, containers, backups and filesystems; one SQLite file.
- Change classes (expected, routine, suspicious, unreviewed), declared changes, review.
- `find`, `search`, `changes`, `status`, Markdown and HTML pages, `serve`, MCP server for AI agents.
- Document titles and front matter (author, tags, date) from Markdown, HTML, Office, ODF, EPUB and PDF.
- Fleet: `collect` on members, `pull` over ssh or a shared inbox on the hub; schedules for every OS.
