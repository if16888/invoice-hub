"""Lifecycle-safe coalescing guard for deferred Settings normalization."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid


def _release_normalize_gate(window_ref: weakref.ReferenceType) -> None:
    window = window_ref()
    if window is not None and isValid(window):
        window.setProperty("settingsAiNormalizeInFlight", False)


def install_settings_refresh_guard(page: QWidget | None) -> None:
    """Make existing zero-delay AI refresh callbacks safe and coalesced.

    ``settings_pages_baseline`` resolves ``_normalize_ai`` when each queued
    lambda runs. Replacing that module-level function after page migration makes
    already queued callbacks lifecycle-safe without reconnecting anonymous
    signals. Multiple callbacks in the same event-loop turn collapse into one.
    """
    if page is None or not isValid(page):
        return

    from . import settings_pages_baseline as settings_pages

    current = settings_pages._normalize_ai
    if bool(getattr(current, "_settings_lifecycle_guard", False)):
        page.setProperty("settingsRefreshGuardInstalled", True)
        return

    original = current

    def guarded(window) -> None:
        if window is None or not isValid(window):
            return
        if bool(window.property("settingsAiNormalizeInFlight")):
            return

        window.setProperty("settingsAiNormalizeInFlight", True)
        try:
            original(window)
        except RuntimeError as exc:
            # PySide raises RuntimeError when the Python wrapper outlives the
            # underlying C++ object. Treat that shutdown path as a no-op while
            # preserving unrelated runtime errors.
            if not isValid(window) or "deleted" in str(exc).lower():
                return
            raise
        finally:
            if isValid(window):
                QTimer.singleShot(
                    0,
                    lambda ref=weakref.ref(window): _release_normalize_gate(ref),
                )

    guarded._settings_lifecycle_guard = True
    guarded._settings_original_normalize = original
    settings_pages._normalize_ai = guarded
    page.setProperty("settingsRefreshGuardInstalled", True)


__all__ = ["install_settings_refresh_guard"]
