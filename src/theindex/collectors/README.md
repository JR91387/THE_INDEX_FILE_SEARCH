# Collectors

A collector is one or more **standalone** Python scripts (stdlib only, no package imports), so any of them
can run on a remote machine with nothing installed: `ssh host python3 - < jobs_cron.py`.
Each prints one JSON document; the engine merges a collector's scripts and ingests the result.

```json
{
  "collector": "jobs",            "script": "jobs_cron",       "host": "host-a",
  "kinds": ["job"],               "status": "ok | partial | failed",
  "started_at": "2026-01-01T00:00:00Z", "finished_at": "...",
  "items":    [{"kind": "job", "key": "crontab:alice:1a2b3c", "attrs": {}, "metrics": {}}],
  "coverage": ["crontab:alice:"],
  "links":    [],
  "gaps":     [{"kind": "denied", "target": "/var/spool/cron/crontabs", "reason": "..."}],
  "errors":   []
}
```

| Field | Meaning |
|---|---|
| `attrs` | Fields whose change matters. Hashed and diffed; a change creates a history row. |
| `metrics` | Numbers that move every run (`next_run`, `size_bytes`...). Codes from `ref_metric`. |
| `coverage` | Key prefixes this run listed **in full**. Unseen items are retired only under these. |
| `gaps` | What could not be seen. Kinds from `ref_gap_kind`. |
| `status` | `partial` or `failed` runs never retire anything. |
| `coverage_except` | Prefixes inside a covered area that could not be listed (never retired). |
| `carry` (per item) | attrs kept from the stored item when not measured this run. |
| `content` (per item) | `[{"type", "files", "bytes"}]` content mix of a measured folder. |

| Collector | Scripts |
|---|---|
| `folders` | `folders.py` (read-only walk, rotation, content detection; optional sudo via contrib/) |
| `jobs` | `jobs_cron.py`, `jobs_systemd.py` |
| `containers` | `containers.py` (docker CLI; mounts become `mounts` links) |
| `filesystems` | `filesystems.py` (/proc/self/mounts + statvfs with a timeout) |
| `backups` | `backups.py` (checks from `[[backups]]`, passed as one JSON argument) |
| `filetree` | `filetree.py` (directories and files, JSON Lines, skips unchanged directories) + `titles.py` (document titles from a worklist) |

`links` (optional): `[{"from": ["container", "app"], "type": "mounts", "to": ["folder", "/srv/app"]}]`.
A link is stored once both ends exist on the device; until then it is counted as unresolved.

**folders options** (one JSON argument): `roots`, `depth`, `slots`/`slot` (rotation), `exclude`, `budget_s`, `ext`,
`markers`, `mixed_threshold`. `exclude` is added to a built-in list (`/var/lib/docker`, `/var/lib/containers`,
`/var/lib/snapd`, `/var/cache`, `/proc`, `/sys`, `/dev`, `/run`, any `lost+found`); an entry without `/` matches a
folder name anywhere. `budget_s` (default 1800) limits the walk: a rotation unit still unfinished is not measured,
gets a `not_visible` gap ("budget exceeded") and keeps its previous values through `carry`.

**Running as root (`[folders] sudo = true`):** the launcher is the fixed command
`sudo -n /usr/bin/python3 -I /usr/local/lib/the-index/folders_root.py`. A launcher gets its arguments on
**stdin** (one per line; for folders, the options JSON), never on the command line. `folders_root.py` takes
`roots`, `exclude` and `depth` only from `/etc/the-index/folders.json`, sets `privileged`, and then runs
`folders.scan()`. With `privileged` set, `biggest_file` is a bare file name. A missing or invalid options file
gives a `failed` payload (nothing retires). Set `THE_INDEX_SCANNER_CONF` only in tests (a non-root process).

**Time limits** (`collectors.timeout_for`): jobs 60 s, containers 120 s, filesystems 60 s, backups 600 s,
folders `budget_s` + 300 s. On expiry the whole process group is killed (a root child that refuses the signal is
killed alone) and the run records a `failed` payload instead of raising.

