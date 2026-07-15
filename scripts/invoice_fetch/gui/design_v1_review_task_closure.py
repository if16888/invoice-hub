"""Final task-ownership closure for the Design Baseline v1.0 Review workspace.

The Review workspace is intentionally dense, but it must still own one job:
reviewing the current invoice queue. Import, mailbox scanning and export already
have dedicated primary pages and therefore do not belong in the Review command
bar. Buyer-profile mismatch information also needs to be concise and actionable
without exposing another Settings shortcut inside the review flow.

This stage changes presentation and signal wiring only. Existing import, scan and
export callbacks remain available from their dedicated pages and global shortcuts.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidget

from ..reimbursement import buyer_warning


_CROSS_WORKFLOW_BUTTONS = (
    "btn_import_local",
    "btn_scan_email",
    "btn_toolbar_export",
)


def _remove_widget_from_layout(layout: QLayout | None, widget: QWidget) -> bool:
    if layout is None:
        return False
    for index in range(layout.count() - 1, -1, -1):
        item = layout.itemAt(index)
        if item.widget() is widget:
            layout.removeWidget(widget)
            return True
        nested = item.layout()
        if nested is not None and _remove_widget_from_layout(nested, widget):
            return True
    return False


def _remove_cross_workflow_actions(window) -> None:
    """Remove Import/Scan/Export controls from the visible Review command bar."""
    toolbar = getattr(window, "workbench_top_toolbar", None)
    toolbar_layout = toolbar.layout() if toolbar is not None else None

    for attr in _CROSS_WORKFLOW_BUTTONS:
        button = getattr(window, attr, None)
        if button is None:
            continue
        _remove_widget_from_layout(toolbar_layout, button)
        parent = button.parentWidget()
        if parent is not None:
            _remove_widget_from_layout(parent.layout(), button)
        button.hide()
        button.setFocusPolicy(Qt.NoFocus)
        button.setAttribute(Qt.WA_DontShowOnScreen, True)
        button.setProperty("reviewCrossWorkflowActionRemoved", True)

    more = getattr(window, "btn_more", None)
    if more is not None:
        more.setText("更多")
        more.setToolTip("更多审核操作")
        more.setAccessibleName("更多审核操作")
        more.setMinimumWidth(72)
        more.setMaximumWidth(88)
        more.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    search = getattr(window, "txt_search", None)
    if search is not None:
        search.setPlaceholderText("搜索发票号、销售方、购买方、金额或邮件主题")
        search.setAccessibleName("搜索发票记录")

    if toolbar_layout is not None:
        toolbar_layout.setSpacing(8)
        toolbar_layout.invalidate()
    if toolbar is not None:
        toolbar.setToolTip("发票审核：搜索、筛选和处理当前记录")
        toolbar.adjustSize()


def _buyer_warning_summary(full_text: str) -> str:
    text = str(full_text or "").strip()
    if not text:
        return ""
    if "税号" in text or "纳税人识别号" in text:
        return "购买方信息与默认开票主体不一致"
    return "购买方与默认开票主体不一致"


def _refresh_compact_buyer_warning(window) -> None:
    detail = getattr(window, "_detail_panel", None)
    label = getattr(detail, "lbl_buyer_warning", None) if detail is not None else None
    if label is None:
        return

    invoice = getattr(window, "current_invoice", None) or {}
    full_text = buyer_warning(invoice, getattr(window, "config", {}) or {}) if invoice else ""
    summary = _buyer_warning_summary(full_text)

    label.setText(summary)
    label.setToolTip(full_text)
    label.setAccessibleDescription(full_text)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    label.setProperty("tone", "warning" if summary else "muted")
    label.setVisible(bool(summary))

    row = getattr(detail, "buyer_warning_action_row", None)
    if row is not None:
        row.setVisible(bool(summary))
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    button = getattr(detail, "btn_edit_reimbursement_title", None)
    if button is not None:
        parent = button.parentWidget()
        if parent is not None:
            _remove_widget_from_layout(parent.layout(), button)
        button.hide()
        button.setFocusPolicy(Qt.NoFocus)
        button.setAttribute(Qt.WA_DontShowOnScreen, True)
        button.setProperty("reviewCompanyActionRemoved", True)

    label.style().unpolish(label)
    label.style().polish(label)
    label.update()


def _install_warning_refresh(window, page: QWidget) -> None:
    if page.property("designV1BuyerWarningRefreshInstalled"):
        _refresh_compact_buyer_warning(window)
        return
    page.setProperty("designV1BuyerWarningRefreshInstalled", True)

    table = getattr(window, "table", None)
    if table is not None:
        table.itemSelectionChanged.connect(
            lambda target=window: QTimer.singleShot(
                0, lambda: _refresh_compact_buyer_warning(target)
            )
        )

    center_stack = getattr(window, "center_stack", None)
    if center_stack is not None:
        center_stack.currentChanged.connect(
            lambda _index, target=window, review_page=page: QTimer.singleShot(
                0,
                lambda: (
                    _refresh_compact_buyer_warning(target)
                    if center_stack.currentWidget() is review_page
                    else None
                ),
            )
        )

    _refresh_compact_buyer_warning(window)


def apply_design_v1_review_task_closure(page: QWidget | None) -> None:
    """Enforce final Review task ownership and compact warning disclosure."""
    if page is None or page.property("designV1ReviewTaskClosureApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    if not hasattr(window, "table"):
        return

    page.setProperty("designV1ReviewTaskClosureApplied", True)
    _remove_cross_workflow_actions(window)
    _install_warning_refresh(window, page)


__all__ = [
    "apply_design_v1_review_task_closure",
    "_buyer_warning_summary",
    "_refresh_compact_buyer_warning",
]
