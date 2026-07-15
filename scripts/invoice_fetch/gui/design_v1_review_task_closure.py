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

import weakref

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidget
from shiboken6 import isValid

from ..reimbursement import buyer_warning
from .ui_components import fit_button_to_content


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
        # These controls belong to their dedicated first-level pages. Keep the
        # existing callback object available to legacy command code, but never
        # leave a review compatibility widget off-canvas or clickable.
        target_page = getattr(window, "imports_page", None) if attr != "btn_toolbar_export" else getattr(window, "export_page", None)
        if target_page is not None:
            button.setParent(target_page)
        button.hide()
        button.setProperty("reviewCrossWorkflowActionRemoved", True)
        button.setProperty("reviewCompatibilityControl", None)

    more = getattr(window, "btn_more", None)
    if more is not None:
        more.setText("更多")
        more.setToolTip("更多审核操作")
        more.setAccessibleName("更多审核操作")
        # Keep the compact label but leave enough room for its styled size hint
        # at all supported Windows scale factors.
        fit_button_to_content(more, minimum=72, horizontal_padding=24)
        more.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    search = getattr(window, "txt_search", None)
    if search is not None:
        search.setPlaceholderText("搜索发票号 / 销售方 / 购买方 / 金额    Ctrl + F")
        search.setAccessibleName("搜索发票")

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
    if window is None or not isValid(window):
        return
    detail = getattr(window, "_detail_panel", None)
    if detail is None or not isValid(detail):
        return
    label = getattr(detail, "lbl_buyer_warning", None)
    if label is None or not isValid(label):
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
    if row is not None and isValid(row):
        row.setVisible(bool(summary))
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    button = getattr(detail, "btn_edit_reimbursement_title", None)
    if button is not None and isValid(button):
        parent = button.parentWidget()
        if parent is not None:
            _remove_widget_from_layout(parent.layout(), button)
        button.hide()
        button.setFocusPolicy(Qt.NoFocus)
        button.setProperty("reviewCompanyActionRemoved", True)

    label.style().unpolish(label)
    label.style().polish(label)
    label.update()


def _refresh_from_ref(window_ref: weakref.ReferenceType) -> None:
    target = window_ref()
    if target is not None and isValid(target):
        _refresh_compact_buyer_warning(target)


def _refresh_visible_review_from_refs(
    window_ref: weakref.ReferenceType,
    page_ref: weakref.ReferenceType,
    stack_ref: weakref.ReferenceType,
) -> None:
    target = window_ref()
    review_page = page_ref()
    stack = stack_ref()
    if (
        target is None
        or review_page is None
        or stack is None
        or not isValid(target)
        or not isValid(review_page)
        or not isValid(stack)
    ):
        return
    if stack.currentWidget() is review_page:
        _refresh_compact_buyer_warning(target)


def _install_warning_refresh(window, page: QWidget) -> None:
    if page.property("designV1BuyerWarningRefreshInstalled"):
        _refresh_compact_buyer_warning(window)
        return
    page.setProperty("designV1BuyerWarningRefreshInstalled", True)

    window_ref = weakref.ref(window)
    page_ref = weakref.ref(page)

    table = getattr(window, "table", None)
    if table is not None:
        table.itemSelectionChanged.connect(
            lambda ref=window_ref: QTimer.singleShot(
                0, lambda target_ref=ref: _refresh_from_ref(target_ref)
            )
        )

    center_stack = getattr(window, "center_stack", None)
    if center_stack is not None:
        stack_ref = weakref.ref(center_stack)
        center_stack.currentChanged.connect(
            lambda _index, wref=window_ref, pref=page_ref, sref=stack_ref: QTimer.singleShot(
                0,
                lambda: _refresh_visible_review_from_refs(wref, pref, sref),
            )
        )

    _refresh_compact_buyer_warning(window)


def apply_design_v1_review_task_closure(page: QWidget | None) -> None:
    """Enforce final Review task ownership and compact warning disclosure."""
    if page is None or not isValid(page) or page.property("designV1ReviewTaskClosureApplied"):
        return
    window = page.window()
    if window is None or not isValid(window):
        return
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
