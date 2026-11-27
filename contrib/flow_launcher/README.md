# THE INDEX for Flow Launcher (Windows)

Press the Flow Launcher hotkey, type `ix` and some words, and THE INDEX's folders and documents come up:
matches on file name, document title and folder path, best first. Enter opens the file or folder; the
context menu (Shift+Enter) opens the folder that holds it. Results from other machines or offline catalogs
are listed but do not open.

## Install
1. Install THE INDEX and run `the-index scan` once, so there is a database.
2. Copy this folder into `%APPDATA%\FlowLauncher\Plugins\THE_INDEX\` and restart Flow Launcher.
   Flow sets up its own Python for Python plugins; this one needs nothing beyond the standard library.
3. If `the-index` is not on `PATH`, or you use the single-file build or another database, set the
   environment variable `THE_INDEX_CMD` to the command line, for example
   `py C:\Tools\the-index.pyz --db D:\index\the-index.db`.

## How it works
Flow runs `main.py` with one JSON request; the plugin runs `the-index find --json` and turns the results
into Flow rows. It reads nothing else and writes nothing. The keyword (`ix`) can be changed in Flow's
plugin settings.

Status: unit-tested on Linux with recorded replies; not yet tried in Flow Launcher on a real Windows PC.

**Faster:** if THE INDEX is importable by the launcher's Python (installed with pip, or `THE_INDEX_LIB` set to its
`src` folder or `.pyz` file), searches run inside the plugin instead of starting `the-index` each time. `THE_INDEX_CMD`
turns this off. `THE_INDEX_CONFIG` picks a config file.
