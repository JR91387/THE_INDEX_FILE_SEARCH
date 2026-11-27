#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Install THE INDEX folder scanner as root-owned files plus one sudoers rule, so an unprivileged user can
# measure folders it cannot read. The scanner is read-only: it lists folders and stats files, never opens or
# writes them. Run as root:
#   sudo bash contrib/install_folder_scanner.sh <user> [--roots /a:/b] [--exclude /x:/y] [--depth N]
# The options are written to /etc/the-index/folders.json (root-owned); the scanner run through sudo reads
# roots, exclude and depth ONLY from there. Re-running without options keeps an existing file.
# Undo:  sudo rm -r /etc/sudoers.d/the-index /usr/local/lib/the-index /etc/the-index
# Then set in the config:      [folders] sudo = true
set -euo pipefail

usage="usage: install_folder_scanner.sh <user who runs the-index> [--roots /a:/b] [--exclude /x:/y] [--depth N]"
user="${1:?$usage}"
shift
roots="/home:/srv:/opt:/var/lib" exclude="" depth=2 given=0
while (($#)); do
    case "$1" in
        --roots) roots="${2:?$usage}" ;;
        --exclude) exclude="${2:?$usage}" ;;
        --depth) depth="${2:?$usage}" ;;
        *) echo "$usage" >&2; exit 1 ;;
    esac
    given=1
    shift 2
done

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest_dir=/usr/local/lib/the-index
conf_dir=/etc/the-index
conf="$conf_dir/folders.json"
rule=/etc/sudoers.d/the-index
python=/usr/bin/python3

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
id "$user" >/dev/null 2>&1 || { echo "no such user: $user" >&2; exit 1; }
[[ -x $python ]] || { echo "missing $python" >&2; exit 1; }

# root-owned copies: the user can run them but not change them
install -d -o root -g root -m 0755 "$dest_dir"
install -o root -g root -m 0755 "$here/../src/theindex/collectors/folders.py" "$dest_dir/folders.py"
install -o root -g root -m 0755 "$here/folders_root.py" "$dest_dir/folders_root.py"
echo "installed $dest_dir/folders.py and folders_root.py"

# fixed scan options: the only place the sudo-run scanner takes roots, exclude and depth from
if [[ $given -eq 1 || ! -e $conf ]]; then
    tmp="$(mktemp)"
    "$python" -I - "$roots" "$exclude" "$depth" > "$tmp" <<'PY'
import json
import sys

roots, exclude, depth = sys.argv[1:4]
split = lambda text: [p for p in text.split(":") if p]  # noqa: E731
conf = {"roots": split(roots), "exclude": split(exclude), "depth": int(depth)}
if not conf["roots"] or not all(p.startswith("/") for p in conf["roots"] + conf["exclude"] if "/" in p):
    sys.exit("roots and path excludes must be absolute")
print(json.dumps(conf, indent=1))
PY
    install -d -o root -g root -m 0755 "$conf_dir"
    install -o root -g root -m 0644 "$tmp" "$conf"
    rm -f "$tmp"
fi
echo "options $conf:"
cat "$conf"

# one rule: exactly this interpreter and script, no arguments (the options travel on stdin)
tmp="$(mktemp)"
printf "%s ALL=(root) NOPASSWD: %s -I %s\n" "$user" "$python" "$dest_dir/folders_root.py" > "$tmp"
visudo -cf "$tmp" >/dev/null
install -o root -g root -m 0440 "$tmp" "$rule"
rm -f "$tmp"
echo "installed $rule:"
cat "$rule"
logger -t the-index "folder scanner installed for $user ($dest_dir, $conf, $rule)" || true
