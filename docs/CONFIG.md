# Config reference

TOML file at `$XDG_CONFIG_HOME/the-index/config.toml` (or `--config PATH`). Every key is optional. A missing default file means all defaults; a `--config PATH` that
does not exist is an error. Bad values (blackout windows, port 1-65535, percentages 0-100, thresholds 0-1) stop with
one `error:` line naming the key.
Annotated sample: `examples/config.example.toml`.

| Section | Key | Default | Meaning |
|---|---|---|---|
| `paths` | `db_path` | `$XDG_DATA_HOME/the-index/index.db` | The SQLite database |
| `paths` | `pages_dir` | `$XDG_STATE_HOME/the-index/pages` | Where pages are written: `index.md`, one `.md` per section, `the_index.html` |
| `paths` | `pages_on_scan` | `true` | Write the pages after every `scan` (a write failure prints one stderr line and never fails the scan). Must be `true` or `false` |
| `paths` | `purposes_file`, `links_file` | none | Hand-written purposes and links (formats in `examples/`) |
| `serve` | `port` | `8765` | Port for `the-index serve` (127.0.0.1 only; `--port` overrides). Open the printed link: it carries a one-time token |
| `device` | `name` | hostname | This machine's name in the index |
| `device` | `role` | none | Free text role |
| `schedule` | `collectors` | all five | `folders`, `jobs`, `containers`, `filesystems`, `backups` |
| `schedule` | `pre_run_gate` | none | Command; non-zero exit skips the run (recorded) |
| `schedule` | `blackout` | `[]` | `"HH:MM-HH:MM"` local windows; may wrap midnight |
| `rules` | `emergency_after` | `3d` | Backup age that counts as an emergency |
| `rules` | `size_drop_suspicious` | `0.5` | Backup shrink fraction that is suspicious |
| `rules` | `mixed_threshold` | `0.6` | Byte share below which folder content is "mixed" |
| `rules` | `fs_warn_pct`, `fs_emergency_pct` | `85`, `95` | Filesystem fullness limits |

## `[folders]`
| Key | Default | Meaning |
|---|---|---|
| `roots` | `/home`, `/srv`, `/opt`, `/var/lib` | Folders to catalog |
| `depth` | `2` | Levels below each root that get an item |
| `slots` | `7` | Rotation: each top-level folder is walked once every `slots` nights; `scan --measure-all` walks all now |
| `exclude` | `[]` | Paths not cataloged or walked, added to the built-in excludes (`/var/lib/docker`, `/var/lib/containers`, `/var/lib/snapd`, `/var/cache`, `/proc`, `/sys`, `/dev`, `/run`, `lost+found`) |
| `budget_s` | `1800` | Time limit for one night's walk; on expiry the unit becomes a blind spot and keeps last night's numbers |
| `sudo`, `sudo_python`, `script` | off, `/usr/bin/python3`, `/usr/local/lib/the-index/folders_root.py` | Run the root-owned scanner via sudo (see `contrib/`). Under sudo, roots/exclude/depth come only from `/etc/the-index/folders.json`, written by the installer |

Walks stay on one filesystem and never follow symlinks. A folder's size includes everything below it.

## `[filetree]`
| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Catalog directories and files |
| `roots` | same as `[folders] roots` | Folders to walk |
| `exclude` | `[]` | Paths not walked, added to the `[folders]` built-in excludes |
| `cache_markers` | `node_modules`, `.git`, `__pycache__`, `.venv`, `.cache`, `CACHEDIR.TAG` | Directories counted but not listed |
| `full_every` | `7` | Every Nth run lists every directory, even unchanged ones |
| `budget_s` | `1800` | Time limit for one walk; unvisited directories keep their rows |
| `titles` | `true` | Read document titles (first 64 KB, only when a file changed) |
| `title_budget` | `20000` | Most files whose title is read per run |
| `meta` | `true` | Also keep front matter (author, date, tags, description, lang) from the same read |

## `[inbox]`
| Key | Default | Meaning |
|---|---|---|
| `dir` | none | Shared folder for payloads from other machines. Also the default for `collect --out` and `ingest --inbox` |
| `role` | `hub` | `hub` or `member` (anything else is an error). `hub` ingests the inbox during `scan`; `member` writes to it with `the-index collect --out` |

A member keeps its title cache in `$XDG_DATA_HOME/the-index/member.db` (`titles` table) and its filetree state in
`member-state.tsv` next to it. Files in the inbox are moved, never deleted: `done/YYYY-MM/` once taken, `bad/` when
unreadable (an open `bad_payload` gap on the hub until the next clean drain). Names starting with `.` are ignored.

