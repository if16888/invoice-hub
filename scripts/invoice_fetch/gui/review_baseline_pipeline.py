"""Deterministic Design Baseline v1.0 pipeline for the Review workspace.

The Review page is assembled from legacy-compatible widgets and then normalized
by a small set of focused migrations.  These migrations used to be queued as
independent zero-delay callbacks, which made the final result depend on event
queue ordering and left several callbacks alive while windows were closing.

This module owns the order explicitly and schedules exactly one deferred
callback after the page has finished constructing its controls.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from .review_detail_closure import apply_review_detail_closure
from .review_detail_width_fix import apply_review_detail_width_fix
from .review_table_width_contract import apply_review_table_width_contract
from .review_toolbar_filter_fixes import apply_review_toolbar_filter_fixes
from .review_workspace_baseline import apply_review_workspace_baseline
from .review_workspace_closure import apply_review_workspace_closure


ReviewStage = tuple[str, Callable[[QWidget], None]]

REVIEW_BASELINE_STAGES: tuple[ReviewStage, ...] = (
    ("workspace_baseline", apply_review_workspace_baseline),
    ("toolbar_and_filters", apply_review_toolbar_filter_fixes),
    ("table_width", apply_review_table_width_contract),
    ("detail_width", apply_review_detail_width_fix),
    ("workspace_closure", apply_review_workspace_closure),
    ("detail_closure", apply_review_detail_closure),
)


def apply_review_baseline_pipeline(page: QWidget | None) -> None:
    """Apply all Review migrations once, in their documented order."""
    if page is None or not isValid(page):
        return
    if page.property("reviewBaselinePipelineApplied"):
        return

    completed: list[str] = []
    for name, stage in REVIEW_BASELINE_STAGES:
        stage(page)
        completed.append(name)

    page.setProperty("reviewBaselinePipelineStages", tuple(completed))
    page.setProperty("reviewBaselinePipelineApplied", True)


def schedule_review_baseline_pipeline(page: QWidget | None) -> None:
    """Queue one safe callback after Review controls have been constructed."""
    if page is None or not isValid(page):
        return
    if page.property("reviewBaselinePipelineApplied") or page.property(
        "reviewBaselinePipelineScheduled"
    ):
        return

    page.setProperty("reviewBaselinePipelineScheduled", True)
    page_ref = weakref.ref(page)

    def run_pipeline() -> None:
        target = page_ref()
        if target is None or not isValid(target):
            return
        try:
            apply_review_baseline_pipeline(target)
        finally:
            if isValid(target):
                target.setProperty("reviewBaselinePipelineScheduled", False)

    QTimer.singleShot(0, run_pipeline)


__all__ = [
    "REVIEW_BASELINE_STAGES",
    "apply_review_baseline_pipeline",
    "schedule_review_baseline_pipeline",
]
