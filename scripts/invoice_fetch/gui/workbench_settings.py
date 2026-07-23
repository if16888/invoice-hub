"""Persistent settings for the desktop workbench.

The workbench uses a small set of non-sensitive UI preferences.  Keep these
preferences in an explicit INI-backed store so a restricted Windows registry
does not make the UI appear to save successfully while silently discarding
the value.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from ..config import RUNTIME_DIR

WORKBENCH_SETTINGS_FILENAME = "workbench.ini"


def workbench_settings() -> QSettings:
    """Return the shared, writable settings store for workbench preferences."""
    path = Path(RUNTIME_DIR) / WORKBENCH_SETTINGS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return QSettings(str(path), QSettings.IniFormat)


__all__ = [
    "WORKBENCH_SETTINGS_FILENAME",
    "workbench_settings",
]
