"""Workarounds for the local toolchain.

uv on this machine installs wheel contents with the macOS UF_HIDDEN flag set.
Qt's plugin scanner ignores hidden files, so every platform plugin (cocoa,
offscreen) becomes invisible and the app dies at QApplication() with
"Could not find the Qt platform plugin".  The flag comes back after every
`uv run`, so clear it at startup rather than by hand.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def unhide_qt_plugins() -> int:
    if sys.platform != "darwin":
        return 0
    try:
        import PyQt6
        root = Path(PyQt6.__file__).resolve().parent / "Qt6" / "plugins"
    except Exception:
        return 0
    cleared = 0
    for path in [root, *root.rglob("*")]:
        try:
            flags = path.lstat().st_flags
        except OSError:
            continue
        if flags & stat.UF_HIDDEN:
            try:
                os.chflags(path, flags & ~stat.UF_HIDDEN)
                cleared += 1
            except OSError:
                pass
    return cleared
