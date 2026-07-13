"""Design Baseline v1.0 normalization for Dashboard and Task Flow pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget

from .ui_components import ChecklistRow


DASHBOARD_MIN_WIDTH = 960
DASHBOARD_MAX_WIDTH = 1360
IMPORT_SOURCE_WIDTH = 248
IMPORT_RESULT_WIDTH = 340
EXPORT_GROUP_WIDTH = 280
EXPORT_CHECK_WIDTH = 360
PRIMARY_MAX_WIDTH = 180


def _content_width_button(button, *, minimum: int = 112, maximum: int = PRIMARY_MAX_WIDTH) -> None:
    if button is None:
        return
    required = button.fontMetrics().horizontalAdvance(button.text()) + 28
    button.setMinimumWidth(max(minimum, required))
    button.setMaximumWidth(max(maximum, required))
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


def apply_dashboard_baseline(page: QWidget) -> None:
    if page is None or page.property("dashboardBaselineApplied"):
        return
    window = page.window()
    if page is not getattr(window, "overview_page", None):
        return
    page.setProperty("dashboardBaselineApplied", True)

    host = getattr(window, "overview_content_host", None)
    if host is not None:
        host.setMinimumWidth(DASHBOARD_MIN_WIDTH)
        host.setMaximumWidth(DASHBOARD_MAX_WIDTH)
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    review_button = None
    for button in page.findChildren(QWidget):
        if hasattr(button, "text") and callable(button.text) and button.text() in {"开始审核", "继续审核"}:
            review_button = button
            break
    if review_button is not None:
        review_button.setText("继续审核")
        _content_width_button(review_button, minimum=120)
        window.btn_overview_continue_review = review_button

    activity = getattr(window, "overview_activity_card", None)
    if activity is not None:
        activity.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)


def _flatten_nested_surface(widget: QWidget | None, object_name: str) -> None:
    if widget is None:
        return
    widget.setObjectName(object_name)
    widget.setProperty("class", "SubtleSection")
    widget.setStyleSheet(
        "QFrame { background: transparent; border: none; border-radius: 0; }"
        "QLabel { background: transparent; border: none; }"
    )
    layout = widget.layout()
    if layout is not None:
        layout.setContentsMargins(0, 0, 0, 0)


def apply_import_baseline(page: QWidget) -> None:
    if page is None or page.property("importBaselineApplied"):
        return
    window = page.window()
    if page is not getattr(window, "imports_page", None):
        return
    page.setProperty("importBaselineApplied", True)

    source = getattr(window, "import_source_card", None)
    if source is not None:
        source.setFixedWidth(IMPORT_SOURCE_WIDTH)
        source.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
    task = getattr(window, "import_task_stack", None)
    if task is not None:
        task.setMaximumWidth(900)
        task.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    result = getattr(window, "import_mail_recent_card", None)
    if result is not None:
        result.setFixedWidth(IMPORT_RESULT_WIDTH)
        result.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)

    _flatten_nested_surface(getattr(window, "import_rules_detail", None), "ImportRulesSubtleSection")
    command = getattr(window, "import_mail_command_bar", None)
    if command is not None:
        command.setStyleSheet("QFrame#CommandBar { background: transparent; border: none; }")
        if command.layout is not None:
            command.layout.setContentsMargins(0, 4, 0, 0)

    _content_width_button(getattr(window, "btn_import_scan_selected", None), minimum=112)
    _content_width_button(getattr(window, "btn_import_local_task", None), minimum=112)


def apply_export_baseline(page: QWidget) -> None:
    if page is None or page.property("exportBaselineApplied"):
        return
    window = page.window()
    if page is not getattr(window, "export_page", None):
        return
    page.setProperty("exportBaselineApplied", True)

    group = getattr(window, "export_group_card", None)
    if group is not None:
        group.setFixedWidth(EXPORT_GROUP_WIDTH)
        group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
    invoices = getattr(window, "export_invoices_card", None)
    if invoices is not None:
        invoices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    integrity = getattr(window, "export_integrity_card", None)
    if integrity is not None:
        integrity.setFixedWidth(EXPORT_CHECK_WIDTH)
        integrity.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)

    if integrity is not None and not hasattr(window, "export_check_naming"):
        naming = ChecklistRow("文件命名", "按日期与商户", ok=True)
        naming.setObjectName("ExportNamingChecklistRow")
        hint = getattr(window, "lbl_export_action_hint", None)
        index = integrity.body_layout.indexOf(hint) if hint is not None else -1
        if index >= 0:
            integrity.body_layout.insertWidget(index, naming)
        else:
            integrity.body_layout.addWidget(naming)
        window.export_check_naming = naming

    _content_width_button(getattr(window, "btn_run_export_page", None), minimum=128)


def apply_task_flow_baseline(page: QWidget) -> None:
    """Dispatch Task Flow normalization after the page has been assigned."""
    window = page.window()
    if page is getattr(window, "imports_page", None):
        apply_import_baseline(page)
    elif page is getattr(window, "export_page", None):
        apply_export_baseline(page)


__all__ = [
    "apply_dashboard_baseline",
    "apply_import_baseline",
    "apply_export_baseline",
    "apply_task_flow_baseline",
]
