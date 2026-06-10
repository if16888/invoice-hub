# -*- coding: utf-8 -*-
"""Invoice detail panel — right-side single-invoice review panel for Invoice Hub."""

from dataclasses import dataclass
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
            visible = not self.txt_note.isVisible()
            self.txt_note.setVisible(visible)
            self.btn_toggle_note.setText("个人备注 -" if visible else "个人备注 +")

    def _connect_dirty_tracking(self):
        for widget in (self.txt_number, self.txt_date, self.txt_seller,
                       self.txt_buyer, self.txt_amount):
            widget.textEdited.connect(self._cb.on_form_dirty)
        self.combo_category.currentTextChanged.connect(self._cb.on_form_dirty)
        self.txt_note.textChanged.connect(self._cb.on_form_dirty)

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
        right_content_layout.setContentsMargins(0, 0, 0, 0)
        right_content_layout.setSpacing(6)
        right_content_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.right_layout = right_content_layout
        self.right_content_widget.setWidget(self.right_detail_content)

        # ── empty state widget ────────────────────────────────────
        self.right_empty_widget = QWidget()
        right_empty_layout = QVBoxLayout(self.right_empty_widget)
        right_empty_layout.setContentsMargins(16, 16, 16, 16)
        right_empty_layout.setSpacing(10)
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
        self.lbl_right_empty_desc.setStyleSheet("color: #6B7280; line-height: 1.5;")
        right_empty_card_layout.addWidget(self.lbl_right_empty_desc)

        right_empty_layout.addWidget(right_empty_card)
        right_empty_layout.addStretch(2)
        self.right_stack.addWidget(self.right_content_widget)
        self.right_stack.addWidget(self.right_empty_widget)
        self.right_stack.setCurrentWidget(self.right_content_widget)

        # ── 1. Summary Card ───────────────────────────────────────
        self.summary_card = QGroupBox("发票摘要")
        self.summary_card.setProperty("class", "SummaryCard")
        self.summary_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setSpacing(6)

        summary_header = QHBoxLayout()
        summary_header.setContentsMargins(0, 0, 0, 0)
        summary_header.setSpacing(8)
        self.lbl_sum_status = QLabel("未选中发票")
        self.lbl_sum_status.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_sum_status.setAlignment(Qt.AlignCenter)
        self.lbl_sum_status.setMaximumWidth(80)
        self.lbl_sum_status.setProperty("class", "StatusBadge")
        self._set_summary_placeholder()

        self.lbl_sum_amount = QLabel("¥—")
        self.lbl_sum_amount.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self.lbl_sum_amount.setProperty("class", "SummaryAmount")
        summary_header.addWidget(self.lbl_sum_amount)
        summary_header.addStretch(1)
        summary_header.addWidget(self.lbl_sum_status)

        summary_metadata = QWidget()
        summary_metadata_layout = QGridLayout(summary_metadata)
        summary_metadata_layout.setContentsMargins(0, 0, 0, 0)
        summary_metadata_layout.setHorizontalSpacing(12)
        summary_metadata_layout.setVerticalSpacing(3)
        summary_metadata_layout.setColumnStretch(0, 1)
        summary_metadata_layout.setColumnStretch(1, 1)
        self.lbl_sum_date = QLabel("开票日期: —")
        self.lbl_sum_date.setFont(QFont("Segoe UI", 9))
        self.lbl_sum_date.setProperty("class", "SummaryMeta")
        self.lbl_sum_category = QLabel("消费类型: —")
        self.lbl_sum_category.setFont(QFont("Segoe UI", 9))
        self.lbl_sum_category.setProperty("class", "SummaryMeta")
        self.lbl_sum_number = QLabel("发票号码: —")
        self.lbl_sum_number.setFont(QFont("Segoe UI", 9))
        self.lbl_sum_number.setProperty("class", "SummaryMeta")
        self.lbl_sum_seller = QLabel("销售方: —")
        self.lbl_sum_seller.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_sum_seller.setProperty("class", "SummarySeller")
        summary_metadata_layout.addWidget(self.lbl_sum_date, 0, 0)
        summary_metadata_layout.addWidget(self.lbl_sum_category, 0, 1)
        summary_metadata_layout.addWidget(self.lbl_sum_number, 1, 0)
        summary_metadata_layout.addWidget(self.lbl_sum_seller, 1, 1)

        summary_layout.addLayout(summary_header)
        summary_layout.addWidget(summary_metadata)
        self.lbl_date_warning = QLabel("")
        self.lbl_date_warning.setWordWrap(True)
        self.lbl_date_warning.setProperty("class", "InlineWarning")
        self.lbl_date_warning.setVisible(False)
        summary_layout.addWidget(self.lbl_date_warning)

        right_content_layout.addWidget(self.summary_card)

        # ── 2. Inline Review Actions ──────────────────────────────
        self.inline_review_layout = QHBoxLayout()
        self.inline_review_layout.setSpacing(6)
        self.inline_review_layout.setContentsMargins(0, 4, 0, 4)

        self.btn_app = QPushButton("通过并下一张")
        self.btn_app.setProperty("class", "PrimaryBtn")
        self.btn_app.setMaximumWidth(110)
        self.btn_app.clicked.connect(self._cb.on_approve_next)
        self.inline_review_layout.addWidget(self.btn_app)

        self.btn_ign = QPushButton("忽略")
        self.btn_ign.setProperty("class", "SecondaryBtn")
        self.btn_ign.setMaximumWidth(60)
        self.btn_ign.clicked.connect(self._cb.on_ignore)
        self.inline_review_layout.addWidget(self.btn_ign)

        self.btn_err = QPushButton("异常")
        self.btn_err.setProperty("class", "DangerOutlineBtn")
        self.btn_err.setMaximumWidth(60)
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
        self.btn_inline_more.setMenu(self.inline_more_menu)
        self.inline_review_layout.addWidget(self.btn_inline_more)
        self.inline_review_layout.addStretch(1)

        right_content_layout.addLayout(self.inline_review_layout)

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
        self.btn_rev.clicked.connect(self._cb.on_reset_review)

        self.btn_delete_invoice = QPushButton("删除发票", self)
        self.btn_delete_invoice.setVisible(False)
        self.btn_delete_invoice.setProperty("class", "TextDangerBtn")
        self.btn_delete_invoice.setMaximumWidth(96)
        self.btn_delete_invoice.clicked.connect(self._cb.on_delete_or_restore)

        # ── 3. Core Info ──────────────────────────────────────────
        self.detail_core_section = QFrame()
        self.detail_core_section.setProperty("class", "DetailSection")
        detail_core_layout = QVBoxLayout(self.detail_core_section)
        detail_core_layout.setContentsMargins(10, 8, 10, 10)
        detail_core_layout.setSpacing(6)
        core_title = QLabel("核心信息")
        core_title.setProperty("class", "SectionTitle")
        detail_core_layout.addWidget(core_title)

        core_fields = QWidget()
        self.invoice_core_grid = QGridLayout(core_fields)
        self.invoice_core_grid.setContentsMargins(0, 0, 0, 0)
        self.invoice_core_grid.setHorizontalSpacing(8)
        self.invoice_core_grid.setVerticalSpacing(6)
        self.invoice_core_grid.setColumnStretch(1, 1)
        self.invoice_core_grid.setColumnStretch(3, 1)

        def add_core_field(row, field_column, label_text, widget):
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            column = field_column * 2
            self.invoice_core_grid.addWidget(label, row, column)
            self.invoice_core_grid.addWidget(widget, row, column + 1)

        self.txt_number = QLineEdit()
        self.txt_date = QLineEdit()
        self.txt_date.setPlaceholderText("YYYY-MM-DD")
        self.txt_amount = QLineEdit()
        self.combo_category = QComboBox()
        self.combo_category.setEditable(True)
        # Category options populated by app after panel creation
        self.txt_seller = QLineEdit()
        self.txt_buyer = QLineEdit()
        self.txt_seller.textChanged.connect(self.txt_seller.setToolTip)
        self.txt_buyer.textChanged.connect(self.txt_buyer.setToolTip)

        add_core_field(0, 0, "发票号码:", self.txt_number)
        add_core_field(0, 1, "费用日期:", self.txt_date)
        add_core_field(1, 0, "发票金额 (元):", self.txt_amount)
        add_core_field(1, 1, "消费类型:", self.combo_category)
        add_core_field(2, 0, "销售方名称:", self.txt_seller)
        add_core_field(2, 1, "购买方名称:", self.txt_buyer)
        detail_core_layout.addWidget(core_fields)
        right_content_layout.addWidget(self.detail_core_section)

        # ── 4. Files (Attachment & Evidence) ──────────────────────
        path_widget = QWidget()
        path_layout = QHBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(4)
        self.txt_path = QLineEdit()
        self.txt_path.setReadOnly(True)
        path_layout.addWidget(self.txt_path, 1)
        self.btn_open_file = QPushButton("查看")
        self.btn_open_file.clicked.connect(self._cb.on_open_file)
        self.btn_open_file.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_open_file.setMinimumWidth(50)
        self.btn_open_file.setProperty("class", "SecondaryBtn")
        path_layout.addWidget(self.btn_open_file)

        self.btn_add_attachment = QPushButton("补原件")
        self.btn_add_attachment.clicked.connect(self._cb.on_add_attachment)
        self.btn_add_attachment.setFont(QFont("Segoe UI", 9))
        self.btn_add_attachment.setMinimumWidth(60)
        self.btn_add_attachment.setProperty("class", "SecondaryBtn")
        path_layout.addWidget(self.btn_add_attachment)

        self.btn_retry_download = QPushButton("重试下载")
        self.btn_retry_download.clicked.connect(self._cb.on_retry_download)
        self.btn_retry_download.setFont(QFont("Segoe UI", 9))
        self.btn_retry_download.setMinimumWidth(65)
        self.btn_retry_download.setProperty("class", "SecondaryBtn")
        path_layout.addWidget(self.btn_retry_download)

        # Evidence selector
        docs_widget = QWidget()
        docs_layout = QHBoxLayout(docs_widget)
        docs_layout.setContentsMargins(0, 0, 0, 0)
        docs_layout.setSpacing(4)

        self.combo_supporting_docs = QComboBox()
        self.combo_supporting_docs.setMinimumWidth(120)
        self.combo_supporting_docs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_supporting_docs.view().setTextElideMode(Qt.ElideMiddle)
        self.combo_supporting_docs.currentIndexChanged.connect(self._cb.on_supporting_doc_changed)
        docs_layout.addWidget(self.combo_supporting_docs, 1)

        self.btn_open_extra_files = QPushButton("查看")
        self.btn_open_extra_files.clicked.connect(self._cb.on_open_evidence)
        self.btn_open_extra_files.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_open_extra_files.setMinimumWidth(50)
        self.btn_open_extra_files.setProperty("class", "SecondaryBtn")
        self.btn_open_extra_files.setEnabled(False)
        docs_layout.addWidget(self.btn_open_extra_files)

        self.detail_files_section = QFrame()
        self.detail_files_section.setProperty("class", "DetailSection")
        detail_files_layout = QVBoxLayout(self.detail_files_section)
        detail_files_layout.setContentsMargins(10, 6, 10, 8)
        detail_files_layout.setSpacing(6)
        files_title = QLabel("原件与证明材料")
        files_title.setProperty("class", "SectionTitle")
        detail_files_layout.addWidget(files_title)

        file_fields = QWidget()
        file_fields_layout = QFormLayout(file_fields)
        file_fields_layout.setContentsMargins(0, 0, 0, 0)
        file_fields_layout.setLabelAlignment(Qt.AlignRight)
        file_fields_layout.setSpacing(3)
        file_fields_layout.addRow("原件文件:", path_widget)
        file_fields_layout.addRow("证明材料:", docs_widget)
        detail_files_layout.addWidget(file_fields)
        right_content_layout.addWidget(self.detail_files_section)

        # ── 5. Claim Group ────────────────────────────────────────
        self.claim_setup_section = QFrame()
        self.claim_setup_section.setProperty("class", "DetailSection")
        claim_setup_layout = QVBoxLayout(self.claim_setup_section)
        claim_setup_layout.setContentsMargins(10, 8, 10, 10)
        claim_setup_layout.setSpacing(6)
        claim_setup_title = QLabel("报销组")
        claim_setup_title.setProperty("class", "SectionTitle")
        claim_setup_layout.addWidget(claim_setup_title)

        claim_combo_row = QHBoxLayout()
        claim_combo_row.setSpacing(6)
        self.combo_claims = QComboBox()
        self.combo_claims.currentIndexChanged.connect(self._cb.on_claim_combo_changed)
        claim_combo_row.addWidget(self.combo_claims, 1)

        self.btn_refresh_claims = QPushButton("刷新")
        self.btn_refresh_claims.clicked.connect(self._cb.on_refresh_claims)
        self.btn_refresh_claims.setMaximumWidth(72)
        self.btn_refresh_claims.setProperty("class", "SecondaryBtn")
        claim_combo_row.addWidget(self.btn_refresh_claims)
        claim_setup_layout.addLayout(claim_combo_row)

        claim_action_row = QHBoxLayout()
        claim_action_row.setSpacing(6)
        self.btn_add_to_claim = QPushButton("加入当前发票")
        self.btn_add_to_claim.clicked.connect(self._cb.on_link_to_claim)
        self.btn_add_to_claim.setProperty("class", "SecondaryBtn")
        self.btn_add_to_claim.setMaximumWidth(120)
        claim_action_row.addWidget(self.btn_add_to_claim)

        self.txt_new_claim = QLineEdit()
        self.txt_new_claim.setPlaceholderText("输入新报销组名称...")
        claim_action_row.addWidget(self.txt_new_claim, 1)
        self.btn_create_claim = QPushButton("新建报销组")
        self.btn_create_claim.setProperty("class", "SecondaryBtn")
        self.btn_create_claim.setMaximumWidth(96)
        self.btn_create_claim.clicked.connect(self._cb.on_create_claim)
        claim_action_row.addWidget(self.btn_create_claim)
        claim_setup_layout.addLayout(claim_action_row)

        claim_total_row = QHBoxLayout()
        claim_total_row.setSpacing(12)
        self.lbl_claim_total = QLabel("当前报销组 0 张｜合计 ¥0.00")
        self.lbl_claim_total.setProperty("class", "SectionHint")
        claim_total_row.addWidget(self.lbl_claim_total, 1)

        self.btn_export = QPushButton("导出报销包")
        self.btn_export.setProperty("class", "SecondaryBtn")
        self.btn_export.setMaximumWidth(120)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._cb.on_export_claim)
        claim_total_row.addWidget(self.btn_export)
        claim_setup_layout.addLayout(claim_total_row)

        self.lbl_export_summary = QLabel()
        self.lbl_export_summary.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        self.lbl_export_summary.setWordWrap(True)
        self.lbl_export_summary.setText("上一次导出：暂无")
        self.lbl_export_summary.setVisible(False)
        claim_setup_layout.addWidget(self.lbl_export_summary)
        right_content_layout.addWidget(self.claim_setup_section)

        # ── 6. Personal Notes ─────────────────────────────────────
        self.review_note_section = QFrame()
        self.review_note_section.setProperty("class", "DetailSection")
        review_note_layout = QVBoxLayout(self.review_note_section)
        review_note_layout.setContentsMargins(10, 4, 10, 4)
        review_note_layout.setSpacing(4)

        note_title_layout = QHBoxLayout()
        self.btn_toggle_note = QPushButton("个人备注 +")
        self.btn_toggle_note.setProperty("class", "TextBtn")
        self.btn_toggle_note.setStyleSheet(
            "text-align: left; font-weight: bold; color: #4B5563; "
            "border: none; background: transparent; padding: 0;"
        )
        self.btn_toggle_note.clicked.connect(self._toggle_note_visibility)
        note_title_layout.addWidget(self.btn_toggle_note)
        note_title_layout.addStretch(1)
        review_note_layout.addLayout(note_title_layout)

        self.txt_note = QTextEdit()
        self.txt_note.setMaximumHeight(45)
        self.txt_note.setPlaceholderText(
            "可填写报销说明、事项背景、客户/项目等本地备注。"
        )
        self.txt_note.setVisible(False)
        review_note_layout.addWidget(self.txt_note)
        right_content_layout.addWidget(self.review_note_section)

        # ── 7. More Source Info ───────────────────────────────────
        self.btn_more_source = QToolButton()
        self.btn_more_source.setText("更多来源信息")
        self.btn_more_source.setCheckable(True)
        self.btn_more_source.setChecked(False)
        self.btn_more_source.setArrowType(Qt.RightArrow)
        self.btn_more_source.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_more_source.setProperty("class", "Disclosure")
        self.btn_more_source.toggled.connect(self._toggle_more_source_info)
        right_content_layout.addWidget(self.btn_more_source, 0, Qt.AlignLeft)

        self.more_source_widget = QWidget()
        more_source_layout = QFormLayout(self.more_source_widget)
        more_source_layout.setContentsMargins(0, 0, 0, 0)
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
        right_content_layout.addWidget(self.more_source_widget)

        # ── 8. Bottom Status + Save ───────────────────────────────
        self.closing_card = QFrame()
        self.closing_card.setFrameShape(QFrame.StyledPanel)
        self.closing_card.setStyleSheet("""
            QFrame {
                background-color: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 4px;
            }
        """)
        closing_layout = QHBoxLayout(self.closing_card)
        closing_layout.setContentsMargins(8, 4, 8, 4)
        closing_layout.setSpacing(4)

        self.lbl_closing_desc = QLabel("请选择发票以查看建议")
        self.lbl_closing_desc.setWordWrap(True)
        self.lbl_closing_desc.setFont(QFont("Segoe UI", 8))
        self.lbl_closing_desc.setStyleSheet(
            "color: #4B5563; border: none; background: transparent;"
        )
        closing_layout.addWidget(self.lbl_closing_desc)

        right_content_layout.addWidget(self.closing_card)

        self.lbl_dirty_hint = QLabel("未修改")
        self.lbl_dirty_hint.setStyleSheet("color: #6B7280; font-size: 11px;")

        self.btn_save_draft = QPushButton("保存修改")
        self.btn_save_draft.setProperty("class", "PrimaryBtn")
        self.btn_save_draft.setMinimumWidth(96)
        self.btn_save_draft.setMaximumWidth(120)
        self.btn_save_draft.clicked.connect(self._cb.on_save_fields)

        save_row = QHBoxLayout()
        save_row.setContentsMargins(0, 0, 0, 0)
        save_row.addWidget(self.lbl_dirty_hint)
        save_row.addStretch(1)
        save_row.addWidget(self.btn_save_draft)
        right_content_layout.addLayout(save_row)

        right_content_layout.addStretch(1)

        # initial states
        self.btn_save_draft.setEnabled(False)
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
