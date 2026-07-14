"""Deterministic Design Baseline v1.0 pipeline for Settings.

Settings used to queue several independent zero-delay migrations. Their final
result could depend on callback order, especially during startup and shutdown.
This module owns the order and schedules one guarded callback after the page tree
has finished constructing.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from .settings_baseline import apply_settings_baseline
from .settings_feedback_fixes import apply_settings_feedback_fixes
from .settings_legacy_contract import install_ai_refresh_compatibility
from .settings_pages_baseline import apply_remaining_settings_baseline
from .settings_refresh_guard import install_settings_refresh_guard
from .settings_token_contract import apply_settings_token_contract
from .ui_visibility_contracts import install_settings_visibility_contract


SettingsStage = tuple[str, Callable[[QWidget], None]]

SETTINGS_BASELINE_STAGES: tuple[SettingsStage, ...] = (
    ("golden_page", apply_settings_baseline),
    ("ai_compatibility", install_ai_refresh_compatibility),
    ("remaining_pages", apply_remaining_settings_baseline),
    # Existing callbacks queued by remaining_pages resolve _normalize_ai only
    # when they run, so install the lifecycle guard before returning to Qt.
    ("refresh_guard", install_settings_refresh_guard),
    ("feedback_closure", apply_settings_feedback_fixes),
    # Token QSS is last among visual stages and therefore owns final rendering.
    ("token_contract", apply_settings_token_contract),
    ("visibility_contract", install_settings_visibility_contract),
)


def apply_settings_baseline_pipeline(page: QWidget | None) -> None:
    """Apply all Settings migrations once, in their documented order."""
    if page is None or not isValid(page):
        return
    if page.property("settingsBaselinePipelineApplied"):
        return

    page.setProperty("settingsBaselinePipelineFailedStage", "")
    completed: list[str] = []
    for name, stage in SETTINGS_BASELINE_STAGES:
        page.setProperty("settingsBaselinePipelineActiveStage", name)
        try:
            stage(page)
        except Exception:
            page.setProperty("settingsBaselinePipelineFailedStage", name)
            page.setProperty("settingsBaselinePipelineStages", tuple(completed))
            page.setProperty("settingsBaselinePipelineActiveStage", "")
            page.setProperty("settingsBaselinePipelineApplied", False)
            raise
        completed.append(name)

    page.setProperty("settingsBaselinePipelineActiveStage", "")
    page.setProperty("settingsBaselinePipelineStages", tuple(completed))
    page.setProperty("settingsBaselinePipelineApplied", True)


def schedule_settings_baseline_pipeline(page: QWidget | None) -> None:
    """Queue one safe callback after Settings controls have been constructed."""
    if page is None or not isValid(page):
        return
    if page.property("settingsBaselinePipelineApplied") or page.property(
        "settingsBaselinePipelineScheduled"
    ):
        return

    page.setProperty("settingsBaselinePipelineScheduled", True)
    page_ref = weakref.ref(page)

    def run_pipeline() -> None:
        target = page_ref()
        if target is None or not isValid(target):
            return
        try:
            apply_settings_baseline_pipeline(target)
        finally:
            if isValid(target):
                target.setProperty("settingsBaselinePipelineScheduled", False)

    QTimer.singleShot(0, run_pipeline)


__all__ = [
    "SETTINGS_BASELINE_STAGES",
    "apply_settings_baseline_pipeline",
    "schedule_settings_baseline_pipeline",
]