## `[sources]`
| Key | Default | Meaning |
|---|---|---|
| `native` | `auto` | Use plocate, Spotlight or Everything when present; `off` always walks |

`auto` runs `collectors/sources.py` instead of the walk on non-full runs when a source is present: `plocate` or
`locate` (database under 2 days old; names, then stat for size and time), `mdfind` + `mdls` (names and titles), or
`es` (Everything's command line, names only). On full runs the walk runs as usual and the native file count per
root is compared with it; a difference over max(50, 1%) opens an `index_mismatch` gap. Native runs never retire.

## `[[pull]]`
One table per member the hub fetches over ssh (`the-index pull`, and `scan` on a hub).
| Key | Default | Meaning |
|---|---|---|
| `host` | required | ssh destination (`alice@host-b`, or a `Host` alias from `~/.ssh/config`) |
| `ssh_options` | `[]` | Extra ssh arguments, e.g. `["-p", "2222"]`. `BatchMode=yes` and `ConnectTimeout=10` are always set |
| `timeout_s` | `900` | Longest one pull may take |
| `command` | `the-index` | The member's command, if not on its `PATH` |

## `[watch]`
| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Run the watcher as a user service when `schedule` is installed |
| `roots` | `[filetree] roots` | Folders to watch (keep them inside the `[filetree]` roots) |
| `debounce_s` | `2` | Seconds of quiet before changed folders are listed |

`schedule --watch` installs the watcher even when `enabled` is false; `schedule --remove` removes it.

## Purposes and links files
Pipe-delimited, whole-line `#` comments, optional `[device]` headers (lines before any header apply to all
devices). Formats: `examples/purposes.example.txt`, `examples/links.example.txt`. A purpose glob starting with
`container:` sets a container's expected state. Loaded after the collectors on every `scan`.

## `[[backups]]`
| Key | Types | Meaning |
|---|---|---|
| `name` | all | Unique name (the item key) |
| `type` | all | `file_age`, `log_pattern` or `command` |
| `path` | file_age, log_pattern | Glob of backup files / the log file |
| `min_bytes` | file_age | Smaller files do not count as good (default 1) |
| `success` | log_pattern | Regex for a success line; optional `(?P<when>...)` ISO time |
| `command`, `timeout_s` | command | Exit 0 = a good copy now. Runs as the scanning user. |
| `max_age` | all | Older than this = warning (`emergency_after` still applies) |
| `sources`, `destination` | all | Folders backed up / where copies land (links) |

## Scan behaviour
- **Exit code.** `scan` exits 0 whenever a run was recorded, including partial or failed collector runs and
  files warnings (the front page shows them). It exits 2 with one `error: ...` line only when nothing could be
  recorded (bad config, unreadable database, missing `--from-json` file). Errors are never tracebacks.
- **One collector failing** records a failed run for that collector; the others still run.
- **One scan at a time.** A second `scan` while one runs prints `skipped: previous scan still running`,
  records a skipped run if it can, and exits 0 (lock file `<db_path>.lock`).
- **First scan** measures every folder (no rotation); later scans rotate over `slots` nights.
- **Reads never write.** `status`, `search` and `pages` open the database read-only when it is current, so
  they work on a read-only file and never wait on a scan. Search is rebuilt once at the end of each scan.

## `schedule` command
`the-index schedule [--role hub|member] [--remove] [--print]` installs, on Linux, a systemd user timer (`the-index.timer`, `OnCalendar=daily`,
`RandomizedDelaySec=1h`, `Persistent=true`) that runs `scan` with `Nice=19`, `IOSchedulingClass=idle`,
`CPUWeight=10`. `--config` and `--db` given to `schedule` are passed on to the scheduled `scan`. Re-running is
safe. Units go to `$XDG_CONFIG_HOME/systemd/user/`. If `systemctl --user` is unavailable it prints a crontab
line (and never edits the crontab). If lingering is off it prints one hint line (`loginctl enable-linger`).

On macOS it writes `~/Library/LaunchAgents/io.the-index.scan.plist` (daily, `LowPriorityIO`, `Nice` 19) and loads it
with `launchctl bootstrap gui/<uid>`; on Windows it creates a Task Scheduler task `THE INDEX` for the current user
(daily, idle priority, no admin) from an XML definition. `--role member` schedules `collect` instead of `scan`.
`--print` shows what would be installed and changes nothing.
