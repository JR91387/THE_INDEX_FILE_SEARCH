# THE INDEX for Albert

Type `ix` and words in [Albert](https://albertlauncher.github.io/) (Linux, macOS) to find folders and documents
in THE INDEX. Each row shows the title (or name) and `device:path  size`. Actions: **Open** and **Open containing
folder** (only for paths that exist on this machine), **Copy path**.

Status: **not yet tried in a real Albert.** It is written to the `albert.pyi` stub of
[albert-plugin-python](https://github.com/albertlauncher/albert-plugin-python), Python interface 5.0
(`md_iid = "5.0"`, `Plugin(PluginInstance, GeneratorQueryHandler)`, `items()` yielding `StandardItem` lists), and
tested only against a stand-in `albert` module.

## Install

1. Have `the-index` on the PATH, or set `THE_INDEX_CMD` in the environment Albert starts with, for example
   `THE_INDEX_CMD="python3 /opt/the-index.pyz --db /srv/data/index.db"`.
2. Copy this folder into Albert's Python plugin directory under a name that is not `albert`:
   on Linux `~/.local/share/albert/python/plugins/the_index/` (so that `.../the_index/__init__.py` exists). On
   macOS use the matching Albert data directory.
   `mkdir -p ~/.local/share/albert/python/plugins/the_index && cp contrib/albert/__init__.py ~/.local/share/albert/python/plugins/the_index/`
3. In Albert: Settings, Plugins, enable the Python plugin, then enable "THE INDEX". Restart Albert if it does not
   show up. The default trigger is `ix ` and can be changed there.

Standard library only; names and titles are shown as text and never run.

**Faster:** if THE INDEX is importable by the launcher's Python (installed with pip, or `THE_INDEX_LIB` set to its
`src` folder or `.pyz` file), searches run inside the plugin instead of starting `the-index` each time. `THE_INDEX_CMD`
turns this off. `THE_INDEX_CONFIG` picks a config file.
