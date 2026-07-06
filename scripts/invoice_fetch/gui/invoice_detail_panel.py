# -*- coding: utf-8 -*-



"""Invoice detail panel — right-side single-invoice review panel for Invoice Hub."""







from dataclasses import dataclass



from pathlib import Path



from typing import Callable







from PySide6.QtWidgets import (



    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,



    QLineEdit, QTextEdit, QComboBox, QFormLayout, QGridLayout,



    QGroupBox, QScrollArea, QStackedWidget, QSizePolicy, QToolButton,



    QTabWidget, QMenu, QLayout,



)



from PySide6.QtCore import Qt, Signal



from PySide6.QtGui import QFont



from .ui_components import make_button, make_badge, build_action_cluster











class DoubleClickLineEdit(QLineEdit):



    """Read-only file field that exposes a clear double-click action."""







    doubleClicked = Signal()







    def mouseDoubleClickEvent(self, event):



        if event.button() == Qt.LeftButton:



            self.doubleClicked.emit()



            event.accept()



            return



        super().mouseDoubleClickEvent(event)











class DoubleClickLabel(QLabel):



    """Compact filename or missing-state label with a double-click action."""







    doubleClicked = Signal()







    def mouseDoubleClickEvent(self, event):



        if event.button() == Qt.LeftButton:



            self.doubleClicked.emit()



            event.accept()



            return



        super().mouseDoubleClickEvent(event)











def create_labeled_action_row(



    label_text: str,



    content_widget: QWidget,



    action_widgets: list[QWidget] | None,



    *,



    label_width: int = 64,



    spacing: int = 10,



    label_alignment=Qt.AlignRight | Qt.AlignVCenter,



) -> tuple[QHBoxLayout, QLabel, QFrame | None]:



    """Build a compact row with a fixed-width label, flexible content, and an optional fixed action cluster."""



    row_layout = QHBoxLayout()



    row_layout.setContentsMargins(0, 0, 0, 0)



    row_layout.setSpacing(spacing)







    label_widget = QLabel(label_text)



    label_widget.setProperty("class", "FieldLabel")



    label_widget.setFixedWidth(label_width)



    label_widget.setAlignment(label_alignment)



    row_layout.addWidget(label_widget)







    content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)



    row_layout.addWidget(content_widget, 1)







    action_cluster = None



    if action_widgets:



        action_cluster = build_action_cluster(action_widgets)



        row_layout.addWidget(action_cluster, 0)







    return row_layout, label_widget, action_cluster


