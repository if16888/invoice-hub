"""Targeted review-workspace fixes from physical Windows visual review.

The module keeps the existing review/business callbacks intact and only
rearranges already-created widgets. It addresses the concrete UI defects seen
in the v0.1.4 review screenshots: clipped seller names, a cramped primary
review action, hidden amount/date fields, compressed reimbursement controls,
and an inconsistent sidebar help target.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .ui_components import ElidedTextLabel


PARTY_LABEL_WIDTH = 48
PRIMARY_ACTION_MIN_WIDTH = 172


def _find_layout_containing(layout: QLayout | None, widget: QWidget):
    if layout is None:
        return None
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget:
            return layout
        nested = item.layout()
        if nested is not None:
            found = _find_layout_containing(nested, widget)
            if found is not None:
                return found
    return None


def _clear_layout(layout: QLayout, preserve: set[QWidget] | None = None) -> None:
    preserve = preserve or set()
    while layout.count():
        item = layout.takeAt(0)
        nested = item.layout()
        widget = item.widget()
        if nested is not None:
            _clear_layout(nested, preserve)
            nested.deleteLater()
        elif widget is not None:
            if widget in preserve:
                widget.setParent(None)
            else:
                widget.deleteLater()


def _field_key(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setProperty("class", "DetailFieldKey")
    label.setFixedWidth(PARTY_LABEL_WIDTH)
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return label


def _replace_summary_parties(window) -> None:
    detail = window._detail_panel
    if detail.property("summaryPartiesConsolidated"):
        return
    detail.setProperty("summaryPartiesConsolidated", True)

    summary_layout = detail.summary_card.layout()
    old_seller = detail.lbl_sum_seller
    seller_layout = _find_layout_containing(summary_layout, old_seller)
    if seller_layout is None:
        return

    seller_value = ElidedTextLabel("—", detail.summary_card)
    seller_value.setProperty("class", "DetailSeller")
    seller_value.setAccessibleName("销售方")
    seller_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    seller_layout.replaceWidget(old_seller, seller_value)
    old_seller.hide()
    old_seller.deleteLater()
    seller_layout.insertWidget(0, _field_key("销售方", detail.summary_card))
    detail.lbl_sum_seller = seller_value
    window.lbl_sum_seller = seller_value

    buyer_row = QHBoxLayout()
    buyer_row.setContentsMargins(0, 0, 0, 0)
    buyer_row.setSpacing(8)
    buyer_row.addWidget(_field_key("购买方", detail.summary_card))
    buyer_value = ElidedTextLabel("—", detail.summary_card)
    buyer_value.setProperty("class", "DetailParty")
    buyer_value.setAccessibleName("购买方")
    buyer_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    buyer_row.addWidget(buyer_value, 1)

    seller_row_index = 2
    for index in range(summary_layout.count()):
        if summary_layout.itemAt(index).layout() is seller_layout:
            seller_row_index = index
            break
    summary_layout.insertLayout(seller_row_index + 1, buyer_row)
    detail.lbl_sum_buyer = buyer_value
    window.lbl_sum_buyer = buyer_value

    date_layout = _find_layout_containing(summary_layout, detail.lbl_sum_date)
    if date_layout is not None:
        date_index = date_layout.indexOf(detail.lbl_sum_date)
        date_layout.insertWidget(max(0, date_index), _field_key("费用日期", detail.summary_card))
        detail.lbl_sum_date.setAccessibleName("费用日期")

    # The number already belongs to the complete field grid below. Keeping it in
    # the summary duplicates information and consumes the narrow header height.
    detail.lbl_sum_number.hide()
    detail.lbl_sum_number.setProperty("summaryDuplicateHidden", True)

    detail.summary_card.layout().setSpacing(6)
    detail.fixed_header_container.setMaximumHeight(360)


def _rebuild_review_actions(window) -> None:
    detail = window._detail_panel
    if detail.property("reviewActionsReflowed"):
        return
    detail.setProperty("reviewActionsReflowed", True)

    old_layout = detail.inline_review_layout
    while old_layout.count():
        item = old_layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(detail.summary_card)

    stack = QFrame(detail.summary_card)
    stack.setObjectName("ReviewActionStack")
    stack.setProperty("class", "ReviewActionStack")
    stack_layout = QVBoxLayout(stack)
    stack_layout.setContentsMargins(0, 0, 0, 0)
    stack_layout.setSpacing(8)

    detail.btn_app.setMinimumWidth(PRIMARY_ACTION_MIN_WIDTH)
    detail.btn_app.setMaximumWidth(16777215)
    detail.btn_app.setFixedHeight(36)
    detail.btn_app.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    font = detail.btn_app.font()
    font.setBold(True)
    detail.btn_app.setFont(font)
    stack_layout.addWidget(detail.btn_app)

    secondary = QHBoxLayout()
    secondary.setContentsMargins(0, 0, 0, 0)
    secondary.setSpacing(8)
    for button in (detail.btn_ign, detail.btn_err):
        button.setMinimumWidth(84)
        button.setMaximumWidth(112)
        button.setFixedHeight(36)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        secondary.addWidget(button, 1)
    detail.btn_inline_more.setFixedSize(40, 36)
    secondary.addWidget(detail.btn_inline_more, 0)
    stack_layout.addLayout(secondary)

    old_layout.addWidget(stack, 1)
    detail.review_action_stack = stack
    window.review_action_stack = stack


def _show_complete_core_fields(window) -> None:
    detail = window._detail_panel
    for label in (
        detail.lbl_core_number,
        detail.lbl_core_date,
        detail.lbl_core_amount,
        detail.lbl_core_category,
        detail.lbl_core_buyer,
        detail.lbl_core_seller,
    ):
        label.show()
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    detail.invoice_core_grid.setColumnStretch(0, 0)
    detail.invoice_core_grid.setColumnStretch(1, 1)
    detail.detail_core_section.setProperty("completeCoreFields", True)


def _rebuild_claim_section(window) -> None:
    detail = window._detail_panel
    section = detail.claim_setup_section
    if section.property("claimLayoutReflowed"):
        return
    section.setProperty("claimLayoutReflowed", True)

    preserve = {
        detail.lbl_claim_assignment,
        detail.btn_claim_assignment,
        detail.combo_claims,
        detail.claim_actions_widget,
        detail.new_claim_widget,
        detail.btn_refresh_claims,
        detail.lbl_claim_total,
        detail.lbl_export_summary,
        detail.btn_new_claim_toggle,
    }
    layout = section.layout()
    _clear_layout(layout, preserve)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    title = QLabel("当前报销组", section)
    title.setProperty("class", "SectionTitle")
    layout.addWidget(title)

    assignment_row = QHBoxLayout()
    assignment_row.setContentsMargins(0, 0, 0, 0)
    assignment_row.setSpacing(8)
    detail.lbl_claim_assignment.setParent(section)
    detail.lbl_claim_assignment.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    assignment_row.addWidget(detail.lbl_claim_assignment, 1)
    detail.btn_claim_assignment.setParent(section)
    detail.btn_claim_assignment.setMinimumWidth(64)
    detail.btn_claim_assignment.setMaximumWidth(88)
    assignment_row.addWidget(detail.btn_claim_assignment, 0)
    layout.addLayout(assignment_row)

    detail.lbl_claim_total.setParent(section)
    detail.lbl_claim_total.setWordWrap(False)
    detail.lbl_claim_total.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    layout.addWidget(detail.lbl_claim_total)

    actions_widget = detail.claim_actions_widget
    actions_widget.setParent(section)
    actions_widget.setObjectName("ClaimActionRow")
    actions_widget.setProperty("class", "ClaimActionRow")
    actions_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    actions = actions_widget.layout()
    while actions.count():
        item = actions.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(actions_widget)
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(8)
    for button, minimum in (
        (detail.btn_add_to_claim, 84),
        (detail.btn_export, 64),
        (detail.btn_delete_claim, 82),
    ):
        button.setParent(actions_widget)
        button.setMinimumWidth(minimum)
        button.setMaximumWidth(120)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        actions.addWidget(button, 1)
    layout.addWidget(actions_widget)

    detail.new_claim_widget.setParent(section)
    layout.addWidget(detail.new_claim_widget)

    detail.combo_claims.setParent(section)
    detail.combo_claims.hide()
    detail.btn_refresh_claims.setParent(section)
    detail.btn_refresh_claims.hide()
    detail.lbl_export_summary.setParent(section)
    detail.lbl_export_summary.hide()
    detail.btn_new_claim_toggle.setParent(section)
    detail.btn_new_claim_toggle.hide()

    section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    detail.claim_section_title = title
    detail.claim_action_row = actions

    content = detail.reimbursement_scroll.widget()
    if content is not None and content.layout() is not None:
        content.layout().setContentsMargins(12, 12, 12, 12)
        content.layout().setSpacing(12)


def _sync_seller_tooltips(window) -> None:
    table = getattr(window, "table", None)
    if table is None or table.columnCount() <= 4:
        return
    for row in range(table.rowCount()):
        item = table.item(row, 4)
        if item is not None:
            full_text = item.text()
            if item.toolTip() != full_text:
                item.setToolTip(full_text)


def _install_seller_tooltip_sync(window) -> None:
    table = window.table
    if table.property("sellerTooltipSyncInstalled"):
        return
    table.setProperty("sellerTooltipSyncInstalled", True)
    model = table.model()
    refresh = lambda *_args: QTimer.singleShot(0, lambda: _sync_seller_tooltips(window))
    model.rowsInserted.connect(refresh)
    model.modelReset.connect(refresh)
    model.dataChanged.connect(refresh)
    _sync_seller_tooltips(window)


def _show_shortcut_popup(window) -> None:
    popup = window.shortcut_disclosure
    button = window.btn_shortcut_help
    if popup.isVisible():
        popup.hide()
        return

    popup.set_expanded(False)
    popup.adjustSize()
    anchor = button.mapToGlobal(QPoint(0, 0))
    popup_size = popup.sizeHint()
    x = anchor.x()
    y = anchor.y() - popup_size.height() - 8
    screen = QGuiApplication.screenAt(anchor)
    if screen is not None:
        available = screen.availableGeometry()
        x = max(available.left() + 8, min(x, available.right() - popup_size.width() - 8))
        y = max(available.top() + 8, min(y, available.bottom() - popup_size.height() - 8))
    popup.move(x, y)
    popup.show()
    popup.raise_()


def _normalize_help_entry(window) -> None:
    button = getattr(window, "btn_shortcut_help", None)
    popup = getattr(window, "shortcut_disclosure", None)
    if button is None or popup is None or button.property("unifiedHelpEntry"):
        return
    button.setProperty("unifiedHelpEntry", True)
    button.setText("帮助")
    button.setAccessibleName("帮助")
    button.setToolTip("查看审核快捷键")
    button.setIconSize(QSize(16, 16))
    button.setFlat(False)
    button.setStyleSheet("")
    button.setCursor(Qt.PointingHandCursor)
    button.setMinimumHeight(36)
    try:
        button.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    button.clicked.connect(lambda _checked=False: _show_shortcut_popup(window))
    window._show_shortcut_help_popup = lambda: _show_shortcut_popup(window)


def _target_detail_width(window) -> int:
    width = max(0, window.width())
    if width <= 1366:
        return 352
    if width <= 1440:
        return 380
    return 400


def _apply_responsive_detail_width(window) -> None:
    detail = getattr(window, "_detail_panel", None)
    if detail is None:
        return
    target = _target_detail_width(window)
    detail.setMinimumWidth(target)
    detail.setMaximumWidth(target)


class _ReviewResizeFilter(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Resize:
            # InvoiceReviewApp applies its legacy metrics in resizeEvent. Run
            # once more afterwards so the physical-review width wins.
            QTimer.singleShot(0, lambda: _apply_responsive_detail_width(self.window))
        return False


def _install_responsive_detail_width(window) -> None:
    if hasattr(window, "_review_feedback_resize_filter"):
        _apply_responsive_detail_width(window)
        return
    resize_filter = _ReviewResizeFilter(window)
    window.installEventFilter(resize_filter)
    window._review_feedback_resize_filter = resize_filter
    _apply_responsive_detail_width(window)


def sync_review_feedback_state(window) -> None:
    """Refresh visual values after the app has populated the selected invoice."""
    detail = getattr(window, "_detail_panel", None)
    if detail is None:
        return
    invoice = getattr(window, "current_invoice", None) or {}
    seller = str(invoice.get("seller_name") or "").strip()
    buyer = str(invoice.get("buyer_name") or "").strip()
    expense_date = str(invoice.get("expense_date") or invoice.get("invoice_date") or "").strip()
    amount = str(invoice.get("total_amount") or "").strip()
    category = str(invoice.get("category") or "未分类").strip()

    if hasattr(detail, "lbl_sum_seller"):
        detail.lbl_sum_seller.set_value(seller or "—")
    if hasattr(detail, "lbl_sum_buyer"):
        detail.lbl_sum_buyer.set_value(buyer or "—")
    detail.lbl_sum_category.setText(category or "未分类")
    detail.lbl_sum_category.setToolTip(category)
    detail.lbl_sum_date.setText(expense_date or "—")
    detail.lbl_sum_date.setToolTip(expense_date)

    detail.lbl_core_date.set_value(expense_date or "—")
    detail.lbl_core_amount.set_value(detail._format_amount_display(amount))
    detail.lbl_core_seller.set_value(seller or "—")
    detail.lbl_core_buyer.set_value(buyer or "—")

    claim_text = detail.lbl_claim_total.text().strip()
    detail.lbl_claim_total.setToolTip(claim_text)
    detail.btn_add_to_claim.setToolTip(detail.btn_add_to_claim.text())
    valid_claims = any(
        isinstance(detail.combo_claims.itemData(index), int)
        and detail.combo_claims.itemData(index) > 0
        for index in range(detail.combo_claims.count())
    )
    detail.claim_empty_hint.setVisible(not valid_claims)
    _sync_seller_tooltips(window)


def apply_review_feedback_fixes(window) -> None:
    """Apply all physical-review corrections once to the review page."""
    page = getattr(window, "review_page", None)
    if page is None or page.property("reviewFeedbackFixesApplied"):
        return
    page.setProperty("reviewFeedbackFixesApplied", True)
    _replace_summary_parties(window)
    _rebuild_review_actions(window)
    _show_complete_core_fields(window)
    _rebuild_claim_section(window)
    _install_seller_tooltip_sync(window)
    _normalize_help_entry(window)
    _install_responsive_detail_width(window)
    window._detail_panel.combo_claims.currentIndexChanged.connect(
        lambda _index: QTimer.singleShot(0, lambda: sync_review_feedback_state(window))
    )
    sync_review_feedback_state(window)


__all__ = ["apply_review_feedback_fixes", "sync_review_feedback_state"]
