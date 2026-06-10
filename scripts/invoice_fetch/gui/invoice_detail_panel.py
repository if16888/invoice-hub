# -*- coding: utf-8 -*-
"""Invoice detail panel — right-side single-invoice review panel for Invoice Hub."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QLineEdit, QTextEdit, QComboBox, QFormLayout, QGridLayout,
    QGroupBox, QScrollArea, QStackedWidget, QSizePolicy, QToolButton,
    QMenu, QLayout,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


@dataclass
class InvoiceDetailCallbacks:
    """Callbacks for InvoiceDetailPanel actions — wired by the owning window."""

    on_approve_next: Callable[[], None] = lambda: None
    on_ignore: Callable[[], None] = lambda: None
    on_mark_error: Callable[[], None] = lambda: None
    on_reset_review: Callable[[], None] = lambda: None
    on_delete_or_restore: Callable[[], None] = lambda: None

    on_open_file: Callable[[], None] = lambda: None
    on_add_attachment: Callable[[], None] = lambda: None
    on_retry_download: Callable[[], None] = lambda: None
    on_open_evidence: Callable[[], None] = lambda: None

    on_copy_number: Callable[[], None] = lambda: None
    on_locate_file: Callable[[], None] = lambda: None
    on_open_dir: Callable[[], None] = lambda: None

    on_create_claim: Callable[[], None] = lambda: None
    on_link_to_claim: Callable[[], None] = lambda: None
    on_refresh_claims: Callable[[], None] = lambda: None
    on_export_claim: Callable[[], None] = lambda: None

    on_save_fields: Callable[[], None] = lambda: None
    on_form_dirty: Callable[[], None] = lambda: None
    on_supporting_doc_changed: Callable[[int], None] = lambda idx: None
    on_claim_combo_changed: Callable[[], None] = lambda: None


class InvoiceDetailPanel(QWidget):
    """Right-side single-invoice detail panel.

    Contains: summary card, review actions, core info, files,
    claim group, notes, more-source info, bottom status line, and save button.
    """

    def __init__(self, callbacks: InvoiceDetailCallbacks = None, parent=None):
        super().__init__(parent)
        self._cb = callbacks or InvoiceDetailCallbacks()
        self._suspend_dirty_tracking = False
        self._invoice_snapshot = None
        self.current_invoice = None
        self.supporting_doc_items: list[dict] = []
        self.blockSignals(True)  # prevent callback cascade during widget creation
        self._setup_ui()
        self.blockSignals(False)
        self._connect_dirty_tracking()

    # ── public helpers ────────────────────────────────────────────

    def populate_category_options(self, options: list[str], current: str = None):
        """Fill the editable category dropdown with merged options."""
        self.combo_category.blockSignals(True)
        self.combo_category.clear()
        self.combo_category.addItems(options)
        if current:
            self.combo_category.setCurrentText(current)
        self.combo_category.blockSignals(False)

    def suspend_dirty_tracking(self):
        self._suspend_dirty_tracking = True

    def resume_dirty_tracking(self):
        self._suspend_dirty_tracking = False

    # ── internal helpers ──────────────────────────────────────────

    def _refresh_widget_style(self, widget):
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _update_status_badge(self, status):
        status_styles = {
            "to_review": ("待审核", "review"),
            "approved": ("已通过", "approved"),
            "ignored": ("已忽略", "ignored"),
            "error": ("异常", "error"),
        }
        text, variant = status_styles.get(status, ("未知", "placeholder"))
        self.lbl_sum_status.setText(text)
        self.lbl_sum_status.setProperty("variant", variant)
        self._refresh_widget_style(self.lbl_sum_status)

    def _set_summary_placeholder(self):
        self.lbl_sum_status.setText("未选择发票")
        self.lbl_sum_status.setProperty("variant", "placeholder")
        self._refresh_widget_style(self.lbl_sum_status)

    def _toggle_more_source_info(self, expanded: bool):
        self.more_source_widget.setVisible(expanded)
        self.btn_more_source.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def _toggle_note_visibility(self):
        if hasattr(self, "txt_note") and hasattr(self, "btn_toggle_note"):
            editing = not self.txt_note.isVisible()
            self.txt_note.setVisible(editing)
            if editing:
                self.btn_toggle_note.setText("备注 + 收起")
                self.lbl_note_summary.setVisible(False)
            else:
                note_text = self.txt_note.toPlainText().strip()
                if note_text:
                    summary = note_text[:60] + ("…" if len(note_text) > 60 else "")
                    self.lbl_note_summary.setText(f"备注: {summary}")
                    self.lbl_note_summary.setVisible(True)
                self.btn_toggle_note.setText("备注 + 添加" if not note_text else "备注 + 编辑")
                self.lbl_note_summary.setVisible(bool(note_text))

    def _connect_dirty_tracking(self):
        for widget in (self.txt_number, self.txt_date, self.txt_seller,
                       self.txt_buyer, self.txt_amount):
            widget.textEdited.connect(self._cb.on_form_dirty)
        self.combo_category.currentTextChanged.connect(self._cb.on_form_dirty)
        self.txt_note.textChanged.connect(self._cb.on_form_dirty)

    def _toggle_new_claim_input(self):
        """Show/hide the new-claim-group input row."""
        visible = not self.new_claim_widget.isVisible()
        self.new_claim_widget.setVisible(visible)
        self.btn_new_claim_toggle.setText("− 取消" if visible else "+ 新建报销组")

    # ── public detail API ────────────────────────────────────────

    def clear_detail(self):
        """Reset all detail fields to empty/placeholder state."""
        self.txt_id.clear()
        self.txt_number.clear()
        self.txt_date.clear()
        self.txt_invoice_date.clear()
        self.txt_date_source.clear()
        self.txt_seller.clear()
        self.txt_buyer.clear()
        self.txt_amount.clear()
        self.combo_category.setCurrentText("")
        self.txt_subject.clear()
        self.txt_path.clear()
        self.txt_path.setToolTip("")
        self.btn_open_file.setEnabled(False)
        self.btn_add_attachment.setEnabled(False)
        self.btn_retry_download.setEnabled(False)
        self.btn_retry_download.setVisible(False)
        self.txt_full_path.clear()
        self.txt_full_path.setToolTip("")
        self.txt_url.clear()
        self.txt_item_name.clear()
        self.combo_supporting_docs.blockSignals(True)
        self.combo_supporting_docs.clear()
        self.combo_supporting_docs.addItem("暂无证明材料")
        self.combo_supporting_docs.setToolTip("酒店水单、行程记录、支付截图等证明材料会显示在这里。")
        self.supporting_doc_items = []
        self.combo_supporting_docs.blockSignals(False)
        self.btn_open_extra_files.setEnabled(False)
        self.txt_note.clear()
        # Summary card
        self.lbl_sum_amount.setText("¥—")
        self.lbl_sum_date.setText("—")
        self.lbl_sum_number.setText("发票号码: —")
        self.lbl_sum_seller.setText("—")
        self.lbl_sum_category.setText("—")
        self.lbl_date_warning.clear()
        self.lbl_date_warning.setVisible(False)
        self._set_summary_placeholder()
        self.txt_buyer.setPlaceholderText("")
        # Notes
        self.lbl_note_summary.setText("")
        self.lbl_note_summary.setVisible(False)
        self.btn_toggle_note.setText("备注 + 添加")
        self.txt_note.setVisible(False)
        # Closing card
        self.lbl_closing_desc.setText("")
        self.lbl_closing_desc.setVisible(False)
        # Dirty hint
        self.lbl_dirty_hint.setText("")
        # Disable action buttons
        self.btn_app.setEnabled(False)
        self.btn_ign.setEnabled(False)
        self.btn_err.setEnabled(False)
        self.btn_rev.setEnabled(False)
        self.btn_inline_more.setEnabled(False)
        self.btn_add_to_claim.setEnabled(False)
        self.btn_save_draft.setEnabled(False)
        # Also disable form text fields
        self.txt_number.setEnabled(False)
        self.txt_date.setEnabled(False)
        self.txt_seller.setEnabled(False)
        self.txt_buyer.setEnabled(False)
        self.txt_amount.setEnabled(False)
        self.combo_category.setEnabled(False)
        self.combo_supporting_docs.setEnabled(False)
        self.txt_note.setEnabled(False)

    def set_no_selection_state(self):
        """Disable form fields — no invoice selected."""
        self.txt_number.setEnabled(False)
        self.txt_date.setEnabled(False)
        self.txt_seller.setEnabled(False)
        self.txt_buyer.setEnabled(False)
        self.txt_amount.setEnabled(False)
        self.combo_category.setEnabled(False)
        self.combo_supporting_docs.setEnabled(False)
        self.txt_note.setEnabled(False)
        self.lbl_batch_hint.setText("请选择一个发票记录")

    def set_single_selection_state(self):
        """Enable form fields — single invoice selected."""
        self.txt_number.setEnabled(True)
        self.txt_date.setEnabled(True)
        self.txt_seller.setEnabled(True)
        self.txt_buyer.setEnabled(True)
        self.txt_amount.setEnabled(True)
        self.combo_category.setEnabled(True)
        self.txt_note.setEnabled(True)
        self.btn_app.setEnabled(True)
        self.btn_ign.setEnabled(True)
        self.btn_err.setEnabled(True)
        self.btn_rev.setEnabled(True)
        self.btn_inline_more.setEnabled(True)
        self.btn_add_to_claim.setEnabled(True)
        self.lbl_batch_hint.setText("已选择 1 张发票")

    def set_multi_selection_state(self, count: int):
        """Enable review buttons for multi-selection; disable form fields."""
        self.btn_app.setEnabled(True)
        self.btn_ign.setEnabled(True)
        self.btn_err.setEnabled(True)
        self.btn_rev.setEnabled(True)
        self.btn_inline_more.setEnabled(True)
        self.txt_number.setEnabled(False)
        self.txt_date.setEnabled(False)
        self.txt_seller.setEnabled(False)
        self.txt_buyer.setEnabled(False)
        self.txt_amount.setEnabled(False)
        self.combo_category.setEnabled(False)
        self.txt_note.setEnabled(False)
        self.lbl_batch_hint.setText(f"已选择 {count} 张发票，可批量处理")

    def set_summary(self, *, amount: str = "", status: str = "",
                    date: str = "", category: str = "", seller: str = "",
                    number: str = "", buyer_warning: str = "", date_warning: str = ""):
        """Populate the summary card."""
        self.lbl_sum_amount.setText(self._format_amount_display(amount))
        self.lbl_sum_date.setText(date if date else "—")
        self.lbl_sum_number.setText(f"发票号码: {number}" if number else "发票号码: —")
        self.lbl_sum_seller.setText(seller if seller else "—")
        self.lbl_sum_category.setText(category if category else "未分类")
        self._update_status_badge(status)
        if date_warning:
            self.lbl_date_warning.setText(date_warning)
            self.lbl_date_warning.setVisible(True)
        else:
            self.lbl_date_warning.setVisible(False)

    def set_form_fields(self, *, inv_id: str = "", number: str = "",
                        date: str = "", invoice_date: str = "",
                        date_source: str = "", seller: str = "", buyer: str = "",
                        amount: str = "", category: str = ""):
        """Populate the basic-info form fields."""
        self.txt_id.setText(inv_id)
        self.txt_number.setText(number)
        self.txt_date.setText(date)
        self.txt_invoice_date.setText(invoice_date)
        self.txt_date_source.setText(date_source)
        self.txt_seller.setText(seller)
        self.txt_buyer.setText(buyer)
        self.txt_amount.setText(amount)
        self.combo_category.setCurrentText(category)

    def set_attachment_state(self, *, has_file: bool = False, has_url: bool = False,
                             file_name: str = "", file_path: str = ""):
        """Update attachment-related widgets."""
        self.txt_path.setText(file_name if file_name else "")
        self.txt_path.setToolTip(file_path)
        self.btn_open_file.setEnabled(has_file)
        self.btn_retry_download.setEnabled(not has_file and has_url)
        self.btn_retry_download.setVisible(has_url)
        self.btn_add_attachment.setEnabled(True)

    def set_note(self, text: str):
        """Set the personal note content."""
        self.txt_note.setPlainText(text)
        has_note = bool(text.strip())
        self.txt_note.setVisible(False)  # start collapsed
        if has_note:
            summary = text[:60] + ("…" if len(text) > 60 else "")
            self.lbl_note_summary.setText(f"备注: {summary}")
            self.lbl_note_summary.setVisible(True)
            self.btn_toggle_note.setText("备注 + 编辑")
        else:
            self.lbl_note_summary.setText("")
            self.lbl_note_summary.setVisible(False)
            self.btn_toggle_note.setText("备注 + 添加")

    def set_closing_status(self, missing_fields: bool = False, is_error: bool = False):
        """Set bottom status bar — only shown for warnings."""
        if missing_fields:
            self.lbl_closing_desc.setText("⚠️ 关键字段缺失，请在上方表单中补全。")
            self.lbl_closing_desc.setVisible(True)
        elif is_error:
            self.lbl_closing_desc.setText("❌ 异常发票 ｜ 需核对")
            self.lbl_closing_desc.setVisible(True)
        else:
            self.lbl_closing_desc.setText("")
            self.lbl_closing_desc.setVisible(False)

    def set_dirty_state(self, dirty: bool):
        """Update save button and dirty hint."""
        self.btn_save_draft.setEnabled(dirty)
        self.lbl_dirty_hint.setText("已修改" if dirty else "")

    def set_claim_summary(self, text: str = "", export_enabled: bool = False):
        """Update claim group summary text and export button state."""
        self.lbl_claim_total.setText(text)
        self.btn_export.setEnabled(export_enabled)

    def set_supporting_documents(self, items: list[dict]):
        """Populate the supporting-documents combo from extra_paths."""
        self.combo_supporting_docs.blockSignals(True)
        self.combo_supporting_docs.clear()
        self.supporting_doc_items = items
        if not items:
            self.combo_supporting_docs.addItem("暂无证明材料")
            self.combo_supporting_docs.setToolTip("酒店水单、行程记录、支付截图等证明材料会显示在这里。")
            self.btn_open_extra_files.setEnabled(False)
        else:
            for doc in items:
                label = doc.get("label") or Path(doc.get("path", "")).name
                self.combo_supporting_docs.addItem(label, doc)
            self.combo_supporting_docs.setToolTip("")
            self.btn_open_extra_files.setEnabled(True)
        self.combo_supporting_docs.blockSignals(False)

    def get_selected_supporting_document(self) -> dict | None:
        """Return the currently selected supporting document, or None."""
        idx = self.combo_supporting_docs.currentIndex()
        if idx < 0 or idx >= len(self.supporting_doc_items):
            return None
        return self.supporting_doc_items[idx]

    def get_form_values(self) -> dict:
        """Return current form field values for saving."""
        return {
            "invoice_number": self.txt_number.text().strip(),
            "expense_date": self.txt_date.text().strip(),
            "total_amount": self.txt_amount.text().strip(),
            "category": self.combo_category.currentText().strip(),
            "seller_name": self.txt_seller.text().strip(),
            "buyer_name": self.txt_buyer.text().strip(),
        }

    def _format_amount_display(self, amount_text: str) -> str:
        """Format amount for display."""
        amount_text = str(amount_text or "").strip()
        if not amount_text:
            return "¥—"
        try:
            from decimal import Decimal, InvalidOperation
            return f"¥{Decimal(amount_text):.2f}"
        except (InvalidOperation, ValueError, TypeError):
            return f"¥{amount_text}"

    # ── UI construction ───────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Stack: detail content vs empty state
        self.right_stack = QStackedWidget()
        layout.addWidget(self.right_stack, 1)

        # ── scrollable detail content ─────────────────────────────
        self.right_content_widget = QScrollArea()
        self.right_content_widget.setWidgetResizable(True)
        self.right_content_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.right_content_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.right_content_widget.setFrameShape(QFrame.NoFrame)

        self.right_detail_content = QWidget()
        right_content_layout = QVBoxLayout(self.right_detail_content)
        right_content_layout.setContentsMargins(10, 6, 10, 10)
        right_content_layout.setSpacing(8)
        right_content_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.right_layout = right_content_layout
        self.right_content_widget.setWidget(self.right_detail_content)

        # ── empty state widget ────────────────────────────────────
        self.right_empty_widget = QWidget()
        right_empty_layout = QVBoxLayout(self.right_empty_widget)
        right_empty_layout.setContentsMargins(16, 16, 16, 16)
        right_empty_layout.setSpacing(12)
        right_empty_layout.addStretch(1)

        right_empty_card = QWidget()
        right_empty_card.setProperty("class", "SummaryCard")
        right_empty_card_layout = QVBoxLayout(right_empty_card)
        right_empty_card_layout.setContentsMargins(20, 18, 20, 18)
        right_empty_card_layout.setSpacing(8)

        self.lbl_right_empty_title = QLabel("当前没有发票记录")
        self.lbl_right_empty_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.lbl_right_empty_title.setStyleSheet("color: #111827;")
        self.lbl_right_empty_title.setAlignment(Qt.AlignCenter)
        right_empty_card_layout.addWidget(self.lbl_right_empty_title)

        self.lbl_right_empty_desc = QLabel(
            "导入本地发票或扫描邮箱后，这里会显示发票摘要、详情和原件预览。"
        )
        self.lbl_right_empty_desc.setWordWrap(True)
        self.lbl_right_empty_desc.setAlignment(Qt.AlignCenter)
        self.lbl_right_empty_desc.setStyleSheet("color: #6B7280;")
        right_empty_card_layout.addWidget(self.lbl_right_empty_desc)

        right_empty_layout.addWidget(right_empty_card)
        right_empty_layout.addStretch(2)
        self.right_stack.addWidget(self.right_content_widget)
        self.right_stack.addWidget(self.right_empty_widget)
        self.right_stack.setCurrentWidget(self.right_content_widget)

        # ═══════════════════════════════════════════════════════════
        # Zone 1 — Summary + Review Actions
        # ═══════════════════════════════════════════════════════════
        self.summary_card = QFrame()
        self.summary_card.setProperty("class", "SummaryCard")
        self.summary_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.summary_card.setStyleSheet('''
            QFrame.SummaryCard {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
            }
        ''')
        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(6)

        # Row 1: amount + status badge
        amount_row = QHBoxLayout()
        amount_row.setContentsMargins(0, 0, 0, 0)
        amount_row.setSpacing(10)
        self.lbl_sum_amount = QLabel("¥—")
        self.lbl_sum_amount.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self.lbl_sum_amount.setStyleSheet("color: #111827;")
        amount_row.addWidget(self.lbl_sum_amount)
        amount_row.addStretch(1)
        self.lbl_sum_status = QLabel("未选择发票")
        self.lbl_sum_status.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_sum_status.setAlignment(Qt.AlignCenter)
        self.lbl_sum_status.setMaximumWidth(80)
        self.lbl_sum_status.setProperty("class", "StatusBadge")
        self._set_summary_placeholder()
        amount_row.addWidget(self.lbl_sum_status)
        summary_layout.addLayout(amount_row)

        # Row 2: category | date (two key fields, readable)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(10)
        self.lbl_sum_category = QLabel("—")
        self.lbl_sum_category.setFont(QFont("Segoe UI", 12))
        self.lbl_sum_category.setStyleSheet("color: #374151;")
        meta_row.addWidget(self.lbl_sum_category)
        sep1 = QLabel("|")
        sep1.setStyleSheet("color: #D1D5DB; font-size: 13px;")
        meta_row.addWidget(sep1)
        self.lbl_sum_date = QLabel("—")
        self.lbl_sum_date.setFont(QFont("Segoe UI", 12))
        self.lbl_sum_date.setStyleSheet("color: #374151;")
        meta_row.addWidget(self.lbl_sum_date)
        meta_row.addStretch(1)
        summary_layout.addLayout(meta_row)

        # Row 3: seller (prominent)
        seller_row = QHBoxLayout()
        seller_row.setContentsMargins(0, 0, 0, 0)
        seller_row.setSpacing(8)
        self.lbl_sum_seller = QLabel("—")
        self.lbl_sum_seller.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.lbl_sum_seller.setStyleSheet("color: #111827;")
        seller_row.addWidget(self.lbl_sum_seller, 1)
        summary_layout.addLayout(seller_row)

        # Row 4: invoice number
        num_row = QHBoxLayout()
        num_row.setContentsMargins(0, 0, 0, 0)
        num_row.setSpacing(8)
        self.lbl_sum_number = QLabel("发票号码: —")
        self.lbl_sum_number.setFont(QFont("Segoe UI", 11))
        self.lbl_sum_number.setStyleSheet("color: #4B5563;")
        num_row.addWidget(self.lbl_sum_number)
        num_row.addStretch(1)
        summary_layout.addLayout(num_row)

        # Date warning (hidden by default)
        self.lbl_date_warning = QLabel("")
        self.lbl_date_warning.setWordWrap(True)
        self.lbl_date_warning.setProperty("class", "InlineWarning")
        self.lbl_date_warning.setVisible(False)
        summary_layout.addWidget(self.lbl_date_warning)

        # Row 5: review action buttons
        self.inline_review_layout = QHBoxLayout()
        self.inline_review_layout.setSpacing(8)
        self.inline_review_layout.setContentsMargins(0, 4, 0, 0)

        self.btn_app = QPushButton("通过并下一张")
        self.btn_app.setProperty("class", "PrimaryBtn")
        self.btn_app.setMaximumWidth(120)
        self.btn_app.setMinimumHeight(30)
        self.btn_app.setFont(QFont("Segoe UI", 12))
        self.btn_app.clicked.connect(self._cb.on_approve_next)
        self.inline_review_layout.addWidget(self.btn_app)

        self.btn_ign = QPushButton("忽略")
        self.btn_ign.setProperty("class", "SecondaryBtn")
        self.btn_ign.setMaximumWidth(60)
        self.btn_ign.setMinimumHeight(30)
        self.btn_ign.setFont(QFont("Segoe UI", 12))
        self.btn_ign.clicked.connect(self._cb.on_ignore)
        self.inline_review_layout.addWidget(self.btn_ign)

        self.btn_err = QPushButton("异常")
        self.btn_err.setProperty("class", "DangerOutlineBtn")
        self.btn_err.setMaximumWidth(60)
        self.btn_err.setMinimumHeight(30)
        self.btn_err.setFont(QFont("Segoe UI", 12))
        self.btn_err.clicked.connect(self._cb.on_mark_error)
        self.inline_review_layout.addWidget(self.btn_err)

        self.inline_more_menu = QMenu(self)
        self.action_inline_reset = self.inline_more_menu.addAction("重置为待审核")
        self.action_inline_delete = self.inline_more_menu.addAction("删除发票")
        self.inline_more_menu.addSeparator()
        self.action_copy_number = self.inline_more_menu.addAction("复制发票号码")
        self.action_locate_file = self.inline_more_menu.addAction("定位原件文件")
        self.action_open_dir = self.inline_more_menu.addAction("打开文件所在目录")

        self.action_inline_reset.triggered.connect(self._cb.on_reset_review)
        self.action_inline_delete.triggered.connect(self._cb.on_delete_or_restore)
        self.action_copy_number.triggered.connect(self._cb.on_copy_number)
        self.action_locate_file.triggered.connect(self._cb.on_locate_file)
        self.action_open_dir.triggered.connect(self._cb.on_open_dir)

        self.btn_inline_more = QPushButton("⋯")
        self.btn_inline_more.setProperty("class", "SecondaryBtn")
        self.btn_inline_more.setMaximumWidth(40)
        self.btn_inline_more.setMinimumHeight(30)
        self.btn_inline_more.setFont(QFont("Segoe UI", 13))
        self.btn_inline_more.setMenu(self.inline_more_menu)
        self.inline_review_layout.addWidget(self.btn_inline_more)
        self.inline_review_layout.addStretch(1)

        summary_layout.addLayout(self.inline_review_layout)
        right_content_layout.addWidget(self.summary_card)

        # Compat variables for hidden/deprecated review actions tab
        self.review_actions_section = QFrame(self)
        self.review_actions_section.setVisible(False)
        self.review_actions_section.setProperty("class", "DetailSection")

        self.lbl_batch_hint = QLabel("请选择一个发票记录", self)
        self.lbl_batch_hint.setVisible(False)

        self.btn_rev = QPushButton("重置为待审核", self)
        self.btn_rev.setVisible(False)
        self.btn_rev.setProperty("class", "SecondaryBtn")
        self.btn_rev.setMaximumWidth(132)

        self.btn_delete_invoice = QPushButton("删除发票", self)
        self.btn_delete_invoice.setVisible(False)
        self.btn_delete_invoice.setProperty("class", "TextDangerBtn")
        self.btn_delete_invoice.setMaximumWidth(96)
        self.btn_delete_invoice.clicked.connect(self._cb.on_delete_or_restore)

        # ═══════════════════════════════════════════════════════════
        # Zone 2 — 基本信息
        # ═══════════════════════════════════════════════════════════
        self.detail_core_section = QFrame()
        self.detail_core_section.setProperty("class", "DetailSection")
        self.detail_core_section.setStyleSheet('''
            QFrame.DetailSection {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
            }
        ''')
        detail_core_layout = QVBoxLayout(self.detail_core_section)
        detail_core_layout.setContentsMargins(12, 8, 12, 10)
        detail_core_layout.setSpacing(8)

        # Title row with save button
        core_title_row = QHBoxLayout()
        core_title_row.setContentsMargins(0, 0, 0, 0)
        core_title_row.setSpacing(8)
        core_title = QLabel("基本信息")
        core_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        core_title.setStyleSheet("color: #111827; border: none; background: transparent;")
        core_title_row.addWidget(core_title)
        core_title_row.addStretch(1)

        self.lbl_dirty_hint = QLabel("")
        self.lbl_dirty_hint.setFont(QFont("Segoe UI", 11))
        self.lbl_dirty_hint.setStyleSheet("color: #6B7280; border: none; background: transparent;")
        core_title_row.addWidget(self.lbl_dirty_hint)

        self.btn_save_draft = QPushButton("保存修改")
        self.btn_save_draft.setProperty("class", "PrimaryBtn")
        self.btn_save_draft.setMinimumWidth(80)
        self.btn_save_draft.setMaximumWidth(100)
        self.btn_save_draft.setMinimumHeight(28)
        self.btn_save_draft.setFont(QFont("Segoe UI", 12))
        self.btn_save_draft.clicked.connect(self._cb.on_save_fields)
        core_title_row.addWidget(self.btn_save_draft)
        detail_core_layout.addLayout(core_title_row)

        # Form grid — 4 rows, readable layout
        core_fields = QWidget()
        self.invoice_core_grid = QGridLayout(core_fields)
        self.invoice_core_grid.setContentsMargins(0, 0, 0, 0)
        self.invoice_core_grid.setHorizontalSpacing(10)
        self.invoice_core_grid.setVerticalSpacing(8)

        def core_label(text):
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setStyleSheet("color: #374151; border: none; background: transparent;")
            return lbl

        self.txt_number = QLineEdit()
        self.txt_number.setFont(QFont("Segoe UI", 12))
        self.txt_number.setMinimumHeight(28)
        self.txt_date = QLineEdit()
        self.txt_date.setFont(QFont("Segoe UI", 12))
        self.txt_date.setMinimumHeight(28)
        self.txt_date.setPlaceholderText("YYYY-MM-DD")
        self.txt_amount = QLineEdit()
        self.txt_amount.setFont(QFont("Segoe UI", 12))
        self.txt_amount.setMinimumHeight(28)
        self.combo_category = QComboBox()
        self.combo_category.setEditable(True)
        self.combo_category.setFont(QFont("Segoe UI", 12))
        self.combo_category.setMinimumHeight(28)
        self.txt_seller = QLineEdit()
        self.txt_seller.setFont(QFont("Segoe UI", 12))
        self.txt_seller.setMinimumHeight(28)
        self.txt_buyer = QLineEdit()
        self.txt_buyer.setFont(QFont("Segoe UI", 12))
        self.txt_buyer.setMinimumHeight(28)
        self.txt_seller.textChanged.connect(self.txt_seller.setToolTip)
        self.txt_buyer.textChanged.connect(self.txt_buyer.setToolTip)

        # Row 0: number | date
        self.invoice_core_grid.addWidget(core_label("发票号码:"), 0, 0)
        self.invoice_core_grid.addWidget(self.txt_number, 0, 1)
        self.invoice_core_grid.addWidget(core_label("费用日期:"), 0, 2)
        self.invoice_core_grid.addWidget(self.txt_date, 0, 3)

        # Row 1: amount | category
        self.invoice_core_grid.addWidget(core_label("金额:"), 1, 0)
        self.invoice_core_grid.addWidget(self.txt_amount, 1, 1)
        self.invoice_core_grid.addWidget(core_label("消费类型:"), 1, 2)
        self.invoice_core_grid.addWidget(self.combo_category, 1, 3)

        # Row 2: seller (full width)
        self.invoice_core_grid.addWidget(core_label("销售方:"), 2, 0)
        self.invoice_core_grid.addWidget(self.txt_seller, 2, 1, 1, 3)

        # Row 3: buyer (full width)
        self.invoice_core_grid.addWidget(core_label("购买方:"), 3, 0)
        self.invoice_core_grid.addWidget(self.txt_buyer, 3, 1, 1, 3)

        self.invoice_core_grid.setColumnStretch(1, 1)
        self.invoice_core_grid.setColumnStretch(3, 1)
        detail_core_layout.addWidget(core_fields)
        right_content_layout.addWidget(self.detail_core_section)

        # ═══════════════════════════════════════════════════════════
        # Zone 3 — 材料与报销 (merged files + claim group)
        # ═══════════════════════════════════════════════════════════
        self.detail_files_section = QFrame()
        self.detail_files_section.setProperty("class", "DetailSection")
        self.detail_files_section.setStyleSheet('''
            QFrame.DetailSection {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
            }
        ''')
        detail_files_layout = QVBoxLayout(self.detail_files_section)
        detail_files_layout.setContentsMargins(12, 8, 12, 10)
        detail_files_layout.setSpacing(8)
        files_title = QLabel("材料与报销")
        files_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        files_title.setStyleSheet("color: #111827; border: none; background: transparent;")
        detail_files_layout.addWidget(files_title)

        # — attachment row —
        attach_row = QHBoxLayout()
        attach_row.setContentsMargins(0, 0, 0, 0)
        attach_row.setSpacing(6)
        attach_label = QLabel("原件:")
        attach_label.setFont(QFont("Segoe UI", 12))
        attach_label.setStyleSheet("color: #374151; border: none; background: transparent;")
        attach_row.addWidget(attach_label)
        self.txt_path = QLineEdit()
        self.txt_path.setReadOnly(True)
        self.txt_path.setFont(QFont("Segoe UI", 12))
        self.txt_path.setMinimumHeight(28)
        attach_row.addWidget(self.txt_path, 1)
        self.btn_open_file = QPushButton("查看")
        self.btn_open_file.clicked.connect(self._cb.on_open_file)
        self.btn_open_file.setFont(QFont("Segoe UI", 12))
        self.btn_open_file.setMinimumHeight(28)
        self.btn_open_file.setProperty("class", "SecondaryBtn")
        attach_row.addWidget(self.btn_open_file)
        self.btn_add_attachment = QPushButton("补原件")
        self.btn_add_attachment.clicked.connect(self._cb.on_add_attachment)
        self.btn_add_attachment.setFont(QFont("Segoe UI", 12))
        self.btn_add_attachment.setMinimumHeight(28)
        self.btn_add_attachment.setProperty("class", "SecondaryBtn")
        attach_row.addWidget(self.btn_add_attachment)
        self.btn_retry_download = QPushButton("重试下载")
        self.btn_retry_download.clicked.connect(self._cb.on_retry_download)
        self.btn_retry_download.setFont(QFont("Segoe UI", 12))
        self.btn_retry_download.setMinimumHeight(28)
        self.btn_retry_download.setProperty("class", "SecondaryBtn")
        attach_row.addWidget(self.btn_retry_download)
        detail_files_layout.addLayout(attach_row)

        # — evidence row —
        evidence_row = QHBoxLayout()
        evidence_row.setContentsMargins(0, 0, 0, 0)
        evidence_row.setSpacing(6)
        evidence_label = QLabel("证明:")
        evidence_label.setFont(QFont("Segoe UI", 12))
        evidence_label.setStyleSheet("color: #374151; border: none; background: transparent;")
        evidence_row.addWidget(evidence_label)
        self.combo_supporting_docs = QComboBox()
        self.combo_supporting_docs.setFont(QFont("Segoe UI", 12))
        self.combo_supporting_docs.setMinimumHeight(28)
        self.combo_supporting_docs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_supporting_docs.view().setTextElideMode(Qt.ElideMiddle)
        self.combo_supporting_docs.currentIndexChanged.connect(self._cb.on_supporting_doc_changed)
        evidence_row.addWidget(self.combo_supporting_docs, 1)
        self.btn_open_extra_files = QPushButton("查看")
        self.btn_open_extra_files.clicked.connect(self._cb.on_open_evidence)
        self.btn_open_extra_files.setFont(QFont("Segoe UI", 12))
        self.btn_open_extra_files.setMinimumHeight(28)
        self.btn_open_extra_files.setProperty("class", "SecondaryBtn")
        self.btn_open_extra_files.setEnabled(False)
        evidence_row.addWidget(self.btn_open_extra_files)
        detail_files_layout.addLayout(evidence_row)

        # — claim group row —
        claim_row = QHBoxLayout()
        claim_row.setContentsMargins(0, 2, 0, 0)
        claim_row.setSpacing(6)
        claim_label = QLabel("报销组:")
        claim_label.setFont(QFont("Segoe UI", 12))
        claim_label.setStyleSheet("color: #374151; border: none; background: transparent;")
        claim_row.addWidget(claim_label)
        self.combo_claims = QComboBox()
        self.combo_claims.setFont(QFont("Segoe UI", 12))
        self.combo_claims.setMinimumHeight(28)
        self.combo_claims.currentIndexChanged.connect(self._cb.on_claim_combo_changed)
        claim_row.addWidget(self.combo_claims, 1)
        self.btn_refresh_claims = QPushButton("刷新")
        self.btn_refresh_claims.clicked.connect(self._cb.on_refresh_claims)
        self.btn_refresh_claims.setFont(QFont("Segoe UI", 12))
        self.btn_refresh_claims.setMinimumHeight(28)
        self.btn_refresh_claims.setProperty("class", "SecondaryBtn")
        claim_row.addWidget(self.btn_refresh_claims)
        detail_files_layout.addLayout(claim_row)

        # — claim total + actions row —
        claim_total_row = QHBoxLayout()
        claim_total_row.setContentsMargins(0, 0, 0, 0)
        claim_total_row.setSpacing(8)
        self.lbl_claim_total = QLabel("当前组 0 张｜合计 ¥0.00")
        self.lbl_claim_total.setFont(QFont("Segoe UI", 12))
        self.lbl_claim_total.setStyleSheet("color: #374151; border: none; background: transparent;")
        claim_total_row.addWidget(self.lbl_claim_total, 1)

        self.btn_add_to_claim = QPushButton("加入当前发票")
        self.btn_add_to_claim.clicked.connect(self._cb.on_link_to_claim)
        self.btn_add_to_claim.setProperty("class", "SecondaryBtn")
        self.btn_add_to_claim.setFont(QFont("Segoe UI", 12))
        self.btn_add_to_claim.setMinimumHeight(28)
        self.btn_add_to_claim.setMaximumWidth(130)
        claim_total_row.addWidget(self.btn_add_to_claim)

        self.btn_export = QPushButton("导出报销包")
        self.btn_export.setProperty("class", "SecondaryBtn")
        self.btn_export.setEnabled(False)
        self.btn_export.setFont(QFont("Segoe UI", 12))
        self.btn_export.setMinimumHeight(28)
        self.btn_export.setMaximumWidth(120)
        self.btn_export.clicked.connect(self._cb.on_export_claim)
        claim_total_row.addWidget(self.btn_export)
        detail_files_layout.addLayout(claim_total_row)

        # — new claim group (hidden by default) —
        self.btn_new_claim_toggle = QPushButton("+ 新建报销组")
        self.btn_new_claim_toggle.setProperty("class", "TextBtn")
        self.btn_new_claim_toggle.setFont(QFont("Segoe UI", 12))
        self.btn_new_claim_toggle.setStyleSheet(
            "text-align: left; color: #4B5563; border: none; background: transparent; padding: 0;"
        )
        self.btn_new_claim_toggle.clicked.connect(self._toggle_new_claim_input)
        detail_files_layout.addWidget(self.btn_new_claim_toggle, 0, Qt.AlignLeft)

        self.new_claim_widget = QWidget()
        new_claim_layout = QHBoxLayout(self.new_claim_widget)
        new_claim_layout.setContentsMargins(0, 2, 0, 0)
        new_claim_layout.setSpacing(6)
        self.txt_new_claim = QLineEdit()
        self.txt_new_claim.setFont(QFont("Segoe UI", 12))
        self.txt_new_claim.setPlaceholderText("输入新报销组名称...")
        self.txt_new_claim.setMinimumHeight(28)
        new_claim_layout.addWidget(self.txt_new_claim, 1)
        self.btn_create_claim = QPushButton("确认新建")
        self.btn_create_claim.setProperty("class", "SecondaryBtn")
        self.btn_create_claim.setFont(QFont("Segoe UI", 12))
        self.btn_create_claim.setMinimumHeight(28)
        self.btn_create_claim.setMaximumWidth(100)
        self.btn_create_claim.clicked.connect(self._cb.on_create_claim)
        new_claim_layout.addWidget(self.btn_create_claim)
        self.new_claim_widget.setVisible(False)
        detail_files_layout.addWidget(self.new_claim_widget)

        # Export summary (hidden, one-liner)
        self.lbl_export_summary = QLabel()
        self.lbl_export_summary.setFont(QFont("Segoe UI", 11))
        self.lbl_export_summary.setStyleSheet("color: #9CA3AF; border: none; background: transparent;")
        self.lbl_export_summary.setWordWrap(True)
        self.lbl_export_summary.setText("上一次导出：暂无")
        self.lbl_export_summary.setVisible(False)
        detail_files_layout.addWidget(self.lbl_export_summary)

        # Also expose claim_setup_section for backward compat
        self.claim_setup_section = self.detail_files_section

        right_content_layout.addWidget(self.detail_files_section)

        # ═══════════════════════════════════════════════════════════
        # Zone 4 — 备注 / 更多来源信息
        # ═══════════════════════════════════════════════════════════
        self.review_note_section = QFrame()
        self.review_note_section.setProperty("class", "DetailSection")
        self.review_note_section.setStyleSheet('''
            QFrame.DetailSection {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
            }
        ''')
        review_note_layout = QVBoxLayout(self.review_note_section)
        review_note_layout.setContentsMargins(12, 6, 12, 8)
        review_note_layout.setSpacing(6)

        # Inline note summary row
        note_row = QHBoxLayout()
        note_row.setContentsMargins(0, 0, 0, 0)
        note_row.setSpacing(6)
        self.btn_toggle_note = QPushButton("备注 + 添加")
        self.btn_toggle_note.setProperty("class", "TextBtn")
        self.btn_toggle_note.setFont(QFont("Segoe UI", 12))
        self.btn_toggle_note.setStyleSheet(
            "text-align: left; color: #4B5563; border: none; background: transparent; padding: 0;"
        )
        self.btn_toggle_note.clicked.connect(self._toggle_note_visibility)
        note_row.addWidget(self.btn_toggle_note)
        self.lbl_note_summary = QLabel("")
        self.lbl_note_summary.setFont(QFont("Segoe UI", 12))
        self.lbl_note_summary.setStyleSheet("color: #374151; border: none; background: transparent;")
        self.lbl_note_summary.setWordWrap(True)
        self.lbl_note_summary.setVisible(False)
        note_row.addWidget(self.lbl_note_summary, 1)
        review_note_layout.addLayout(note_row)

        self.txt_note = QTextEdit()
        self.txt_note.setFont(QFont("Segoe UI", 12))
        self.txt_note.setMinimumHeight(56)
        self.txt_note.setMaximumHeight(72)
        self.txt_note.setPlaceholderText("可填写报销说明、事项背景、客户/项目等。")
        self.txt_note.setVisible(False)
        review_note_layout.addWidget(self.txt_note)
        right_content_layout.addWidget(self.review_note_section)

        # — More source info (folded) —
        self.btn_more_source = QToolButton()
        self.btn_more_source.setText("更多来源信息")
        self.btn_more_source.setFont(QFont("Segoe UI", 12))
        self.btn_more_source.setCheckable(True)
        self.btn_more_source.setChecked(False)
        self.btn_more_source.setArrowType(Qt.RightArrow)
        self.btn_more_source.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_more_source.setProperty("class", "Disclosure")
        self.btn_more_source.toggled.connect(self._toggle_more_source_info)
        right_content_layout.addWidget(self.btn_more_source, 0, Qt.AlignLeft)

        self.more_source_widget = QWidget()
        more_source_layout = QFormLayout(self.more_source_widget)
        more_source_layout.setContentsMargins(4, 4, 0, 4)
        more_source_layout.setLabelAlignment(Qt.AlignRight)
        more_source_layout.setSpacing(4)

        self.txt_id = QLineEdit()
        self.txt_id.setReadOnly(True)
        self.txt_id.setFont(QFont("Segoe UI", 11))
        more_source_layout.addRow("发票 ID:", self.txt_id)

        self.txt_invoice_date = QLineEdit()
        self.txt_invoice_date.setReadOnly(True)
        self.txt_invoice_date.setFont(QFont("Segoe UI", 11))
        more_source_layout.addRow("开票日期:", self.txt_invoice_date)

        self.txt_date_source = QLineEdit()
        self.txt_date_source.setReadOnly(True)
        self.txt_date_source.setFont(QFont("Segoe UI", 11))
        more_source_layout.addRow("日期来源:", self.txt_date_source)

        self.txt_subject = QLineEdit()
        self.txt_subject.setReadOnly(True)
        self.txt_subject.setFont(QFont("Segoe UI", 11))
        more_source_layout.addRow("邮件主题:", self.txt_subject)

        self.txt_url = QLineEdit()
        self.txt_url.setReadOnly(True)
        self.txt_url.setFont(QFont("Segoe UI", 11))
        more_source_layout.addRow("下载链接:", self.txt_url)

        self.txt_item_name = QLineEdit()
        self.txt_item_name.setReadOnly(True)
        self.txt_item_name.setFont(QFont("Segoe UI", 11))
        more_source_layout.addRow("项目名称:", self.txt_item_name)

        self.txt_full_path = QLineEdit()
        self.txt_full_path.setReadOnly(True)
        self.txt_full_path.setFont(QFont("Segoe UI", 11))
        more_source_layout.addRow("完整文件路径:", self.txt_full_path)
        self.more_source_widget.setVisible(False)
        right_content_layout.addWidget(self.more_source_widget)

        # ── Bottom status bar (minimal, only warnings) ────────────
        self.closing_card = QFrame()
        self.closing_card.setFrameShape(QFrame.StyledPanel)
        self.closing_card.setStyleSheet('''
            QFrame {
                background-color: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 4px;
            }
        ''')
        closing_layout = QHBoxLayout(self.closing_card)
        closing_layout.setContentsMargins(10, 4, 10, 4)
        closing_layout.setSpacing(4)

        self.lbl_closing_desc = QLabel("")
        self.lbl_closing_desc.setWordWrap(True)
        self.lbl_closing_desc.setFont(QFont("Segoe UI", 11))
        self.lbl_closing_desc.setStyleSheet("color: #4B5563; border: none; background: transparent;")
        self.lbl_closing_desc.setVisible(False)
        closing_layout.addWidget(self.lbl_closing_desc)
        closing_layout.addStretch(1)

        right_content_layout.addWidget(self.closing_card)
        right_content_layout.addStretch(1)

        # initial states
        self.btn_save_draft.setEnabled(False)
        self.lbl_dirty_hint.setText("")
        self.btn_app.setEnabled(False)
        self.btn_ign.setEnabled(False)
        self.btn_err.setEnabled(False)
        self.btn_rev.setEnabled(False)
        self.btn_inline_more.setEnabled(False)
        self.btn_add_to_claim.setEnabled(False)
        self.btn_open_file.setEnabled(False)
        self.btn_add_attachment.setEnabled(False)
        self.btn_retry_download.setEnabled(False)
        self.btn_retry_download.setVisible(False)
        self.btn_open_extra_files.setEnabled(False)
        self.txt_number.setEnabled(False)
        self.txt_date.setEnabled(False)
        self.txt_seller.setEnabled(False)
        self.txt_buyer.setEnabled(False)
        self.txt_amount.setEnabled(False)
        self.combo_category.setEnabled(False)
        self.combo_supporting_docs.setEnabled(False)
        self.txt_note.setEnabled(False)
