"""Shared page archetype contracts for the desktop product surfaces."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QWidget

from .business_pages_baseline import apply_dashboard_baseline, apply_task_flow_baseline
from .design_baseline_styles import apply_global_design_baseline
from .design_tokens import DESIGN_V1_METRICS
from .review_baseline_pipeline import schedule_review_baseline_pipeline
from .settings_baseline_pipeline import schedule_settings_baseline_pipeline

BASELINE_PAGE_MARGIN = DESIGN_V1_METRICS["page_margin"]
BASELINE_SECTION_GAP = DESIGN_V1_METRICS["section_gap"]
WORKSPACE_HORIZONTAL_MARGIN = DESIGN_V1_METRICS["workspace_horizontal_margin"]
WORKSPACE_SECTION_GAP = DESIGN_V1_METRICS["workspace_gap"]


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
        QTimer.singleShot(0, lambda p=page: apply_dashboard_baseline(p))
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
        return layout


class SettingsPageLayout(_PageLayoutContract):
    archetype = "settings"
    maximum_width = 1120

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        super().apply(page, layout)
        schedule_settings_baseline_pipeline(page)
        return layout
