"""Design Baseline v1.0 normalization for Dashboard and Task Flow pages."""

from __future__ import annotations

from functools import wraps
from types import MethodType

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget
from shiboken6 import isValid

from ..review_status import APPROVED
from .icon_provider import IconProvider
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


def _set_semantic_checklist_value(
    row: ChecklistRow,
    value: str,
    ok: bool | None = None,
    *,
    state: str | None = None,
) -> None:
    """Render checklist state with semantic icons instead of Unicode glyphs."""
    if state is None:
        state = "success" if ok is True else ("danger" if ok is False else "muted")
    if state not in {"success", "warning", "danger", "muted"}:
        state = "muted"

    row.lbl_value.setText(str(value))
    row.lbl_value.setProperty("state", state)
    row.setProperty("state", state)

    semantic = {
        "success": "success",
        "warning": "warning",
        "danger": "danger",
        "muted": "info",
    }[state]
    row.lbl_icon.setText("")
    row.lbl_icon.setStyleSheet("")
    row.lbl_value.setStyleSheet("")
    row.lbl_icon.setPixmap(IconProvider.icon(semantic).pixmap(QSize(14, 14)))
    row.lbl_icon.setToolTip(
        {
            "success": "检查通过",
            "warning": "可继续，但会使用默认值",
            "danger": "检查未通过",
            "muted": "等待检查",
        }[state]
    )
    for widget in (row, row.lbl_value):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def _apply_semantic_checklist_row(row: ChecklistRow | None) -> None:
    if row is None or row.property("semanticChecklistApplied"):
        return
    row.setProperty("semanticChecklistApplied", True)
    current = row.lbl_value.text()
    row.set_value = MethodType(_set_semantic_checklist_value, row)
    row.set_value(current, state="muted")


def _export_naming_state(invoices: list[dict]) -> tuple[str, str]:
    """Return truthful export-filename readiness for approved invoices."""
    approved = [
        invoice
        for invoice in invoices
        if str(invoice.get("review_status") or "").strip() == APPROVED
    ]
    if not approved:
        return "等待可导出发票", "muted"

    fallback_count = 0
    for invoice in approved:
        expense_date = str(
            invoice.get("expense_date") or invoice.get("invoice_date") or ""
        ).strip()
        seller = str(invoice.get("seller_name") or "").strip()
        if not expense_date or not seller:
            fallback_count += 1

    if fallback_count:
        return f"{fallback_count} 张将使用默认名称", "warning"
    return f"{len(approved)} 张可按日期与商户命名", "success"


def _sync_export_naming_check(window) -> None:
    row = getattr(window, "export_check_naming", None)
    group_list = getattr(window, "export_group_list", None)
    db = getattr(window, "db", None)
    if row is None or group_list is None or db is None or not getattr(db, "is_open", False):
        return

    current_item = group_list.currentItem()
    claim_id = current_item.data(Qt.UserRole) if current_item is not None else None
    if claim_id is None:
        row.set_value("等待选择报销组", state="muted")
        return

    try:
        invoices = db.get_claim_invoices(claim_id)
    except Exception:
        row.set_value("暂时无法检查", state="warning")
        return

    text, state = _export_naming_state(list(invoices or []))
    row.set_value(text, state=state)


def _schedule_export_naming_check(window) -> None:
    QTimer.singleShot(
        0,
        lambda: _sync_export_naming_check(window) if isValid(window) else None,
    )


def _install_export_naming_refresh(window, page: QWidget) -> None:
    if page.property("exportNamingRefreshInstalled"):
        return
    page.setProperty("exportNamingRefreshInstalled", True)

    group_list = getattr(window, "export_group_list", None)
    if group_list is not None:
        group_list.currentRowChanged.connect(
            lambda _row: _schedule_export_naming_check(window)
        )

    for method_name in ("_sync_export_claim_selection", "_refresh_export_page"):
        original = getattr(window, method_name, None)
        if original is None:
            continue

        @wraps(original)
        def wrapped(*args, __original=original, **kwargs):
            result = __original(*args, **kwargs)
            _schedule_export_naming_check(window)
            return result

        setattr(window, method_name, wrapped)


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
        naming = ChecklistRow("文件命名", "等待选择报销组", ok=None)
        naming.setObjectName("ExportNamingChecklistRow")
        hint = getattr(window, "lbl_export_action_hint", None)
        index = integrity.body_layout.indexOf(hint) if hint is not None else -1
        if index >= 0:
            integrity.body_layout.insertWidget(index, naming)
        else:
            integrity.body_layout.addWidget(naming)
        window.export_check_naming = naming

    for name in (
        "export_check_approved",
        "export_check_pending",
        "export_check_missing_attach",
        "export_check_missing_amount",
        "export_check_dir",
        "export_check_naming",
    ):
        _apply_semantic_checklist_row(getattr(window, name, None))

    _install_export_naming_refresh(window, page)
    _sync_export_naming_check(window)
    _content_width_button(getattr(window, "btn_run_export_page", None), minimum=128)


def apply_task_flow_baseline(page: QWidget) -> None:
    """Dispatch Task Flow normalization after the page has been assigned."""
    window = page.window()
    if page is getattr(window, "imports_page", None):
        apply_import_baseline(page)
    elif page is getattr(window, "export_page", None):
        apply_export_baseline(page)


__all__ = [
    "_apply_semantic_checklist_row",
    "_export_naming_state",
    "apply_dashboard_baseline",
    "apply_import_baseline",
    "apply_export_baseline",
    "apply_task_flow_baseline",
]
