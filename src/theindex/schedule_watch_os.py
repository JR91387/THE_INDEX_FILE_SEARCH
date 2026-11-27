# SPDX-License-Identifier: MIT
"""`schedule --watch` install and remove on macOS (launchctl) and Windows (schtasks).

Unverified on a real host: the same launchctl and schtasks calls as schedule_mac.py / schedule_win.py, tested
with mocks."""
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from . import schedule, schedule_watch


def apply(args):
    if not args.remove and schedule.role_of(args) != "hub":
        raise ValueError("watch writes the database: schedule it with role hub")
    if sys.platform == "darwin":
        return mac_remove(args) if args.remove else mac_install(args)
    return win_remove() if args.remove else win_install(args)


def mac_path(args):
    from . import schedule_mac
    return schedule_mac.plist_path(args).with_name(f"{schedule_watch.LABEL}.plist")


def _mac_unload():
    from . import schedule_mac
    target = f"gui/{os.getuid()}/{schedule_watch.LABEL}"
    loaded = schedule_mac._launchctl("print", target)
    if loaded is not None and loaded.returncode == 0:
        schedule_mac._launchctl("bootout", target)


def mac_install(args):
    from . import schedule_mac
    path = mac_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(schedule_watch.render_mac(args))
    _mac_unload()
    done = schedule_mac._launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
    if done is None or done.returncode != 0:
        raise OSError(f"could not load {path.name}: {(done.stderr if done else '').strip()}")
    print(f"watching: {path} (kept alive, low priority)")
    return 0


def mac_remove(args):
    path = mac_path(args)
    if path.exists():
        _mac_unload()
        path.unlink()
        print("watch removed")
    return 0


def win_install(args):
    from . import schedule_win
    root = ET.fromstring(schedule_watch.render_win(args))
    data = ET.tostring(root, encoding="UTF-16", xml_declaration=True)        # schtasks wants UTF-16
    fd, name = tempfile.mkstemp(suffix=".xml", prefix="the-index-watch-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        done = schedule_win._schtasks("/Create", "/TN", schedule_watch.TASK, "/XML", name, "/F")
    finally:
        Path(name).unlink(missing_ok=True)
    if done is None or done.returncode != 0:
        raise OSError(f"could not create task {schedule_watch.TASK!r}: {(done.stderr if done else '').strip()}")
    schedule_win._schtasks("/Run", "/TN", schedule_watch.TASK)
    print(f"watching: task {schedule_watch.TASK!r} (at logon, low priority)")
    return 0


def win_remove():
    from . import schedule_win
    done = schedule_win._schtasks("/Delete", "/TN", schedule_watch.TASK, "/F")
    if done is not None and done.returncode == 0:
        print("watch removed")
    return 0
