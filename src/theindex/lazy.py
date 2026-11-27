# SPDX-License-Identifier: MIT
"""Modules loaded on first use, so a quick command (`find`, `describe`) starts without importing the scanner,
the web server or the page builder."""
import importlib


class Lazy:
    def __init__(self, name):
        self.__dict__["_name"] = name                 # ".scan" or ".pages.serve", relative to the package

    def __getattr__(self, attr):
        return getattr(importlib.import_module(self._name, __package__), attr)


def command(module, name):
    """A COMMANDS entry that imports `module` only when the command runs."""
    return lambda cfg, args: getattr(module, name)(cfg, args)