## `filetree`: JSON Lines stream
One JSON document per line, because a single document of a million files is too big. Record type in `t`:

| `t` | Fields | Meaning |
|---|---|---|
| `header` | `collector` (`filetree` or `catalog`), `payload_id` (inbox), `machine` (inbox), `script`, `host`, `os` (`linux`/`darwin`/`windows`), `case_insensitive`, `full`, `roots`, `started_at`, `targeted` | First line |
| `dir` | `key` (path_key), `path`, `parent` (path_key or null), `mtime_ns`, `ctime_ns`, `size`, `files`, `cache`, `agents` | Listed directory. `size`/`files` = direct files; for `cache: true`, the whole subtree |
| `file` | `dir` (path_key), `name`, `size`, `mtime_ns`, `ctime_ns`, `inode`; optional `title`, `title_src`, `title_sig`, `meta` (object; only with `title_sig`) | Only inside listed, non-cache dirs. Title fields are sent when the title was read on the sending machine |
| `skip` | `key`, `path`, `parent`, `mtime_ns`, `ctime_ns` | Unchanged since the state file: keep its files |
| `gone` | `key`, `path` | Targeted runs only: a target that no longer exists (or is no longer a directory) |
| `gap` | `kind`, `target`, `reason` | `denied`, `network` (reason = mount source, e.g. `nfs host-b:/export`), `budget`, `unreadable` |
| `trailer` | `status`, `finished_at`, `counts`, `errors` | Last line. No trailer = the run is `partial` |

`sources.py '<options JSON>'` prints the same stream from an OS index (`--probe` prints `{"source", "reason"}`).
Its header adds `source` (`plocate`, `spotlight`, `everything`, `mft`) and `no_retire: true` (the ingest skips retirement);
it never prints `skip` records; `count_only` prints just a trailer whose `counts.roots` maps root -> file count.
Title-type files may carry `title`, `title_src: "native"`, `title_sig` (`size:mtime_ns`).

Arguments: `filetree.py '<options JSON>' [--state FILE]`. Options: `roots`, `exclude`, `cache_markers`,
`agent_markers`, `full`, `budget_s`, `targets`, `targets_file`. The state file (read-only) is TSV `path_key  mtime_ns  ctime_ns`.
Retirement: on an `ok` run, a directory under a root that is neither `dir` nor `skip` is retired (unless
under a gap target); a file is retired when its directory was listed and the file was not.

**Targeted runs** (`the-index watch`): options `targets` (list of directories) and/or `targets_file` (one path
per line; a long list must go in a file, one argument is at most 128 KB on Linux). Header `targeted: true`. Each
target is listed whatever the state file says (non-recursively); a child directory found in the state file is a
`skip` and is not entered; a child not in it (new, or back after being retired) is listed with its whole new
subtree. The state file holds only the known active children of the targets. `roots` stays the filetree roots:
a target equal to a root has `parent` null, any other has its parent's key. Retirement on an `ok` targeted run is
limited to the listed dirs: their missing files, their child dirs that were neither `dir` nor `skip`, and `gone`
targets, each dir with its subtree (never under a gap target). The run is recorded as collector `watch`.

## `titles`: worklist in, titles out
`titles.py --worklist FILE '<options JSON>'`: the worklist is JSON Lines `{"id": 12, "path": "/srv/data/a.pdf"}`;
output is JSON Lines `{"id": 12, "title": "Annual report", "src": "pdf_xmp", "meta": {"author": "Alice"}}` (`title` null when
none). `meta` is the front matter found in the same read: `author`, `date`, `tags` (list, at most 20), `description`, `lang`;
strings are at most 300 characters with control characters removed, empty values are left out, and the whole `meta` key is
omitted when nothing was found (a title can be null while `meta` is present). Sources: Markdown YAML front matter, HTML
`<meta>` and `<html lang>`, OOXML `docProps/core.xml`, ODF `meta.xml`, EPUB OPF, PDF Info and XMP; PDF `/CreationDate`
becomes `YYYY-MM-DD`.
Options: `budget_s`, `max_files`. Reads at most 64 KB per file (PDF: first and last 64 KB).
