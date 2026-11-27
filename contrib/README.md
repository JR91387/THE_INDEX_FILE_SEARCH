# contrib

| File | What it does |
|---|---|
| `install_folder_scanner.sh` | Root step: copies `folders.py` and `folders_root.py` to `/usr/local/lib/the-index/` (root-owned), writes `/etc/the-index/folders.json` (root-owned) and adds one sudoers rule so `the-index` can measure folders its user cannot read. Then set `[folders] sudo = true`. |
| `folders_root.py` | The entry point the sudoers rule allows. Reads roots, exclude and depth from the root-owned file only. |
| `flow_launcher/` | A Flow Launcher (Windows) plugin: type `ix` and words in its pop-up bar to find folders and documents. See its README. |
| `albert/` | An Albert launcher (Linux, macOS) plugin: type `ix` and words to find folders and documents. Written to Albert's Python interface 5.0; not yet tried in a real Albert. See its README. |

```
sudo bash contrib/install_folder_scanner.sh alice --roots /home:/srv/data --exclude /srv/data/tmp --depth 2
```

Without options the defaults are used (`/home:/srv:/opt:/var/lib`, depth 2); re-running without options keeps
an existing `/etc/the-index/folders.json`. Edit that file (as root) to change what the scanner may see.

**What the sudoers rule allows:** the named user can run exactly `/usr/bin/python3 -I
/usr/local/lib/the-index/folders_root.py`, with no arguments and no wildcard. The scan roots, excludes and depth
come only from `/etc/the-index/folders.json`; whatever the caller sends for them is ignored, so the rule cannot
be used to look at other trees. The caller's other options (rotation slot, content rules, time budget) arrive on
stdin. Only folder names, owners, sizes and file types of those roots are revealed, never file contents, and
`biggest_file` is a bare file name. Without the rule, unreadable folders are listed as blind spots instead.
Re-run the installer after upgrading (older installs used a rule with `*` and `folders.py`; the installer
replaces it).
