"""Shared page archetype contracts for the desktop product surfaces."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QWidget

from .business_pages_baseline import apply_dashboard_baseline, apply_task_flow_baseline
from .design_baseline_styles import apply_global_design_baseline
from .review_detail_closure import apply_review_detail_closure
from .review_detail_width_fix import apply_review_detail_width_fix
from .review_table_width_contract import apply_review_table_width_contract
from .review_toolbar_filter_fixes import apply_review_toolbar_filter_fixes
from .review_workspace_baseline import apply_review_workspace_baseline
from .review_workspace_closure import apply_review_workspace_closure
from .settings_baseline import apply_settings_baseline
from .settings_feedback_fixes import apply_settings_feedback_fixes
from .settings_legacy_contract import install_ai_refresh_compatibility
from .settings_pages_baseline import apply_remaining_settings_baseline
from .ui_visibility_contracts import install_settings_visibility_contract

BASELINE_PAGE_MARGIN = 24
BASELINE_SECTION_GAP = 16
WORKSPACE_HORIZONTAL_MARGIN = 12
WORKSPACE_SECTION_GAP = 8


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
        QTimer.singleShot(0, lambda p=page: apply_review_workspace_baseline(p))
        QTimer.singleShot(0, lambda p=page: apply_review_toolbar_filter_fixes(p))
        QTimer.singleShot(0, lambda p=page: apply_review_table_width_contract(p))
        QTimer.singleShot(0, lambda p=page: apply_review_detail_width_fix(p))
        # Run last: convert compatibility-only geometry and duplicate detail
        # ownership into the final interactive Review workspace.
        QTimer.singleShot(0, lambda p=page: apply_review_workspace_closure(p))
        QTimer.singleShot(0, lambda p=page: apply_review_detail_closure(p))
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
        QTimer.singleShot(0, lambda p=page: apply_settings_baseline(p))
        QTimer.singleShot(0, lambda p=page: install_ai_refresh_compatibility(p))
        QTimer.singleShot(0, lambda p=page: apply_remaining_settings_baseline(p))
        QTimer.singleShot(0, lambda p=page: apply_settings_feedback_fixes(p))
        QTimer.singleShot(0, lambda p=page: install_settings_visibility_contract(p))
        return layout
