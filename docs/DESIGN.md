# Design

THE INDEX is a catalog: what exists, where, who owns it, what runs it, is it backed up, and what changed.
Collectors (plain scripts) observe; the engine records; views answer questions; pages present them.

## Data model
| Group | Tables |
|---|---|
| Lookups (id + unique `code`, icon) | `ref_*` -- every coded value; plugins add rows with `is_builtin = 0` |
| What exists | `device`, `scan_run`, `item` (attrs JSON), `item_version`, `metric_sample`, `item_link`, `folder_content` |
| Explanations | `purpose` (from the purposes file), `gap` (blind spots) |
| Change | `change`, `declared_change` |

- **attrs vs metrics.** attrs (owner, mode, command, image, state...) are diffed: any change is a `change`
  row and a new `item_version`. Metrics (size, next run...) are samples; they only become a change when they
  cross a limit (`threshold`).
- **Nothing is erased.** DELETE aborts on every table except `purpose`. Gone items get `retired_run`.
- **Retirement is conservative.** Only OK runs retire, and only under `coverage` prefixes.
- **Icons** are SVG text (`currentColor`, theme-aware) with an emoji fallback, loaded from `src/theindex/icons/`.
  They are Tabler Icons (MIT), bundled in the repo; see `THIRD_PARTY_NOTICES.md`. Plugin icons must be MIT-compatible.

## Change classes (first match wins)
| Class | When |
|---|---|
| expected | Matches an active, unexpired declared change (key glob, device, kind, action) |
| routine | First scan of a collector (baseline), or only routine fields changed |
| suspicious | New job; job command/user changed; owner/group/mode changed; container gone; backup shrank past `size_drop_suspicious`; folder content flips to unknown/archive |
| unreviewed | Everything else |

## Schema files
| Kind | Files | Applied |
|---|---|---|
| Migrations | `NNN_*.sql` | Once each, tracked by `PRAGMA user_version` |
| Re-applied | `seed_*.sql`, `views.sql`, `search.sql`, icons | Every init/upgrade (idempotent) |

## Roadmap
Done: Markdown pages written after every scan (`pages_on_scan`), a self-contained `the_index.html`
snapshot, `search --json`, and the on-demand `serve` review mode.
Next: see the sections below. Not built yet: ssh pull, a Windows `.exe`, full front matter, live file watchers.

## Locations and files
Scope: THE INDEX helps an LLM **find** a location or a document. It records folders, file names, sizes,
dates and document titles. It never stores or indexes file body text.

| Table | One row per | Notes |
|---|---|---|
| `dir` | directory walked by `filetree` | `size_bytes`/`file_count` = direct files; `size_total`/`files_total` = whole subtree (rolled up in SQL after each run); `agent_files` = AI-project markers found in it; `is_cache` = counted, not listed |
| `file` | non-cache file | name, ext, size, mtime, inode; `title`, `title_src`, `title_sig`; `first_seen_run`, `title_run`, `retired_run` |

- **Updated in place.** File rows carry no history. Documents (title types) record events as columns:
  `first_seen_run`, `title_run` (title changed), `retired_run`. `v_file_events` exposes them to
  `changes --since`; they are never front-page changes. Nothing is deleted: gone rows are retired and
  revived if they come back.
- **Skip unchanged folders.** A directory's mtime changes only when an entry is added, removed or renamed.
  The collector gets the last-seen `mtime_ns`/`ctime_ns` per directory; an unchanged directory is not
  listed again (its files are carried), but its subdirectories are still visited. ctime is compared on
  POSIX only (on Windows `st_ctime` is the creation time). Every `full_every`-th run lists everything.
  File sizes inside an unchanged directory refresh on the full run.
- **Cache directories** (`node_modules`, `.git`, `__pycache__`, `.venv`, `CACHEDIR.TAG`...) count toward
  totals but get no file rows; their totals refresh when their own mtime changes and on the full run.
- **AI-project markers** (`ref_agent_marker`: `AGENTS.md`, `CLAUDE.md`, `.claude`, `GEMINI.md`,
  `.cursor`...) are recorded on any directory at any depth; `v_projects` lists them.
- **Size tree.** `v_tree` gives each directory's total and its share of the parent; `v_dirs_largest`
  the biggest.

## Titles
Title types: `.md .markdown .html .htm .docx .xlsx .pptx .odt .ods .odp .epub .pdf`. A title is read when
`title_sig` (`size:mtime_ns`) differs from the stored one, from at most the first 64 KB (PDF: first and
last 64 KB; zip members at most 1 MB uncompressed). Sources in order: Markdown front matter `title:`, first
`# ` heading; HTML `<title>`; Office/ODF/EPUB metadata XML; PDF XMP `dc:title`, then Info `/Title`.
Nightly cap `title_budget`. Errors give no title and are never fatal. `titles = false` turns reading off.
**Front matter** comes from the same read: `author`, `date`, `tags` (at most 20), `description`, `lang`, each at most
300 characters, control characters removed. Sources: Markdown YAML front matter (scalars, `[a, b]` and `- a`
lists), HTML `<meta name=author|description|keywords>` and `<html lang>`, OOXML `docProps/core.xml`, ODF `meta.xml`,
EPUB OPF, PDF Info/XMP. Stored as `file.meta` JSON; author, tags and description are searchable (`file_fts.meta`).
`meta = false` keeps titles only. Body text is never read beyond the first 64 KB and never stored.

