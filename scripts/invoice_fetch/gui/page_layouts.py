"""Shared page archetype contracts for the desktop product surfaces."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QWidget

from .business_pages_baseline import apply_dashboard_baseline, apply_task_flow_baseline
from .settings_baseline import apply_settings_baseline
from .settings_pages_baseline import apply_remaining_settings_baseline
from .styles import PAGE_MARGIN, SECTION_GAP
from .ui_visibility_contracts import install_settings_visibility_contract


class _PageLayoutContract:
    archetype = "base"
    maximum_width = 16777215

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        page.setProperty("pageArchetype", cls.archetype)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(SECTION_GAP)
        layout.setAlignment(Qt.AlignTop)
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
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        QTimer.singleShot(0, lambda p=page: apply_remaining_settings_baseline(p))
        QTimer.singleShot(0, lambda p=page: install_settings_visibility_contract(p))
        return layout
