"""Shared page archetype contracts for the desktop product surfaces."""

import weakref
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QWidget
from shiboken6 import isValid

from .business_pages_baseline import apply_dashboard_baseline, apply_task_flow_baseline
from .design_baseline_styles import apply_global_design_baseline
from .design_system_v11 import apply_design_system_v11
from .design_tokens import DESIGN_V1_METRICS
from .hci_v1 import schedule_dashboard_hci_v1, schedule_task_flow_hci_v1
from .hci_v1_closure import (
    schedule_dashboard_hci_closure,
    schedule_task_flow_hci_closure,
)
from .review_baseline_pipeline import schedule_review_baseline_pipeline
from .review_settings_issue_fixes import apply_settings_action_clarity
from .selection_surfaces import schedule_selection_surface_contracts
from .settings_baseline import apply_settings_baseline
from .settings_feedback import apply_settings_feedback_fixes
from .settings_legacy_contract import install_ai_refresh_compatibility
from .settings_pages_baseline import apply_remaining_settings_baseline
from .settings_refresh_guard import install_settings_refresh_guard
from .settings_status import install_settings_semantic_status_contract
from .settings_theme import apply_settings_token_contract
from .ui_visibility_contracts import install_settings_visibility_contract

BASELINE_PAGE_MARGIN = DESIGN_V1_METRICS["page_margin"]
BASELINE_SECTION_GAP = DESIGN_V1_METRICS["section_gap"]
WORKSPACE_HORIZONTAL_MARGIN = DESIGN_V1_METRICS["workspace_horizontal_margin"]
WORKSPACE_SECTION_GAP = DESIGN_V1_METRICS["workspace_gap"]


SettingsStage = tuple[str, Callable[[QWidget], None]]

SETTINGS_BASELINE_STAGES: tuple[SettingsStage, ...] = (
    ("golden_page", apply_settings_baseline),
    ("ai_compatibility", install_ai_refresh_compatibility),
    ("remaining_pages", apply_remaining_settings_baseline),
    # Existing callbacks queued by remaining_pages resolve _normalize_ai only
    # when they run, so install the lifecycle guard before returning to Qt.
    ("refresh_guard", install_settings_refresh_guard),
    ("feedback_closure", apply_settings_feedback_fixes),
    # Token QSS is last among the baseline visual stages and therefore owns
    # final rendering before semantic status labels are normalized.
    ("token_contract", apply_settings_token_contract),
    ("semantic_status", install_settings_semantic_status_contract),
    ("visibility_contract", install_settings_visibility_contract),
    ("action_clarity", apply_settings_action_clarity),
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


class _PageLayoutContract:
    archetype = "base"
    maximum_width = 16777215

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        page.setProperty("pageArchetype", cls.archetype)
        layout.setContentsMargins(
            BASELINE_PAGE_MARGIN,
            BASELINE_PAGE_MARGIN,
            BASELINE_PAGE_MARGIN,
            BASELINE_PAGE_MARGIN,
        )
        layout.setSpacing(BASELINE_SECTION_GAP)
        layout.setAlignment(Qt.AlignTop)
        QTimer.singleShot(0, lambda p=page: apply_global_design_baseline(p))
        schedule_selection_surface_contracts(page)
        apply_design_system_v11(page)
        return layout

    @classmethod
    def centered_host(cls, parent: QWidget, content: QWidget) -> QWidget:
        host = QWidget(parent)
        host.setProperty("pageArchetypeHost", cls.archetype)
        host.setMaximumWidth(cls.maximum_width)
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(content, 1, Qt.AlignTop)
        row.addStretch(1)
        return host


class DashboardPageLayout(_PageLayoutContract):
    archetype = "dashboard"
    maximum_width = 1360

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        super().apply(page, layout)
        # Baseline owns geometry; HCI then owns task hierarchy and final closure
        # retires duplicate legacy actions.
        QTimer.singleShot(0, lambda p=page: apply_dashboard_baseline(p))
        schedule_dashboard_hci_v1(page)
        schedule_dashboard_hci_closure(page)
        return layout


class WorkspacePageLayout(_PageLayoutContract):
    archetype = "workspace"

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        super().apply(page, layout)
        layout.setContentsMargins(
            WORKSPACE_HORIZONTAL_MARGIN,
            0,
            WORKSPACE_HORIZONTAL_MARGIN,
            0,
        )
        layout.setSpacing(WORKSPACE_SECTION_GAP)
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        schedule_review_baseline_pipeline(page)
        return layout


class TaskFlowPageLayout(_PageLayoutContract):
    archetype = "task_flow"
    maximum_width = 1440

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        super().apply(page, layout)
        QTimer.singleShot(0, lambda p=page: apply_task_flow_baseline(p))
        schedule_task_flow_hci_v1(page)
        schedule_task_flow_hci_closure(page)
        return layout


class SettingsPageLayout(_PageLayoutContract):
    archetype = "settings"
    maximum_width = 1120

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        super().apply(page, layout)
        schedule_settings_baseline_pipeline(page)
        return layout