## Agent interface
CLI `--json` and an MCP server (`the-index mcp`, stdio JSON-RPC) share one query layer (`query.py`).
Every JSON answer is `{"schema_version": 1, "query": {...}, "results": [...], "more": N}`; default limit
25, maximum 500; `more` counts what was left out. `the-index describe --json` lists commands, fields and
filters so an unfamiliar agent can learn the tool. File names, titles and paths are untrusted text: they
are returned only as data fields, never mixed into prose. The database is read-only for queries.
`find` ranks by relevance when a search matches at most 2 000 rows or uses a filter; a larger plain search returns
folders, then name matches, then title and front-matter matches, newest first, straight from the index, with an
exact `more` count (relevance over tens of thousands of hits costs ~100 ms and tells little).
When a search finds fewer than its limit, file names containing every word (each at least 3 characters) as a
substring fill the rest, like Everything (`mber` finds `amber_notes.txt`), from a trigram index on names
(`file_name_tri`, about 10 bytes per file); those extra matches are counted up to 1 000.

## Fleet
- One SQLite database, one writer: the **hub**. Members run `the-index collect --out DIR`, which writes
  each payload atomically into a shared inbox; the hub runs `the-index ingest --inbox DIR` (also part of
  `scan` when `[inbox] role = "hub"`). Ingested files move to `done/YYYY-MM/`, malformed ones to `bad/`.
  A payload id makes re-ingest a no-op (`inbox_receipt`). Devices ingested from the inbox get reach `inbox`.
  Members read document titles themselves (cache keyed by `size:mtime_ns`) and send them with the file records.
- **Identity:** a device is keyed by `machine_hash` = sha256 of `the-index:` + the OS machine id
  (`/etc/machine-id`, macOS IOPlatformUUID, Windows MachineGuid). The name is only a label.
- **Paths:** `path_key` = NFC Unicode, `/` separators, case-folded on case-insensitive volumes; the
  display path is kept as found.
- **Owner-only disks:** network mounts are never walked; they become a `network` gap (or a `mounts` link
  to the serving device when known). The gap reason names the source (`nfs host-b:/export`) and `v_network_mounts`
  shows `served_by` when a known device is named. Each disk is indexed once, by its own machine.
- **ssh pull:** `the-index pull [HOST...]` (and `scan` on a hub, for `[[pull]]` hosts) runs
  `ssh -o BatchMode=yes HOST the-index collect --out -` with the running user's own keys (never a prompt). The
  member streams framed payloads: one line `#the-index-payload <name> <bytes>`, then exactly that many bytes. The
  hub writes each frame into the inbox atomically and drains it with the inbox code; an unreachable host or a bad
  frame is one gap for that host. THE INDEX must be installed on the member, which keeps its own scan state.
- **Schedules:** `the-index schedule [--role hub|member]` installs the OS's own timer: a systemd user timer (or a
  printed crontab line) on Linux, a LaunchAgent on macOS, a Task Scheduler task on Windows (current user, no admin,
  low priority). A hub runs `scan --quiet`, a member `collect` (silent on success).

## OS sources
`[sources] native = "auto"` uses an index the OS already keeps (plocate on Linux, Spotlight on macOS,
Everything on Windows) when present. The walk still runs every `full_every`-th night and differences
become an `index_mismatch` gap. A native source never retires rows on its own.
What each gives: **plocate/locate** (Linux) names only, so each path is stat-ed for size and times, and a database
older than 2 days counts as absent; **Spotlight** (macOS) names via `mdfind`, plus document titles via `mdls`
(stored with `title_src` `native`, so those files are never opened); **Everything** (Windows) names via its `es`
command line, found on PATH and never bundled; as Administrator on NTFS the **MFT** source (Everything's
method: the USN file table via `DeviceIoControl`, then stat per file) goes first, UNVERIFIED on a real Windows host.
A native listing is complete for its root: no `skip` records,
header `no_retire: true`. Any failure prints a `partial` trailer and the same scan falls back to the walk.

## Offline catalogs
`the-index catalog import FILE --name NAME` loads an Everything file list (EFU, CSV) or our JSON Lines as a
device with reach `offline`, so unplugged drives and backups stay findable. `catalog export` writes one
from the database.

## Dependencies
Standard library only. Dependencies earn their place; none has yet. If one ever does, it must be MIT, BSD
or Apache-2.0 and live in `src/theindex/_vendor/<package>/` exactly as released (LICENSE kept, pinned in
`_vendor/VENDOR.toml` with source, version and file hashes, imports rewritten, never edited by hand; local
patches in `patches/vendor/`).
**Windows bundle:** `tools/build_windows.py` assembles, on any OS, a zip with Python's official embeddable package
(PSF license), THE INDEX under `lib/` (added to the `python3XX._pth` file, since embeddable Python ignores
`PYTHONPATH`) and `the-index.cmd`. Nothing to install; unzip and run. A true single-file .exe is left to a CI job.

## Live updates
`the-index watch` (off unless `[watch] enabled = true` or started by hand) listens to the OS change feed:
inotify on Linux, FSEvents on macOS, `ReadDirectoryChangesW` on Windows (the USN change journal when run as admin).
Events are debounced (`debounce_s`) into a set of changed directories; each is listed alone (header `targeted`,
which retires only inside the listed directories) through the normal ingest, then titles and front matter for
changed documents. A full event queue, or too few inotify watches, marks the next scan as a full walk and opens one
gap. It prints nothing and runs at low priority; the scheduled scan stays the safety net.

## Performance
Targets, method and measured results are in `docs/PERFORMANCE.md`; `the-index bench` reproduces them on any machine.
