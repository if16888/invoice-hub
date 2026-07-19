"""Final task-ownership closure for the Design Baseline v1.0 Review workspace.

The Review workspace is intentionally dense, but it must still own one job:
reviewing the current invoice queue. Import, mailbox scanning and export already
have dedicated primary pages and therefore do not belong in the Review command
bar. Buyer-profile mismatch information also needs to be concise, accurate and
synchronized with the selected invoice.
"""

from __future__ import annotations

import weakref

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidget
from shiboken6 import isValid

from ..reimbursement import buyer_warning, compact_buyer_warning
from .ui_components import fit_button_to_content


_CROSS_WORKFLOW_BUTTONS = (
    "btn_import_local",
    "btn_scan_email",
    "btn_toolbar_export",
)


class _CommandCompatibility:
    """Non-widget compatibility surface for legacy callers."""

    def __init__(self, action, legacy_text=None):
        self._action = action
        self._legacy_text = legacy_text
        self._props = {
            "reviewCrossWorkflowActionRemoved": True,
            "reviewCompatibilityControl": None,
        }

    def property(self, name):
        return self._props.get(name, self._action.property(name))

    def setProperty(self, name, value):
        self._props[name] = value

    def text(self):
        return self._legacy_text or self._action.text()

    def setText(self, value):
        self._legacy_text = value

    def style(self):
        return _NullStyle()

    def isEnabled(self):
        return self._action.isEnabled()

    def setEnabled(self, value):
        self._action.setEnabled(value)

    def clearFocus(self):
        pass

    def setFocus(self, *_args):
        pass

    def isVisible(self):
        return False

    def isHidden(self):
        return True

    def menu(self):
        return None


class _NullStyle:
    def unpolish(self, *_args):
        pass

    def polish(self, *_args):
        pass


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
        button.setProperty("reviewCrossWorkflowActionRemoved", True)
        action_name = {
            "btn_import_local": "action_import_local",
            "btn_scan_email": "action_scan_email",
            "btn_toolbar_export": "action_toolbar_export",
        }[attr]
        button.deleteLater()
        legacy_text = {
            "btn_import_local": "导入",
            "btn_scan_email": "扫描邮箱",
            "btn_toolbar_export": "导出",
        }[attr]
        setattr(
            window,
            attr,
            _CommandCompatibility(getattr(window, action_name), legacy_text),
        )

    more = getattr(window, "btn_more", None)
    if more is not None:
        more.setText("更多")
        more.setToolTip("更多审核操作")
        more.setAccessibleName("更多审核操作")
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


def _hide_redundant_review_header(window) -> None:
    """Keep Review as a dense workbench without a duplicate page title block."""
    header = getattr(window, "review_header", None)
    if header is None or not isValid(header):
        return
    parent = header.parentWidget()
    if parent is not None:
        _remove_widget_from_layout(parent.layout(), header)
    header.hide()
    header.setProperty("reviewDenseHeaderRemoved", True)


def _buyer_warning_summary(full_text: str) -> str:
    """Return canonical compact copy without migration-only aliases."""
    return compact_buyer_warning(full_text)


def _selected_invoice(window) -> dict:
    """Resolve the invoice represented by the current table selection.

    Selection is preferred over ``window.current_invoice`` because queue reloads
    temporarily preserve the latter while rebuilding the table.
    """
    table = getattr(window, "table", None)
    invoices = getattr(window, "invoices_list", None) or []
    if table is not None and isValid(table):
        selection_model = table.selectionModel()
        if selection_model is not None:
            selected = selection_model.selectedRows()
            if len(selected) == 1:
                row = selected[0].row()
                if 0 <= row < len(invoices):
                    return invoices[row] or {}
            if len(selected) > 1:
                return {}
    return getattr(window, "current_invoice", None) or {}


