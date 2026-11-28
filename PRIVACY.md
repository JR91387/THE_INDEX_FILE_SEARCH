# Privacy

THE INDEX runs on your machine and keeps what it finds on your machine.

- **No telemetry.** It never reports usage, errors or anything else to anyone.
- **No network calls of its own.** The only connections are ones you set up:
  - `the-index pull HOST` runs `ssh` to machines you name, with your own ssh keys;
  - `tools/build_windows.py --download` fetches Python's embeddable package from python.org;
  - `the-index serve` listens on 127.0.0.1 (this machine only).
- **What it stores:** one SQLite file (path in your config) holding folder and file names, sizes and dates,
  document titles and front matter (author, tags, date, description, language), scheduled jobs, containers,
  backups, filesystems, and the history of what changed. It never stores the contents of your files.
- **What it reads:** names and metadata, plus the first part of supported documents to find a title and
  front matter. Folders and files it may not read are skipped and listed as blind spots.
- **AI agents** see the catalog only if you connect one (`the-index mcp`, `--json`). What the agent does
  with it is up to that agent and its provider.

Delete the database file and the pages folder and nothing is left.