def wrap_layout_in_card(row_layout: QHBoxLayout, object_name: str) -> QFrame:
    """Wrap an existing compact row layout in a lightweight card container."""
    card = QFrame()
    card.setObjectName(object_name)
    card.setProperty("class", "DetailRowCard")
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(10, 8, 10, 8)
    card_layout.setSpacing(0)
    card_layout.addLayout(row_layout)
    return card











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



    on_add_evidence: Callable[[], None] = lambda: None



    on_retry_download: Callable[[], None] = lambda: None



    on_open_evidence: Callable[[], None] = lambda: None







    on_copy_number: Callable[[], None] = lambda: None



    on_locate_file: Callable[[], None] = lambda: None



    on_open_dir: Callable[[], None] = lambda: None







    on_create_claim: Callable[[], None] = lambda: None



    on_delete_claim: Callable[[], None] = lambda: None



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







    NEW_CLAIM_VALUE = "__new_claim__"







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







    def _apply_note_state(self, expanded: bool):
        """Apply the collapsed/expanded visual state for the note area.

        Rules:
        - expanded=True:  show note_content_row + txt_note, hide lbl_note_summary
        - expanded=False, has text:  hide note_content_row, show lbl_note_summary with summary
        - expanded=False, no text:   hide note_content_row, hide lbl_note_summary entirely
        """
        if not hasattr(self, "txt_note") or not hasattr(self, "btn_toggle_note"):
            return

        if expanded:
            self.txt_note.setVisible(True)
            if hasattr(self, "note_content_row"):
                self.note_content_row.setVisible(True)
            self.lbl_note_summary.setVisible(False)
            self.btn_toggle_note.setText("备注 + 收起")
        else:
            note_text = self.txt_note.toPlainText().strip()
            self.txt_note.setVisible(False)
            if hasattr(self, "note_content_row"):
                self.note_content_row.setVisible(False)
            if note_text:
                summary = note_text[:60] + ("…" if len(note_text) > 60 else "")
                self.lbl_note_summary.setText(f"备注：{summary}")
                self.lbl_note_summary.setVisible(True)
            else:
                self.lbl_note_summary.setText("")
                self.lbl_note_summary.setVisible(False)
            self.btn_toggle_note.setText("备注 + 展开")

    def _toggle_note_visibility(self):
        if not hasattr(self, "txt_note") or not hasattr(self, "btn_toggle_note"):
            return

        expanding = self.txt_note.isHidden()
        self._apply_note_state(expanded=expanding)







    def _connect_dirty_tracking(self):



        for widget in (self.txt_number, self.txt_date, self.txt_seller,



                       self.txt_buyer, self.txt_amount):



            widget.textEdited.connect(self._cb.on_form_dirty)



        self.combo_category.currentTextChanged.connect(self._cb.on_form_dirty)



        self.txt_note.textChanged.connect(self._cb.on_form_dirty)







    def _set_new_claim_input_visible(self, visible: bool):



        """Show the inline creator selected from the claim dropdown."""



        self.new_claim_widget.setVisible(visible)



        self.btn_new_claim_toggle.setVisible(False)



        if visible:



            self.txt_new_claim.setFocus()







    def _toggle_new_claim_input(self):



        """Close the inline creator and return to the first available group."""



        visible = self.new_claim_widget.isHidden()



        self._set_new_claim_input_visible(visible)



        if visible or self.combo_claims.currentData() != self.NEW_CLAIM_VALUE:



            return



        for index in range(self.combo_claims.count()):



            if self.combo_claims.itemData(index) != self.NEW_CLAIM_VALUE:



                self.combo_claims.setCurrentIndex(index)



                return



        self.combo_claims.setCurrentIndex(-1)







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
        self.supporting_doc_items = []
        self.combo_supporting_docs.blockSignals(True)
        self.combo_supporting_docs.clear()
        self.combo_supporting_docs.addItem("暂无证明材料")
        self.combo_supporting_docs.setToolTip("酒店水单、行程记录、支付截图等证明材料会显示在这里。")
        self.combo_supporting_docs.blockSignals(False)
        self.update_evidence_row([])
        self.lbl_sum_amount.setText("¥—")



        self.lbl_sum_date.setText("—")



        self.lbl_sum_number.setText("发票号码: —")



        self.lbl_sum_seller.setText("—")



        self.lbl_sum_category.setText("—")



        self.lbl_date_warning.clear()



        self.lbl_date_warning.setVisible(False)



        self.lbl_buyer_warning.clear()



        self.lbl_buyer_warning.setVisible(False)



        self._set_summary_placeholder()
        self._update_fixed_header_height_cap()



        self.txt_buyer.setPlaceholderText("")



        # Notes — reset to: no text, collapsed, no content row, no summary
        self.txt_note.setPlainText("")
        self._apply_note_state(expanded=False)



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







    def _update_fixed_header_height_cap(self):
        compact_header = not self.lbl_date_warning.isVisible() and not self.lbl_buyer_warning.isVisible()
        self.fixed_header_container.setMaximumHeight(280)

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







        if buyer_warning:



            self.lbl_buyer_warning.setText(f"⚠️ {buyer_warning}")



            self.lbl_buyer_warning.setVisible(True)



        else:



            self.lbl_buyer_warning.setVisible(False)







    def set_form_fields(self, *, inv_id: str = "", number: str = "",



                        date: str = "", invoice_date: str = "",



                        date_source: str = "", seller: str = "", buyer: str = "",



                        amount: str = "", category: str = "",



                        subject: str = "", item_name: str = "",



                        full_path: str = "", url: str = ""):



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



        self.txt_subject.setText(subject)



        self.txt_item_name.setText(item_name)



        self.txt_full_path.setText(full_path)



        self.txt_full_path.setToolTip(full_path)



        self.txt_url.setText(url)







    def set_attachment_state(self, *, has_file: bool = False, has_url: bool = False,



                             file_name: str = "", file_path: str = "",



                             can_download: bool = False):



        """Update attachment-related widgets."""



        if not has_file and can_download:



            self.txt_path.setText("未下载原件（可重试下载或手动补原件）")



            self.txt_path.setToolTip("请点击右侧按钮重新尝试自动下载，或者人工补全发票原件文件。")



        else:



            self.txt_path.setText(file_name if file_name else "")



            self.txt_path.setToolTip(file_path)



        self.btn_open_file.setEnabled(has_file)



        self.btn_open_file.setVisible(has_file)



        self.btn_locate_file.setVisible(has_file)



        self.btn_add_attachment.setText("替换" if has_file else "补充")



        self.btn_add_attachment.setVisible(True)



        self.btn_retry_download.setEnabled(not has_file and has_url)



        self.btn_retry_download.setVisible(not has_file and has_url)



        self.btn_add_attachment.setEnabled(True)



        action = "替换" if has_file else "补充"



        self.txt_path.setStatusTip(f"双击{action}原件")







    def set_note(self, text: str):
        """Set the personal note content and apply collapsed display state.

        Default behaviour (regardless of whether text is empty):
        - Empty text:     collapsed, no summary row, no editor row.
        - Non-empty text: collapsed, lbl_note_summary shows a one-line preview.

        The user must click "备注 + 展开" to open the editor.
        """
        self.txt_note.setPlainText(text)
        # Always start collapsed so the note area never takes up unnecessary space.
        # _apply_note_state reads txt_note content to decide whether to show the summary.
        self._apply_note_state(expanded=False)







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



        was_dirty = self.btn_save_draft.isEnabled()



        if dirty:



            if hasattr(self, "_saved_timer") and self._saved_timer.isActive():



                self._saved_timer.stop()



            self.btn_save_draft.setProperty("variant", "primary")



            self.btn_save_draft.setEnabled(True)



            self.lbl_dirty_hint.setText("已修改")



            self.lbl_dirty_hint.setProperty("class", "StatusHint")



            self.lbl_dirty_hint.setProperty("variant", "warning")



        else:



            self.btn_save_draft.setProperty("variant", "secondary")



            self.btn_save_draft.setEnabled(False)



            if was_dirty:
                self.show_saved_state()



            else:



                if not (hasattr(self, "_saved_timer") and self._saved_timer.isActive()):



                    self.lbl_dirty_hint.setText("")



        self._refresh_widget_style(self.lbl_dirty_hint)



        self._refresh_widget_style(self.btn_save_draft)

    def show_saved_state(self):

        """Show a saved acknowledgement after a refresh rebuilds the form."""

        self.lbl_dirty_hint.setText("已保存")

        self.lbl_dirty_hint.setProperty("class", "StatusHint")

        self.lbl_dirty_hint.setProperty("variant", "success")

        from PySide6.QtCore import QTimer

        if not hasattr(self, "_saved_timer"):

            self._saved_timer = QTimer(self)

            self._saved_timer.setSingleShot(True)

            self._saved_timer.timeout.connect(self._clear_saved_text)

        self._saved_timer.start(5000)

        self._refresh_widget_style(self.lbl_dirty_hint)







    def _clear_saved_text(self):



        try:



            self.lbl_dirty_hint.setText("")



        except RuntimeError:



            pass







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
        self.update_evidence_row(items)

    def update_evidence_row(self, items: list[dict]):
        """Update the row-style evidence display from a list of supporting-doc items."""
        has_doc = bool(items)
        if has_doc:
            doc = items[0]
            label = doc.get("label") or doc.get("path", "").split("/")[-1].split("\\")[-1]
            max_chars = 40
            display_name = (label[:max_chars] + "…") if len(label) > max_chars else label

            if len(items) > 1:
                self.lbl_evidence_name.setText(f"{display_name} +{len(items)-1}")
                self.btn_add_evidence.setText("管理")
            else:
                self.lbl_evidence_name.setText(display_name)
                self.btn_add_evidence.setText("替换/管理")

            self.lbl_evidence_name.setToolTip(f"{doc.get('path', '') or label}\n双击管理/替换证明材料")
            self.evidence_content_widget.setCurrentWidget(self.evidence_name_page)
            self.lbl_evidence_name.setVisible(True)
            self.lbl_evidence_missing.setVisible(False)
            self.btn_open_extra_files.setEnabled(True)
            self.btn_open_extra_files.setVisible(True)
            self.btn_add_evidence.setEnabled(True)
            self.btn_add_evidence.setVisible(True)
        else:
            self.evidence_content_widget.setCurrentWidget(self.evidence_missing_page)
            self.lbl_evidence_name.setVisible(False)
            self.lbl_evidence_missing.setVisible(True)
            self.btn_open_extra_files.setEnabled(False)
            self.btn_open_extra_files.setVisible(False)
            self.btn_add_evidence.setText("补充")
            self.btn_add_evidence.setEnabled(True)
            self.btn_add_evidence.setVisible(True)
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







    def _finalize_fixed_header_and_tabs(self):
        """Move the review summary outside the scrolling detail tab content."""
        self.right_stack.removeWidget(self.right_content_widget)

        self.detail_page = QWidget()
        page_layout = QVBoxLayout(self.detail_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(6)

        self.fixed_header_container = QFrame()
        self.fixed_header_container.setObjectName("DetailFixedHeader")
        self.fixed_header_container.setMaximumHeight(280)
        fixed_layout = QVBoxLayout(self.fixed_header_container)
        fixed_layout.setContentsMargins(0, 0, 0, 0)
        fixed_layout.setSpacing(0)
        fixed_layout.addWidget(self.summary_card)
        self.fixed_summary = self.summary_card
        self.fixed_risk_notice = self.summary_card
        self.fixed_review_actions = self.summary_card
        page_layout.addWidget(self.fixed_header_container, 0)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.setObjectName("DetailTabs")
        self.detail_tabs.setDocumentMode(True)
        self.detail_tabs.tabBar().setExpanding(True)
        self.detail_tabs.addTab(self.right_content_widget, "基本信息")

        self.reimbursement_scroll = QScrollArea()
        self.reimbursement_scroll.setWidgetResizable(True)
        self.reimbursement_scroll.setFrameShape(QFrame.NoFrame)
        self.reimbursement_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        reimbursement_content = QWidget()
        reimbursement_layout = QVBoxLayout(reimbursement_content)
        reimbursement_layout.setContentsMargins(8, 8, 8, 8)
        self.claim_empty_hint = QLabel("暂无报销组。可先新建报销组，再将当前发票加入报销。")
        self.claim_empty_hint.setWordWrap(True)
        self.claim_empty_hint.setProperty("class", "SectionHint")
        self.claim_empty_hint.setProperty("variant", "compact")
        reimbursement_layout.addWidget(self.claim_empty_hint)
        reimbursement_layout.addWidget(self.claim_setup_section)
        reimbursement_layout.addStretch(1)
        self.reimbursement_scroll.setWidget(reimbursement_content)
        self.detail_tabs.addTab(self.reimbursement_scroll, "报销信息")

        self.contract_scroll = QScrollArea()
        self.contract_scroll.setWidgetResizable(True)
        self.contract_scroll.setFrameShape(QFrame.NoFrame)
        self.contract_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        contract_content = QWidget()
        contract_layout = QVBoxLayout(contract_content)
        contract_layout.setContentsMargins(12, 12, 12, 12)
        contract_layout.setSpacing(10)
        self.contract_placeholder = QFrame()
        self.contract_placeholder.setProperty("class", "DetailSection")
        self.contract_placeholder.setProperty("variant", "flat")
        contract_placeholder_layout = QVBoxLayout(self.contract_placeholder)
        contract_placeholder_layout.setContentsMargins(12, 12, 12, 12)
        contract_placeholder_layout.setSpacing(6)
        contract_title = QLabel("关联合同")
        contract_title.setProperty("class", "SectionTitle")
        contract_hint = QLabel("当前版本暂未接入合同数据，后续将在这里显示匹配结果与关联操作。")
        contract_hint.setWordWrap(True)
        contract_hint.setProperty("class", "SectionHint")
        contract_placeholder_layout.addWidget(contract_title)
        contract_placeholder_layout.addWidget(contract_hint)
        contract_layout.addWidget(self.contract_placeholder)
        contract_layout.addStretch(1)
        self.contract_scroll.setWidget(contract_content)

        self.operation_scroll = QScrollArea()
        self.operation_scroll.setWidgetResizable(True)
        self.operation_scroll.setFrameShape(QFrame.NoFrame)
        self.operation_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        operation_content = QWidget()
        operation_layout = QVBoxLayout(operation_content)
        operation_layout.setContentsMargins(0, 0, 0, 0)
        operation_layout.setSpacing(0)
        self.operation_placeholder = QWidget()
        self.operation_placeholder.setVisible(False)
        operation_layout.addWidget(self.operation_placeholder)
        operation_layout.addStretch(1)
        self.operation_scroll.setWidget(operation_content)
        page_layout.addWidget(self.detail_tabs, 1)

        self.right_stack.insertWidget(0, self.detail_page)
        self.right_stack.setCurrentWidget(self.detail_page)

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



        right_content_layout.setContentsMargins(0, 0, 0, 0)



        right_content_layout.setSpacing(0)



        # Allow the content widget to expand beyond minimum size to fill QScrollArea viewport
        # right_content_layout.setSizeConstraint(QLayout.SetMinimumSize)



        self.right_layout = right_content_layout



        self.right_content_widget.setWidget(self.right_detail_content)







        self.detail_workbench = QFrame()



        self.detail_workbench.setProperty("class", "DetailWorkbench")



        self.detail_workbench.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)



        workbench_layout = QVBoxLayout(self.detail_workbench)



        workbench_layout.setContentsMargins(0, 0, 0, 0)



        workbench_layout.setSpacing(0)



        self.detail_workbench_layout = workbench_layout



        right_content_layout.addWidget(self.detail_workbench, 1)







        def add_workbench_divider():



            divider = QFrame()



            divider.setProperty("class", "DetailDivider")



            divider.setFrameShape(QFrame.HLine)



            divider.setFixedHeight(1)



            workbench_layout.addWidget(divider)



            return divider







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



        self.lbl_right_empty_title.setProperty("class", "EmptyTitle")



        self.lbl_right_empty_title.setAlignment(Qt.AlignCenter)



        right_empty_card_layout.addWidget(self.lbl_right_empty_title)







        self.lbl_right_empty_desc = QLabel(



            "导入本地发票或扫描邮箱后，这里会显示发票摘要、详情和原件预览。"



        )



        self.lbl_right_empty_desc.setWordWrap(True)



        self.lbl_right_empty_desc.setAlignment(Qt.AlignCenter)



        self.lbl_right_empty_desc.setProperty("class", "EmptyDesc")



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
        self.summary_card.setObjectName("DetailSummaryCard")



        self.summary_card.setProperty("class", "SummaryCard")



        self.summary_card.setProperty("variant", "embedded")



        self.summary_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)



        summary_layout = QVBoxLayout(self.summary_card)



        summary_layout.setContentsMargins(12, 12, 12, 10)



        summary_layout.setSpacing(6)







        # Row 1: amount + status badge



        amount_row = QHBoxLayout()



        amount_row.setContentsMargins(0, 0, 0, 0)



        amount_row.setSpacing(6)



        self.lbl_sum_amount = QLabel("¥—")



        self.lbl_sum_amount.setProperty("class", "DetailAmount")



        amount_row.addWidget(self.lbl_sum_amount)



        amount_row.addStretch(1)



        self.lbl_sum_status = QLabel("未选择发票")



        self.lbl_sum_status.setAlignment(Qt.AlignCenter)



        self.lbl_sum_status.setMaximumWidth(80)



        self.lbl_sum_status.setProperty("class", "StatusBadge")
        self.lbl_sum_status.setProperty("surface", "detail")



        self._set_summary_placeholder()



        amount_row.addWidget(self.lbl_sum_status)



        summary_layout.addLayout(amount_row)







        # Row 2: category | date (two key fields, readable)



        meta_row = QHBoxLayout()



        meta_row.setContentsMargins(0, 0, 0, 0)



        meta_row.setSpacing(6)



        self.lbl_sum_category = QLabel("—")



        self.lbl_sum_category.setProperty("class", "DetailMeta")



        meta_row.addWidget(self.lbl_sum_category)



        sep1 = QLabel("|")



        sep1.setProperty("class", "Separator")



        meta_row.addWidget(sep1)



        self.lbl_sum_date = QLabel("—")



        self.lbl_sum_date.setProperty("class", "DetailMeta")



        meta_row.addWidget(self.lbl_sum_date)



        meta_row.addStretch(1)



        summary_layout.addLayout(meta_row)







        # Row 3: seller (prominent)



        seller_row = QHBoxLayout()



        seller_row.setContentsMargins(0, 0, 0, 0)



        seller_row.setSpacing(8)



        self.lbl_sum_seller = QLabel("—")



        self.lbl_sum_seller.setProperty("class", "DetailSeller")
        self.lbl_sum_seller.setWordWrap(True)



        seller_row.addWidget(self.lbl_sum_seller, 1)



        summary_layout.addLayout(seller_row)







        # Row 4: invoice number



        num_row = QHBoxLayout()



        num_row.setContentsMargins(0, 0, 0, 0)



        num_row.setSpacing(8)



        self.lbl_sum_number = QLabel("发票号码: —")



        self.lbl_sum_number.setProperty("class", "DetailCaption")
        self.lbl_sum_number.setWordWrap(True)



        num_row.addWidget(self.lbl_sum_number)



        num_row.addStretch(1)



        summary_layout.addLayout(num_row)







        # Date warning (hidden by default)



        self.lbl_date_warning = QLabel("")



        self.lbl_date_warning.setWordWrap(True)



        self.lbl_date_warning.setProperty("class", "InlineWarning")
        self.lbl_date_warning.setProperty("surface", "detail")



        self.lbl_date_warning.setVisible(False)



        summary_layout.addWidget(self.lbl_date_warning)







        # Buyer warning (hidden by default)



        self.lbl_buyer_warning = QLabel("")



        self.lbl_buyer_warning.setWordWrap(True)



        self.lbl_buyer_warning.setProperty("class", "InlineWarning")
        self.lbl_buyer_warning.setProperty("surface", "detail")



        self.lbl_buyer_warning.setVisible(False)



        summary_layout.addWidget(self.lbl_buyer_warning)







        # Row 5: review action buttons



        self.inline_review_layout = QHBoxLayout()



        self.inline_review_layout.setSpacing(4)



        self.inline_review_layout.setContentsMargins(0, 0, 0, 0)







        self.inline_review_layout.setSpacing(10)
        self.btn_app = make_button("通过并下一张", variant="primary", tooltip="快捷键：Enter")
        self.btn_app.setFixedHeight(42)
        self.btn_app.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)



        self.btn_app.clicked.connect(self._cb.on_approve_next)



        self.inline_review_layout.addWidget(self.btn_app)







        self.btn_ign = make_button("忽略", variant="secondary", tooltip="快捷键：Del")
        self.btn_ign.setFixedHeight(42)
        self.btn_ign.setFixedWidth(88)



        self.btn_ign.clicked.connect(self._cb.on_ignore)



        self.inline_review_layout.addWidget(self.btn_ign)







        self.btn_err = make_button("异常", variant="danger", tooltip="快捷键：Ctrl+E")
        self.btn_err.setFixedHeight(42)
        self.btn_err.setFixedWidth(96)



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







        self.btn_inline_more = make_button("⋯", variant="ghost")
        self.btn_inline_more.setFixedSize(40, 42)



        self.btn_inline_more.setMenu(self.inline_more_menu)



        self.inline_review_layout.addWidget(self.btn_inline_more)



        self.inline_review_layout.addStretch(1)







        summary_layout.addLayout(self.inline_review_layout)



        workbench_layout.addWidget(self.summary_card)



        add_workbench_divider()







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



        self.detail_core_section.setProperty("variant", "flat")



        detail_core_layout = QVBoxLayout(self.detail_core_section)



        detail_core_layout.setContentsMargins(12, 10, 12, 10)



        detail_core_layout.setSpacing(10)







        # Title row with save button



        core_title_row = QHBoxLayout()



        core_title_row.setContentsMargins(0, 0, 0, 0)



        core_title_row.setSpacing(8)



        core_title = QLabel("基本信息")



        core_title.setProperty("class", "SectionTitle")



        core_title_row.addWidget(core_title)



        core_title_row.addStretch(1)







        self.lbl_dirty_hint = QLabel("")



        self.lbl_dirty_hint.setProperty("class", "SectionHint")



        core_title_row.addWidget(self.lbl_dirty_hint)







        self.btn_save_draft = make_button("保存", variant="secondary", min_width=72)



        self.btn_save_draft.setToolTip("保存字段修改")



        self.btn_save_draft.clicked.connect(self._cb.on_save_fields)



        core_title_row.addWidget(self.btn_save_draft)



        detail_core_layout.addLayout(core_title_row)







        # Form grid — 3 rows, compact layout



        core_fields = QWidget()



        core_fields.setObjectName("DetailFieldStack")
        self.invoice_core_grid = QGridLayout(core_fields)



        self.invoice_core_grid.setContentsMargins(0, 0, 0, 0)



        self.invoice_core_grid.setHorizontalSpacing(10)



        self.invoice_core_grid.setVerticalSpacing(10)







        def core_label(text):



            lbl = QLabel(text)



            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)



            lbl.setProperty("class", "DetailFieldKey")



            lbl.setFixedWidth(74)



            return lbl







        self.txt_number = QLineEdit()
        self.txt_number.setProperty("class", "DetailFieldInput")
        self.txt_number.setProperty("readonly", "true")



        self.txt_number.setFixedHeight(28)



        self.txt_number.setMinimumWidth(100)



        self.txt_date = QLineEdit()
        self.txt_date.setProperty("class", "DetailFieldInput")
        self.txt_date.setProperty("readonly", "true")



        self.txt_date.setFixedHeight(28)



        self.txt_date.setMinimumWidth(100)



        self.txt_date.setPlaceholderText("YYYY-MM-DD")



        self.txt_amount = QLineEdit()
        self.txt_amount.setProperty("class", "DetailFieldInput")
        self.txt_amount.setProperty("readonly", "true")



        self.txt_amount.setFixedHeight(28)



        self.txt_amount.setMinimumWidth(100)



        self.combo_category = QComboBox()
        self.combo_category.setProperty("class", "DetailFieldInput")



        self.combo_category.setEditable(True)



        self.combo_category.setFixedHeight(28)



        self.combo_category.setMinimumWidth(100)



        self.txt_seller = QLineEdit()
        self.txt_seller.setProperty("class", "DetailFieldInput")



        self.txt_seller.setFixedHeight(28)



        self.txt_seller.setMinimumWidth(100)



        self.txt_buyer = QLineEdit()
        self.txt_buyer.setProperty("class", "DetailFieldInput")



        self.txt_buyer.setFixedHeight(28)



        self.txt_buyer.setMinimumWidth(100)



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







        # Row 2: buyer | seller (compactly sharing one row side-by-side)



        self.invoice_core_grid.addWidget(core_label("购买方:"), 2, 0)



        self.invoice_core_grid.addWidget(self.txt_buyer, 2, 1)



        self.invoice_core_grid.addWidget(core_label("销售方:"), 2, 2)



        self.invoice_core_grid.addWidget(self.txt_seller, 2, 3)







        self.invoice_core_grid.setColumnStretch(1, 1)



        self.invoice_core_grid.setColumnStretch(3, 1)

        date_label = self.invoice_core_grid.itemAtPosition(0, 2).widget()
        amount_label = self.invoice_core_grid.itemAtPosition(1, 0).widget()
        category_label = self.invoice_core_grid.itemAtPosition(1, 2).widget()
        buyer_label = self.invoice_core_grid.itemAtPosition(2, 0).widget()
        seller_label = self.invoice_core_grid.itemAtPosition(2, 2).widget()
        stacked_rows = (
            (0, self.invoice_core_grid.itemAtPosition(0, 0).widget(), self.txt_number),
            (1, date_label, self.txt_date),
            (2, amount_label, self.txt_amount),
            (3, category_label, self.combo_category),
            (4, buyer_label, self.txt_buyer),
            (5, seller_label, self.txt_seller),
        )
        for row_index, label_widget, field_widget in stacked_rows:
            self.invoice_core_grid.addWidget(label_widget, row_index, 0)
            self.invoice_core_grid.addWidget(field_widget, row_index, 1)
        self.invoice_core_grid.setColumnStretch(3, 0)



        detail_core_layout.addWidget(core_fields)



        workbench_layout.addWidget(self.detail_core_section)



        add_workbench_divider()







        # ═══════════════════════════════════════════════════════════



        # Zone 3 — 材料



        # ═══════════════════════════════════════════════════════════



        self.detail_files_section = QFrame()



        self.detail_files_section.setProperty("class", "DetailSection")



        self.detail_files_section.setProperty("variant", "flat")



        detail_files_layout = QVBoxLayout(self.detail_files_section)



        detail_files_layout.setContentsMargins(12, 10, 12, 10)



        detail_files_layout.setSpacing(8)



        files_title = QLabel("材料")



        files_title.setProperty("class", "SectionTitle")



        detail_files_layout.addWidget(files_title)







        self.txt_path = DoubleClickLineEdit()



        self.txt_path.setReadOnly(True)



        self.txt_path.setMinimumHeight(28)



        self.txt_path.setPlaceholderText("双击补充原件")



        self.txt_path.setProperty("class", "DetailValueField")
        self.txt_path.doubleClicked.connect(self._cb.on_open_dir)







        self.btn_open_file = make_button("打开", variant="secondary", min_width=56)



        self.btn_open_file.clicked.connect(self._cb.on_open_file)



        self.btn_open_file.setVisible(False)







        self.btn_locate_file = make_button("定位", variant="secondary", min_width=56)



        self.btn_locate_file.clicked.connect(self._cb.on_locate_file)







        self.btn_add_attachment = make_button("补充", variant="secondary", min_width=56)



        self.btn_add_attachment.clicked.connect(self._cb.on_add_attachment)



        self.btn_add_attachment.setVisible(False)







        self.btn_retry_download = make_button("重下", variant="secondary", min_width=56)



        self.btn_retry_download.clicked.connect(self._cb.on_retry_download)



        self.btn_retry_download.setVisible(False)







        self.original_row, self.original_label, self.original_actions_frame = create_labeled_action_row(



            "原件:",



            self.txt_path,



            [



                self.btn_open_file,



                self.btn_locate_file,



                self.btn_add_attachment,



                self.btn_retry_download,



            ],



        )



        self.original_card = wrap_layout_in_card(self.original_row, "DetailOriginalRowCard")
        detail_files_layout.addWidget(self.original_card)







        self.evidence_content_widget = QWidget()



        self.evidence_content_widget = QStackedWidget()



        self.evidence_content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)



        self.evidence_content_widget.setMinimumHeight(28)







        self.evidence_missing_page = QWidget()



        missing_layout = QHBoxLayout(self.evidence_missing_page)



        missing_layout.setContentsMargins(0, 0, 0, 0)



        missing_layout.setSpacing(0)







        self.lbl_evidence_missing = DoubleClickLabel("缺失")



        self.lbl_evidence_missing.setMinimumHeight(20)



        self.lbl_evidence_missing.setProperty("class", "StatusBadge")



        self.lbl_evidence_missing.setProperty("variant", "warning")
        self.lbl_evidence_missing.setProperty("surface", "detail")



        self.lbl_evidence_missing.setAlignment(Qt.AlignCenter)



        self.lbl_evidence_missing.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)



        self.lbl_evidence_missing.setMinimumWidth(56)



        self.lbl_evidence_missing.setToolTip("双击补充证明材料")



        self.lbl_evidence_missing.doubleClicked.connect(self._cb.on_add_evidence)



        missing_layout.addWidget(self.lbl_evidence_missing, 0, Qt.AlignLeft | Qt.AlignVCenter)



        missing_layout.addStretch(1)







        self.evidence_name_page = QWidget()



        evidence_name_layout = QHBoxLayout(self.evidence_name_page)



        evidence_name_layout.setContentsMargins(0, 0, 0, 0)



        evidence_name_layout.setSpacing(0)







        self.lbl_evidence_name = DoubleClickLabel("")



        self.lbl_evidence_name.setProperty("class", "EvidenceFileName")



        self.lbl_evidence_name.setMinimumHeight(28)



        self.lbl_evidence_name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)



        self.lbl_evidence_name.doubleClicked.connect(self._cb.on_add_evidence)



        self.lbl_evidence_name.setVisible(False)



        evidence_name_layout.addWidget(self.lbl_evidence_name, 1)







        self.evidence_content_widget.addWidget(self.evidence_missing_page)



        self.evidence_content_widget.addWidget(self.evidence_name_page)



        self.evidence_content_widget.setCurrentWidget(self.evidence_missing_page)







        self.btn_open_extra_files = make_button("打开", variant="secondary", min_width=56)



        self.btn_open_extra_files.clicked.connect(self._cb.on_open_evidence)



        self.btn_open_extra_files.setEnabled(False)



        self.btn_open_extra_files.setVisible(False)







        self.btn_add_evidence = make_button("补充", variant="secondary", min_width=56)



        self.btn_add_evidence.clicked.connect(self._cb.on_add_evidence)



        self.btn_add_evidence.setVisible(False)







        self.evidence_row, self.evidence_label, self.evidence_actions_frame = create_labeled_action_row(



            "证明:",



            self.evidence_content_widget,



            [



                self.btn_open_extra_files,



                self.btn_add_evidence,



            ],



        )



        self.evidence_card = wrap_layout_in_card(self.evidence_row, "DetailEvidenceRowCard")
        detail_files_layout.addWidget(self.evidence_card)



        # Expose claim_setup_section for backward compat



        # Hidden QComboBox retained for backward-compat with on_supporting_doc_changed



        self.combo_supporting_docs = QComboBox()



        self.combo_supporting_docs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)



        self.combo_supporting_docs.view().setTextElideMode(Qt.ElideMiddle)



        self.combo_supporting_docs.currentIndexChanged.connect(self._cb.on_supporting_doc_changed)



        self.combo_supporting_docs.setVisible(False)



        detail_files_layout.addWidget(self.combo_supporting_docs)







        self.claim_setup_section = QFrame()



        self.claim_setup_section.setProperty("class", "DetailSection")



        self.claim_setup_section.setProperty("variant", "flat")



        claim_setup_layout = QVBoxLayout(self.claim_setup_section)



        claim_setup_layout.setContentsMargins(12, 10, 12, 10)



        claim_setup_layout.setSpacing(8)







        self.combo_claims = QComboBox()



        self.combo_claims.setMinimumHeight(28)



        self.combo_claims.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)



        self.combo_claims.currentIndexChanged.connect(self._cb.on_claim_combo_changed)







        self.btn_new_claim_toggle = QPushButton("+")



        self.btn_new_claim_toggle.setToolTip("新建报销组")



        self.btn_new_claim_toggle.setProperty("class", "SecondaryBtn")



        self.btn_new_claim_toggle.setFixedSize(30, 28)



        self.btn_new_claim_toggle.clicked.connect(self._toggle_new_claim_input)



        self.btn_new_claim_toggle.setVisible(False)







        self.btn_add_to_claim = make_button("加入", variant="secondary", min_width=56)



        self.btn_add_to_claim.setToolTip("将当前选中的发票加入此报销组")



        self.btn_add_to_claim.clicked.connect(self._cb.on_link_to_claim)







        self.btn_export = make_button("导出", variant="secondary", min_width=56)



        self.btn_export.setToolTip("导出当前报销组")



        self.btn_export.setEnabled(False)



        self.btn_export.clicked.connect(self._cb.on_export_claim)







        self.btn_delete_claim = make_button("删除空组", variant="danger", min_width=76)



        self.btn_delete_claim.setToolTip("仅可删除没有关联记录的报销组")



        self.btn_delete_claim.setEnabled(False)



        self.btn_delete_claim.clicked.connect(self._cb.on_delete_claim)







        self.claim_row, self.claim_label, self.claim_actions_widget = create_labeled_action_row(



            "报销组:",



            self.combo_claims,



            [



                self.btn_add_to_claim,



                self.btn_export,



                self.btn_delete_claim,



            ],



        )



        claim_setup_layout.addLayout(self.claim_row)







        # Inline new claim widget (initially hidden)



        self.new_claim_widget = QWidget()



        new_claim_layout = QHBoxLayout(self.new_claim_widget)



        new_claim_layout.setContentsMargins(0, 2, 0, 0)



        new_claim_layout.setSpacing(6)



        self.txt_new_claim = QLineEdit()



        self.txt_new_claim.setPlaceholderText("输入新报销组名称...")



        self.txt_new_claim.setMinimumHeight(28)



        new_claim_layout.addWidget(self.txt_new_claim, 1)







        self.btn_create_claim = make_button("确认", variant="secondary", min_width=56)



        self.btn_create_claim.clicked.connect(self._cb.on_create_claim)



        new_claim_layout.addWidget(self.btn_create_claim)







        self.btn_cancel_create_claim = make_button("取消", variant="secondary", min_width=56)



        self.btn_cancel_create_claim.clicked.connect(self._toggle_new_claim_input)



        new_claim_layout.addWidget(self.btn_cancel_create_claim)







        self.new_claim_widget.setVisible(False)



        claim_setup_layout.addWidget(self.new_claim_widget)







        # Hidden compatibility controls keep existing app proxies stable.



        self.btn_refresh_claims = QPushButton("刷新")



        self.btn_refresh_claims.clicked.connect(self._cb.on_refresh_claims)



        self.btn_refresh_claims.setVisible(False)



        claim_setup_layout.addWidget(self.btn_refresh_claims)







        self.lbl_claim_total = QLabel("0 条记录 · 合计 ¥0.00", self)



        self.lbl_claim_total.setProperty("class", "ClaimTotal")



        self.lbl_claim_total.setVisible(True)



        self.lbl_claim_total.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)



        self.claim_summary_row = QHBoxLayout()



        self.claim_summary_row.setContentsMargins(0, 0, 0, 0)



        self.claim_summary_row.setSpacing(8)



        self.claim_summary_row.addWidget(self.lbl_claim_total, 1)



        claim_setup_layout.addLayout(self.claim_summary_row)











        # Export summary (hidden, one-liner)



        self.lbl_export_summary = QLabel()



        self.lbl_export_summary.setProperty("class", "ExportSummary")



        self.lbl_export_summary.setWordWrap(True)



        self.lbl_export_summary.setText("上一次导出：暂无")



        self.lbl_export_summary.setVisible(False)



        claim_setup_layout.addWidget(self.lbl_export_summary)







        # Also expose claim_setup_section for backward compat



        self.claim_setup_section = self.claim_setup_section







        workbench_layout.addWidget(self.detail_files_section)



        add_workbench_divider()



        workbench_layout.addWidget(self.claim_setup_section)



        add_workbench_divider()







        # ═══════════════════════════════════════════════════════════



        # Zone 4 — 备注 / 更多来源信息



        # ═══════════════════════════════════════════════════════════



        self.review_note_section = QFrame()



        self.review_note_section.setProperty("class", "DetailSection")



        self.review_note_section.setProperty("variant", "flat")



        review_note_layout = QVBoxLayout(self.review_note_section)



        review_note_layout.setContentsMargins(12, 10, 12, 10)



        review_note_layout.setSpacing(6)







        # Inline note summary row



        note_row = QHBoxLayout()



        note_row.setContentsMargins(0, 0, 0, 0)



        note_row.setSpacing(6)



        self.btn_toggle_note = QPushButton("备注 + 展开")



        self.btn_toggle_note.setProperty("class", "TextBtn")



        self.btn_toggle_note.clicked.connect(self._toggle_note_visibility)



        note_row.addWidget(self.btn_toggle_note)



        self.lbl_note_summary = QLabel("")



        self.lbl_note_summary.setProperty("class", "NoteSummary")



        self.lbl_note_summary.setWordWrap(True)



        self.lbl_note_summary.setVisible(False)



        note_row.addWidget(self.lbl_note_summary, 1)



        review_note_layout.addLayout(note_row)







        self.txt_note = QTextEdit()



        self.txt_note.setMinimumHeight(56)



        self.txt_note.setMaximumHeight(72)



        self.txt_note.setPlaceholderText("可填写报销说明、事项背景、客户/项目等。")



        self.txt_note.setVisible(False)



        self.note_editor_row, self.note_editor_label, _ = create_labeled_action_row(
            "备注:",
            self.txt_note,
            [],
            label_alignment=Qt.AlignRight | Qt.AlignTop,
        )

        # Wrap the editor row in a QWidget so it can be hidden as a unit.
        # Add note_editor_row as a sub-layout to preserve its exact stretch factors.
        self.note_content_row = QWidget()
        note_content_row_layout = QVBoxLayout(self.note_content_row)
        note_content_row_layout.setContentsMargins(10, 8, 10, 8)
        note_content_row_layout.setSpacing(0)
        note_content_row_layout.addLayout(self.note_editor_row)
        self.note_content_row.setVisible(False)

        review_note_layout.addWidget(self.note_content_row)



        workbench_layout.addWidget(self.review_note_section)



        add_workbench_divider()







        # — More source info (folded) —



        self.source_info_section = QFrame()



        self.source_info_section.setProperty("class", "DetailSection")



        self.source_info_section.setProperty("variant", "flat")



        source_info_layout = QVBoxLayout(self.source_info_section)



        source_info_layout.setContentsMargins(12, 10, 12, 10)



        source_info_layout.setSpacing(4)







        self.btn_more_source = QToolButton()



        self.btn_more_source.setText("更多来源信息")



        self.btn_more_source.setCheckable(True)



        self.btn_more_source.setChecked(False)



        self.btn_more_source.setArrowType(Qt.RightArrow)



        self.btn_more_source.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)



        self.btn_more_source.setProperty("class", "Disclosure")



        self.btn_more_source.toggled.connect(self._toggle_more_source_info)



        source_info_layout.addWidget(self.btn_more_source, 0, Qt.AlignLeft)







        self.more_source_widget = QWidget()



        more_source_layout = QFormLayout(self.more_source_widget)



        more_source_layout.setContentsMargins(0, 6, 0, 2)



        more_source_layout.setLabelAlignment(Qt.AlignRight)



        more_source_layout.setSpacing(4)







        self.txt_id = QLineEdit()



        self.txt_id.setReadOnly(True)



        more_source_layout.addRow("发票 ID:", self.txt_id)







        self.txt_invoice_date = QLineEdit()



        self.txt_invoice_date.setReadOnly(True)



        more_source_layout.addRow("开票日期:", self.txt_invoice_date)







        self.txt_date_source = QLineEdit()



        self.txt_date_source.setReadOnly(True)



        more_source_layout.addRow("日期来源:", self.txt_date_source)







        self.txt_subject = QLineEdit()



        self.txt_subject.setReadOnly(True)



        more_source_layout.addRow("邮件主题:", self.txt_subject)







        self.txt_url = QLineEdit()



        self.txt_url.setReadOnly(True)



        more_source_layout.addRow("下载链接:", self.txt_url)







        self.txt_item_name = QLineEdit()



        self.txt_item_name.setReadOnly(True)



        more_source_layout.addRow("项目名称:", self.txt_item_name)







        self.txt_full_path = QLineEdit()



        self.txt_full_path.setReadOnly(True)



        more_source_layout.addRow("完整文件路径:", self.txt_full_path)



        self.more_source_widget.setVisible(False)



        source_info_layout.addWidget(self.more_source_widget)



        workbench_layout.addWidget(self.source_info_section)







        # ── Bottom status bar (minimal, only warnings) ────────────



        self.closing_card = QFrame()



        self.closing_card.setProperty("class", "DetailStatus")



        closing_layout = QHBoxLayout(self.closing_card)



        closing_layout.setContentsMargins(10, 4, 10, 4)



        closing_layout.setSpacing(4)







        self.lbl_closing_desc = QLabel("")



        self.lbl_closing_desc.setWordWrap(True)



        self.lbl_closing_desc.setProperty("class", "ClosingDesc")



        self.lbl_closing_desc.setVisible(False)



        closing_layout.addWidget(self.lbl_closing_desc)



        closing_layout.addStretch(1)







        workbench_layout.addWidget(self.closing_card)



        workbench_layout.addStretch(1)







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
        self._finalize_fixed_header_and_tabs()
