"""Persistent settings for the desktop workbench.

The workbench uses a small set of non-sensitive UI preferences.  Keep these
preferences in an explicit INI-backed store so a restricted Windows registry
does not make the UI appear to save successfully while silently discarding
the value.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings

from ..config import RUNTIME_DIR

WORKBENCH_SETTINGS_FILENAME = "workbench.ini"
_LEGACY_KEYS = (
    "nav_collapsed_manual",
    "shortcut_help_expanded",
    "splitter/main",
    "splitter/left",
)
_log = logging.getLogger(__name__)


def workbench_settings(runtime_dir: Path | None = None) -> QSettings:
    """Return the shared, writable settings store for workbench preferences."""
    root = Path(RUNTIME_DIR) if runtime_dir is None else Path(runtime_dir)
    path = root / WORKBENCH_SETTINGS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return QSettings(str(path), QSettings.IniFormat)


def sync_workbench_settings(settings: QSettings) -> bool:
    """Persist workbench preferences and report filesystem failures to logs."""
    settings.sync()
    if settings.status() != QSettings.NoError:
        _log.warning("workbench settings write failed: %s", settings.fileName())
        return False
    return True


def migrate_legacy_workbench_settings(
    target: QSettings,
    legacy: QSettings | None = None,
) -> bool:
    """Copy preferences from the pre-INI QSettings store once.

    ``legacy`` is injectable for tests. Production callers use the old
    organization/application constructor, which reads the Windows registry on
    Windows and the platform's native QSettings store elsewhere.
    """
    marker = "migration/legacy_qsettings_v1"
    if target.value(marker, False, type=bool):
        return True

    legacy = legacy if legacy is not None else QSettings("InvoiceHub", "workbench")
    if legacy.status() != QSettings.NoError:
        _log.warning("legacy workbench settings read failed: %s", legacy.fileName())
        return False

    for key in _LEGACY_KEYS:
        if not target.contains(key) and legacy.contains(key):
            target.setValue(key, legacy.value(key))

    target.setValue(marker, True)
    return sync_workbench_settings(target)


__all__ = [
    "WORKBENCH_SETTINGS_FILENAME",
    "migrate_legacy_workbench_settings",
    "sync_workbench_settings",
    "workbench_settings",
]
