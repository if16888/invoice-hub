"""Lifecycle-safe coalescing guards for deferred UI refreshes."""

from __future__ import annotations

import weakref
from types import ModuleType

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid


def _release_refresh_gate(
    window_ref: weakref.ReferenceType,
    gate_property: str,
) -> None:
    window = window_ref()
    if window is not None and isValid(window):
        window.setProperty(gate_property, False)


def _install_function_guard(
    module: ModuleType,
    function_name: str,
    gate_property: str,
) -> None:
    current = getattr(module, function_name)
    if bool(getattr(current, "_settings_lifecycle_guard", False)):
        return

    original = current

    def guarded(window) -> None:
        if window is None or not isValid(window):
            return
        # closeEvent marks the window as shutting down before child widgets are
        # destroyed.  A queued zero-delay refresh can therefore still receive a
        # valid Python/Qt window while its owned item views are already entering
        # teardown.  Once shutdown starts, UI refreshes have no useful work left
        # to do and must not touch that child tree.
        if bool(getattr(window, "_shutdown_requested", False)):
            return
        if bool(window.property(gate_property)):
            return

        window.setProperty(gate_property, True)
        try:
            original(window)
        except RuntimeError as exc:
            # A queued callback may run while Qt is destroying child widgets.
            # Treat deleted-object shutdown paths as a no-op while preserving
            # unrelated runtime errors.
            if not isValid(window) or "deleted" in str(exc).lower():
                return
            raise
        finally:
            if isValid(window):
                if bool(getattr(window, "_shutdown_requested", False)):
                    window.setProperty(gate_property, False)
                else:
                    QTimer.singleShot(
                        0,
                        lambda ref=weakref.ref(window), prop=gate_property: (
                            _release_refresh_gate(ref, prop)
                        ),
                    )

    guarded._settings_lifecycle_guard = True
    guarded._settings_original_refresh = original
    guarded._settings_guarded_function = function_name
    setattr(module, function_name, guarded)


def install_settings_refresh_guard(page: QWidget | None) -> None:
    """Make existing zero-delay UI callbacks safe and coalesced.

    Existing signal lambdas resolve their module-level refresh functions only
    when they run. Replacing those functions after page migration protects
    callbacks that are already queued, without reconnecting anonymous signals.
    Multiple callbacks for one surface in the same event-loop turn collapse into
    one refresh.
    """
    if page is None or not isValid(page):
        return

    from . import review_feedback_fixes
    from . import settings_baseline
    from . import settings_pages_baseline

    _install_function_guard(
        settings_pages_baseline,
        "_normalize_ai",
        "settingsAiNormalizeInFlight",
    )
    _install_function_guard(
        settings_baseline,
        "_refresh_mailbox_visuals",
        "settingsMailboxRefreshInFlight",
    )
    _install_function_guard(
        review_feedback_fixes,
        "_sync_seller_tooltips",
        "reviewSellerTooltipSyncInFlight",
    )
    page.setProperty("settingsRefreshGuardInstalled", True)


__all__ = ["install_settings_refresh_guard"]
