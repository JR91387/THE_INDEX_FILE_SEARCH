# SPDX-License-Identifier: MIT
"""Run a collector script as a child process and stream its stdout (shared by files_run and files_source)."""
import subprocess
import threading
from pathlib import Path

from . import collectors

HERE = Path(collectors.__file__).resolve().parent


def stream(argv, timeout, sink):
    """Run a collector script, feed its stdout lines to sink(lines); kill it at the timeout."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace", start_new_session=True)
    timer = threading.Timer(timeout, collectors.stop, (proc,))
    timer.start()
    try:
        return sink(proc.stdout)
    finally:
        timer.cancel()
        proc.stdout.close()
        proc.wait()
