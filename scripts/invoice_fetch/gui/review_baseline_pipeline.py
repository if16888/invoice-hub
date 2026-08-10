"""Deterministic Design Baseline v1.0 pipeline for the Review workspace.

The Review page is assembled from legacy-compatible widgets and then normalized
by a small set of focused migrations. These migrations used to be queued as
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

from .company_tax_profile import apply_company_tax_profile
from .design_system_v11 import apply_design_system_v11
from .design_v1_review_task_closure import apply_design_v1_review_task_closure
from .hci_v1 import apply_review_hci_v1
from .hci_v1_closure import apply_review_hci_closure
from .review_detail_closure import apply_review_detail_closure
from .review_detail_width_fix import apply_review_detail_width_fix
from .review_list_paging_fix import apply_review_list_paging_fix
from .review_settings_issue_fixes import apply_review_attachment_action_fix
from .review_table_width_contract import apply_review_table_width_contract
from .review_toolbar_filter_fixes import apply_review_toolbar_filter_fixes
from .review_workspace_baseline import apply_review_workspace_baseline
from .review_workspace_closure import apply_review_workspace_closure


ReviewStage = tuple[str, Callable[[QWidget], None]]


REVIEW_BASELINE_STAGES: tuple[ReviewStage, ...] = (
    ("workspace_baseline", apply_review_workspace_baseline),
    ("toolbar_and_filters", apply_review_toolbar_filter_fixes),
    ("company_tax_profile", apply_company_tax_profile),
    ("attachment_action_clarity", apply_review_attachment_action_fix),
    ("table_width", apply_review_table_width_contract),
    ("detail_width", apply_review_detail_width_fix),
    ("workspace_closure", apply_review_workspace_closure),
    ("detail_closure", apply_review_detail_closure),
    # Paging owns the final count copy and reconnects the search debounce timer.
    ("list_paging", apply_review_list_paging_fix),
    # Task ownership runs late so no earlier compatibility stage can restore
    # cross-workflow buttons or expand the buyer warning again.
    ("task_ownership", apply_design_v1_review_task_closure),
    # Visual language is deliberately final for legacy compatibility surfaces.
    ("visual_language_v11", apply_design_system_v11),
    # HCI v1 is interaction-only and must run after all visual/baseline stages.
    ("hci_v1_task_flow", apply_review_hci_v1),
    # Closure owns shortcut focus safety and review-mode lifecycle guarantees.
    ("hci_v1_closure", apply_review_hci_closure),
)


def apply_review_baseline_pipeline(page: QWidget | None) -> None:
    """Apply all Review migrations once, in their documented order."""
    if page is None or not isValid(page):
        return
    if page.property("reviewBaselinePipelineApplied"):
        return

    page.setProperty("reviewBaselinePipelineFailedStage", "")
    completed: list[str] = []
    for name, stage in REVIEW_BASELINE_STAGES:
        page.setProperty("reviewBaselinePipelineActiveStage", name)
        try:
            stage(page)
        except Exception:
            page.setProperty("reviewBaselinePipelineFailedStage", name)
            raise
        completed.append(name)

    page.setProperty("reviewBaselinePipelineActiveStage", "")
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
