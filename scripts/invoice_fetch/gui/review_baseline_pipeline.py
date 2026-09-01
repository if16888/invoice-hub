"""Deterministic Review baseline and post-baseline HCI pipelines.

The Review page is assembled from legacy-compatible widgets and then normalized
by a small set of focused migrations. Design System v1.1 remains the final
*baseline* stage. HCI v1.0 is an interaction extension that runs only after that
visual baseline has settled.
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
from .review_paging import install_review_paging
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
    ("list_paging", install_review_paging),
    # Task ownership runs late so no earlier compatibility stage can restore
    # cross-workflow buttons or expand the buyer warning again.
    ("task_ownership", apply_design_v1_review_task_closure),
    # Keep the established Design System contract: visual language is the final
    # Review baseline stage.
    ("visual_language_v11", apply_design_system_v11),
)


REVIEW_HCI_STAGES: tuple[ReviewStage, ...] = (
    ("hci_v1_task_flow", apply_review_hci_v1),
    ("hci_v1_closure", apply_review_hci_closure),
)


def _apply_stages(
    page: QWidget,
    stages: tuple[ReviewStage, ...],
    *,
    active_property: str,
    failed_property: str,
) -> tuple[str, ...]:
    completed: list[str] = []
    page.setProperty(failed_property, "")
    for name, stage in stages:
        page.setProperty(active_property, name)
        try:
            stage(page)
        except Exception:
            page.setProperty(failed_property, name)
            raise
        completed.append(name)
    page.setProperty(active_property, "")
    return tuple(completed)


def apply_review_baseline_pipeline(page: QWidget | None) -> None:
    """Apply the established Review visual/geometry baseline once."""
    if page is None or not isValid(page):
        return
    if page.property("reviewBaselinePipelineApplied"):
        return

    completed = _apply_stages(
        page,
        REVIEW_BASELINE_STAGES,
        active_property="reviewBaselinePipelineActiveStage",
        failed_property="reviewBaselinePipelineFailedStage",
    )
    page.setProperty("reviewBaselinePipelineStages", completed)
    page.setProperty("reviewBaselinePipelineApplied", True)


def apply_review_hci_pipeline(page: QWidget | None) -> None:
    """Apply HCI interaction stages only after the baseline has settled."""
    if page is None or not isValid(page):
        return
    if page.property("reviewHciPipelineApplied"):
        return
    if not page.property("reviewBaselinePipelineApplied"):
        apply_review_baseline_pipeline(page)

    completed = _apply_stages(
        page,
        REVIEW_HCI_STAGES,
        active_property="reviewHciPipelineActiveStage",
        failed_property="reviewHciPipelineFailedStage",
    )
    page.setProperty("reviewHciPipelineStages", completed)
    page.setProperty("reviewHciPipelineApplied", True)


def schedule_review_baseline_pipeline(page: QWidget | None) -> None:
    """Queue one safe callback for baseline followed by post-baseline HCI."""
    if page is None or not isValid(page):
        return
    if (
        page.property("reviewBaselinePipelineApplied")
        and page.property("reviewHciPipelineApplied")
    ) or page.property("reviewBaselinePipelineScheduled"):
        return

    page.setProperty("reviewBaselinePipelineScheduled", True)
    page_ref = weakref.ref(page)

    def run_pipeline() -> None:
        target = page_ref()
        if target is None or not isValid(target):
            return
        try:
            apply_review_baseline_pipeline(target)
            apply_review_hci_pipeline(target)
        finally:
            if isValid(target):
                target.setProperty("reviewBaselinePipelineScheduled", False)

    QTimer.singleShot(0, run_pipeline)


__all__ = [
    "REVIEW_BASELINE_STAGES",
    "REVIEW_HCI_STAGES",
    "apply_review_baseline_pipeline",
    "apply_review_hci_pipeline",
    "schedule_review_baseline_pipeline",
]