def _refresh_compact_buyer_warning(window) -> None:
    if window is None or not isValid(window):
        return
    detail = getattr(window, "_detail_panel", None)
    if detail is None or not isValid(detail):
        return
    label = getattr(detail, "lbl_buyer_warning", None)
    if label is None or not isValid(label):
        return

    invoice = _selected_invoice(window)
    full_text = buyer_warning(invoice, getattr(window, "config", {}) or {}) if invoice else ""
    display_text = _buyer_warning_summary(full_text)

    # Match InvoiceDetailPanel.set_summary exactly so initial selection, filter
    # changes and later row changes never alternate between two phrasings.
    label.setText(f"⚠️ {display_text}" if display_text else "")
    label.setToolTip(display_text)
    label.setAccessibleDescription(display_text)
    label.setObjectName("CompactBuyerWarning")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    label.setMinimumWidth(0)
    label.setMaximumWidth(16777215)
    label.setMinimumHeight(44)
    label.setMaximumHeight(72)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    label.setProperty("tone", "warning" if display_text else "muted")
    label.setVisible(bool(display_text))

    # Keep the editable/read-only buyer field synchronized with the same source.
    # The visible banner uses compact copy; the field tooltip retains the detailed
    # compatibility wording used by diagnostics and existing integrations.
    buyer_field = getattr(window, "txt_buyer", None)
    if buyer_field is None:
        buyer_field = getattr(detail, "txt_buyer", None)
    if buyer_field is not None and isValid(buyer_field):
        actual_buyer = str(invoice.get("buyer_name") or "").strip() if invoice else ""
        buyer_field.setToolTip(full_text or actual_buyer)
        buyer_field.setAccessibleDescription(display_text or actual_buyer)

    row = getattr(detail, "buyer_warning_action_row", None)
    if row is not None and isValid(row):
        row.setVisible(bool(display_text))
        row.setMinimumWidth(0)
        row.setMaximumWidth(16777215)
        row.setMinimumHeight(44)
        row.setMaximumHeight(72)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        row_layout = row.layout()
        if row_layout is not None:
            row_layout.setContentsMargins(0, 0, 0, 0)

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
    label.setMinimumHeight(44)
    label.setMaximumHeight(72)
    if row is not None and isValid(row):
        row.setMinimumHeight(44)
        row.setMaximumHeight(72)
    label.update()


def _refresh_from_ref(window_ref: weakref.ReferenceType) -> None:
    target = window_ref()
    if target is not None and isValid(target):
        _refresh_compact_buyer_warning(target)


def _schedule_refresh(window_ref: weakref.ReferenceType) -> None:
    QTimer.singleShot(0, lambda ref=window_ref: _refresh_from_ref(ref))


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
            lambda ref=window_ref: _schedule_refresh(ref)
        )
        model = table.model()
        if model is not None:
            # Queue reloads block table signals and then call the selection
            # handler directly. Model changes provide a reliable final refresh
            # after the rebuilt selection and current invoice are synchronized.
            model.modelReset.connect(lambda ref=window_ref: _schedule_refresh(ref))
            model.layoutChanged.connect(lambda ref=window_ref: _schedule_refresh(ref))
            model.rowsInserted.connect(
                lambda *_args, ref=window_ref: _schedule_refresh(ref)
            )

    segment = getattr(window, "status_segment_control", None)
    if segment is not None and hasattr(segment, "changed"):
        segment.changed.connect(
            lambda _key, ref=window_ref: _schedule_refresh(ref)
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
    _schedule_refresh(window_ref)


def apply_design_v1_review_task_closure(page: QWidget | None) -> None:
    """Enforce final Review task ownership and synchronized warning disclosure."""
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
    _hide_redundant_review_header(window)
    _remove_cross_workflow_actions(window)
    _install_warning_refresh(window, page)


__all__ = [
    "apply_design_v1_review_task_closure",
    "_buyer_warning_summary",
    "_refresh_compact_buyer_warning",
    "_selected_invoice",
]
