# -*- coding: utf-8 -*-
"""
Invoice Hub PySide6 App Window
"""

import json
import os
import sys
import logging
import time
from io import BytesIO
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QFormLayout, QLineEdit,
    QTextEdit, QPlainTextEdit, QPushButton, QComboBox, QLabel, QMessageBox, QGroupBox, QCheckBox,
    QScrollArea, QAbstractItemView, QHeaderView, QFileDialog, QDialog,
    QStackedWidget, QProgressBar, QFrame, QTabWidget, QMenu, QSizePolicy,
    QButtonGroup, QGridLayout, QStyle, QLayout, QToolButton
)
from PySide6.QtCore import Qt, QUrl, QThread, Signal, QTimer, QEvent
from PySide6.QtGui import QShortcut
from PySide6.QtGui import QFont, QColor, QDesktopServices, QAction, QPixmap

HAS_QT_PDF = None
_QPDF_CLASSES = None

def check_has_qt_pdf() -> bool:
    global HAS_QT_PDF
    if HAS_QT_PDF is None:
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        HAS_QT_PDF = QPdfDocument is not None and QPdfView is not None
    return HAS_QT_PDF


def get_qt_pdf_classes():
    global _QPDF_CLASSES
    if _QPDF_CLASSES is not None:
        return _QPDF_CLASSES
    try:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
        _QPDF_CLASSES = (QPdfDocument, QPdfView)
    except ImportError:
        _QPDF_CLASSES = (None, None)
    return _QPDF_CLASSES

from ..db import InvoiceDB, is_pending_evidence_invoice
from .. import APP_VERSION
from ..config import PROJECT_ROOT, RUNTIME_DIR, load_config_safe, save_config
from ..diagnostics import collect_app_info, export_diagnostics_zip
from ..reimbursement import amount_total, buyer_warning, format_amount_total, get_date_warning
from ..review_status import TO_REVIEW, APPROVED, IGNORED, ERROR
from ..log_privacy import PrivacyLogFilter, mask_email, sanitize_log_message
from .styles import APP_STYLESHEET
from .helpers import _mask_url, _read_manifest_summary, resolve_stored_path

_log = logging.getLogger("invoice_fetch.gui.app")
_log.addFilter(PrivacyLogFilter())

GITHUB_ISSUES_URL = "https://github.com/if16888/invoice-hub/issues/new/choose"
LOG_DRAWER_EXPANDED_HEIGHT = 120
FEEDBACK_PRIVACY_NOTICE = (
    "请不要上传真实发票、receipt、水单、行程单、邮箱授权码、API Key、SQLite 数据库、"
    "Excel 报销包或完整下载链接。建议只上传应用生成的脱敏诊断包。"
)

DEFAULT_CATEGORY_OPTIONS = ["餐饮", "交通", "住宿", "办公", "通讯", "其他"]
CONFIG_CATEGORY_LABELS = {
    "hotel": "住宿",
    "taxi": "交通",
    "meal": "餐饮",
    "telecom": "通讯",
    "transport": "交通",
}


class InvoiceReviewApp(QMainWindow):
    def __init__(self, db_path: Path, splash=None, startup_probe: bool = False):
        super().__init__()
        self.splash = splash
        self.startup_probe = startup_probe
        import time as _time_mod
        start_time = _time_mod.time()

        self.db_path = db_path
        if self.splash:
            self.splash.show_message("正在打开本地数据库...", 40)
        self.db = InvoiceDB(db_path)
        self.config = load_config_safe()
        db_time = _time_mod.time()
        self.db_open_ms = int((db_time - start_time) * 1000)

        self.current_filter_status = None  # None means "All"
        self.invoices_list = []
        self.current_invoice = None
        self.supporting_doc_items = []
        self._invoice_snapshot = None
        self._suspend_dirty_tracking = False
        self._is_first_load = True
        self._deferred_init_done = False
        self._first_load_notice = None
        self._last_scan_summary = {}
        self._limited_first_load_active = False
        self._limited_first_load_total = 0

        self.setWindowTitle(f"Invoice Hub {APP_VERSION} - 发票审核与报销整理")

        if self.startup_probe:
            self._init_ui_probe()
            init_time = _time_mod.time()
            self.gui_init_ms = int((init_time - db_time) * 1000)
            return

        # Set premium business window icon
        logo_path = Path(__file__).resolve().parent / "assets" / "logo_icon.png"
        if logo_path.exists():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(logo_path)))
        self.resize(1150, 850)
        self.setStyleSheet(APP_STYLESHEET)


        if self.splash:
            self.splash.show_message("正在初始化界面布局...", 70)
        self._init_ui()
        init_time = _time_mod.time()
        self.gui_init_ms = int((init_time - db_time) * 1000)

        # Startup responsiveness logs
        self.write_log(f"⚡ [系统启动] GUI Import/Load Start: 正在初始化界面主框架...")
        self.write_log(f"💾 [系统启动] DB Open Complete: 成功打开本地 SQLite 数据库 (耗时: {db_time - start_time:.4f}秒)")
        self.write_log(f"🎨 [系统启动] GUI Init Complete: UI 工作流外壳与部件构建完成 (耗时: {init_time - db_time:.4f}秒)")

        # Register deferred load
        QTimer.singleShot(50, self._deferred_init)

    def _deferred_init(self):
        # If the window has already been closed or DB closed (e.g. during rapid unit tests), bypass!
        if not hasattr(self, "db") or self.db is None or not self.db.is_open:
            return
        if getattr(self, "_deferred_init_done", False):
            return
        self._deferred_init_done = True

        import time as _time_mod
        start_time = _time_mod.time()
        if self.splash:
            self.splash.show_message("正在加载发票列表...", 90)

        try:
            self._load_invoices()
            self._load_claims()
        except Exception as e:
            # Show a user-visible warning or status bar message instead of silently swallowing the error!
            err_msg = f"发票列表加载失败: {e}"
            _log.error(err_msg)
            self.statusBar().showMessage(err_msg, 6000)
            self.write_log(f"⚠️ [加载失败] {err_msg}")
            # Ensure splash screen closes even if load fails so GUI doesn't get blocked
            if self.splash:
                self.splash.close()
            return

        load_time = _time_mod.time()
        self.first_load_ms = int((load_time - start_time) * 1000)

        # Close splash screen
        if self.splash:
            self.splash.show_message("加载完成！", 100)
            self.splash.close()

        self.write_log(f"📊 [系统启动] First Invoice List Loaded: 成功检索并渲染首批数据 (耗时: {load_time - start_time:.4f}秒)")
        status_msg = f"本地数据库 invoices.db 加载成功，发票列表加载耗时 {load_time - start_time:.4f} 秒"
        if getattr(self, "_first_load_notice", None):
            status_msg = f"{status_msg}｜{self._first_load_notice}"
        self.statusBar().showMessage(status_msg, 4000)

    def closeEvent(self, event):
        self.db.close()
        event.accept()

    def _init_ui_probe(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

    def _make_menu_action(self, text: str, icon_id, handler, tooltip: str = "") -> QAction:
        action = QAction(self.style().standardIcon(icon_id), text, self)
        action.setObjectName("action_" + text.lower().replace(" ", "_"))
        action.setToolTip(tooltip or text)
        action.triggered.connect(handler)
        return action

    def _init_ui(self):
        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        main_layout = self.main_layout
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        self.search_reload_timer = QTimer(self)
        self.search_reload_timer.setSingleShot(True)
        self.search_reload_timer.setInterval(250)
        self.search_reload_timer.timeout.connect(self._load_invoices)

        # 0. Top Action Bar
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)

        self.btn_import_local = QPushButton("导入发票")
        self.btn_import_local.clicked.connect(self._import_local_clicked)
        self.btn_import_local.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_import_local.setProperty("class", "ToolbarActionBtn")
        action_layout.addWidget(self.btn_import_local)

        self.btn_mobile_upload = QPushButton("扫码上传")
        self.btn_mobile_upload.clicked.connect(self._mobile_upload_clicked)
        self.btn_mobile_upload.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_mobile_upload.setProperty("class", "ToolbarActionBtn")
        action_layout.addWidget(self.btn_mobile_upload)

        self.btn_scan_email = QPushButton("扫描邮箱")
        self.btn_scan_email.clicked.connect(self._scan_email_clicked)
        self.btn_scan_email.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_scan_email.setProperty("class", "ToolbarActionBtn")
        action_layout.addWidget(self.btn_scan_email)

        self.btn_toolbar_export = QPushButton("一键导出")
        self.btn_toolbar_export.clicked.connect(self._export_claim_package)
        self.btn_toolbar_export.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_toolbar_export.setProperty("class", "ToolbarActionBtn")
        action_layout.addWidget(self.btn_toolbar_export)

        # "更多  ▼" consolidated drop-down menu
        self.btn_more = QPushButton("更多  ▼")
        self.btn_more.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_more.setProperty("class", "ToolbarActionBtn")

        self.more_menu = QMenu(self)
        self.more_menu.setToolTipsVisible(True)

        self.action_refresh = self._make_menu_action(
            "刷新数据", QStyle.SP_BrowserReload, self._manual_refresh, "刷新当前发票列表"
        )
        self.action_runtime = self._make_menu_action(
            "打开数据目录", QStyle.SP_DirOpenIcon, self._open_runtime_dir, "打开本地运行数据目录"
        )
        self.action_exports = self._make_menu_action(
            "打开导出目录", QStyle.SP_DriveHDIcon, self._open_exports_directory, "打开本地导出目录"
        )
        self.action_logs = self._make_menu_action(
            "打开日志目录", QStyle.SP_FileDialogDetailedView, self._open_logs_directory, "打开本地日志目录"
        )
        self.action_copy_diag = self._make_menu_action(
            "复制诊断信息", QStyle.SP_FileDialogInfoView, self._copy_diagnostic_info, "复制脱敏诊断信息"
        )
        self.action_export_diag = self._make_menu_action(
            "导出脱敏诊断包", QStyle.SP_DialogSaveButton, self._export_diagnostics_package, "导出可用于反馈的脱敏诊断包"
        )
        self.action_github_issues = self._make_menu_action(
            "打开 GitHub Issues", QStyle.SP_MessageBoxQuestion, self._open_github_issues, "打开公开 Issue 反馈入口"
        )
        self.action_settings = self._make_menu_action(
            "系统设置", QStyle.SP_ComputerIcon, self._open_settings_dialog, "打开系统设置"
        )
        self.action_about = self._make_menu_action(
            "关于 Invoice Hub", QStyle.SP_MessageBoxInformation, self._show_about_dialog, "查看版本、数据目录和日志目录"
        )

        self.more_menu.addAction(self.action_refresh)
        self.more_menu.addAction(self.action_runtime)
        self.more_menu.addAction(self.action_exports)
        self.more_menu.addAction(self.action_logs)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self.action_copy_diag)
        self.more_menu.addAction(self.action_export_diag)
        self.more_menu.addAction(self.action_github_issues)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self.action_settings)
        self.more_menu.addAction(self.action_about)

        self.btn_more.setMenu(self.more_menu)
        action_layout.addWidget(self.btn_more)

        action_layout.addStretch()
        main_layout.addLayout(action_layout)

        # 1. Top Filter Bar
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        lbl_filter = QLabel("状态筛选:")
        lbl_filter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        filter_layout.addWidget(lbl_filter)

        self.filter_buttons = {}
        self.filter_base_labels = {
            "all": "全部",
            TO_REVIEW: "待审核",
            APPROVED: "已通过",
            IGNORED: "已忽略",
            ERROR: "异常",
        }

        for status, text in self.filter_base_labels.items():
            btn = QPushButton(text)
            btn.setProperty("class", "FilterBtn")
            btn.setCheckable(True)
            btn.setMinimumWidth(86)
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            if status == "all":
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, s=status: self._change_filter(s))
            filter_layout.addWidget(btn)
            self.filter_buttons[status] = btn

        filter_layout.addStretch()
        main_layout.addLayout(filter_layout)

        # 1b. Search & Secondary Filters
        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("搜索发票号 / 销售方 / 购买方 / 金额 / 邮件主题")
        self.txt_search.textChanged.connect(self._schedule_invoice_reload)
        search_layout.addWidget(self.txt_search, 2)

        self.chk_unlinked = QCheckBox("未关联报销组")
        self.chk_unlinked.stateChanged.connect(self._schedule_invoice_reload)
        search_layout.addWidget(self.chk_unlinked)

        self.chk_needs_fix = QCheckBox("未识别/待补全")
        self.chk_needs_fix.stateChanged.connect(self._schedule_invoice_reload)
        search_layout.addWidget(self.chk_needs_fix)

        self.chk_show_deleted = QCheckBox("显示已删除")
        self.chk_show_deleted.stateChanged.connect(self._schedule_invoice_reload)
        search_layout.addWidget(self.chk_show_deleted)

        self.btn_reset_filters = QPushButton("重置")
        self.btn_reset_filters.setProperty("class", "SecondaryBtn")
        self.btn_reset_filters.setMaximumWidth(70)
        self.btn_reset_filters.clicked.connect(self._reset_invoice_filters)
        search_layout.addWidget(self.btn_reset_filters)

        search_layout.addStretch()
        main_layout.addLayout(search_layout)

        # 2. Main Content Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.main_splitter = splitter
        main_layout.addWidget(splitter, 1)

        # Left Column - Invoice Table Panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        # Use QStackedWidget for Table vs Empty State
        self.left_stack = QStackedWidget()

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "状态", "费用日期", "金额", "发票号码", "销售方", "消费类型", "来源", "报销组"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.verticalHeader().setMinimumSectionSize(24)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

        # Set explicit column widths for readability
        self.table.setColumnWidth(0, 72)   # 状态
        self.table.setColumnWidth(1, 96)   # 日期
        self.table.setColumnWidth(2, 88)   # 金额
        self.table.setColumnWidth(3, 190)  # 发票号码
        self.table.setColumnWidth(5, 72)   # 类型
        self.table.setColumnWidth(6, 72)   # 来源
        self.table.setColumnWidth(7, 110)  # 报销组

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)

        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)

        self.left_stack.addWidget(self.table)

        # Empty State Widget
        self.empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(15)

        self.lbl_empty_title = QLabel("当前没有发票记录")
        self.lbl_empty_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.lbl_empty_title.setStyleSheet("color: #4B5563;")
        empty_layout.addWidget(self.lbl_empty_title)

        self.lbl_guide = QLabel(
            "您可以执行以下操作以加载发票数据：\n\n"
            "  1. 点击“导入发票”选择本地文件夹导入 PDF/ZIP 发票；\n"
            "  2. 点击“配置邮箱”配置您的邮箱，然后点击“扫描邮箱”开始增量同步；\n"
            "  3. 点击“扫码上传”，用手机上传 PDF/OFD、相册图片或拍照材料。"
        )
        self.lbl_guide.setFont(QFont("Segoe UI", 10))
        self.lbl_guide.setStyleSheet("color: #6B7280; line-height: 1.5; border: 1px dashed #D1D5DB; padding: 15px; border-radius: 6px; background-color: #F9FAFB;")
        self.lbl_guide.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        empty_layout.addWidget(self.lbl_guide)

        # Onboarding Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.setAlignment(Qt.AlignCenter)

        self.empty_btn_import = QPushButton("导入发票")
        self.empty_btn_import.clicked.connect(self._import_local_clicked)
        self.empty_btn_import.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.empty_btn_import.setProperty("class", "SecondaryBtn")

        self.empty_btn_settings = QPushButton("配置邮箱")
        self.empty_btn_settings.clicked.connect(self._open_settings_dialog)
        self.empty_btn_settings.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.empty_btn_settings.setProperty("class", "SecondaryBtn")

        self.empty_btn_scan = QPushButton("扫描邮箱")
        self.empty_btn_scan.clicked.connect(self._scan_email_clicked)
        self.empty_btn_scan.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.empty_btn_scan.setProperty("class", "SecondaryBtn")

        self.empty_btn_mobile_upload = QPushButton("扫码上传")
        self.empty_btn_mobile_upload.clicked.connect(self._mobile_upload_clicked)
        self.empty_btn_mobile_upload.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.empty_btn_mobile_upload.setProperty("class", "SecondaryBtn")

        # Search / filter fail actions
        self.empty_btn_clear_search = QPushButton("🧹 清空搜索")
        self.empty_btn_clear_search.clicked.connect(self._clear_search_clicked)
        self.empty_btn_clear_search.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.empty_btn_clear_search.setProperty("class", "PrimaryBtn")

        self.empty_btn_reset_filters = QPushButton("🔄 重置筛选")
        self.empty_btn_reset_filters.clicked.connect(self._reset_invoice_filters)
        self.empty_btn_reset_filters.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.empty_btn_reset_filters.setProperty("class", "SecondaryBtn")

        btn_layout.addWidget(self.empty_btn_import)
        btn_layout.addWidget(self.empty_btn_mobile_upload)
        btn_layout.addWidget(self.empty_btn_settings)
        btn_layout.addWidget(self.empty_btn_scan)
        btn_layout.addWidget(self.empty_btn_clear_search)
        btn_layout.addWidget(self.empty_btn_reset_filters)

        empty_layout.addLayout(btn_layout)

        self.left_stack.addWidget(self.empty_widget)

        # Upper container to group left_stack and preview controls
        self.left_upper_widget = QWidget()
        left_upper_layout = QVBoxLayout(self.left_upper_widget)
        left_upper_layout.setContentsMargins(0, 0, 0, 0)
        left_upper_layout.setSpacing(6)
        left_upper_layout.addWidget(self.left_stack)

        # Initialize the New Preview Panel
        self._init_preview_panel()

        # Vertical QSplitter for Left Column
        self.left_splitter = QSplitter(Qt.Vertical)
        self.left_splitter.addWidget(self.left_upper_widget)
        self.left_splitter.addWidget(self.preview_panel)
        self.left_splitter.setSizes([380, 620])
        self.preview_panel.setMinimumHeight(180)



        left_layout.addWidget(self.left_splitter)

        splitter.addWidget(left_panel)

        # Right Column - Fixed Summary Card & QTabWidget Panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(6)
        self.right_stack = QStackedWidget()
        right_layout.addWidget(self.right_stack, 1)

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

        # 1. Selected Invoice Summary Card
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

        quick_layout = QHBoxLayout()
        quick_layout.setSpacing(6)

        self.btn_sum_open_file = QPushButton("查看原件")
        self.btn_sum_open_file.setProperty("class", "SecondaryBtn")
        self.btn_sum_open_file.clicked.connect(self._open_attachment)
        self.btn_sum_open_file.setEnabled(False)
        self.btn_sum_open_file.setMaximumWidth(96)

        self.btn_sum_copy_number = QPushButton("复制号码", self)
        self.btn_sum_copy_number.setProperty("class", "SecondaryBtn")
        self.btn_sum_copy_number.clicked.connect(self._copy_invoice_number)
        self.btn_sum_copy_number.setEnabled(False)
        self.btn_sum_copy_number.setMaximumWidth(96)
        self.btn_sum_copy_number.setVisible(False)

        self.btn_sum_locate_file = QPushButton("定位文件", self)
        self.btn_sum_locate_file.setProperty("class", "SecondaryBtn")
        self.btn_sum_locate_file.clicked.connect(self._locate_attachment)
        self.btn_sum_locate_file.setEnabled(False)
        self.btn_sum_locate_file.setMaximumWidth(96)
        self.btn_sum_locate_file.setVisible(False)

        quick_layout.addWidget(self.btn_sum_open_file)
        quick_layout.addStretch()

        summary_layout.addLayout(summary_header)
        summary_layout.addWidget(summary_metadata)
        self.lbl_buyer_warning = QLabel("")
        self.lbl_buyer_warning.setWordWrap(True)
        self.lbl_buyer_warning.setProperty("class", "InlineWarning")
        self.lbl_buyer_warning.setVisible(False)
        summary_layout.addWidget(self.lbl_buyer_warning)
        self.lbl_buyer_warning_hint = QLabel("可在下方“购买方名称”字段修正后保存。", self)
        self.lbl_buyer_warning_hint.setStyleSheet("color: #6B7280; font-size: 12px;")
        self.lbl_buyer_warning_hint.setVisible(False)
        summary_layout.addWidget(self.lbl_buyer_warning_hint)

        self.lbl_date_warning = QLabel("")
        self.lbl_date_warning.setWordWrap(True)
        self.lbl_date_warning.setProperty("class", "InlineWarning")
        self.lbl_date_warning.setVisible(False)
        summary_layout.addWidget(self.lbl_date_warning)
        summary_layout.addLayout(quick_layout)

        right_content_layout.addWidget(self.summary_card)

        # New inline review actions bar
        self.inline_review_layout = QHBoxLayout()
        self.inline_review_layout.setSpacing(6)
        self.inline_review_layout.setContentsMargins(0, 4, 0, 4)

        self.btn_app = QPushButton("通过并下一张")
        self.btn_app.setProperty("class", "PrimaryBtn")
        self.btn_app.setMaximumWidth(110)
        self.btn_app.clicked.connect(lambda: self._set_selected_status(APPROVED))
        self.inline_review_layout.addWidget(self.btn_app)

        self.btn_ign = QPushButton("忽略")
        self.btn_ign.setProperty("class", "SecondaryBtn")
        self.btn_ign.setMaximumWidth(60)
        self.btn_ign.clicked.connect(lambda: self._set_selected_status(IGNORED))
        self.inline_review_layout.addWidget(self.btn_ign)

        self.btn_err = QPushButton("异常")
        self.btn_err.setProperty("class", "DangerOutlineBtn")
        self.btn_err.setMaximumWidth(60)
        self.btn_err.clicked.connect(lambda: self._set_selected_status(ERROR))
        self.inline_review_layout.addWidget(self.btn_err)

        self.inline_more_menu = QMenu(self)
        self.action_inline_reset = self.inline_more_menu.addAction("重置为待审核")
        self.action_inline_delete = self.inline_more_menu.addAction("删除发票")
        self.inline_more_menu.addSeparator()
        self.action_copy_number = self.inline_more_menu.addAction("复制发票号码")
        self.action_locate_file = self.inline_more_menu.addAction("定位原件文件")
        self.action_open_dir = self.inline_more_menu.addAction("打开文件所在目录")

        self.action_inline_reset.triggered.connect(lambda: self._set_selected_status(TO_REVIEW))
        self.action_inline_delete.triggered.connect(self._handle_detail_delete_clicked)
        self.action_copy_number.triggered.connect(self._copy_invoice_number)
        self.action_locate_file.triggered.connect(self._locate_attachment_file)
        self.action_open_dir.triggered.connect(self._locate_attachment)

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

        self.btn_delete_invoice = QPushButton("删除发票", self)
        self.btn_delete_invoice.setVisible(False)
        self.btn_delete_invoice.setProperty("class", "TextDangerBtn")
        self.btn_delete_invoice.setMaximumWidth(96)

        # 2. Right-Side QTabWidget
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        # ── Tab 1: 发票详情 ───────────────────────────
        tab_details = QWidget()
        tab_details_layout = QVBoxLayout(tab_details)
        tab_details_layout.setContentsMargins(10, 10, 10, 10)
        tab_details_layout.setSpacing(6)

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
        self._refresh_category_options()
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
        tab_details_layout.addWidget(self.detail_core_section)

        path_widget = QWidget()
        path_layout = QHBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(4)
        self.txt_path = QLineEdit()
        self.txt_path.setReadOnly(True)
        path_layout.addWidget(self.txt_path, 1)
        self.btn_open_file = QPushButton("查看")
        self.btn_open_file.clicked.connect(self._open_attachment)
        self.btn_open_file.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_open_file.setMinimumWidth(50)
        self.btn_open_file.setProperty("class", "SecondaryBtn")
        path_layout.addWidget(self.btn_open_file)

        self.btn_add_attachment = QPushButton("补原件")
        self.btn_add_attachment.clicked.connect(self._add_attachment_manually)
        self.btn_add_attachment.setFont(QFont("Segoe UI", 9))
        self.btn_add_attachment.setMinimumWidth(60)
        self.btn_add_attachment.setProperty("class", "SecondaryBtn")
        path_layout.addWidget(self.btn_add_attachment)

        self.btn_retry_download = QPushButton("重试下载")
        self.btn_retry_download.clicked.connect(self._retry_download_link)
        self.btn_retry_download.setFont(QFont("Segoe UI", 9))
        self.btn_retry_download.setMinimumWidth(65)
        self.btn_retry_download.setProperty("class", "SecondaryBtn")
        path_layout.addWidget(self.btn_retry_download)

        # 证明材料布局
        docs_widget = QWidget()
        docs_layout = QHBoxLayout(docs_widget)
        docs_layout.setContentsMargins(0, 0, 0, 0)
        docs_layout.setSpacing(4)

        self.combo_supporting_docs = QComboBox()
        self.combo_supporting_docs.setMinimumWidth(120)
        self.combo_supporting_docs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_supporting_docs.view().setTextElideMode(Qt.ElideMiddle)
        self.combo_supporting_docs.currentIndexChanged.connect(self._on_supporting_docs_combo_changed)
        docs_layout.addWidget(self.combo_supporting_docs, 1)

        self.btn_open_extra_files = QPushButton("查看")
        self.btn_open_extra_files.clicked.connect(self._open_extra_docs)
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
        tab_details_layout.addWidget(self.detail_files_section)

        self.review_note_section = QFrame()
        self.review_note_section.setProperty("class", "DetailSection")
        review_note_layout = QVBoxLayout(self.review_note_section)
        review_note_layout.setContentsMargins(10, 4, 10, 4)
        review_note_layout.setSpacing(4)

        note_title_layout = QHBoxLayout()
        self.btn_toggle_note = QPushButton("个人备注 +")
        self.btn_toggle_note.setProperty("class", "TextBtn")
        self.btn_toggle_note.setStyleSheet("text-align: left; font-weight: bold; color: #4B5563; border: none; background: transparent; padding: 0;")
        self.btn_toggle_note.clicked.connect(self._toggle_note_visibility)
        note_title_layout.addWidget(self.btn_toggle_note)
        note_title_layout.addStretch(1)
        review_note_layout.addLayout(note_title_layout)

        self.txt_note = QTextEdit()
        self.txt_note.setMaximumHeight(45)
        self.txt_note.setPlaceholderText("可填写报销说明、事项背景、客户/项目等本地备注。")
        self.txt_note.setVisible(False)
        review_note_layout.addWidget(self.txt_note)
        tab_details_layout.addWidget(self.review_note_section)

        self.btn_more_source = QToolButton()
        self.btn_more_source.setText("更多来源信息")
        self.btn_more_source.setCheckable(True)
        self.btn_more_source.setChecked(False)
        self.btn_more_source.setArrowType(Qt.RightArrow)
        self.btn_more_source.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_more_source.setProperty("class", "Disclosure")
        self.btn_more_source.toggled.connect(self._toggle_more_source_info)
        tab_details_layout.addWidget(self.btn_more_source, 0, Qt.AlignLeft)

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
        tab_details_layout.addWidget(self.more_source_widget)

        self.lbl_dirty_hint = QLabel("未修改")
        self.lbl_dirty_hint.setStyleSheet("color: #6B7280; font-size: 11px;")

        self.btn_save_draft = QPushButton("保存修改")
        self.btn_save_draft.setProperty("class", "PrimaryBtn")
        self.btn_save_draft.setMinimumWidth(96)
        self.btn_save_draft.setMaximumWidth(120)
        self.btn_save_draft.clicked.connect(self._save_invoice_fields)

        save_row = QHBoxLayout()
        save_row.setContentsMargins(0, 0, 0, 0)
        save_row.addWidget(self.lbl_dirty_hint)
        save_row.addStretch(1)
        save_row.addWidget(self.btn_save_draft)
        tab_details_layout.addLayout(save_row)

        # Reimbursement Closing Card
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
        self.lbl_closing_desc.setStyleSheet("color: #4B5563; border: none; background: transparent;")
        closing_layout.addWidget(self.lbl_closing_desc)

        tab_details_layout.addWidget(self.closing_card)
        tab_details_layout.addStretch(1)

        self.detail_tabs.addTab(tab_details, "发票详情")

        # ── Tab 3: 报销与导出 ─────────────────────────
        tab_claim = QWidget()
        tab_claim_layout = QVBoxLayout(tab_claim)
        tab_claim_layout.setContentsMargins(10, 10, 10, 10)
        tab_claim_layout.setSpacing(8)

        self.claim_setup_section = QFrame()
        self.claim_setup_section.setProperty("class", "DetailSection")
        claim_setup_layout = QVBoxLayout(self.claim_setup_section)
        claim_setup_layout.setContentsMargins(10, 8, 10, 10)
        claim_setup_layout.setSpacing(6)
        claim_setup_title = QLabel("报销组")
        claim_setup_title.setProperty("class", "SectionTitle")
        claim_setup_layout.addWidget(claim_setup_title)

        lbl_new_claim = QLabel("新建报销组:")
        lbl_new_claim.setProperty("class", "SectionHint")
        claim_setup_layout.addWidget(lbl_new_claim)

        claim_create_box = QHBoxLayout()
        claim_create_box.setSpacing(6)
        self.txt_new_claim = QLineEdit()
        self.txt_new_claim.setPlaceholderText("输入新报销组名称...")
        claim_create_box.addWidget(self.txt_new_claim, 1)
        self.btn_create_claim = QPushButton("新建")
        self.btn_create_claim.setProperty("class", "SecondaryBtn")
        self.btn_create_claim.setMaximumWidth(80)
        self.btn_create_claim.clicked.connect(self._create_claim)
        claim_create_box.addWidget(self.btn_create_claim)
        claim_setup_layout.addLayout(claim_create_box)

        lbl_link_claim = QLabel("关联已有报销组:")
        lbl_link_claim.setProperty("class", "SectionHint")
        claim_setup_layout.addWidget(lbl_link_claim)

        link_box = QHBoxLayout()
        link_box.setSpacing(6)
        self.combo_claims = QComboBox()
        self.combo_claims.currentIndexChanged.connect(self._update_claim_total)
        link_box.addWidget(self.combo_claims, 1)

        self.btn_refresh_claims = QPushButton("刷新")
        self.btn_refresh_claims.clicked.connect(self._load_claims)
        self.btn_refresh_claims.setMaximumWidth(72)
        self.btn_refresh_claims.setProperty("class", "SecondaryBtn")
        link_box.addWidget(self.btn_refresh_claims)

        self.btn_add_to_claim = QPushButton("关联发票")
        self.btn_add_to_claim.clicked.connect(self._link_invoices_to_claim)
        self.btn_add_to_claim.setProperty("class", "SecondaryBtn")
        self.btn_add_to_claim.setMaximumWidth(104)
        link_box.addWidget(self.btn_add_to_claim)
        claim_setup_layout.addLayout(link_box)

        self.lbl_claim_total = QLabel("当前报销组 0 张｜合计 ¥0.00")
        self.lbl_claim_total.setProperty("class", "SectionHint")
        claim_setup_layout.addWidget(self.lbl_claim_total)
        tab_claim_layout.addWidget(self.claim_setup_section)

        self.claim_export_section = QFrame()
        self.claim_export_section.setProperty("class", "DetailSection")
        claim_export_layout = QVBoxLayout(self.claim_export_section)
        claim_export_layout.setContentsMargins(10, 8, 10, 10)
        claim_export_layout.setSpacing(8)
        claim_export_title = QLabel("导出")
        claim_export_title.setProperty("class", "SectionTitle")
        claim_export_layout.addWidget(claim_export_title)

        export_btn_layout = QHBoxLayout()
        export_btn_layout.setSpacing(6)
        export_btn_layout.addStretch(1)

        self.btn_export = QPushButton("一键打包导出")
        self.btn_export.setProperty("class", "SecondaryBtn")
        self.btn_export.setMaximumWidth(140)
        self.btn_export.clicked.connect(self._export_claim_package)
        export_btn_layout.addWidget(self.btn_export)

        claim_export_layout.addLayout(export_btn_layout)

        self.lbl_export_summary = QLabel()
        self.lbl_export_summary.setProperty("class", "InfoPanel")
        self.lbl_export_summary.setWordWrap(True)
        self.lbl_export_summary.setText("<b>上一次导出结果：</b><br>暂无导出记录")
        claim_export_layout.addWidget(self.lbl_export_summary)
        tab_claim_layout.addWidget(self.claim_export_section)
        tab_claim_layout.addStretch()

        self.detail_tabs.addTab(tab_claim, "报销组")

        self._connect_invoice_dirty_tracking()
        self.btn_save_draft.setEnabled(False)

        right_content_layout.addWidget(self.detail_tabs, 1)
        self.right_stack.setCurrentWidget(self.right_content_widget)

        splitter.addWidget(right_panel)

        # Set default proportions: Table takes 60%, Form takes 40%
        splitter.setSizes([650, 450])

        # 3. Bottom Status Bar & Collapsible Log Panel
        status_bar = QWidget()
        self.status_bar = status_bar
        status_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        status_bar.setFixedHeight(32)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(6, 2, 6, 2)

        self.lbl_status_left = QLabel("当前筛选 0 张｜未选择发票｜最近操作：系统就绪")
        self.lbl_status_left.setFont(QFont("Segoe UI", 9))
        self.lbl_status_left.setStyleSheet("color: #4B5563;")
        status_layout.addWidget(self.lbl_status_left, 1)

        self.lbl_version = QLabel(APP_VERSION)
        self.lbl_version.setFont(QFont("Segoe UI", 8))
        self.lbl_version.setStyleSheet("color: #6B7280;")
        self.lbl_version.setToolTip("当前 Invoice Hub 版本")
        status_layout.addWidget(self.lbl_version)

        self.btn_load_all = QPushButton("加载全部")
        self.btn_load_all.setProperty("class", "OutlineBtn")
        self.btn_load_all.setFixedHeight(24)
        self.btn_load_all.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_load_all.setStyleSheet("padding: 2px 10px; font-size: 12px;")
        self.btn_load_all.setToolTip("首屏仅加载了部分记录，点击加载完整列表")
        self.btn_load_all.clicked.connect(self._load_all_invoices_clicked)
        self.btn_load_all.setVisible(False)
        status_layout.addWidget(self.btn_load_all)

        self.btn_toggle_log = QPushButton("展开日志")
        self.btn_toggle_log.setProperty("class", "SecondaryBtn")
        self.btn_toggle_log.setMinimumWidth(100)
        self.btn_toggle_log.setFixedHeight(24)
        self.btn_toggle_log.setStyleSheet("padding: 2px 10px; font-size: 12px;")
        self.btn_toggle_log.clicked.connect(self._toggle_log)
        status_layout.addWidget(self.btn_toggle_log)

        # Collapsible log drawer (hidden by default)
        self.log_container = QWidget()
        self.log_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        log_container_layout = QVBoxLayout(self.log_container)
        log_container_layout.setContentsMargins(0, 0, 0, 0)
        log_container_layout.setSpacing(4)

        log_header = QWidget()
        log_header_layout = QHBoxLayout(log_header)
        log_header_layout.setContentsMargins(6, 0, 6, 0)

        lbl_log_title = QLabel("系统运行日志")
        lbl_log_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl_log_title.setStyleSheet("color: #111827;")

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Consolas", 9))
        self.txt_log.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E5E7EB; color: #374151;")

        self.btn_clear_log = QPushButton("清空")
        self.btn_clear_log.setProperty("class", "SecondaryBtn")
        self.btn_clear_log.setMinimumWidth(68)
        self.btn_clear_log.setMaximumWidth(80)
        self.btn_clear_log.setToolTip("清空当前运行日志")
        self.btn_clear_log.clicked.connect(self.txt_log.clear)

        self.btn_copy_log = QPushButton("复制")
        self.btn_copy_log.setProperty("class", "SecondaryBtn")
        self.btn_copy_log.setMinimumWidth(68)
        self.btn_copy_log.setMaximumWidth(80)
        self.btn_copy_log.setToolTip("复制当前运行日志")
        self.btn_copy_log.clicked.connect(self._copy_log_to_clipboard)

        log_header_layout.addWidget(lbl_log_title, 1)
        log_header_layout.addWidget(self.btn_clear_log)
        log_header_layout.addWidget(self.btn_copy_log)

        log_container_layout.addWidget(log_header)
        log_container_layout.addWidget(self.txt_log)

        # Bottom dock area keeps the status bar pinned while the log drawer expands separately.
        self.bottom_panel = QWidget()
        self.bottom_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.bottom_panel.setMinimumHeight(32)
        self.bottom_panel.setMaximumHeight(32)
        bottom_layout = QVBoxLayout(self.bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(4)
        bottom_layout.addWidget(status_bar)

        main_layout.addWidget(self.bottom_panel)
        self.log_drawer = QWidget()
        self.log_drawer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        log_drawer_layout = QVBoxLayout(self.log_drawer)
        log_drawer_layout.setContentsMargins(0, 0, 0, 0)
        log_drawer_layout.setSpacing(0)
        log_drawer_layout.addWidget(self.log_container)
        main_layout.addWidget(self.log_drawer)
        self._log_panel_visible = False
        self._set_log_panel_visible(False)

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

    def _refresh_widget_style(self, widget):
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _set_summary_placeholder(self):
        self.lbl_sum_status.setText("未选择发票")
        self.lbl_sum_status.setProperty("variant", "placeholder")
        self._refresh_widget_style(self.lbl_sum_status)

    def _set_right_panel_state(self, has_records: bool):
        if not hasattr(self, "right_stack"):
            return
        target = self.right_content_widget if has_records else self.right_empty_widget
        if self.right_stack.currentWidget() != target:
            self.right_stack.setCurrentWidget(target)

    def _schedule_invoice_reload(self, *_args):
        # Debounce invoice reloads when search/filter controls change.
        if hasattr(self, "search_reload_timer"):
            self.search_reload_timer.start()

    def _reset_invoice_filters(self):
        # Reset search and quick filters to the default view.
        self.txt_search.setText("")
        self.chk_unlinked.setChecked(False)
        self.chk_needs_fix.setChecked(False)
        if hasattr(self, "chk_show_deleted"):
            self.chk_show_deleted.setChecked(False)
        if hasattr(self, "search_reload_timer"):
            self.search_reload_timer.stop()
        self.current_filter_status = None
        for s, btn in self.filter_buttons.items():
            btn.setChecked(s == "all")
        self._load_invoices()

    def _base_filter_label(self, status) -> str:
        return self.filter_base_labels.get(status, str(status))

    def _update_filter_counts(self, invoices_or_counts):
        if not hasattr(self, "filter_buttons"):
            return
        if isinstance(invoices_or_counts, dict):
            counts = invoices_or_counts
        else:
            counts = {
                "all": len(invoices_or_counts),
                TO_REVIEW: 0,
                APPROVED: 0,
                IGNORED: 0,
                ERROR: 0,
            }
            for inv in invoices_or_counts:
                status = inv.get("review_status") or TO_REVIEW
                if status in counts:
                    counts[status] += 1
        for status, btn in self.filter_buttons.items():
            btn.setText(f"{self._base_filter_label(status)} {counts.get(status, 0)}")

    def _apply_non_status_filters(
        self,
        invoices: list[dict],
        needle: str,
        unlinked_only: bool,
        needs_fix_only: bool,
    ) -> list[dict]:
        filtered: list[dict] = []
        for inv in invoices:
            claim_name = str(inv.get("claim_name") or "").strip()
            quality = self._get_invoice_quality(inv)

            if unlinked_only and claim_name:
                continue
            if needs_fix_only and quality not in {"未识别", "待补全"}:
                continue

            if needle:
                haystack = " ".join([
                    str(inv.get("invoice_number") or ""),
                    str(inv.get("seller_name") or ""),
                    str(inv.get("buyer_name") or ""),
                    str(inv.get("total_amount") or ""),
                    str(inv.get("mail_subject") or ""),
                    str(inv.get("category") or ""),
                    str(inv.get("attachment_path") or ""),
                    claim_name,
                ]).lower()
                if needle not in haystack:
                    continue

            filtered.append(inv)
        return filtered

    def _clear_search_clicked(self):
        if hasattr(self, "txt_search"):
            self.txt_search.setText("")
            if hasattr(self, "search_reload_timer"):
                self.search_reload_timer.stop()
            self._load_invoices()

    def _get_invoice_source(self, inv: dict) -> str:
        attachment_path = str(inv.get("attachment_path") or "")
        mail_uid = inv.get("mail_uid")
        download_url = str(inv.get("download_url") or "")
        mail_sender = str(inv.get("mail_sender") or "")
        if mail_sender == "mobile_qr":
            return "手机"
        if attachment_path and mail_uid is not None:
            return "邮箱+本地"
        if attachment_path:
            return "本地"
        if download_url:
            return "链接"
        if mail_uid is not None:
            return "邮箱"
        return "未知"

    def _get_invoice_quality(self, inv: dict) -> str:
        inv_num = str(inv.get("invoice_number") or "").strip()
        total_amt = str(inv.get("total_amount") or "").strip()
        inv_date = str(inv.get("expense_date") or inv.get("invoice_date") or "").strip()
        seller = str(inv.get("seller_name") or "").strip()
        if not inv_num and not total_amt and not seller:
            return "未识别"
        if not inv_num or not total_amt or not inv_date or not seller:
            return "待补全"
        return ""

    def _get_invoice_display_status(self, inv: dict) -> str:
        review_status = inv.get("review_status") or TO_REVIEW
        quality = self._get_invoice_quality(inv)
        if quality:
            return quality
        status_mapping = {
            TO_REVIEW: "待审核",
            APPROVED: "已通过",
            IGNORED: "已忽略",
            ERROR: "异常",
        }
        return status_mapping.get(review_status, str(review_status))

    def _get_invoice_snapshot(self, inv: dict) -> dict:
        return {
            "invoice_number": str(inv.get("invoice_number") or "").strip(),
            "invoice_date": str(inv.get("expense_date") or inv.get("invoice_date") or "").strip(),
            "seller_name": str(inv.get("seller_name") or "").strip(),
            "buyer_name": str(inv.get("buyer_name") or "").strip(),
            "total_amount": str(inv.get("total_amount") or "").strip(),
            "category": str(inv.get("category") or "").strip(),
            "confirmed_note": str(inv.get("confirmed_note") or "").strip(),
        }

    def _get_invoice_form_snapshot(self) -> dict:
        return {
            "invoice_number": self.txt_number.text().strip(),
            "invoice_date": self.txt_date.text().strip(),
            "seller_name": self.txt_seller.text().strip(),
            "buyer_name": self.txt_buyer.text().strip(),
            "total_amount": self.txt_amount.text().strip(),
            "category": self.combo_category.currentText().strip(),
            "confirmed_note": self.txt_note.toPlainText().strip(),
        }

    def _refresh_category_options(self, selected: str | None = None):
        """Merge built-in, config, and existing DB categories into the editable dropdown."""
        current = selected if selected is not None else self.combo_category.currentText().strip()
        options: list[str] = []

        def add_option(value):
            value = str(value or "").strip()
            if value and value not in options:
                options.append(value)

        for value in DEFAULT_CATEGORY_OPTIONS:
            add_option(value)

        cfg = load_config_safe()
        cfg_categories = cfg.get("categories", {})
        if isinstance(cfg_categories, dict):
            for key, value in cfg_categories.items():
                if isinstance(value, dict):
                    add_option(value.get("name") or value.get("label") or CONFIG_CATEGORY_LABELS.get(str(key), key))
                else:
                    add_option(CONFIG_CATEGORY_LABELS.get(str(key), key))

        try:
            for value in self.db.list_categories():
                add_option(value)
        except Exception as exc:
            _log.debug("Failed to load category options: %s", exc)

        if current:
            add_option(current)

        self.combo_category.blockSignals(True)
        self.combo_category.clear()
        self.combo_category.addItems(options)
        if current:
            self.combo_category.setCurrentText(current)
        self.combo_category.blockSignals(False)

    def _format_amount_display(self, amount_text: str) -> str:
        amount_text = str(amount_text or "").strip()
        if not amount_text:
            return "¥—"

        try:
            from decimal import Decimal, InvalidOperation

            return f"¥{Decimal(amount_text):.2f}"
        except (InvalidOperation, ValueError, TypeError):
            return f"¥{amount_text}"

    def _buyer_warning(self, inv: dict) -> str:
        cfg = load_config_safe()
        return buyer_warning(inv, cfg.get("reimbursement", {}))

    def _update_save_button_state(self):
        if not hasattr(self, "btn_save_draft"):
            return
        if not self.current_invoice or self._invoice_snapshot is None:
            self.btn_save_draft.setEnabled(False)
            if hasattr(self, "lbl_dirty_hint"):
                self.lbl_dirty_hint.setText("未修改")
            return
        changed = self._get_invoice_form_snapshot() != self._invoice_snapshot
        self.btn_save_draft.setEnabled(changed)
        if hasattr(self, "lbl_dirty_hint"):
            self.lbl_dirty_hint.setText("有未保存修改" if changed else "未修改")

    def _mark_invoice_form_dirty(self):
        if self._suspend_dirty_tracking:
            return
        self._update_save_button_state()

    def _connect_invoice_dirty_tracking(self):
        for widget in (self.txt_number, self.txt_date, self.txt_seller, self.txt_buyer, self.txt_amount):
            widget.textEdited.connect(self._mark_invoice_form_dirty)
        self.combo_category.currentTextChanged.connect(self._mark_invoice_form_dirty)
        self.txt_note.textChanged.connect(self._mark_invoice_form_dirty)

    def _toggle_more_source_info(self, expanded: bool):
        self.more_source_widget.setVisible(expanded)
        self.btn_more_source.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def _toggle_note_visibility(self):
        if hasattr(self, "txt_note") and hasattr(self, "btn_toggle_note"):
            visible = not self.txt_note.isVisible()
            self.txt_note.setVisible(visible)
            self.btn_toggle_note.setText("个人备注 -" if visible else "个人备注 +")

    def _toggle_log(self):
        current = getattr(self, "_log_panel_visible", self.log_container.isVisible())
        self._set_log_panel_visible(not current)

    def _set_log_panel_visible(self, visible: bool):
        if not hasattr(self, "log_container"):
            return

        if getattr(self, "_log_panel_visible", None) == visible:
            if visible and self.log_container.isVisible() and self.log_container.maximumHeight() == LOG_DRAWER_EXPANDED_HEIGHT:
                self.btn_toggle_log.setText("收起日志")
                return
            if (
                not visible
                and not self.log_container.isVisible()
                and self.log_container.maximumHeight() == 0
                and hasattr(self, "log_drawer")
                and self.log_drawer.maximumHeight() == 0
            ):
                self.btn_toggle_log.setText("展开日志")
                return

        self._log_panel_visible = visible
        self.btn_toggle_log.setText("收起日志" if visible else "展开日志")

        if visible:
            self.log_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            self.log_container.setMinimumHeight(LOG_DRAWER_EXPANDED_HEIGHT)
            self.log_container.setMaximumHeight(LOG_DRAWER_EXPANDED_HEIGHT)
            self.log_container.setVisible(True)
            if hasattr(self, "log_drawer"):
                self.log_drawer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.log_drawer.setMinimumHeight(LOG_DRAWER_EXPANDED_HEIGHT)
                self.log_drawer.setMaximumHeight(LOG_DRAWER_EXPANDED_HEIGHT)
                self.log_drawer.setVisible(True)
        else:
            self.log_container.setVisible(False)
            self.log_container.setMinimumHeight(0)
            self.log_container.setMaximumHeight(0)
            self.log_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            if hasattr(self, "log_drawer"):
                self.log_drawer.setVisible(False)
                self.log_drawer.setMinimumHeight(0)
                self.log_drawer.setMaximumHeight(0)
        self._apply_log_layout_state(visible)
        if not visible and self.isMaximized():
            QTimer.singleShot(0, self._normalize_maximized_geometry)

    def _apply_log_layout_state(self, log_visible: bool):
        if hasattr(self, "preview_panel"):
            self.preview_panel.setMinimumHeight(180)
            self.preview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if hasattr(self, "left_upper_widget"):
            self.left_upper_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.log_container.updateGeometry()
        if hasattr(self, "log_drawer"):
            self.log_drawer.updateGeometry()
            if self.log_drawer.layout() is not None:
                self.log_drawer.layout().invalidate()
        if hasattr(self, "bottom_panel"):
            self.bottom_panel.updateGeometry()
            if self.bottom_panel.layout() is not None:
                self.bottom_panel.layout().invalidate()
        if hasattr(self, "main_splitter"):
            self.main_splitter.updateGeometry()
            if self.main_splitter.layout() is not None:
                self.main_splitter.layout().invalidate()
        if hasattr(self, "left_splitter"):
            self.left_splitter.updateGeometry()
            if self.left_splitter.layout() is not None:
                self.left_splitter.layout().invalidate()
        if hasattr(self, "main_layout"):
            self.main_layout.invalidate()
        central = self.centralWidget()
        if central is not None and central.layout() is not None:
            central.layout().invalidate()
            central.updateGeometry()
            central.update()
        self.updateGeometry()

    def _normalize_maximized_geometry(self):
        if not self.isMaximized():
            return
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        if available.isEmpty():
            return
        toggle_bottom_right = self.btn_toggle_log.mapToGlobal(self.btn_toggle_log.rect().bottomRight())
        if not available.contains(toggle_bottom_right):
            self.setGeometry(available)
            self.showMaximized()

    def _copy_log_to_clipboard(self):
        log_text = self.txt_log.toPlainText()
        if log_text:
            QApplication.clipboard().setText(log_text)
            self.statusBar().showMessage("日志已复制到剪贴板", 2000)

    def _copy_invoice_number(self):
        inv_number = self.txt_number.text().strip()
        if inv_number:
            QApplication.clipboard().setText(inv_number)
            self.statusBar().showMessage(f"已复制发票号码: {inv_number}", 2000)

    # Controller & Data loading

    def _change_filter(self, status):
        # Handle top-bar filter button clicks and update UI checked state.
        self.current_filter_status = None if status == "all" else status
        for s, btn in self.filter_buttons.items():
            btn.setChecked(s == status)
        self._load_invoices()
        self.statusBar().showMessage(f"已切换筛选条件: {self.filter_buttons[status].text()}", 2000)

    def _manual_refresh(self):
        # Refresh invoice list and claims dropdown manually, notify status bar.
        self._load_invoices()
        self._load_claims()
        self.statusBar().showMessage("数据已成功刷新！", 3000)

    def _load_all_invoices_clicked(self):
        """User clicked 'Load All' to bypass the first-load limit."""
        self._is_first_load = False
        self._limited_first_load_active = False
        self._limited_first_load_total = 0
        self._load_invoices()

    def _load_invoices(self):
        # Fetch invoices from DB with filter, then apply search/quality filters.
        db_elapsed_ms = 0
        filter_elapsed_ms = 0
        render_elapsed_ms = 0
        if not getattr(self, "db", None) or not self.db.is_open:
            _log.warning("Skipping invoice load because database is closed or unavailable.")
            self.invoices_list = []
            self.table.setRowCount(0)
            self._clear_detail_form()
            return

        prev_id = self.current_invoice.get("id") if getattr(self, "current_invoice", None) else None

        # Determine query limit for first load: if _is_first_load is True and no search text/quick filter is active
        needle = self.txt_search.text().strip().lower() if hasattr(self, "txt_search") else ""
        unlinked_only = self.chk_unlinked.isChecked() if hasattr(self, "chk_unlinked") else False
        needs_fix_only = self.chk_needs_fix.isChecked() if hasattr(self, "chk_needs_fix") else False

        is_default_view = not needle and not unlinked_only and not needs_fix_only
        limit_val = None
        first_load_limited = False
        if self._is_first_load and is_default_view and self.current_filter_status is None:
            limit_val = 100
            first_load_limited = True

        counts = None
        try:
            include_deleted = self.chk_show_deleted.isChecked() if hasattr(self, "chk_show_deleted") else False
            db_start = time.perf_counter()
            display_source = self.db.list_invoices(
                status=self.current_filter_status,
                limit=limit_val,
                include_deleted=include_deleted
            )
            if is_default_view:
                counts = {
                    "all": self.db.count_invoices_for_status(status=None, include_deleted=include_deleted),
                    TO_REVIEW: self.db.count_invoices_for_status(status=TO_REVIEW, include_deleted=include_deleted),
                    APPROVED: self.db.count_invoices_for_status(status=APPROVED, include_deleted=include_deleted),
                    IGNORED: self.db.count_invoices_for_status(status=IGNORED, include_deleted=include_deleted),
                    ERROR: self.db.count_invoices_for_status(status=ERROR, include_deleted=include_deleted),
                }
                count_source = []
            else:
                count_source = self.db.list_invoices(
                    status=None,
                    limit=None,
                    include_deleted=include_deleted,
                )
            db_elapsed_ms = int((time.perf_counter() - db_start) * 1000)
            if self._is_first_load:
                self._is_first_load = False
        except Exception as e:
            _log.error("Failed to load invoices from DB: %s", e)
            QMessageBox.critical(self, "错误", f"加载发票失败: {e}")
            display_source = []
            count_source = []
            counts = None

        filter_start = time.perf_counter()
        displayed_invoices = self._apply_non_status_filters(
            display_source,
            needle,
            unlinked_only,
            needs_fix_only,
        )
        if is_default_view and counts is not None:
            count_filtered_invoices = counts
        else:
            count_filtered_invoices = self._apply_non_status_filters(
                count_source,
                needle,
                unlinked_only,
                needs_fix_only,
            )
        filter_elapsed_ms = int((time.perf_counter() - filter_start) * 1000)

        self.invoices_list = displayed_invoices
        self._update_filter_counts(count_filtered_invoices)

        # Track limited first-load state for UI hints
        total_matching = count_filtered_invoices.get("all", 0) if isinstance(count_filtered_invoices, dict) else len(count_filtered_invoices)
        if first_load_limited and total_matching > len(displayed_invoices):
            self._limited_first_load_active = True
            self._limited_first_load_total = total_matching
            shown = len(displayed_invoices)
            notice = (
                f"首屏已加载最近 {shown} / {total_matching} 张。"
                f"点击\"加载全部\"查看完整列表，或使用搜索/筛选缩小范围。"
            )
            self._first_load_notice = notice
            self.write_log(f"ℹ️ [首屏提示] {notice}")
        else:
            self._limited_first_load_active = False
            self._limited_first_load_total = 0
            self._first_load_notice = None

        # Show/hide the load-all button
        if hasattr(self, "btn_load_all"):
            if self._limited_first_load_active:
                self.btn_load_all.setText(f"加载全部 {self._limited_first_load_total} 张")
                self.btn_load_all.setVisible(True)
            else:
                self.btn_load_all.setVisible(False)

        render_start = time.perf_counter()
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
            self.table.setCurrentItem(None)
            if self.table.selectionModel() is not None:
                self.table.selectionModel().clearCurrentIndex()
            self.table.setRowCount(len(self.invoices_list))
            for idx, inv in enumerate(self.invoices_list):
                inv_num = str(inv.get("invoice_number") or "")
                inv_date = str(inv.get("invoice_date") or "")
                expense_date = str(inv.get("expense_date") or "")
                date_source = str(inv.get("date_source") or "")
                display_date = expense_date or inv_date
                total_amt = str(inv.get("total_amount") or "")
                category = str(inv.get("category") or "未分类")
                seller = str(inv.get("seller_name") or "")
                claim_name = str(inv.get("claim_name") or "")
                attachment_path = str(inv.get("attachment_path") or "")
                display_status = self._get_invoice_display_status(inv)
                source_text = self._get_invoice_source(inv)
                review_status = inv.get("review_status") or TO_REVIEW
                quality = self._get_invoice_quality(inv)
                buyer_check_warning = self._buyer_warning(inv)
                date_warn = get_date_warning(inv)
                combined_warning = ""
                if buyer_check_warning and date_warn:
                    combined_warning = f"{buyer_check_warning}\n{date_warn}"
                elif buyer_check_warning:
                    combined_warning = buyer_check_warning
                elif date_warn:
                    combined_warning = date_warn

                row_items = [
                    display_status,
                    display_date or "—",
                    total_amt or "—",
                    inv_num or "—",
                    seller or "—",
                    category or "未分类",
                    source_text,
                    claim_name or "—",
                ]

                for col, text in enumerate(row_items):
                    item = QTableWidgetItem(text)

                    if col == 2:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    elif col == 0:
                        if display_status == "已通过":
                            item.setForeground(QColor("#059669"))
                        elif display_status == "已忽略":
                            item.setForeground(QColor("#6B7280"))
                        elif display_status == "异常":
                            item.setForeground(QColor("#DC2626"))
                        elif display_status == "待补全":
                            item.setForeground(QColor("#D97706"))
                        elif display_status == "未识别":
                            item.setForeground(QColor("#D97706"))
                        else:
                            item.setForeground(QColor("#D97706"))
                        item.setToolTip(f"审核状态: {review_status}\n数据质量: {quality or '正常'}")
                    elif col == 1:
                        date_source_disp = {
                            "travel_date": "乘车日期",
                            "invoice_date": "开票日期",
                            "legacy": "历史数据",
                            "service_date": "服务日期",
                            "payment_date": "付款日期",
                        }.get(date_source, "未知")
                        tooltip_lines = [
                            f"费用日期: {display_date or '—'}",
                            f"日期来源: {date_source_disp}",
                            f"开票日期: {inv_date or '—'}"
                        ]
                        item.setToolTip("\n".join(tooltip_lines))
                    elif col == 3 and inv_num:
                        item.setToolTip(inv_num)
                    elif col == 4 and seller:
                        item.setToolTip(seller)
                    elif col == 6 and attachment_path:
                        item.setToolTip(attachment_path)
                    elif col == 7 and claim_name:
                        item.setToolTip(claim_name)

                    if combined_warning:
                        item.setBackground(QColor("#FEF3C7"))
                        existing_tip = item.toolTip()
                        item.setToolTip(f"{existing_tip}\n{combined_warning}" if existing_tip else combined_warning)

                    self.table.setItem(idx, col, item)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
            render_elapsed_ms = int((time.perf_counter() - render_start) * 1000)

        if len(self.invoices_list) == 0:
            # Check if total records in DB is 0
            total_in_db = 0
            try:
                total_in_db = self.db.count_invoices(include_deleted=True)
            except Exception:
                pass

            if total_in_db == 0:
                self.lbl_empty_title.setText("当前没有发票记录")
                self.lbl_guide.setText(
                    "您可以执行以下操作以加载发票数据：\n\n"
                    "  1. 点击“导入发票”选择本地文件夹导入 PDF/ZIP 发票；\n"
                    "  2. 点击“配置邮箱”配置您的邮箱，然后点击“扫描邮箱”开始增量同步；\n"
                    "  3. 点击“扫码上传”，用手机上传 PDF/OFD、相册图片或拍照材料。"
                )
                self.lbl_guide.setStyleSheet("color: #6B7280; line-height: 1.5; border: 1px dashed #D1D5DB; padding: 15px; border-radius: 6px; background-color: #F9FAFB;")
                self.lbl_guide.setVisible(True)

                self.empty_btn_import.setVisible(True)
                self.empty_btn_mobile_upload.setVisible(True)
                self.empty_btn_settings.setVisible(True)
                self.empty_btn_scan.setVisible(True)
                self.empty_btn_clear_search.setVisible(False)
                self.empty_btn_reset_filters.setVisible(False)
            else:
                self.lbl_empty_title.setText("当前筛选没有匹配记录")
                self.lbl_guide.setText("请清空搜索词或重置筛选条件。")
                self.lbl_guide.setStyleSheet("color: #6B7280; line-height: 1.5; border: none; padding: 0px; background-color: transparent;")
                self.lbl_guide.setVisible(True)

                self.empty_btn_import.setVisible(False)
                self.empty_btn_mobile_upload.setVisible(False)
                self.empty_btn_settings.setVisible(False)
                self.empty_btn_scan.setVisible(False)
                self.empty_btn_clear_search.setVisible(True)
                self.empty_btn_reset_filters.setVisible(True)

            self.left_stack.setCurrentWidget(self.empty_widget)
            self.current_invoice = None
            self.current_preview_docs = []
            self.current_preview_index = 0
            self._preview_empty_message = "当前筛选没有匹配记录" if total_in_db > 0 else "请选择一张发票查看原件"
            self._update_document_preview()
            self._clear_detail_form()
            self._set_selection_total_status([])
            self._set_right_panel_state(total_in_db > 0)
        else:
            self.left_stack.setCurrentWidget(self.table)
            target_row = -1
            if prev_id is not None:
                for idx, inv in enumerate(self.invoices_list):
                    if inv.get("id") == prev_id:
                        target_row = idx
                        break

            # Clear selection and focus to prevent carryover of multi-selection
            self.table.clearSelection()
            self.table.setCurrentItem(None)
            if self.table.selectionModel() is not None:
                self.table.selectionModel().clearCurrentIndex()

            if target_row == -1 and len(self.invoices_list) > 0:
                target_row = 0
            if target_row != -1:
                self.table.selectRow(target_row)
            self._set_right_panel_state(True)

        # Synchronously refresh the status bar to reflect the current limited-load state,
        # because _on_table_selection_changed uses QTimer.singleShot(0) which may not
        # fire until the next event loop iteration.
        selected = self.table.selectionModel().selectedRows() if hasattr(self, "table") else []
        self._set_selection_total_status(selected)

        self.write_log(
            f"[性能] 发票列表刷新: db={db_elapsed_ms}ms "
            f"filter={filter_elapsed_ms}ms render={render_elapsed_ms}ms "
            f"rows={len(self.invoices_list)}"
        )

    def _load_claims(self):
        """Populate the claim groups dropdown from DB."""
        current_claim_id = self.combo_claims.currentData() if hasattr(self, "combo_claims") else None
        try:
            claims = self.db.list_claim_groups()
        except Exception as e:
            _log.error("Failed to load claim groups from DB: %s", e)
            claims = []

        self.combo_claims.clear()
        for c in claims:
            period = ""
            if c.get("period_start") or c.get("period_end"):
                period = f" [{c.get('period_start')}~{c.get('period_end')}]"
            display_text = f"{c.get('id')}: {c.get('name')}{period}"
            self.combo_claims.addItem(display_text, c.get("id"))
        if current_claim_id is not None:
            idx = self.combo_claims.findData(current_claim_id)
            if idx >= 0:
                self.combo_claims.setCurrentIndex(idx)
        self._update_claim_total()

    def _update_claim_total(self):
        if not hasattr(self, "lbl_claim_total"):
            return
        claim_idx = self.combo_claims.currentIndex() if hasattr(self, "combo_claims") else -1
        if claim_idx < 0:
            self.lbl_claim_total.setText("当前报销组 0 张｜合计 ¥0.00")
            return
        claim_id = self.combo_claims.itemData(claim_idx)
        try:
            invoices = self.db.get_claim_invoices(claim_id)
        except Exception as exc:
            _log.debug("Failed to calculate claim total: %s", exc)
            invoices = []
        self.lbl_claim_total.setText(f"当前报销组 {format_amount_total(invoices)}")

    def _clear_detail_form(self):
        # Reset right hand details form to generic empty/placeholder state.
        self._suspend_dirty_tracking = True
        self.current_invoice = None
        self._invoice_snapshot = None
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

        # Clear summary card
        self.lbl_sum_amount.setText("¥—")
        self.lbl_sum_date.setText("费用日期: —")
        self.lbl_sum_number.setText("发票号码: —")
        self.lbl_sum_seller.setText("销售方: —")
        self.lbl_sum_category.setText("消费类型: —")
        self.lbl_buyer_warning.clear()
        self.lbl_buyer_warning.setVisible(False)
        self.lbl_buyer_warning_hint.setVisible(False)
        self.lbl_date_warning.clear()
        self.lbl_date_warning.setVisible(False)
        self._set_summary_placeholder()
        self.btn_sum_open_file.setEnabled(False)
        self.btn_sum_copy_number.setEnabled(False)
        self.btn_sum_locate_file.setEnabled(False)
        self.txt_buyer.setPlaceholderText("")

        if hasattr(self, "action_copy_number"):
            self.action_copy_number.setEnabled(False)
            self.action_locate_file.setEnabled(False)
            self.action_open_dir.setEnabled(False)

        # Disable fields
        self.txt_number.setEnabled(False)
        self.txt_date.setEnabled(False)
        self.txt_seller.setEnabled(False)
        self.txt_buyer.setEnabled(False)
        self.txt_amount.setEnabled(False)
        self.combo_category.setEnabled(False)
        self.combo_supporting_docs.setEnabled(False)
        self.txt_note.setEnabled(False)
        self.btn_save_draft.setEnabled(False)
        self.lbl_dirty_hint.setText("未修改")
        self.btn_open_file.setEnabled(False)

        self.lbl_batch_hint.setText("请选择一个发票记录")
        self.btn_app.setEnabled(False)
        self.btn_ign.setEnabled(False)
        self.btn_err.setEnabled(False)
        self.btn_rev.setEnabled(False)
        self.btn_inline_more.setEnabled(False)
        self._suspend_dirty_tracking = False

        if hasattr(self, "lbl_closing_desc"):
            self.lbl_closing_desc.setText("请选择发票以查看建议")

    def _format_status_count_prefix(self) -> str:
        """Return the leading count segment for the status bar, reflecting limited-load state."""
        shown = len(self.invoices_list)
        if self._limited_first_load_active and self._limited_first_load_total > shown:
            return f"当前显示 {shown} / {self._limited_first_load_total} 张｜首屏限量加载"
        return f"当前筛选 {shown} 张"

    def _set_selection_total_status(self, selected_indexes):
        if not selected_indexes:
            prefix = self._format_status_count_prefix()
            self.lbl_status_left.setText(f"{prefix}｜未选择发票｜最近操作：系统就绪")
            return

        def calculate_async():
            # Ensure index still valid
            if not hasattr(self, "invoices_list") or not self.invoices_list:
                return
            rows = []
            for idx in selected_indexes:
                try:
                    if 0 <= idx.row() < len(self.invoices_list):
                        rows.append(self.invoices_list[idx.row()])
                except Exception:
                    pass
            if not rows:
                return
            prefix = self._format_status_count_prefix()
            count, total, has_missing = amount_total(rows)
            suffix = "｜部分金额缺失" if has_missing else ""
            self.lbl_status_left.setText(f"{prefix}｜已选中 {count} 张｜合计 ¥{total:.2f}{suffix}")

        QTimer.singleShot(0, calculate_async)

    def _update_closing_card(self, inv):
        if not inv:
            if hasattr(self, "lbl_closing_desc"):
                self.lbl_closing_desc.setText("请选择发票以查看建议")
            return
        inv_num = str(inv.get("invoice_number") or "").strip()
        inv_date = str(inv.get("expense_date") or inv.get("invoice_date") or "").strip()
        seller = str(inv.get("seller_name") or "").strip()
        total_amt = str(inv.get("total_amount") or "").strip()
        status = inv.get("review_status") or "to_review"

        if hasattr(self, "lbl_closing_desc"):
            if not inv_num or not inv_date or not seller or not total_amt:
                desc = "⚠️ 关键字段缺失，请在上方表单中补全。"
            elif status == "to_review":
                desc = "💡 字段已完整，确认无误后即可通过审核。"
            elif status == "approved":
                desc = "✅ 已通过 ｜ 可加入报销组"
            elif status == "ignored":
                desc = "ℹ️ 已忽略 ｜ 不参与报销"
            elif status == "error":
                desc = "❌ 异常发票 ｜ 需核对"
            else:
                desc = "💡 字段已完整，确认无误后即可通过审核。"

            if str(inv.get("confirmed_note") or "").strip():
                desc += " ｜ 已填个人备注"
            self.lbl_closing_desc.setText(desc)

    def _on_table_selection_changed(self):
        # Triggered when users select table rows. Handles single and multi-selection modes.
        selected_indexes = self.table.selectionModel().selectedRows()
        num_selected = len(selected_indexes)

        if num_selected == 0:
            self._preview_empty_message = "请选择一张发票查看原件"
            self._clear_detail_form()
            self._set_selection_total_status([])
            self.current_preview_docs = []
            self.current_preview_index = 0
            self._update_document_preview()
            return

        self._set_selection_total_status(selected_indexes)

        self.btn_app.setEnabled(True)
        self.btn_ign.setEnabled(True)
        self.btn_err.setEnabled(True)
        self.btn_rev.setEnabled(True)
        self.btn_inline_more.setEnabled(True)

        if hasattr(self, "action_inline_delete") and num_selected > 0:
            first_inv = self.invoices_list[selected_indexes[0].row()]
            if first_inv.get("is_deleted") == 1:
                self.action_inline_delete.setText("恢复发票")
            else:
                self.action_inline_delete.setText("删除发票")

        if hasattr(self, "btn_delete_invoice") and num_selected > 0:
            first_inv = self.invoices_list[selected_indexes[0].row()]
            if first_inv.get("is_deleted") == 1:
                self.btn_delete_invoice.setText("🔄 恢复发票")
                self.btn_delete_invoice.setStyleSheet("background-color: #F0FDF4; color: #16A34A; border: 1px solid #86EFAC; padding: 6px; font-weight: bold; border-radius: 4px;")
            else:
                self.btn_delete_invoice.setText("🗑️ 删除发票")
                self.btn_delete_invoice.setStyleSheet("background-color: #FEF2F2; color: #DC2626; border: 1px solid #FCA5A5; padding: 6px; font-weight: bold; border-radius: 4px;")

        if num_selected == 1:
            row_idx = selected_indexes[0].row()
            inv = self.invoices_list[row_idx]
            self.current_invoice = inv
            self._suspend_dirty_tracking = True

            # Fetch core values
            inv_id = str(inv.get("id", ""))
            inv_num = str(inv.get("invoice_number") or "")
            inv_date = str(inv.get("invoice_date") or "")
            expense_date = str(inv.get("expense_date") or "")
            date_source = str(inv.get("date_source") or "")
            display_date = expense_date or inv_date
            seller = str(inv.get("seller_name") or "")
            buyer = str(inv.get("buyer_name") or "")
            total_amt = str(inv.get("total_amount") or "")
            category = str(inv.get("category") or "未分类")
            status = inv.get("review_status") or "to_review"
            att_path = str(inv.get("attachment_path") or "")

            # Populate text inputs
            self.txt_id.setText(inv_id)
            self.txt_number.setText(inv_num)
            self.txt_date.setText(display_date)
            self.txt_invoice_date.setText(inv_date)
            date_source_disp = {
                "travel_date": "乘车日期",
                "invoice_date": "开票日期",
                "legacy": "历史数据",
                "service_date": "服务日期",
                "payment_date": "付款日期",
            }.get(date_source, date_source)
            self.txt_date_source.setText(date_source_disp)
            self.txt_seller.setText(seller)
            self.txt_buyer.setText(buyer)
            self.txt_amount.setText(total_amt)
            self.combo_category.setCurrentText(category)
            self.txt_subject.setText(str(inv.get("mail_subject") or ""))
            self.txt_item_name.setText(str(inv.get("item_name") or ""))
            mail_uid = inv.get("mail_uid")
            download_url = str(inv.get("download_url") or "").strip()
            if not att_path and (mail_uid is not None or download_url):
                self.txt_path.setText("未下载原件（可重试下载或手动补原件）")
                self.txt_path.setToolTip("请点击右侧按钮重新尝试自动下载，或者人工补全发票原件文件。")
            else:
                self.txt_path.setText(Path(att_path).name if att_path else "")
                self.txt_path.setToolTip(att_path)

            has_file = bool(att_path)
            self.btn_open_file.setEnabled(has_file)

            has_url = bool(download_url)
            self.btn_retry_download.setEnabled(not has_file and has_url)
            self.btn_retry_download.setVisible(has_url)
            self.btn_add_attachment.setEnabled(True)

            self.txt_full_path.setText(att_path)
            self.txt_full_path.setToolTip(att_path)
            self.txt_url.setText(_mask_url(inv.get("download_url") or ""))
            self._update_supporting_docs_selector(inv)

            note_content = str(inv.get("confirmed_note") or "").strip()
            self.txt_note.setPlainText(note_content)
            has_note = bool(note_content)
            self.txt_note.setVisible(has_note)
            if hasattr(self, "btn_toggle_note"):
                self.btn_toggle_note.setText("个人备注 -" if has_note else "个人备注 +")

            # Update summary card
            self.lbl_sum_amount.setText(self._format_amount_display(total_amt))
            self.lbl_sum_date.setText(f"费用日期: {display_date}" if display_date else "费用日期: —")
            self.lbl_sum_number.setText(f"发票号码: {inv_num}" if inv_num else "发票号码: —")
            self.lbl_sum_seller.setText(f"销售方: {seller}" if seller else "销售方: —")
            self.lbl_sum_category.setText(f"消费类型: {category or '未分类'}")

            buyer_check_warning = self._buyer_warning(inv)
            if buyer_check_warning == "购方抬头不匹配，可能导致退单":
                self.lbl_buyer_warning.setText("抬头不匹配")
                cfg = load_config_safe()
                expected = str(cfg.get("reimbursement", {}).get("buyer_name") or "").strip()
                self.lbl_buyer_warning.setToolTip(f"期望抬头：{expected}\n实际抬头：{buyer}")
                self.lbl_buyer_warning.setVisible(True)
            else:
                self.lbl_buyer_warning.setVisible(False)

            self.lbl_buyer_warning_hint.setVisible(False)

            if not buyer.strip():
                self.txt_buyer.setPlaceholderText("待补全")
            else:
                self.txt_buyer.setPlaceholderText("")

            date_warn = get_date_warning(inv)
            self.lbl_date_warning.setText(date_warn)
            self.lbl_date_warning.setVisible(bool(date_warn))
            self._update_status_badge(status)

            self.btn_sum_open_file.setEnabled(bool(att_path))
            self.btn_sum_copy_number.setEnabled(bool(inv_num))
            self.btn_sum_locate_file.setEnabled(bool(att_path))

            if hasattr(self, "action_copy_number"):
                has_num = bool(inv_num)
                has_att = bool(att_path)
                self.action_copy_number.setEnabled(has_num)
                self.action_locate_file.setEnabled(has_att)
                self.action_open_dir.setEnabled(has_att)

            self.txt_number.setEnabled(True)
            self.txt_date.setEnabled(True)
            self.txt_seller.setEnabled(True)
            self.txt_buyer.setEnabled(True)
            self.txt_amount.setEnabled(True)
            self.combo_category.setEnabled(True)
            self.txt_note.setEnabled(True)
            self.btn_open_file.setEnabled(bool(att_path))
            self.lbl_batch_hint.setText("已选择 1 张发票")

            self._invoice_snapshot = self._get_invoice_snapshot(inv)
            self._suspend_dirty_tracking = False
            self._update_save_button_state()
            self.lbl_dirty_hint.setText("未修改")

            if hasattr(self, "lbl_closing_desc"):
                self._update_closing_card(inv)

            # Update preview documents
            from .helpers import resolve_invoice_documents_with_evidence
            self.current_preview_docs = resolve_invoice_documents_with_evidence(inv, self.db, RUNTIME_DIR)
            self.current_preview_index = 0
            self._preview_empty_message = "当前发票没有可预览的原件"
            if self.current_preview_docs:
                self._preview_empty_message = "请选择一张发票查看原件"
            self._update_document_preview()
        else:
            self._preview_empty_message = "已选择多张发票，请选择单张查看原件"
            self._clear_detail_form()
            self.btn_app.setEnabled(True)
            self.btn_ign.setEnabled(True)
            self.btn_err.setEnabled(True)
            self.btn_rev.setEnabled(True)
            self.btn_inline_more.setEnabled(True)
            self.lbl_batch_hint.setText(f"已选择 {num_selected} 张发票，可批量处理")
            self.current_preview_docs = []
            self.current_preview_index = 0
            self.lbl_file_info.setText("0 / 0 无文件")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.btn_open_ext.setEnabled(False)
            self._show_preview_status(self._preview_empty_message)
            if hasattr(self, "lbl_closing_desc"):
                self.lbl_closing_desc.setText("已选中多张发票，请使用下方或右键菜单进行批量操作。")

    def _show_table_context_menu(self, pos):
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        menu = QMenu(self)

        # Check if all selected are deleted
        all_deleted = True
        for idx in selected_indexes:
            inv = self.invoices_list[idx.row()]
            if inv.get("is_deleted") != 1:
                all_deleted = False
                break

        if all_deleted:
            action_restore = menu.addAction("🔄 恢复发票")
            action_restore.triggered.connect(self._restore_selected_invoices)
        else:
            # Multi-select friendly claim linking options
            claim_idx = self.combo_claims.currentIndex()
            if claim_idx >= 0:
                claim_name = self.combo_claims.currentText()
                action_link = menu.addAction(f"🔗 关联到当前报销组: {claim_name}")
                action_link.triggered.connect(self._link_invoices_to_claim)

                action_unlink = menu.addAction("🔓 从当前报销组取消关联")
                action_unlink.triggered.connect(self._unlink_selected_invoices)
                menu.addSeparator()

            # Batch review status configuration submenu
            menu_status = menu.addMenu("🎯 批量设置审核状态")
            action_app = menu_status.addAction("🟢 已通过")
            action_app.triggered.connect(lambda: self._set_selected_status(APPROVED))
            action_ign = menu_status.addAction("⚪ 已忽略")
            action_ign.triggered.connect(lambda: self._set_selected_status(IGNORED))
            action_err = menu_status.addAction("🔴 异常")
            action_err.triggered.connect(lambda: self._set_selected_status(ERROR))
            action_rev = menu_status.addAction("🟠 待审核")
            action_rev.triggered.connect(lambda: self._set_selected_status(TO_REVIEW))
            menu.addSeparator()

            action_reparse = menu.addAction("🔄 重新解析发票")
            action_reparse.triggered.connect(self._reparse_selected_invoices)
            action_redownload = menu.addAction("📥 重新下载发票")
            action_redownload.triggered.connect(self._redownload_selected_invoices)
            menu.addSeparator()
            action_delete = menu.addAction("🗑️ 删除发票")
            action_delete.triggered.connect(self._delete_selected_invoices)

        menu.exec(self.table.mapToGlobal(pos))

    def _reparse_selected_invoices(self):
        """Reparse PDF metadata in-place for selected invoices, updating DB values."""
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        count = len(selected_indexes)
        success_count = 0
        missing_files = []
        parse_failed_files = []
        duplicate_conflicts = []

        from ..invoice_parser import InvoiceParser
        parser = InvoiceParser()

        # Load categories for metadata classification
        categories = self.config.get("categories", {})

        for idx in selected_indexes:
            inv = self.invoices_list[idx.row()]
            inv_id = inv.get("id")
            attachment_path = inv.get("attachment_path")

            if not attachment_path:
                missing_files.append(f"发票 ID {inv_id}: 无附件文件记录")
                continue

            file_path = self._resolve_attachment_path(attachment_path)
            if not file_path or not file_path.exists():
                missing_files.append(f"发票 ID {inv_id}: 文件不存在 ({attachment_path})")
                continue

            # Run PDF parser
            try:
                info = parser.parse_pdf(str(file_path))
                if info.parse_success:
                    # Classify category and extra fields based on new seller name/original name
                    from ..__main__ import _classify
                    category, extra_type, extra_required = _classify(
                        file_path.name, "local import", info.seller_name, categories
                    )

                    duplicate = self.db.find_invoice_by_unique_fields(
                        info.invoice_number,
                        info.total_amount,
                        info.seller_name,
                    )
                    repair_target_id = inv_id
                    if duplicate and duplicate.get("id") != inv_id:
                        duplicate_claim_count = self.db.count_claim_links(int(duplicate["id"]))
                        if duplicate_claim_count == 0:
                            if self.db.delete_invoice_permanently(int(duplicate["id"])):
                                duplicate_conflicts.append(
                                    f"发票 ID {inv_id}: 已删除旧重复记录 ID {duplicate.get('id')}"
                                )
                                self.write_log(
                                    f"🔁 [重新解析] 发票 ID {inv_id} 命中旧重复记录 ID {duplicate.get('id')}，已删除旧记录并修复当前记录"
                                )
                            else:
                                duplicate_conflicts.append(
                                    f"发票 ID {inv_id}: 发现重复记录 ID {duplicate.get('id')}，但无法清理旧记录"
                                )
                                self.write_log(
                                    f"⚠️ [重新解析] 发票 ID {inv_id} 命中重复记录 ID {duplicate.get('id')}，旧记录清理失败"
                                )
                        else:
                            repair_target_id = int(duplicate["id"])
                            self.write_log(
                                f"🔁 [重新解析] 发票 ID {inv_id} 命中已关联报销组的重复记录 ID {duplicate.get('id')}，改为更新该主记录"
                            )

                    # Update database in-place
                    updated = self.db.update_invoice_parsed_metadata(
                        invoice_id=repair_target_id,
                        invoice_number=info.invoice_number,
                        invoice_code=info.invoice_code,
                        invoice_date=info.invoice_date,
                        amount=info.amount,
                        total_amount=info.total_amount,
                        seller_name=info.seller_name,
                        buyer_name=info.buyer_name,
                        invoice_type=info.invoice_type or inv.get("invoice_type") or "电子发票",
                        category=category,
                        has_extra=inv.get("has_extra") or False,
                        extra_type=extra_type,
                        missing_extra=extra_required,
                        parse_success=True,
                        parse_note=info.parse_note or "重新解析",
                        item_name=getattr(info, "item_name", ""),
                        expense_date=getattr(info, "expense_date", ""),
                        date_source=getattr(info, "date_source", ""),
                    )
                    if updated:
                        if repair_target_id != inv_id:
                            self.db.soft_delete_invoice(inv_id)
                            self.write_log(
                                f"✅ [重新解析] 发票 ID {inv_id} 已合并到主记录 ID {repair_target_id}"
                            )
                        else:
                            self.write_log(f"✅ [重新解析] 发票 ID {inv_id} 已更新解析结果")
                        success_count += 1
                    elif getattr(self.db, "last_error", "") == "unique_conflict":
                        duplicate_conflicts.append(
                            f"发票 ID {inv_id}: 解析结果与已有发票唯一键冲突"
                        )
                        self.write_log(
                            f"⚠️ [重新解析] 发票 ID {inv_id} 与已有发票重复，未覆盖当前记录"
                        )
                    else:
                        parse_failed_files.append(f"发票 ID {inv_id}: 解析结果写入失败 ({info.parse_note})")
                else:
                    parse_failed_files.append(f"发票 ID {inv_id}: 解析失败 ({info.parse_note})")
            except Exception as e:
                parse_failed_files.append(f"发票 ID {inv_id}: 异常 ({str(e)})")

        # Reload data
        self._load_invoices()
        self._load_claims()
        self._on_table_selection_changed()

        # Build notification message
        msg = f"已完成 {count} 张发票的重新解析流程！\n\n成功重新解析并更新: {success_count} 张"
        if missing_files:
            msg += f"\n\n以下发票的本地文件不存在:\n" + "\n".join(missing_files[:10])
            if len(missing_files) > 10:
                msg += f"\n... 以及其他 {len(missing_files)-10} 个文件"
        if duplicate_conflicts:
            msg += f"\n\n以下发票已处理重复记录:\n" + "\n".join(duplicate_conflicts[:10])
            if len(duplicate_conflicts) > 10:
                msg += f"\n... 以及其他 {len(duplicate_conflicts)-10} 个重复项"
        if parse_failed_files:
            msg += f"\n\n以下发票解析失败:\n" + "\n".join(parse_failed_files[:10])
            if len(parse_failed_files) > 10:
                msg += f"\n... 以及其他 {len(parse_failed_files)-10} 个文件"

        QMessageBox.information(self, "重新解析结果", msg)
        self.write_log(
            f"🔄 [重新解析] 完成。成功: {success_count}, 重复处理: {len(duplicate_conflicts)}, "
            f"缺失文件: {len(missing_files)}, 失败: {len(parse_failed_files)}"
        )

    def _redownload_selected_invoices(self):
        """Redownload invoice PDFs from remote download URL using Playwright browser."""
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        count = len(selected_indexes)
        success_count = 0
        no_url_count = 0
        failed_count = 0
        download_failed_files = []
        reread_count = 0
        reread_success_count = 0
        reread_failed_count = 0

        from ..attachment_handler import AttachmentHandler
        from ..config import get_email_accounts
        from ..credentials import get_auth_code, has_auth_code
        from ..invoice_parser import InvoiceParser
        from ..link_downloader import LinkDownloader
        from ..mail_fetcher import MailFetcher
        from ..__main__ import _handle_pending_email

        try:
            downloader = LinkDownloader(download_dir=RUNTIME_DIR / "attachments")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动下载引擎失败: {e}")
            return

        parser = InvoiceParser()
        att_handler = AttachmentHandler(RUNTIME_DIR / "attachments")
        cfg = self.config or load_config_safe()
        categories = cfg.get("categories", {})
        accounts = get_email_accounts(cfg)
        default_account = {
            "mailbox_key": "legacy",
            "address": cfg.get("email", {}).get("address", ""),
            "auth_code": "",
            "imap": cfg.get("imap", {}),
            "search": cfg.get("search", {}),
        }
        account_map = {str(account.get("mailbox_key") or "legacy"): account for account in accounts}
        mail_fetchers: dict[str, tuple[MailFetcher, object]] = {}

        def ensure_mail_fetcher(mailbox_key: str):
            key = str(mailbox_key or "legacy")
            cached = mail_fetchers.get(key)
            if cached is not None:
                return cached[0]

            account = account_map.get(key, default_account)
            email_addr = str(account.get("address") or "")
            if not email_addr or email_addr == "your_email@qq.com":
                raise ValueError("请先在[设置]中配置邮箱账号")
            if not has_auth_code(email_addr):
                raise ValueError(f"邮箱账号 {email_addr} 未配置授权码，请先在[设置]中配置")

            auth_code = get_auth_code(email_addr)
            imap_cfg = account.get("imap") or cfg.get("imap", {})
            self.write_log(f"📥 [重新下载] 连接 IMAP {email_addr} ...")
            mail_fetcher_cm = MailFetcher(
                address=email_addr,
                auth_code=auth_code,
                server=imap_cfg.get("server", "imap.qq.com"),
                port=imap_cfg.get("port", 993),
            )
            mail_fetcher = mail_fetcher_cm.__enter__()
            mail_fetchers[key] = (mail_fetcher, mail_fetcher_cm)
            return mail_fetcher

        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.statusBar().showMessage("正在启动下载引擎并获取发票文件...")
        QApplication.processEvents()

        try:
            for idx in selected_indexes:
                inv = self.invoices_list[idx.row()]
                inv_id = inv.get("id")
                download_url = str(inv.get("download_url") or "")
                mail_uid = inv.get("mail_uid")
                mail_date = inv.get("mail_date") or inv.get("invoice_date") or "unknown_date"

                direct_download_ok = False
                fallback_reason = ""

                if download_url:
                    try:
                        dl = downloader._download_url(download_url, mail_uid or 0, inv_id, mail_date)
                        if dl and dl.file_path and os.path.exists(dl.file_path):
                            info = parser.parse_pdf(dl.file_path)
                            if info.parse_success:
                                from ..__main__ import _classify, _rename_by_invoice_code
                                cat, extra_type, extra_req = _classify(
                                    inv.get("mail_subject") or "",
                                    inv.get("mail_sender") or "",
                                    info.seller_name,
                                    categories,
                                )
                                code = info.invoice_code or info.invoice_number
                                att_path = _rename_by_invoice_code(
                                    dl.file_path,
                                    code,
                                    info.invoice_date or mail_date,
                                    RUNTIME_DIR / "attachments",
                                    category=cat,
                                    total_amount=info.total_amount,
                                    invoice_number=info.invoice_number,
                                    source_mode="reprocess",
                                )
                                updated = self.db.update_invoice_parsed_metadata(
                                    invoice_id=inv_id,
                                    invoice_number=info.invoice_number,
                                    invoice_code=info.invoice_code,
                                    invoice_date=info.invoice_date,
                                    amount=info.amount,
                                    total_amount=info.total_amount,
                                    seller_name=info.seller_name,
                                    buyer_name=info.buyer_name,
                                    invoice_type=info.invoice_type or inv.get("invoice_type") or "电子发票",
                                    category=cat,
                                    has_extra=inv.get("has_extra") or False,
                                    extra_type=extra_type,
                                    missing_extra=extra_req,
                                    parse_success=True,
                                    parse_note="重新下载后解析",
                                    item_name=getattr(info, "item_name", ""),
                                    expense_date=getattr(info, "expense_date", ""),
                                    date_source=getattr(info, "date_source", ""),
                                )
                                if not updated:
                                    if getattr(self.db, "last_error", "") == "unique_conflict":
                                        fallback_reason = "解析结果与已有发票唯一键冲突"
                                        self.write_log(
                                            f"⚠️ [重新下载] 发票 ID {inv_id} 更新元数据时发生唯一键冲突，尝试回读邮件"
                                        )
                                    else:
                                        fallback_reason = "解析结果写入数据库失败"
                                else:
                                    self.db._conn.execute(
                                        "UPDATE invoices SET attachment_path = ? WHERE id = ?",
                                        (att_path, inv_id),
                                    )
                                    self.db._conn.commit()
                                    success_count += 1
                                    direct_download_ok = True
                                    self.write_log(f"✅ [重新下载] 发票 ID {inv_id} 链接下载成功")
                            else:
                                fallback_reason = f"链接下载后解析失败: {info.parse_note}"
                                if os.path.exists(dl.file_path):
                                    os.remove(dl.file_path)
                        else:
                            fallback_reason = "下载超时或链接失效"
                    except Exception as e:
                        fallback_reason = f"链接下载异常: {e}"

                if direct_download_ok:
                    continue

                if not mail_uid:
                    no_url_count += 1
                    failed_count += 1
                    failure_detail = fallback_reason or "无邮件 UID，无法重新读取邮件"
                    download_failed_files.append(f"发票 ID {inv_id}: {failure_detail}")
                    self.write_log(f"❌ [重新下载] 发票 ID {inv_id} {failure_detail}")
                    continue

                reread_count += 1
                if not download_url:
                    no_url_count += 1

                try:
                    mailbox_key = str(inv.get("mailbox_key") or "legacy")
                    account = account_map.get(mailbox_key, default_account)
                    mailbox_folder = account.get("search", {}).get("folder", "INBOX")
                    fetcher = ensure_mail_fetcher(mailbox_key)
                    self.write_log(
                        f"↩️ [重新下载] 发票 ID {inv_id} {fallback_reason or '无下载链接'}，改为重新读取邮件 UID={mail_uid}"
                    )
                    reread_ok = _handle_pending_email(
                        row={"uid": mail_uid, "mail_date": mail_date, "mailbox_key": mailbox_key},
                        fetcher=fetcher,
                        folder=mailbox_folder,
                        att_handler=att_handler,
                        parser=parser,
                        link_dl=downloader,
                        db=self.db,
                        categories=categories,
                    )
                    if reread_ok:
                        success_count += 1
                        reread_success_count += 1
                        self.write_log(f"✅ [重新下载] 发票 ID {inv_id} 已通过重新读取邮件修复")
                        continue

                    reread_failed_count += 1
                    failed_count += 1
                    download_failed_files.append(f"发票 ID {inv_id}: 重新读取邮件后仍未成功入库")
                    self.write_log(f"⚠️ [重新下载] 发票 ID {inv_id} 重新读取邮件后仍未成功入库")
                except Exception as e:
                    reread_failed_count += 1
                    failed_count += 1
                    download_failed_files.append(f"发票 ID {inv_id}: 重新读取邮件失败 ({str(e)})")
                    self.write_log(f"❌ [重新下载] 发票 ID {inv_id} 重新读取邮件失败: {e}")
        finally:
            downloader.close()
            for _, mail_fetcher_cm in mail_fetchers.values():
                mail_fetcher_cm.__exit__(None, None, None)
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()

        self._load_invoices()
        self._load_claims()
        self._on_table_selection_changed()

        msg = f"已完成 {count} 张发票的重新下载流程！\n\n成功处理: {success_count} 张"
        if reread_count:
            msg += (
                f"\n\n其中 {reread_count} 张需要重新读取邮件，"
                f"成功修复 {reread_success_count} 张，失败 {reread_failed_count} 张。"
            )
        if no_url_count:
            msg += f"\n\n{no_url_count} 张没有直接下载链接，已尝试从邮件重新读取。"
        if download_failed_files:
            msg += f"\n\n以下发票仍然失败:\n" + "\n".join(download_failed_files[:10])
            if len(download_failed_files) > 10:
                msg += f"\n... 以及其他 {len(download_failed_files)-10} 个文件"

        QMessageBox.information(self, "重新下载结果", msg)
        self.write_log(
            f"📥 [重新下载] 完成。成功: {success_count}, 回读邮件: {reread_success_count}/{reread_count}, 失败: {failed_count}"
        )

    def _delete_selected_invoices(self):
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        count = len(selected_indexes)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除选中的 {count} 张发票吗？\n删除后发票将不会显示在列表中，但保留数据库恢复能力。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        success_count = 0
        for idx in selected_indexes:
            inv = self.invoices_list[idx.row()]
            inv_id = inv.get("id")
            if inv_id and self.db.soft_delete_invoice(inv_id):
                success_count += 1

        self.write_log(f"🗑️ [删除发票] 成功删除 {success_count}/{count} 张发票。")
        self.statusBar().showMessage(f"成功删除 {success_count} 张发票", 4000)
        self._load_invoices()
        self._load_claims()

    def _restore_selected_invoices(self):
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        count = len(selected_indexes)
        success_count = 0
        for idx in selected_indexes:
            inv = self.invoices_list[idx.row()]
            inv_id = inv.get("id")
            if inv_id and self.db.restore_invoice(inv_id):
                success_count += 1

        self.write_log(f"🔄 [恢复发票] 成功恢复 {success_count}/{count} 张发票。")
        self.statusBar().showMessage(f"成功恢复 {success_count} 张发票", 4000)
        self._load_invoices()
        self._load_claims()

    def _handle_detail_delete_clicked(self):
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return
        first_inv = self.invoices_list[selected_indexes[0].row()]
        if first_inv.get("is_deleted") == 1:
            self._restore_selected_invoices()
        else:
            self._delete_selected_invoices()

    def _open_local_path(self, path):
        """Open a local directory or file path using QDesktopServices safely."""
        success = False
        try:
            success = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as e:
            _log.error("Failed to open local path using QDesktopServices: %s", e)

        if not success:
            try:
                import os
                if hasattr(os, "startfile"):
                    os.startfile(str(path))
            except Exception as ex:
                _log.error("Failed to open local path fallback startfile: %s", ex)

    def _resolve_attachment_path(self, attachment_path: str) -> Path | None:
        """Resolve a DB-stored attachment path to a real local file path."""
        if not attachment_path:
            return None
        return resolve_stored_path(attachment_path, RUNTIME_DIR)

    def _open_attachment(self):
        """Open attachment file locally using system default viewer safely."""
        if not self.current_invoice or not self.current_invoice.get("attachment_path"):
            return
        attachment_path = str(self.current_invoice.get("attachment_path") or "")
        file_path = self._resolve_attachment_path(attachment_path)
        if not file_path:
            return

        if not file_path.exists():
            QMessageBox.warning(
                self,
                "警告",
                f"文件不存在于路径:\n{file_path}\n\n原始记录:\n{attachment_path}",
            )
            return

        self._open_local_path(file_path)
        self.statusBar().showMessage(f"已成功加载本地附件: {file_path.name}", 2000)

    def _add_attachment_manually(self):
        if not self.current_invoice:
            return

        inv_id = self.current_invoice["id"]
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择发票原件",
            "",
            "发票文件 (*.pdf *.ofd *.png *.jpg *.jpeg);;所有文件 (*.*)"
        )
        if not file_path:
            return

        try:
            src_file = Path(file_path)
            ext = src_file.suffix.lower()

            inv_num = self.current_invoice.get("invoice_number") or ""
            inv_code = self.current_invoice.get("invoice_code") or ""
            code = inv_code or inv_num
            date_str = self.current_invoice.get("invoice_date") or self.current_invoice.get("mail_date") or "unknown_date"

            if "-" in date_str:
                date_dir_name = date_str[:10]
            else:
                date_dir_name = "unknown_date"

            dest_dir = RUNTIME_DIR / "attachments" / date_dir_name
            dest_dir.mkdir(parents=True, exist_ok=True)

            if code:
                dest_name = f"{code}{ext}"
            else:
                dest_name = f"manual_{inv_id}{ext}"

            dest_path = dest_dir / dest_name
            if dest_path.exists():
                stem = dest_path.stem
                for n in range(1, 100):
                    cand = dest_dir / f"{stem}_{n}{ext}"
                    if not cand.exists():
                        dest_path = cand
                        break

            import shutil
            shutil.copy2(src_file, dest_path)

            h = hashlib.sha256()
            with open(dest_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            file_hash_val = h.hexdigest()

            rel_path = f"attachments/{date_dir_name}/{dest_path.name}"

            # Update DB
            self.db.update_invoice_file_paths(inv_id, attachment_path=rel_path, file_hash=file_hash_val)

            # Update memory state
            self.current_invoice["attachment_path"] = rel_path
            self.current_invoice["file_hash"] = file_hash_val

            # Refresh GUI and preview
            self._update_detail_fields(self.current_invoice)
            self.current_preview_docs = resolve_invoice_documents_with_evidence(self.current_invoice, self.db, RUNTIME_DIR)
            self.current_preview_index = 0
            self._update_document_preview()
            self._load_invoices()

            _log.info("用户手动补齐发票原件: invoice_id=%s, filename=%s", inv_id, dest_path.name)
            self.statusBar().showMessage("手动补齐原件成功", 3000)

        except Exception as e:
            _log.error("手动补齐原件失败: %s", e)
            QMessageBox.critical(self, "错误", f"补齐原件失败: {e}")

    def _retry_download_link(self):
        if not self.current_invoice:
            return

        url = self.current_invoice.get("download_url") or ""
        if not url.strip():
            return

        from PySide6.QtWidgets import QProgressDialog, QMessageBox
        progress = QProgressDialog("正在从链接尝试下载发票文件...", "取消", 0, 0, self)
        progress.setWindowTitle("下载引擎")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        progress.setValue(0)
        QApplication.processEvents()

        from ..link_downloader import LinkDownloader
        import shutil

        inv_id = self.current_invoice["id"]
        mail_uid = self.current_invoice.get("mail_uid") or 0
        date_str = self.current_invoice.get("invoice_date") or self.current_invoice.get("mail_date") or "unknown_date"

        if "-" in date_str:
            date_dir_name = date_str[:10]
        else:
            date_dir_name = "unknown_date"

        success = False
        try:
            downloader = LinkDownloader(download_dir=RUNTIME_DIR / "attachments")
            res = downloader._download_url(url, mail_uid, 999, date_dir_name)
            if res and res.file_path and os.path.exists(res.file_path):
                src_path = Path(res.file_path)
                ext = src_path.suffix.lower()

                inv_num = self.current_invoice.get("invoice_number") or ""
                inv_code = self.current_invoice.get("invoice_code") or ""
                code = inv_code or inv_num

                dest_dir = RUNTIME_DIR / "attachments" / date_dir_name
                if code:
                    dest_name = f"{code}{ext}"
                else:
                    dest_name = f"downloaded_{inv_id}{ext}"

                dest_path = dest_dir / dest_name
                if dest_path.resolve() != src_path.resolve():
                    if dest_path.exists():
                        stem = dest_path.stem
                        for n in range(1, 100):
                            cand = dest_dir / f"{stem}_{n}{ext}"
                            if not cand.exists():
                                dest_path = cand
                                break
                    shutil.move(src_path, dest_path)

                h = hashlib.sha256()
                with open(dest_path, "rb") as f:
                    while chunk := f.read(8192):
                        h.update(chunk)
                file_hash_val = h.hexdigest()

                rel_path = f"attachments/{date_dir_name}/{dest_path.name}"

                self.db.update_invoice_file_paths(inv_id, attachment_path=rel_path, file_hash=file_hash_val)
                if getattr(res, "parse_note", None):
                    self.db.update_invoice_missing_fields(inv_id, {"parse_note": res.parse_note}, only_if_empty=False)

                self.current_invoice["attachment_path"] = rel_path
                self.current_invoice["file_hash"] = file_hash_val
                if getattr(res, "parse_note", None):
                    self.current_invoice["parse_note"] = res.parse_note

                success = True

            downloader.close()
        except Exception as e:
            _log.error("重试下载发生错误: %s", e)

        progress.close()

        if success:
            QMessageBox.information(self, "成功", "发票原件下载并关联成功！")
            self._update_detail_fields(self.current_invoice)
            self.current_preview_docs = resolve_invoice_documents_with_evidence(self.current_invoice, self.db, RUNTIME_DIR)
            self.current_preview_index = 0
            self._update_document_preview()
            self._load_invoices()
        else:
            QMessageBox.warning(self, "下载失败", "未能从链接获取官方 PDF/OFD，请尝试人工补齐原件文件。")

    def _open_extra_docs(self):
        """Open the currently selected extra/unassociated supporting doc."""
        if not self.current_invoice:
            return

        if not hasattr(self, "supporting_doc_items") or not self.supporting_doc_items:
            QMessageBox.information(self, "提示", "未找到可供查看的证明材料文件。")
            return

        idx = self.combo_supporting_docs.currentIndex()
        if idx < 0 or idx >= len(self.supporting_doc_items):
            QMessageBox.information(self, "提示", "未找到可供查看的证明材料文件。")
            return

        item = self.supporting_doc_items[idx]
        file_path = item["path"]

        if file_path and file_path.exists():
            self._open_local_path(file_path)
            self.statusBar().showMessage(f"已打开证明材料: {file_path.name}", 2000)
        else:
            QMessageBox.warning(
                self,
                "警告",
                f"文件不存在于路径:\n{file_path}",
            )

    def _locate_attachment(self):
        """Open the folder containing the current attachment."""
        if not self.current_invoice or not self.current_invoice.get("attachment_path"):
            return
        attachment_path = str(self.current_invoice.get("attachment_path") or "")
        file_path = self._resolve_attachment_path(attachment_path)
        if not file_path:
            return

        target_dir = file_path.parent if file_path.is_file() else file_path
        if not target_dir.exists():
            QMessageBox.warning(
                self,
                "警告",
                f"文件夹不存在于路径:\n{target_dir}\n\n原始记录:\n{attachment_path}",
            )
            return

        self._open_local_path(target_dir)
        self.statusBar().showMessage(f"已打开附件所在目录: {target_dir}", 2000)

    def _locate_attachment_file(self):
        """Open Explorer and highlight/select the current attachment file."""
        if not self.current_invoice or not self.current_invoice.get("attachment_path"):
            return
        attachment_path = str(self.current_invoice.get("attachment_path") or "")
        file_path = self._resolve_attachment_path(attachment_path)
        if not file_path or not file_path.exists():
            QMessageBox.warning(
                self,
                "警告",
                f"文件不存在于路径:\n{file_path}",
            )
            return

        import sys
        if sys.platform == "win32":
            try:
                import subprocess
                subprocess.run(["explorer.exe", "/select,", str(file_path.resolve())])
                return
            except Exception as e:
                _log.error("Failed to run explorer /select: %s", e)

        self._open_local_path(file_path.parent)

    def _open_exports_directory(self):
        """Open global exports folder, write to status bar."""
        exports_dir = PROJECT_ROOT / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        self._open_local_path(exports_dir)
        self.statusBar().showMessage("已打开总导出 exports 目录", 3000)

    def _save_invoice_fields(self):
        # Save manually edited metadata fields in the form to database.
        if not self.current_invoice:
            return
        inv_id = self.current_invoice["id"]
        number = self.txt_number.text().strip()
        date = self.txt_date.text().strip()
        seller = self.txt_seller.text().strip()
        buyer = self.txt_buyer.text().strip()
        amount = self.txt_amount.text().strip()
        category = self.combo_category.currentText().strip()
        note = self.txt_note.toPlainText().strip()

        if not amount:
            self.statusBar().showMessage("金额为空，已保存为待补全；标记通过前会再次确认。", 5000)
            self.write_log("⚠️ [手工补录] 当前记录金额为空，已按待补全材料保存。")

        try:
            success = self.db.update_invoice_fields(
                invoice_id=inv_id,
                invoice_number=number,
                expense_date=date,
                seller_name=seller,
                buyer_name=buyer,
                total_amount=amount,
                category=category,
                note=note
            )
            if not success:
                if getattr(self.db, "last_error", "") == "unique_conflict":
                    QMessageBox.warning(
                        self,
                        "保存失败",
                        "保存内容与已有发票重复，请检查发票号码、金额和销售方。",
                    )
                else:
                    QMessageBox.warning(self, "保存失败", "未能保存发票修改")
                return

            self.statusBar().showMessage("发票修改已保存", 3000)
            current_row = self.table.currentRow()
            refreshed = self.db.get_invoice(inv_id)
            if refreshed:
                self.current_invoice = refreshed
                self._invoice_snapshot = self._get_invoice_form_snapshot()
            self._refresh_category_options(category)
            self._load_invoices()
            if current_row >= 0 and current_row < self.table.rowCount():
                self.table.selectRow(current_row)
                self._on_table_selection_changed()
            self.lbl_dirty_hint.setText("未修改")
            self.btn_save_draft.setEnabled(False)
        except Exception as e:
            _log.error("Failed to save invoice edits: %s", e)
            QMessageBox.critical(self, "错误", f"保存发票失败: {e}")

    def _approval_missing_fields(self, inv: dict) -> list[str]:
        missing = []
        if not str(inv.get("invoice_number") or "").strip():
            missing.append("发票号码")
        if not str(inv.get("total_amount") or "").strip():
            missing.append("金额")
        if not str(inv.get("expense_date") or inv.get("invoice_date") or "").strip():
            missing.append("费用日期")
        if not str(inv.get("attachment_path") or "").strip():
            missing.append("原件")
        return missing

    def _confirm_approve_incomplete_invoices(
        self,
        invoices: list[dict],
        skipped_evidence_count: int = 0,
    ) -> bool:
        incomplete = []
        has_missing_attachment = False
        for inv in invoices:
            missing = self._approval_missing_fields(inv)
            if missing:
                if "原件" in missing:
                    has_missing_attachment = True
                label = str(inv.get("invoice_number") or inv.get("seller_name") or f"ID {inv.get('id')}").strip()
                incomplete.append(f"- {label}: 缺 {', '.join(missing)}")

        if not incomplete and not skipped_evidence_count:
            return True

        preview = "\n".join(incomplete[:8])
        if len(incomplete) > 8:
            preview += f"\n... 另有 {len(incomplete) - 8} 条"
        selection_summary = ""
        if skipped_evidence_count:
            selection_summary = (
                f"将跳过 {skipped_evidence_count} 条待关联证明材料，"
                f"并处理 {len(invoices)} 条正式发票。\n\n"
            )
        missing_summary = (
            f"以下正式发票仍缺少关键信息：\n{preview}\n\n"
            if incomplete else ""
        )

        if len(invoices) == 1 and has_missing_attachment and len(incomplete) == 1:
            prompt_text = "该发票缺少本地原件文件，是否仍通过？"
        else:
            prompt_text = (
                selection_summary
                + missing_summary
                + "如果这是图片、receipt、水单或其他未识别材料，请确认原件和手工补录信息无误后再通过审核。是否继续标记为已通过？"
            )

        reply = QMessageBox.question(
            self,
            "确认通过审核",
            prompt_text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _set_selected_status(self, status):
        """Set review status of all selected invoices, handles auto-advance selection."""
        result = {
            "success": 0,
            "evidence_only": 0,
            "not_found": 0,
            "other_failed": 0,
        }
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return result

        max_row = -1
        row_indexes = []
        for idx in selected_indexes:
            row_indexes.append(idx.row())
            if idx.row() > max_row:
                max_row = idx.row()

        next_select_row = max_row + 1 - len(selected_indexes)
        selected_invoices = [self.invoices_list[row_idx] for row_idx in row_indexes]
        note = self.txt_note.toPlainText().strip() if len(selected_indexes) == 1 else "批量修改状态"

        actionable_invoices = selected_invoices
        if status == APPROVED:
            evidence_invoices = [
                inv for inv in selected_invoices if is_pending_evidence_invoice(inv)
            ]
            result["evidence_only"] = len(evidence_invoices)
            actionable_invoices = [
                inv for inv in selected_invoices if not is_pending_evidence_invoice(inv)
            ]
            if not actionable_invoices:
                QMessageBox.warning(
                    self,
                    "无法标记通过",
                    (
                        "待关联证明材料不能直接标记为已通过，"
                        "请先关联到主发票或补录为正式报销记录。"
                    ),
                )
                self.statusBar().showMessage(
                    f"已跳过 {result['evidence_only']} 条待关联证明材料。",
                    4000,
                )
                return result
            if not self._confirm_approve_incomplete_invoices(
                actionable_invoices,
                skipped_evidence_count=result["evidence_only"],
            ):
                cancel_message = "已取消标记通过，正式发票仍保持待审核。"
                if result["evidence_only"]:
                    cancel_message += f" 已跳过 {result['evidence_only']} 条待关联证明材料。"
                self.statusBar().showMessage(cancel_message, 4000)
                return result

        try:
            for inv in actionable_invoices:
                updated = self.db.update_invoice_review_status(inv["id"], status, note=note)
                if updated:
                    result["success"] += 1
                    continue
                error = getattr(self.db, "last_error", "")
                if error == "evidence_only":
                    result["evidence_only"] += 1
                elif error == "not_found":
                    result["not_found"] += 1
                else:
                    result["other_failed"] += 1

            summary_parts = []
            if result["success"]:
                summary_parts.append(f"成功 {result['success']} 条")
            if result["evidence_only"]:
                summary_parts.append(f"跳过待关联证明材料 {result['evidence_only']} 条")
            if result["not_found"]:
                summary_parts.append(f"记录不存在 {result['not_found']} 条")
            if result["other_failed"]:
                summary_parts.append(f"失败 {result['other_failed']} 条")
            self.statusBar().showMessage("；".join(summary_parts), 4000)
            self._load_invoices()

            num_rows = self.table.rowCount()
            if num_rows > 0:
                if status == APPROVED and result["success"] == 1 and len(selected_indexes) == 1:
                    for candidate_row in range(max(0, next_select_row), num_rows):
                        candidate = self.invoices_list[candidate_row]
                        if (candidate.get("review_status") or TO_REVIEW) == TO_REVIEW:
                            self.table.selectRow(candidate_row)
                            self.current_invoice = candidate
                            self._invoice_snapshot = self._get_invoice_snapshot(candidate)
                            break
                    else:
                        if next_select_row < 0:
                            next_select_row = 0
                        elif next_select_row >= num_rows:
                            next_select_row = num_rows - 1
                        self.table.selectRow(next_select_row)
                        self.current_invoice = self.invoices_list[next_select_row]
                        self._invoice_snapshot = self._get_invoice_snapshot(self.current_invoice)
                else:
                    if next_select_row < 0:
                        next_select_row = 0
                    elif next_select_row >= num_rows:
                        next_select_row = num_rows - 1
                    self.table.selectRow(next_select_row)
                    self.current_invoice = self.invoices_list[next_select_row]
                    self._invoice_snapshot = self._get_invoice_snapshot(self.current_invoice)
            else:
                self._clear_detail_form()
            return result

        except Exception as e:
            _log.error("Failed to update status: %s", e)
            QMessageBox.critical(self, "错误", f"更新状态失败: {e}")
            result["other_failed"] += 1
            return result

    def _create_claim(self):
        """Insert a new claim group into DB and reload dropdown."""
        name = self.txt_new_claim.text().strip()
        if not name:
            QMessageBox.warning(self, "输入有误", "请输入报销组名称！")
            return

        try:
            self.db.create_claim_group(name=name)
            self.txt_new_claim.clear()
            self._load_claims()
            self.statusBar().showMessage(f"成功创建报销组: '{name}'", 3000)
        except Exception as e:
            _log.error("Failed to create claim group: %s", e)
            QMessageBox.critical(self, "错误", f"新建报销组失败: {e}")

    def _link_invoices_to_claim(self):
        """Map selected invoices to the dropdown claim group in the SQLite DB."""
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            QMessageBox.warning(self, "选择为空", "请先在左侧表格中选中发票记录！")
            return

        claim_idx = self.combo_claims.currentIndex()
        if claim_idx < 0:
            QMessageBox.warning(self, "选择为空", "请选择要关联的目标报销组！")
            return

        claim_id = self.combo_claims.itemData(claim_idx)
        claim_name = self.combo_claims.currentText()
        linked_count = 0
        duplicate_count = 0
        evidence_only_count = 0
        failed_count = 0

        try:
            for idx in selected_indexes:
                inv = self.invoices_list[idx.row()]
                success = self.db.add_invoice_to_claim(claim_id, inv["id"])
                if success:
                    linked_count += 1
                    continue
                error = getattr(self.db, "last_error", "")
                if error == "integrity_error":
                    duplicate_count += 1
                elif error == "evidence_only":
                    evidence_only_count += 1
                else:
                    failed_count += 1

            message_parts = []
            if linked_count:
                message_parts.append(f"成功关联 {linked_count} 张发票")
            if duplicate_count:
                message_parts.append(f"重复 {duplicate_count} 张")
            if evidence_only_count:
                message_parts.append(f"跳过待关联证明材料 {evidence_only_count} 张")
            if failed_count:
                message_parts.append(f"失败 {failed_count} 张")
            if not linked_count:
                message_parts.insert(0, "未关联任何发票")
            msg = "；".join(message_parts) + "。"
            self.statusBar().showMessage(
                f"报销组【{claim_name}】: " + "；".join(message_parts),
                4000,
            )
            dialog_title = "关联结果" if linked_count else "未关联"
            QMessageBox.information(self, dialog_title, msg)
            self._load_claims()
            self._load_invoices()
            return {
                "linked": linked_count,
                "duplicate": duplicate_count,
                "evidence_only": evidence_only_count,
                "failed": failed_count,
            }

        except Exception as e:
            _log.error("Failed to link invoices to claim: %s", e)
            QMessageBox.critical(self, "错误", f"关联发票失败: {e}")
            return {
                "linked": linked_count,
                "duplicate": duplicate_count,
                "evidence_only": evidence_only_count,
                "failed": failed_count + 1,
            }

    def _unlink_selected_invoices(self):
        """Remove selected invoices from the active claim group in the SQLite DB."""
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            QMessageBox.warning(self, "选择为空", "请先在左侧表格中选中发票记录！")
            return

        claim_idx = self.combo_claims.currentIndex()
        if claim_idx < 0:
            QMessageBox.warning(self, "选择为空", "请选择要取消关联的源报销组！")
            return

        claim_id = self.combo_claims.itemData(claim_idx)
        claim_name = self.combo_claims.currentText()
        unlinked_count = 0

        try:
            for idx in selected_indexes:
                inv = self.invoices_list[idx.row()]
                self.db.remove_invoice_from_claim(claim_id, inv["id"])
                unlinked_count += 1

            self.statusBar().showMessage(f"已从报销组【{claim_name}】中取消关联 {unlinked_count} 张发票", 3000)
            QMessageBox.information(self, "成功", f"已成功取消关联 {unlinked_count} 张发票！")
            self._load_claims()
            self._load_invoices()

        except Exception as e:
            _log.error("Failed to unlink invoices from claim: %s", e)
            QMessageBox.critical(self, "错误", f"取消关联失败: {e}")

    def _claim_export_preflight_stats(self, claim_id: int) -> dict:
        invoices = self.db.get_claim_invoices(claim_id)
        stats = {
            APPROVED: 0,
            TO_REVIEW: 0,
            IGNORED: 0,
            ERROR: 0,
            "missing_attachment": 0,
            "missing_amount": 0,
        }
        for inv in invoices:
            status = inv.get("review_status") or TO_REVIEW
            if status in (APPROVED, TO_REVIEW, IGNORED, ERROR):
                stats[status] += 1
            if status in (APPROVED, TO_REVIEW):
                if not str(inv.get("attachment_path") or "").strip():
                    stats["missing_attachment"] += 1
                if not str(inv.get("total_amount") or "").strip():
                    stats["missing_amount"] += 1
        return stats

    def _format_claim_export_preflight_text(self, stats: dict) -> str:
        return (
            "导出已通过 + 待审核发票。\n"
            "ignored/error 永远跳过，不会进入报销包。\n\n"
            "导出前统计:\n"
            f"- approved: {stats.get(APPROVED, 0)}\n"
            f"- to_review: {stats.get(TO_REVIEW, 0)}\n"
            f"- ignored: {stats.get(IGNORED, 0)}\n"
            f"- error: {stats.get(ERROR, 0)}\n"
            f"- 缺附件: {stats.get('missing_attachment', 0)}\n"
            f"- 缺金额: {stats.get('missing_amount', 0)}"
        )

    def _export_claim_package(self):
        """Run standard claim export (offering choices for range scope) and offer direct file manager folder opening."""
        claim_idx = self.combo_claims.currentIndex()
        if claim_idx < 0:
            QMessageBox.warning(self, "关联空", "请选择需要导出的报销组！")
            return

        claim_id = self.combo_claims.itemData(claim_idx)
        claim_name = self.combo_claims.currentText()
        preflight_stats = self._claim_export_preflight_stats(claim_id)
        preflight_text = self._format_claim_export_preflight_text(preflight_stats)

        # Premium selection dialog for export range
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("确认导出范围")
        box.setText(
            f"将开始导出【{claim_name}】的报销文件包。\n\n"
            "默认策略仅打包处于「已审核通过 (approved)」状态的合格发票。\n"
            "对于当前处于「待审核」或「异常」状态的关联记录，您希望如何处理？"
        )
        box.setInformativeText(preflight_text)
        btn_approved_only = box.addButton("🟢 仅打包已通过发票", QMessageBox.YesRole)
        btn_include_all = box.addButton("🟡 导出已通过 + 待审核发票", QMessageBox.NoRole)
        btn_cancel = box.addButton("取消", QMessageBox.RejectRole)

        box.exec()

        if box.clickedButton() == btn_cancel:
            return

        include_to_review = (box.clickedButton() == btn_include_all)

        try:
            # Trigger standard package exporter
            from ..claim_export import export_claim_package
            cfg = load_config_safe()
            export_dir = export_claim_package(
                db=self.db,
                claim_id=claim_id,
                project_root=PROJECT_ROOT,
                runtime_dir=RUNTIME_DIR,
                include_to_review=include_to_review,
                reimbursement_config=cfg.get("reimbursement", {}),
            )

            # Read manifest.json to get item count and skipped counts
            summary = _read_manifest_summary(export_dir)
            item_count = summary.get("item_count", 0)
            skipped = summary.get("skipped_counts", {})
            qa_warnings_count = summary.get("qa_warnings_count", 0)

            # Format skipped stats neatly
            skip_items = [f"{k}: {v}张" for k, v in skipped.items() if v > 0]
            skip_text = ", ".join(skip_items) if skip_items else "无"

            # Render export summary panel
            summary_msg = f"<b>上一次导出结果：</b><br>" \
                          f"• 成功打包发票: <font color='#10B981'><b>{item_count}</b></font> 张<br>" \
                          f"• 过滤跳过记录: {skip_text}"
            self.lbl_export_summary.setText(summary_msg)

            self.statusBar().showMessage(f"报销组【{claim_name}】打包导出成功，共计 {item_count} 张", 4000)

            # Success dialog with direct Open Folder button
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle("导出成功")

            # 不要泄露完整本机路径: show path relative to project root
            relative_export_dir = ""
            try:
                relative_export_dir = "exports/" + Path(export_dir).relative_to(PROJECT_ROOT / "exports").as_posix()
            except Exception:
                try:
                    relative_export_dir = Path(export_dir).relative_to(PROJECT_ROOT).as_posix()
                except Exception:
                    from ..log_privacy import mask_path
                    relative_export_dir = mask_path(export_dir)

            if qa_warnings_count == 0:
                qa_text = "导出完成，质量检查未发现需确认项。"
            else:
                qa_text = f"导出完成，发现 {qa_warnings_count} 个需确认项，请查看质量报告。"

            box.setText(
                f"{qa_text}\n\n"
                f"共计打包发票: {item_count} 张\n"
                f"过滤跳过记录: {skip_text}\n\n"
                f"输出路径: {relative_export_dir}"
            )
            btn_open = box.addButton("📁 打开导出目录", QMessageBox.AcceptRole)
            btn_close = box.addButton("关闭", QMessageBox.RejectRole)
            box.exec()

            if box.clickedButton() == btn_open:
                self._open_local_path(export_dir)

            # UX auto-refresh dropdown & tables
            self._load_claims()
            self._load_invoices()

        except Exception as e:
            _log.error("Failed to export claim package: %s", e)
            QMessageBox.critical(self, "错误", f"打包导出失败: {e}")

    # ── Operations Bar Handlers ───────────────────────────────────────

    def write_log(self, text: str):
        """Append log line to bottom operation log panel."""
        self.txt_log.append(sanitize_log_message(text))
        self.txt_log.ensureCursorVisible()

    def _open_runtime_dir(self):
        """Open the local runtime directory safely."""
        self._open_local_path(RUNTIME_DIR)
        self.write_log("已打开本地 runtime/ 运行时数据存放目录。")
        self.statusBar().showMessage("已打开 runtime 目录", 3000)

    def _open_logs_directory(self):
        """Open the local logs directory."""
        log_dir = RUNTIME_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._open_local_path(log_dir)
        self.write_log("已打开本地日志目录。")
        self.statusBar().showMessage("已打开日志目录", 3000)

    def _copy_diagnostic_info(self):
        """Copy redacted app diagnostics metadata to the clipboard."""
        payload = json.dumps(self._collect_diagnostic_payload(), ensure_ascii=False, indent=2)
        QApplication.clipboard().setText(payload)
        self.write_log("已复制脱敏诊断信息到剪贴板。")
        self.statusBar().showMessage("已复制诊断信息", 3000)

    def _database_user_version(self) -> int | None:
        try:
            row = self.db._conn.execute("PRAGMA user_version").fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None

    def _current_filter_state(self) -> dict:
        return {
            "status": self.current_filter_status or "all",
            "search": self.txt_search.text().strip() if hasattr(self, "txt_search") else "",
            "unlinked_only": bool(self.chk_unlinked.isChecked()) if hasattr(self, "chk_unlinked") else False,
            "needs_fix_only": bool(self.chk_needs_fix.isChecked()) if hasattr(self, "chk_needs_fix") else False,
            "show_deleted": bool(self.chk_show_deleted.isChecked()) if hasattr(self, "chk_show_deleted") else False,
        }

    def _collect_diagnostic_payload(self) -> dict:
        payload = collect_app_info()
        payload["database_user_version"] = self._database_user_version()
        payload["current_filter_state"] = self._current_filter_state()
        payload["last_scan_summary"] = dict(getattr(self, "_last_scan_summary", {}) or {})
        return payload

    def _about_text(self) -> str:
        info = collect_app_info()
        return "\n".join([
            "Invoice Hub",
            f"Version: {APP_VERSION}",
            f"Build: {info.get('build_commit') or 'unavailable'}",
            f"Mode: {info.get('build_mode') or info.get('mode') or 'unknown'}",
            f"Data directory: {RUNTIME_DIR}",
            f"Log directory: {RUNTIME_DIR / 'logs'}",
        ])

    def _show_about_dialog(self):
        """Show app version and local support paths."""
        QMessageBox.information(self, "关于 Invoice Hub", self._about_text())

    def _export_diagnostics_package(self):
        """Export a redacted diagnostics package for support and GitHub issues."""
        confirm = QMessageBox.question(
            self,
            "导出脱敏诊断包",
            (
                f"{FEEDBACK_PRIVACY_NOTICE}\n\n"
                "诊断包只包含 app_info.json、latest.log.redacted、config.redacted.json、"
                "environment.txt 和 privacy_scan_result.txt。\n\n"
                "不会打包 invoices.db、attachments/、exports/、PDF/OFD/图片、Excel、"
                "邮箱授权码、API Key 或完整下载链接。是否继续？"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择诊断包导出目录")
        if not folder:
            return
        try:
            zip_path = export_diagnostics_zip(folder)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", f"导出脱敏诊断包失败: {exc}")
            return
        self.write_log(f"已导出脱敏诊断包: {zip_path.name}")
        self.statusBar().showMessage(f"已导出诊断包: {zip_path.name}", 5000)
        reply = QMessageBox.question(
            self,
            "导出完成",
            f"已生成脱敏诊断包:\n{zip_path}\n\n请勿额外上传 invoices.db、附件原件或未脱敏日志。\n\n是否打开所在文件夹？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self._open_local_path(zip_path.parent)

    def _open_github_issues(self):
        """Open the GitHub issue chooser."""
        QMessageBox.information(
            self,
            "反馈前隐私提示",
            FEEDBACK_PRIVACY_NOTICE,
        )
        if not QDesktopServices.openUrl(QUrl(GITHUB_ISSUES_URL)):
            QApplication.clipboard().setText(GITHUB_ISSUES_URL)
            QMessageBox.warning(
                self,
                "无法打开浏览器",
                f"无法自动打开 GitHub Issues 页面，链接已复制到剪贴板:\n{GITHUB_ISSUES_URL}",
            )
            self.write_log("无法自动打开 GitHub Issues 页面，已复制链接到剪贴板。")
            self.statusBar().showMessage("GitHub Issues 链接已复制", 5000)
            return
        self.write_log("已打开 GitHub Issues 页面。")
        self.statusBar().showMessage("已打开 GitHub Issues", 3000)

    def _import_local_clicked(self):
        """Trigger QFileDialog to choose a directory for invoice importing."""
        folder = QFileDialog.getExistingDirectory(self, "选择本地发票文件夹")
        if not folder:
            return

        path = Path(folder)
        self.write_log(f"📁 [本地导入] 已选择本地文件夹: {path.absolute()}")
        self.statusBar().showMessage(f"正在读取与导入本地发票: {path.name}...")
        self.btn_import_local.setEnabled(False)
        self.btn_scan_email.setEnabled(False)

        # Spawn asynchronous thread worker
        self.import_worker = LocalImportWorker(path, self.db_path)
        self.import_worker.finished.connect(self._import_local_finished)
        self.import_worker.error.connect(self._import_local_error)
        self.import_worker.start()

    def _mobile_upload_clicked(self):
        dialog = MobileUploadDialog(self, self.db_path)
        dialog.upload_finished.connect(self._mobile_upload_finished)
        dialog.exec()

    def _mobile_upload_finished(self):
        self.write_log("📱 [扫码上传] 手机上传批次已更新，正在刷新发票列表。")
        self._load_invoices()
        self._load_claims()

    def _format_local_import_summary(self, stats: dict) -> str:
        return (
            "本地发票批量导入完成：\n\n"
            f"- 成功识别: {stats.get('added', 0)} 条\n"
            f"- 重复跳过: {stats.get('duplicates', 0)} 条\n"
            f"- 冲突待确认: {stats.get('conflicts', 0)} 条\n"
            f"- 需人工确认材料: {stats.get('pending_manual', 0)} 条\n"
            f"- 真正失败: {stats.get('failed', 0)} 条"
        )

    def _import_local_finished(self, stats: dict):
        self.btn_import_local.setEnabled(True)
        self.btn_scan_email.setEnabled(True)
        added = stats.get("added", 0)
        duplicates = stats.get("duplicates", 0)
        conflicts = stats.get("conflicts", 0)
        pending_manual = stats.get("pending_manual", 0)
        failed = stats.get("failed", 0)
        self.write_log(
            f"✅ [本地导入] 完成：成功识别 {added} 条，重复 {duplicates} 条，"
            f"冲突待确认 {conflicts} 条，需人工确认材料 {pending_manual} 条，真正失败 {failed} 条。"
        )
        self.statusBar().showMessage(
            f"本地导入完成: 成功识别 {added}, 重复 {duplicates}, 冲突 {conflicts}, "
            f"需人工确认材料 {pending_manual}, 失败 {failed}",
            4000,
        )

        QMessageBox.information(self, "导入完成", self._format_local_import_summary(stats))
        self._load_invoices()

    def _import_local_error(self, err_msg: str):
        self.btn_import_local.setEnabled(True)
        self.btn_scan_email.setEnabled(True)
        self.write_log(f"❌ [本地导入] 失败: {err_msg}")
        self.statusBar().showMessage("本地发票导入失败！", 4000)
        QMessageBox.critical(self, "错误", f"本地导入执行出错: {err_msg}")

    def _open_settings_dialog(self):
        """Display the modal Settings QDialog for config management."""
        dialog = SettingsDialog(self)
        dialog.exec()

    def _scan_email_clicked(self):
        """Trigger background email incremental scanning and download."""
        from ..config import get_email_accounts, load_config_safe
        cfg = load_config_safe()
        accounts = get_email_accounts(cfg)
        if not accounts:
            raw_accounts = cfg.get("email_accounts")
            raw_accounts = raw_accounts if isinstance(raw_accounts, list) else []
            legacy_email = str(cfg.get("email", {}).get("address") or "").strip()
            legacy_configured = bool(
                legacy_email
                and legacy_email.lower() not in {
                    "your_email@qq.com",
                    "your_email@example.com",
                }
            )
            self.write_log(
                "⚠️ [邮箱扫描] 未找到启用账号："
                f"legacy_email={'已配置' if legacy_configured else '未配置'}，"
                f"email_accounts={len(raw_accounts)}，enabled_accounts=0。"
            )
            QMessageBox.warning(
                self,
                "配置缺失",
                (
                    "当前没有启用的邮箱账号。\n"
                    "如果刚刚在设置页保存过邮箱，请重新保存一次；"
                    "或检查 config.json 中 email_accounts 是否全部 enabled=false。"
                ),
            )
            self._open_settings_dialog()
            return

        from ..credentials import has_auth_code
        missing = [account for account in accounts if not has_auth_code(account.get("address", ""))]
        if missing:
            missing_lines = "\n".join(f"  - {mask_email(account.get('address', ''))}" for account in missing[:8])
            if len(missing) > 8:
                missing_lines += f"\n  ... +{len(missing) - 8}"
            QMessageBox.warning(
                self,
                "\u51ed\u636e\u7f3a\u5931",
                f"\u672a\u68c0\u6d4b\u5230\u4ee5\u4e0b\u90ae\u7bb1\u7684\u6388\u6743\u7801\u5b89\u5168\u51ed\u8bc1\uff1a\n{missing_lines}\n\u8bf7\u524d\u5f80 [\u8bbe\u7f6e] \u9875\u9762\u8865\u5145\u3002",
            )
            self._open_settings_dialog()
            return

        self.write_log("\U0001f4e5 [\u90ae\u7bb1\u626b\u63cf] \u589e\u91cf\u62c9\u53d6\u4efb\u52a1\u5df2\u542f\u52a8...")
        self.statusBar().showMessage("\u6b63\u5728\u5efa\u7acb\u90ae\u7bb1\u8fde\u63a5\u5e76\u626b\u63cf\u63a5\u6536\u90ae\u4ef6...")
        self.btn_import_local.setEnabled(False)
        self.btn_scan_email.setEnabled(False)

        # Spawn asynchronous thread worker
        self.scan_worker = EmailScanWorker(self.db_path)
        self.scan_worker.log.connect(self.write_log)
        self.scan_worker.finished.connect(self._scan_email_finished)
        self.scan_worker.error.connect(self._scan_email_error)
        self.scan_worker.start()

    def _scan_email_finished(self, res: dict):
        self.btn_import_local.setEnabled(True)
        self.btn_scan_email.setEnabled(True)
        summary = self._build_scan_summary(res, getattr(self.scan_worker, "summary_logs", []))
        self._last_scan_summary = summary

        self.write_log(
            "✅ [邮箱扫描] 完成！"
            f"新增 {summary['new']}，恢复 {summary['restored']}，重复 {summary['duplicates']}，"
            f"链接失败 {summary['link_failed']}，待重试 {summary['pending_retry']}。"
        )
        self.statusBar().showMessage(self._format_scan_summary_status(summary), 6000)

        QMessageBox.information(
            self, "扫描完成",
            self._format_scan_summary_message(summary)
        )
        self._load_invoices()
        self._load_claims()

    def _build_scan_summary(self, res: dict, logs: list[str] | None = None) -> dict:
        logs = [str(line or "") for line in (logs or [])]
        restored = sum(1 for line in logs if "已恢复已删除的重复发票" in line)
        duplicates = sum(
            1 for line in logs
            if ("跳过重复" in line or "重复发票" in line) and "已恢复已删除" not in line
        )
        link_failed = sum(1 for line in logs if "未获得官方 PDF/OFD" in line or "链接下载失败" in line)
        pending_retry = sum(1 for line in logs if "保留为待下载" in line or "待下载以便重试" in line or "待重试" in line)
        manual_review_required = int(
            res.get("manual_review_required", res.get("pending_manual", 0)) or 0
        )
        downloaded = int(res.get("downloaded", 0) or 0)
        failed_summaries = [str(x or "") for x in (res.get("failed_summaries") or [])]
        return {
            "scanned_headers": int(
                res.get("scanned_headers", res.get("scanned", 0)) or 0
            ),
            "new_email_headers": int(res.get("new_email_headers", 0) or 0),
            "classified_invoice": int(res.get("classified_invoice", 0) or 0),
            "downloaded_emails": int(
                res.get("downloaded_emails", downloaded) or 0
            ),
            "new": int(
                res.get("new_invoice_records", res.get("new", downloaded)) or 0
            ),
            "restored": max(
                int(res.get("restored_deleted", 0) or 0),
                restored,
            ),
            "duplicates": max(
                int(
                    res.get(
                        "duplicate_invoices",
                        res.get("duplicates", 0),
                    ) or 0
                ),
                duplicates,
            ),
            "link_failed": link_failed,
            "manual_review_required": manual_review_required,
            "pending_retry": max(int(res.get("pending_retry", 0) or 0), pending_retry),
            "failed": int(res.get("failed", res.get("failed_count", 0)) or 0),
            "failed_summaries": failed_summaries[:5],
        }

    def _format_scan_summary_status(self, summary: dict) -> str:
        return (
            f"邮箱扫描完成: 新增记录 {summary.get('new', 0)}，恢复 {summary.get('restored', 0)}，"
            f"重复 {summary.get('duplicates', 0)}，需人工确认材料 {summary.get('manual_review_required', 0)}，"
            f"待重试 {summary.get('pending_retry', 0)}，"
            f"失败 {summary.get('failed', 0)}"
        )

    def _format_scan_summary_message(self, summary: dict) -> str:
        failures = [str(line or "") for line in (summary.get("failed_summaries") or [])]
        failure_text = "\n".join(f"  - {line}" for line in failures[:5]) if failures else "无"
        return (
            "邮箱增量扫描完成。\n\n"
            f"- 扫描邮件头: {summary.get('scanned_headers', 0)} 封\n"
            f"- 新入库邮件头: {summary.get('new_email_headers', 0)} 封\n"
            f"- 判定为发票候选: {summary.get('classified_invoice', 0)} 封\n"
            f"- 成功处理邮件: {summary.get('downloaded_emails', 0)} 封\n"
            f"- 新增记录（发票或待补全材料）: {summary.get('new', 0)} 条\n"
            f"- 恢复软删除: {summary.get('restored', 0)} 条\n"
            f"- 重复已存在: {summary.get('duplicates', 0)} 条\n"
            f"- 链接下载失败: {summary.get('link_failed', 0)} 封\n"
            f"- 其中需人工确认材料: {summary.get('manual_review_required', 0)} 条\n"
            f"- 待重试: {summary.get('pending_retry', 0)} 封\n"
            f"- 处理失败: {summary.get('failed', 0)} 封\n"
            f"失败摘要:\n{failure_text}\n\n"
            "说明：新入库邮件头不等于新增发票；需人工确认材料不是处理失败。\n"
            "如果没有看到预期发票，请清空筛选，或用发票号、购买方、金额搜索。"
        )

    def _scan_email_error(self, err_msg: str):
        self.btn_import_local.setEnabled(True)
        self.btn_scan_email.setEnabled(True)
        self.write_log(f"❌ [邮箱扫描] 失败: {err_msg}")
        self.statusBar().showMessage("邮箱扫描处理失败！", 4000)
        QMessageBox.critical(self, "错误", f"邮箱扫描执行出错: {err_msg}")

    # ── Original Document Preview Panel (原件预览区) Helper Methods ──
    def _init_preview_panel(self):
        self.preview_panel = QGroupBox("原件预览")
        self.preview_panel.setFocusPolicy(Qt.StrongFocus)
        preview_layout = QVBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(0)

        # Initialize Zoom State Variables
        self.image_zoom_mode = "fit_width"
        self.image_zoom_factor = 1.0
        self.current_image_pixmap = None
        self.image_resize_timer = QTimer(self)
        self.image_resize_timer.setSingleShot(True)
        self.image_resize_timer.setInterval(80)
        self.image_resize_timer.timeout.connect(self._update_image_display)

        # Setup Hover Hide Timer
        self.overlay_hide_timer = QTimer(self)
        self.overlay_hide_timer.setSingleShot(True)
        self.overlay_hide_timer.timeout.connect(self._hide_overlay_toolbar)

        # Container widget to hold preview stack and floating overlay toolbar
        self.preview_container = QWidget()
        preview_layout.addWidget(self.preview_container, 1)

        # Install event filter to track mouse entry and exit on preview container
        self.preview_container.installEventFilter(self)

        # Enable Context Menu on preview area
        self.preview_container.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preview_container.customContextMenuRequested.connect(self._show_preview_context_menu)

        container_layout = QVBoxLayout(self.preview_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self.preview_stack = QStackedWidget()
        self.preview_stack.setFrameShape(QFrame.StyledPanel)
        self.preview_stack.installEventFilter(self)

        self.lbl_preview_status = QLabel("请选择一张发票查看原件")
        self.lbl_preview_status.setAlignment(Qt.AlignCenter)
        self.lbl_preview_status.setWordWrap(True)
        self.lbl_preview_status.setStyleSheet("color: #6B7280; font-size: 13px; background-color: #F9FAFB;")
        self.preview_stack.addWidget(self.lbl_preview_status)
        self._preview_empty_message = "请选择一张发票查看原件"

        self.pdf_document = None
        self.pdf_view = None
        self.lbl_pdf_fallback = None

        self.image_scroll_area = QScrollArea()
        self.image_scroll_area.setWidgetResizable(True)
        self.image_scroll_area.setAlignment(Qt.AlignCenter)
        self.image_scroll_area.installEventFilter(self)
        # Dynamic Resizing scaling for image in FitToWidth / FitInView modes
        self.image_scroll_area.resizeEvent = lambda event: (
            QScrollArea.resizeEvent(self.image_scroll_area, event),
            self._schedule_image_display_update()
        )

        self.lbl_image_preview = QLabel()
        self.lbl_image_preview.setAlignment(Qt.AlignCenter)
        self.lbl_image_preview.setStyleSheet("background-color: #FFFFFF;")
        self.image_scroll_area.setWidget(self.lbl_image_preview)

        self.preview_stack.addWidget(self.image_scroll_area)
        container_layout.addWidget(self.preview_stack)

        # Create Floating Overlay Toolbar (weaker visual, smaller height, semi-transparent)
        self.overlay_toolbar = QWidget(self.preview_container)
        self.overlay_toolbar.setObjectName("OverlayToolbar")
        self.overlay_toolbar.setFixedHeight(28)
        self.overlay_toolbar.setStyleSheet("""
            QWidget#OverlayToolbar {
                background-color: rgba(255, 255, 255, 195);
                border: 1px solid #D1D5DB;
                border-radius: 8px;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                padding: 1px 4px;
                font-size: 11px;
                color: #374151;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: rgba(243, 244, 246, 200);
                border-radius: 4px;
                color: #111827;
            }
            QPushButton:disabled {
                color: #9CA3AF;
                background-color: transparent;
            }
        """)

        # Install event filter to prevent hide when inside toolbar itself
        self.overlay_toolbar.installEventFilter(self)

        tb_layout = QHBoxLayout(self.overlay_toolbar)
        tb_layout.setContentsMargins(4, 0, 4, 0)
        tb_layout.setSpacing(3)

        # Left / Prev Doc button (file-level)
        self.btn_prev = QPushButton("←")
        self.btn_prev.clicked.connect(self._prev_preview_doc)
        self.btn_prev.setFixedWidth(18)
        self.btn_prev.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.btn_prev.setToolTip("上一文件")
        tb_layout.addWidget(self.btn_prev)

        # File index/name display (minimal format e.g. 文件 1/2｜主发票｜PDF 1/7)
        self.lbl_file_info = QLabel("0 / 0 无文件")
        self.lbl_file_info.setAlignment(Qt.AlignCenter)
        self.lbl_file_info.setStyleSheet("font-weight: bold; color: #374151; font-size: 11px; padding: 0 2px; background: transparent; border: none;")
        tb_layout.addWidget(self.lbl_file_info)

        # Right / Next Doc button (file-level)
        self.btn_next = QPushButton("→")
        self.btn_next.clicked.connect(self._next_preview_doc)
        self.btn_next.setFixedWidth(18)
        self.btn_next.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.btn_next.setToolTip("下一文件")
        tb_layout.addWidget(self.btn_next)

        # Divider Frame helper
        def add_divider():
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFrameShadow(QFrame.Plain)
            sep.setStyleSheet("color: #E5E7EB; max-height: 14px; background: transparent; border: none; border-left: 1px solid #E5E7EB;")
            tb_layout.addWidget(sep)

        add_divider()

        # ── PDF page-level navigation ──
        self.btn_prev_page = QPushButton("◀ 上一页")
        self.btn_prev_page.clicked.connect(self._prev_pdf_page)
        self.btn_prev_page.setToolTip("PDF 上一页")
        self.btn_prev_page.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.btn_prev_page.setEnabled(False)
        tb_layout.addWidget(self.btn_prev_page)

        self.btn_next_page = QPushButton("下一页 ▶")
        self.btn_next_page.clicked.connect(self._next_pdf_page)
        self.btn_next_page.setToolTip("PDF 下一页")
        self.btn_next_page.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.btn_next_page.setEnabled(False)
        tb_layout.addWidget(self.btn_next_page)

        add_divider()

        # Fit Width Button
        self.btn_fit_width = QPushButton("适宽")
        self.btn_fit_width.clicked.connect(self._zoom_fit_width)
        tb_layout.addWidget(self.btn_fit_width)

        # Fit Page Button
        self.btn_fit_page = QPushButton("整页")
        self.btn_fit_page.clicked.connect(self._zoom_fit_page)
        tb_layout.addWidget(self.btn_fit_page)

        # Zoom 100% Button
        self.btn_zoom_100 = QPushButton("100%")
        self.btn_zoom_100.clicked.connect(self._zoom_100)
        tb_layout.addWidget(self.btn_zoom_100)

        # Zoom Out Button
        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        self.btn_zoom_out.setFixedWidth(14)
        self.btn_zoom_out.setStyleSheet("font-weight: bold; font-size: 11px;")
        tb_layout.addWidget(self.btn_zoom_out)

        # Zoom In Button
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        self.btn_zoom_in.setFixedWidth(14)
        self.btn_zoom_in.setStyleSheet("font-weight: bold; font-size: 11px;")
        tb_layout.addWidget(self.btn_zoom_in)

        add_divider()

        # Open External Button
        self.btn_open_ext = QPushButton("外部打开")
        self.btn_open_ext.clicked.connect(self._open_current_preview_ext)
        tb_layout.addWidget(self.btn_open_ext)

        # Divider and Link Evidence Button
        add_divider()
        self.btn_link_evidence = QPushButton("关联到当前发票")
        self.btn_link_evidence.clicked.connect(self._link_current_evidence_to_invoice)
        self.btn_link_evidence.setStyleSheet("font-weight: bold; color: #059669; padding: 0 4px;")
        self.btn_link_evidence.setVisible(False)
        self.btn_link_evidence.setEnabled(False)
        tb_layout.addWidget(self.btn_link_evidence)

        # Bind container resizing to overlay position alignment (Y-offset smaller = 4px)
        def resize_container(event):
            QWidget.resizeEvent(self.preview_container, event)
            self._reposition_overlay_toolbar()

        self.preview_container.resizeEvent = resize_container

        # Hide overlay initially
        self.overlay_toolbar.setVisible(False)
        self._set_zoom_buttons_enabled(False)

        # Register Ctrl+Left/Ctrl+Right shortcuts for file-level navigation
        self._register_navigation_shortcuts()

    def _reposition_overlay_toolbar(self):
        if self.overlay_toolbar.isVisible() and hasattr(self, "preview_container") and self.preview_container.width() > 0:
            tb_size = self.overlay_toolbar.sizeHint()
            w = min(tb_size.width(), self.preview_container.width() - 20)
            h = 28
            x = (self.preview_container.width() - w) // 2
            y = 4  # Minimal Y offset to not block document content
            self.overlay_toolbar.setGeometry(x, y, w, h)

    def _show_overlay_toolbar(self):
        self.overlay_hide_timer.stop()
        if hasattr(self, "current_preview_docs") and self.current_preview_docs:
            idx = self.current_preview_index
            if 0 <= idx < len(self.current_preview_docs):
                doc = self.current_preview_docs[idx]
                if doc["path"].exists():
                    self.overlay_toolbar.setVisible(True)
                    self.overlay_toolbar.adjustSize()
                    self._reposition_overlay_toolbar()

    def _hide_overlay_toolbar(self):
        self.overlay_toolbar.setVisible(False)

    def _start_hide_overlay_timer(self):
        self.overlay_hide_timer.start(1500)  # Hide after 1.5 seconds

    def _show_preview_context_menu(self, pos):
        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            return
        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return
        doc = self.current_preview_docs[idx]
        if not doc["path"].exists():
            return

        menu = QMenu(self)
        if len(self.current_preview_docs) > 1:
            action_prev = menu.addAction("◀ 上一文件")
            action_prev.triggered.connect(self._prev_preview_doc)
            action_next = menu.addAction("下一文件 ▶")
            action_next.triggered.connect(self._next_preview_doc)
            menu.addSeparator()

        # PDF page navigation
        _, page_count = self._get_pdf_page_info()
        if page_count is not None and page_count > 1:
            action_prev_page = menu.addAction("◀ 上一页")
            action_prev_page.triggered.connect(self._prev_pdf_page)
            action_next_page = menu.addAction("下一页 ▶")
            action_next_page.triggered.connect(self._next_pdf_page)
            menu.addSeparator()

        action_fit_width = menu.addAction("适宽")
        action_fit_width.triggered.connect(self._zoom_fit_width)

        action_fit_page = menu.addAction("整页")
        action_fit_page.triggered.connect(self._zoom_fit_page)

        action_zoom_100 = menu.addAction("100% 原始比例")
        action_zoom_100.triggered.connect(self._zoom_100)

        action_zoom_in = menu.addAction("🔍 放大")
        action_zoom_in.triggered.connect(self._zoom_in)

        action_zoom_out = menu.addAction("🔍 缩小")
        action_zoom_out.triggered.connect(self._zoom_out)

        menu.addSeparator()
        action_open_ext = menu.addAction("📂 外部打开")
        action_open_ext.triggered.connect(self._open_current_preview_ext)

        menu.exec(self.preview_container.mapToGlobal(pos))

    def _focus_is_editing_widget(self) -> bool:
        """Return True if the currently focused widget should receive raw keyboard input."""
        focused = QApplication.focusWidget()
        if focused is None:
            return False
        from PySide6.QtWidgets import (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox,
                                        QAbstractSpinBox, QSpinBox, QDoubleSpinBox)
        if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox,
                                QAbstractSpinBox, QSpinBox, QDoubleSpinBox)):
            return True
        return False

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "preview_container", None):
            if event.type() == QEvent.Type.Enter:
                self._show_overlay_toolbar()
            elif event.type() == QEvent.Type.Leave:
                self._start_hide_overlay_timer()
        elif watched is getattr(self, "overlay_toolbar", None):
            if event.type() == QEvent.Type.Enter:
                self.overlay_hide_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                self._start_hide_overlay_timer()

        # ── Capture Left/Right keys for preview navigation with focus protection ──
        preview_widgets = {
            getattr(self, "preview_container", None),
            getattr(self, "preview_stack", None),
            getattr(self, "pdf_view", None),
            getattr(self, "image_scroll_area", None),
            getattr(self, "overlay_toolbar", None),
        }
        if watched in preview_widgets and watched is not None:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key_Left, Qt.Key_Right):
                    # Only grab focus when active focus is inside preview related area (or no focus)
                    focused = QApplication.focusWidget()
                    is_preview_focused = False
                    if focused:
                        for w in preview_widgets:
                            if w and (focused is w or w.isAncestorOf(focused)):
                                is_preview_focused = True
                                break
                    else:
                        is_preview_focused = True

                    if is_preview_focused:
                        is_pdf_mode = (
                            getattr(self, "pdf_view", None) is not None
                            and self.preview_stack.currentWidget() is self.pdf_view
                        )
                        if event.key() == Qt.Key_Left:
                            if is_pdf_mode:
                                if not self._navigate_pdf_page(-1):
                                    self._prev_preview_doc()
                            else:
                                self._prev_preview_doc()
                            return True
                        elif event.key() == Qt.Key_Right:
                            if is_pdf_mode:
                                if not self._navigate_pdf_page(1):
                                    self._next_preview_doc()
                            else:
                                self._next_preview_doc()
                            return True

        try:
            return super().eventFilter(watched, event)
        except RuntimeError:
            return False

    def _set_zoom_buttons_enabled(self, enabled: bool):
        self.btn_fit_width.setEnabled(enabled)
        self.btn_fit_page.setEnabled(enabled)
        self.btn_zoom_100.setEnabled(enabled)
        self.btn_zoom_in.setEnabled(enabled)
        self.btn_zoom_out.setEnabled(enabled)

    def _show_preview_status(self, text):
        if text == "当前发票没有可预览的原件":
            text = "当前发票没有可预览的原件\n可点击“查看文件”或“定位文件”确认原件位置"
        elif text == "文件不存在":
            text = "原件文件不存在\n可点击“定位文件”确认路径，或重新导入/重新下载"
        elif text == "暂不支持内嵌预览，请点击打开外部文件":
            text = "当前格式暂不支持内嵌预览\n请点击外部打开查看原件"
        elif text == "图片加载失败，暂不支持预览":
            text = "图片加载失败\n请点击外部打开，或重新导入该材料"
        self.lbl_preview_status.setText(text)
        self.preview_stack.setCurrentWidget(self.lbl_preview_status)
        self.overlay_toolbar.setVisible(False)
        self._set_zoom_buttons_enabled(False)

    def _zoom_fit_width(self):
        self.image_zoom_mode = "fit_width"
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self._update_image_display()

    def _zoom_fit_page(self):
        self.image_zoom_mode = "fit_page"
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self._update_image_display()

    def _zoom_100(self):
        self.image_zoom_mode = "custom"
        self.image_zoom_factor = 1.0
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(1.0)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self._update_image_display()

    def _zoom_in(self):
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() * 1.2)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self.image_zoom_mode = "custom"
            self.image_zoom_factor *= 1.2
            self._update_image_display()

    def _zoom_out(self):
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() * 0.8)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self.image_zoom_mode = "custom"
            self.image_zoom_factor *= 0.8
            self._update_image_display()

    def _schedule_image_display_update(self):
        if hasattr(self, "image_resize_timer"):
            self.image_resize_timer.start()
        else:
            self._update_image_display()

    def _update_image_display(self):
        if self.current_image_pixmap is None or self.current_image_pixmap.isNull():
            return

        if self.image_zoom_mode == "fit_width":
            width = self.image_scroll_area.width() - 24
            if width <= 0:
                width = 400
            scaled = self.current_image_pixmap.scaledToWidth(width, Qt.SmoothTransformation)
            self.lbl_image_preview.setPixmap(scaled)
        elif self.image_zoom_mode == "fit_page":
            width = self.image_scroll_area.width() - 24
            height = self.image_scroll_area.height() - 24
            if width <= 0:
                width = 400
            if height <= 0:
                height = 300
            scaled = self.current_image_pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_image_preview.setPixmap(scaled)
        elif self.image_zoom_mode == "custom":
            width = int(self.current_image_pixmap.width() * self.image_zoom_factor)
            if width <= 0:
                width = 100
            scaled = self.current_image_pixmap.scaledToWidth(width, Qt.SmoothTransformation)
            self.lbl_image_preview.setPixmap(scaled)

    def _update_document_preview(self):
        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            self._show_preview_status(getattr(self, "_preview_empty_message", "请选择一张发票查看原件"))
            self.lbl_file_info.setText("0 / 0 无文件")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.btn_open_ext.setEnabled(False)
            if hasattr(self, "btn_link_evidence"):
                self.btn_link_evidence.setVisible(False)
                self.btn_link_evidence.setEnabled(False)
            self.overlay_toolbar.setVisible(False)
            self._set_zoom_buttons_enabled(False)
            return

        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return

        # Synchronize combo box selection
        if hasattr(self, "combo_supporting_docs") and getattr(self, "supporting_doc_items", None):
            current_doc = self.current_preview_docs[idx]
            doc_path = current_doc.get("path")
            if doc_path:
                doc_path_abs = str(doc_path.resolve()).lower()
                for i, item in enumerate(self.supporting_doc_items):
                    if item.get("path") and str(item["path"].resolve()).lower() == doc_path_abs:
                        self.combo_supporting_docs.blockSignals(True)
                        self.combo_supporting_docs.setCurrentIndex(i)
                        status_text = "已关联" if item["status"] == "linked" else "待关联"
                        self.combo_supporting_docs.setToolTip(f"[{status_text}] {item['path']}")
                        self.combo_supporting_docs.blockSignals(False)
                        break

        doc = self.current_preview_docs[idx]
        file_path = doc["path"]
        title = doc["title"]
        basename = doc["basename"]

        # ── Format file info with PDF page distinction ──
        pdf_page, pdf_page_count = self._get_pdf_page_info()
        file_info_text = self._format_preview_file_info(doc, idx, len(self.current_preview_docs), pdf_page, pdf_page_count)
        self.lbl_file_info.setText(file_info_text)
        self.lbl_file_info.setToolTip(f"{title}: {basename}\n路径: {file_path.resolve()}")

        self.btn_prev.setEnabled(len(self.current_preview_docs) > 1)
        self.btn_next.setEnabled(len(self.current_preview_docs) > 1)
        self.btn_open_ext.setEnabled(True)
        # Disable PDF page buttons initially (will be refreshed after PDF load)
        if hasattr(self, "btn_prev_page"):
            self.btn_prev_page.setEnabled(False)
        if hasattr(self, "btn_next_page"):
            self.btn_next_page.setEnabled(False)

        is_pending = (doc.get("type") == "pending_evidence" and doc.get("evidence_id") is not None)
        if hasattr(self, "btn_link_evidence"):
            self.btn_link_evidence.setVisible(is_pending)
            self.btn_link_evidence.setEnabled(is_pending)

        if not file_path.exists():
            self._show_preview_status("文件不存在")
            self.overlay_toolbar.setVisible(False)
            self._set_zoom_buttons_enabled(False)
            return

        # Keep default state as hidden, show toolbar when mouse enters
        self.overlay_toolbar.setVisible(False)
        self._set_zoom_buttons_enabled(True)

        suffix = file_path.suffix.lower()
        file_size_mb = 0.0
        preview_start = time.perf_counter()
        used_fallback = False
        try:
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
        except OSError:
            file_size_mb = 0.0

        if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".heic") and file_size_mb > 8:
            self.write_log(f"[性能] 大图预览可能较慢: {file_size_mb:.1f}MB")

        if suffix == ".pdf":
            QPdfDocument, QPdfView = get_qt_pdf_classes()
            if QPdfDocument is not None and QPdfView is not None:
                if self.pdf_view is None:
                    self.pdf_document = QPdfDocument(self)
                    self.pdf_view = QPdfView(self)
                    self.pdf_view.setDocument(self.pdf_document)
                    # ── PDF MultiPage: prefer MultiPage, fallback to SinglePage ──
                    if hasattr(QPdfView.PageMode, "MultiPage"):
                        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
                    else:
                        self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
                        _log.info("当前 Qt PDF 组件不支持 MultiPage，已降级为单页预览")
                    self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
                    self.preview_stack.addWidget(self.pdf_view)
                    # Install event filter to capture key events that QPdfView may consume
                    self.pdf_view.installEventFilter(self)

                self.pdf_document.load(str(file_path))
                # Re-apply MultiPage preference on every load
                if hasattr(QPdfView.PageMode, "MultiPage"):
                    self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
                else:
                    self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
                self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
                self.preview_stack.setCurrentWidget(self.pdf_view)
                # ── Refresh PDF-page-aware file info after loading ──
                self._refresh_preview_file_info()
                self._update_pdf_page_buttons()
                # ── Connect pageNavigator signal if available ──
                self._connect_pdf_page_navigator()
            else:
                used_fallback = True
                if self.lbl_pdf_fallback is None:
                    self.lbl_pdf_fallback = QLabel("暂不支持内嵌 PDF 预览，请点击【外部打开】")
                    self.lbl_pdf_fallback.setAlignment(Qt.AlignCenter)
                    self.lbl_pdf_fallback.setStyleSheet("color: #D97706; background-color: #FEF3C7; font-weight: bold; padding: 20px;")
                    self.preview_stack.addWidget(self.lbl_pdf_fallback)
                self.preview_stack.setCurrentWidget(self.lbl_pdf_fallback)
                self.overlay_toolbar.setVisible(False)
                self._set_zoom_buttons_enabled(False)
        elif suffix in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".heic"):
            pixmap = QPixmap(str(file_path))
            if pixmap.isNull():
                used_fallback = True
                if suffix == ".heic":
                    self._show_preview_status("该图片格式暂不支持内嵌预览，请点击外部打开")
                else:
                    self._show_preview_status("图片加载失败，暂不支持预览")
                self.overlay_toolbar.setVisible(False)
                self._set_zoom_buttons_enabled(False)
            else:
                self.current_image_pixmap = pixmap
                self.image_zoom_mode = "fit_width"
                self.image_zoom_factor = 1.0
                self._update_image_display()
                self.preview_stack.setCurrentWidget(self.image_scroll_area)
        else:
            used_fallback = True
            self._show_preview_status("暂不支持内嵌预览，请点击打开外部文件")
            self.overlay_toolbar.setVisible(False)
            self._set_zoom_buttons_enabled(False)

        load_elapsed_ms = int((time.perf_counter() - preview_start) * 1000)
        fallback_text = " fallback=1" if used_fallback else ""
        self.write_log(
            f"[性能] 原件预览: type={suffix or '<none>'} "
            f"size={file_size_mb:.1f}MB load={load_elapsed_ms}ms{fallback_text}"
        )

    def _prev_preview_doc(self):
        if hasattr(self, "current_preview_docs") and self.current_preview_docs:
            self.current_preview_index = (self.current_preview_index - 1) % len(self.current_preview_docs)
            self._update_document_preview()
            self._refresh_preview_file_info()
            self._update_pdf_page_buttons()

    def _next_preview_doc(self):
        if hasattr(self, "current_preview_docs") and self.current_preview_docs:
            self.current_preview_index = (self.current_preview_index + 1) % len(self.current_preview_docs)
            self._update_document_preview()
            self._refresh_preview_file_info()
            self._update_pdf_page_buttons()

    # ── PDF multi-page helpers ────────────────────────────────────────

    def _format_preview_file_info(self, doc: dict, file_index: int, file_count: int,
                                   pdf_page: int | None = None, pdf_page_count: int | None = None) -> str:
        """Build display string distinguishing file-level from PDF page-level navigation.

        Non-PDF:  "文件 1/2｜主发票"
        PDF:      "文件 1/2｜主发票｜PDF 1/7"  or  "文件 1/2｜主发票｜PDF 共 7 页"
        """
        title = doc.get("title", "文件")
        base = f"文件 {file_index + 1}/{file_count}｜{title}"

        suffix = file_path = doc.get("path")
        if suffix is not None and hasattr(suffix, "suffix"):
            suffix = suffix.suffix.lower()
        elif suffix is not None and hasattr(suffix, "lower"):
            suffix = suffix.lower()
        else:
            suffix = ""

        if suffix != ".pdf" or pdf_page_count is None:
            return base

        if pdf_page is not None:
            return f"{base}｜PDF {pdf_page}/{pdf_page_count}"
        return f"{base}｜PDF 共 {pdf_page_count} 页"

    def _get_pdf_page_info(self) -> tuple[int | None, int | None]:
        """Return (current_page 1-based, total_pages) or (None, None) if not a PDF."""
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfDocument is None:
            return None, None
        pdf_view = getattr(self, "pdf_view", None)
        pdf_doc = getattr(self, "pdf_document", None)
        if pdf_view is None or pdf_doc is None:
            return None, None
        if self.preview_stack.currentWidget() != pdf_view:
            return None, None
        try:
            page_count = pdf_doc.pageCount()
        except Exception:
            return None, None
        if page_count <= 0:
            return None, None

        current_page = None
        # Try to read current page from pageNavigator (PySide6 >= 6.5)
        try:
            nav = pdf_doc.pageNavigator()
            if nav is not None:
                cp = nav.currentPage()
                if cp is not None and isinstance(cp, int):
                    current_page = cp + 1  # 0-based → 1-based
        except Exception:
            pass
        return current_page, page_count

    def _refresh_preview_file_info(self):
        """Recompute overlay toolbar file-info label in-place without reloading the preview."""
        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            return
        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return
        doc = self.current_preview_docs[idx]
        pdf_page, pdf_page_count = self._get_pdf_page_info()
        text = self._format_preview_file_info(doc, idx, len(self.current_preview_docs), pdf_page, pdf_page_count)
        if hasattr(self, "lbl_file_info"):
            self.lbl_file_info.setText(text)

    def _connect_pdf_page_navigator(self):
        """Try to connect to QPdfDocument's pageNavigator currentPageChanged signal."""
        pdf_doc = getattr(self, "pdf_document", None)
        if pdf_doc is None:
            return
        try:
            nav = pdf_doc.pageNavigator()
            if nav is not None and hasattr(nav, "currentPageChanged"):
                try:
                    nav.currentPageChanged.disconnect(self._on_pdf_page_changed)
                except Exception:
                    pass
                nav.currentPageChanged.connect(self._on_pdf_page_changed)
        except Exception:
            pass

    def _on_pdf_page_changed(self, _page: int):
        """Slot for pageNavigator.currentPageChanged – keep toolbar in sync."""
        self._refresh_preview_file_info()
        self._update_pdf_page_buttons()

    # ── PDF page navigation buttons ──────────────────────────────────

    def _prev_pdf_page(self):
        self._navigate_pdf_page(-1)

    def _next_pdf_page(self):
        self._navigate_pdf_page(1)

    def _navigate_pdf_page(self, delta: int) -> bool:
        """Navigate within PDF pages. Returns True if navigation succeeded."""
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfDocument is None:
            return False
        pdf_view = getattr(self, "pdf_view", None)
        pdf_doc = getattr(self, "pdf_document", None)
        if pdf_view is None or pdf_doc is None:
            return False
        if self.preview_stack.currentWidget() != pdf_view:
            return False
        try:
            page_count = pdf_doc.pageCount()
            nav = pdf_doc.pageNavigator()
            if nav is None:
                return False
            current = nav.currentPage()  # 0-based
            new_page = current + delta
            if new_page < 0 or new_page >= page_count:
                return False
            nav.jump(new_page, 0.0, 0.0)
            self._refresh_preview_file_info()
            self._update_pdf_page_buttons()
            return True
        except Exception:
            return False

    def _update_pdf_page_buttons(self):
        """Enable/disable PDF page-nav buttons based on current state."""
        btn_prev_page = getattr(self, "btn_prev_page", None)
        btn_next_page = getattr(self, "btn_next_page", None)
        if btn_prev_page is None or btn_next_page is None:
            return

        _, page_count = self._get_pdf_page_info()
        if page_count is None or page_count <= 1:
            btn_prev_page.setEnabled(False)
            btn_next_page.setEnabled(False)
            return

        nav = None
        pdf_doc = getattr(self, "pdf_document", None)
        if pdf_doc is not None:
            try:
                nav = pdf_doc.pageNavigator()
            except Exception:
                pass
        if nav is None:
            btn_prev_page.setEnabled(False)
            btn_next_page.setEnabled(False)
            return

        try:
            current = nav.currentPage()  # 0-based
        except Exception:
            btn_prev_page.setEnabled(False)
            btn_next_page.setEnabled(False)
            return

        btn_prev_page.setEnabled(current > 0)
        btn_next_page.setEnabled(current < page_count - 1)

    # ── File-level navigation aliases ────────────────────────────────

    def _prev_preview_file(self):
        """Alias for _prev_preview_doc – file-level navigation."""
        self._prev_preview_doc()

    def _next_preview_file(self):
        """Alias for _next_preview_doc – file-level navigation."""
        self._next_preview_doc()

    def _open_current_preview_ext(self):
        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            return
        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return
        doc = self.current_preview_docs[idx]
        file_path = doc["path"]
        if file_path and file_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path.resolve())))

    def _on_supporting_docs_combo_changed(self, index):
        """Called when combo box item is selected. Updates tooltip and synchronizes preview window."""
        if index < 0 or not getattr(self, "supporting_doc_items", None):
            self.combo_supporting_docs.setToolTip("")
            return

        if index < len(self.supporting_doc_items):
            item = self.supporting_doc_items[index]
            status_text = "已关联" if item["status"] == "linked" else "待关联"
            path_str = str(item["path"]) if item["path"] else "未知路径"
            self.combo_supporting_docs.setToolTip(f"[{status_text}] {path_str}")

            # Sync preview index if the file path is present in current_preview_docs
            if hasattr(self, "current_preview_docs") and self.current_preview_docs:
                resolved_path = item["path"]
                if resolved_path:
                    resolved_abs = str(resolved_path.resolve()).lower()
                    for i, doc in enumerate(self.current_preview_docs):
                        if doc.get("path") and str(doc["path"].resolve()).lower() == resolved_abs:
                            if self.current_preview_index != i:
                                self.current_preview_index = i
                                self._update_document_preview()
                            break

    def _format_supporting_doc_label(self, status_text: str, path: Path, max_len: int = 42) -> str:
        """Format supporting document label with middle elision if file name is too long."""
        prefix = f"[{status_text}] "
        filename = path.name if hasattr(path, "name") else Path(str(path)).name

        max_filename_len = max_len - len(prefix)
        if max_filename_len < 10:
            max_filename_len = 10

        if len(filename) > max_filename_len:
            half = max_filename_len // 2 - 2
            if half < 3:
                half = 3
            filename = filename[:half] + "..." + filename[-half:]

        return f"{prefix}{filename}"

    def _update_supporting_docs_selector(self, inv, selected_path=None):
        """Update the supporting documents combo box selector."""
        self.combo_supporting_docs.blockSignals(True)
        self.combo_supporting_docs.clear()
        self.supporting_doc_items = []

        if not inv:
            self.combo_supporting_docs.addItem("暂无证明材料")
            self.combo_supporting_docs.setEnabled(False)
            self.btn_open_extra_files.setEnabled(False)
            self.combo_supporting_docs.setToolTip("酒店水单、行程记录、支付截图等证明材料会显示在这里。")
            self.combo_supporting_docs.blockSignals(False)
            return

        # 1. Gather linked extra docs
        extra_paths_raw = inv.get("extra_paths") or []
        if isinstance(extra_paths_raw, str):
            try:
                extra_paths_raw = json.loads(extra_paths_raw)
            except json.JSONDecodeError:
                extra_paths_raw = [extra_paths_raw]

        seen_paths = set()

        if isinstance(extra_paths_raw, list):
            for p in extra_paths_raw:
                p_str = str(p).strip()
                if not p_str:
                    continue
                resolved = self._resolve_attachment_path(p_str)
                if resolved:
                    abs_path_lower = str(resolved.resolve()).lower()
                    if abs_path_lower not in seen_paths:
                        seen_paths.add(abs_path_lower)
                        self.supporting_doc_items.append({
                            "label": self._format_supporting_doc_label("已关联", resolved),
                            "path": resolved,
                            "status": "linked",
                            "type": "supporting"
                        })

        # 2. Gather pending evidence docs
        mailbox_key = inv.get("mailbox_key")
        mail_uid = inv.get("mail_uid")
        if mailbox_key and mail_uid is not None:
            try:
                rows = self.db.list_pending_evidence_for_mail(mailbox_key, mail_uid)
                for row in rows:
                    att_p = row.get("attachment_path")
                    if att_p:
                        resolved = self._resolve_attachment_path(str(att_p))
                        if resolved:
                            abs_path_lower = str(resolved.resolve()).lower()
                            if abs_path_lower not in seen_paths:
                                seen_paths.add(abs_path_lower)
                                self.supporting_doc_items.append({
                                    "label": self._format_supporting_doc_label("待关联", resolved),
                                    "path": resolved,
                                    "status": "pending",
                                    "type": "pending_evidence"
                                })
            except Exception as e:
                print(f"Error querying unassociated evidence: {e}")

        # 3. Populate QComboBox
        if self.supporting_doc_items:
            for item in self.supporting_doc_items:
                self.combo_supporting_docs.addItem(item["label"])
            self.combo_supporting_docs.setEnabled(True)
            self.btn_open_extra_files.setEnabled(True)

            # Determine selected index
            matched_index = 0
            if selected_path is not None:
                selected_path_str = str(Path(selected_path).resolve()).lower()
                for i, item in enumerate(self.supporting_doc_items):
                    if item.get("path") and str(item["path"].resolve()).lower() == selected_path_str:
                        matched_index = i
                        break

            self.combo_supporting_docs.setCurrentIndex(matched_index)

            # Set tooltip for selected item
            sel_item = self.supporting_doc_items[matched_index]
            status_text = "已关联" if sel_item["status"] == "linked" else "待关联"
            self.combo_supporting_docs.setToolTip(f"[{status_text}] {sel_item['path']}")
        else:
            self.combo_supporting_docs.addItem("暂无证明材料")
            self.combo_supporting_docs.setEnabled(False)
            self.btn_open_extra_files.setEnabled(False)
            self.combo_supporting_docs.setToolTip("酒店水单、行程记录、支付截图等证明材料会显示在这里。")

        self.combo_supporting_docs.blockSignals(False)

    def _link_current_evidence_to_invoice(self):
        """Link the currently previewed evidence document to the current invoice."""
        if not self.current_invoice:
            return

        invoice_id = self.current_invoice.get("id")
        if not invoice_id:
            return

        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            return

        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return

        doc = self.current_preview_docs[idx]
        if doc.get("type") != "pending_evidence" or doc.get("evidence_id") is None:
            return

        evidence_id = doc["evidence_id"]
        evidence_name = doc["basename"]
        invoice_num = self.current_invoice.get("invoice_number") or "（无发票号）"
        current_file_path = doc["path"]

        # Prompt confirmation
        reply = QMessageBox.question(
            self,
            "确认关联",
            f"确认将该证明材料关联到当前发票吗？\n\n发票号码: {invoice_num}\n证明材料文件名: {evidence_name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            success = self.db.link_evidence_to_invoice(invoice_id, evidence_id)
            if success:
                # Refresh invoice data
                updated_inv = self.db.get_invoice(invoice_id)
                if updated_inv:
                    self.current_invoice = updated_inv
                    for i, item in enumerate(self.invoices_list):
                        if item.get("id") == invoice_id:
                            self.invoices_list[i] = updated_inv
                            break

                # Re-resolve preview docs
                from .helpers import resolve_invoice_documents_with_evidence
                self.current_preview_docs = resolve_invoice_documents_with_evidence(self.current_invoice, self.db, RUNTIME_DIR)

                # Update selector first with the path to keep it selected
                self._update_supporting_docs_selector(self.current_invoice, selected_path=current_file_path)

                # Locate the newly linked document in its new position (type=supporting)
                new_idx = 0
                if current_file_path:
                    current_file_path_abs = str(current_file_path.resolve()).lower()
                    for i, doc_item in enumerate(self.current_preview_docs):
                        if doc_item.get("path") and str(doc_item["path"].resolve()).lower() == current_file_path_abs:
                            new_idx = i
                            break
                self.current_preview_index = new_idx

                # Update preview last which handles synchronization
                self._update_document_preview()
                self.statusBar().showMessage("已成功将证明材料关联到当前发票", 3000)
            else:
                QMessageBox.warning(self, "关联失败", "无法将证明材料关联到当前发票，请重试。")

    def keyPressEvent(self, event):
        # Toggle overlay toolbar visible state temporarily on Alt or Ctrl keypress
        if event.key() in (Qt.Key_Alt, Qt.Key_Control):
            self._show_overlay_toolbar()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() in (Qt.Key_Alt, Qt.Key_Control):
            self._start_hide_overlay_timer()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _register_navigation_shortcuts(self):
        """Register Ctrl+Left / Ctrl+Right for file-level navigation via QShortcut."""
        # ── Ctrl+Left: previous file ──
        self.shortcut_prev_file = QShortcut(Qt.CTRL | Qt.Key_Left, self)
        self.shortcut_prev_file.setContext(Qt.WindowShortcut)
        self.shortcut_prev_file.activated.connect(self._on_ctrl_left)

        # ── Ctrl+Right: next file ──
        self.shortcut_next_file = QShortcut(Qt.CTRL | Qt.Key_Right, self)
        self.shortcut_next_file.setContext(Qt.WindowShortcut)
        self.shortcut_next_file.activated.connect(self._on_ctrl_right)

    def _on_ctrl_left(self):
        if not self._focus_is_editing_widget():
            self._prev_preview_doc()

    def _on_ctrl_right(self):
        if not self._focus_is_editing_widget():
            self._next_preview_doc()




# ── Thread Workers & Settings Dialog ──────────────────────────────────

class MobileUploadDialog(QDialog):
    upload_finished = Signal()

    def __init__(self, parent, db_path: Path):
        super().__init__(parent)
        self.setWindowTitle("扫码上传")
        self.resize(420, 560)
        self.setProperty("class", "WorkflowDialog")
        self.db_path = db_path
        self.server = None
        self.session = None
        self._last_status_total = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("手机扫码上传")
        title.setProperty("class", "DialogTitle")
        layout.addWidget(title)

        self.lbl_status = QLabel("正在启动上传服务...")
        self.lbl_status.setProperty("class", "DialogInfo")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        network_row = QHBoxLayout()
        network_row.setSpacing(6)
        network_row.addWidget(QLabel("网络地址:"))
        self.combo_upload_host = QComboBox()
        self.combo_upload_host.currentIndexChanged.connect(self._network_host_changed)
        network_row.addWidget(self.combo_upload_host, 1)
        layout.addLayout(network_row)

        self.lbl_qr = QLabel()
        self.lbl_qr.setProperty("class", "QrPanel")
        self.lbl_qr.setAlignment(Qt.AlignCenter)
        self.lbl_qr.setMinimumSize(240, 240)
        layout.addWidget(self.lbl_qr)

        self.txt_url = QLineEdit()
        self.txt_url.setReadOnly(True)
        layout.addWidget(self.txt_url)

        stats_box = QGroupBox("上传统计")
        stats_box.setProperty("class", "CompactGroup")
        stats_layout = QFormLayout(stats_box)
        self.lbl_batch = QLabel("—")
        self.lbl_accepted = QLabel("0")
        self.lbl_duplicate = QLabel("0")
        self.lbl_failed = QLabel("0")
        self.lbl_imported = QLabel("0")
        stats_layout.addRow("批次:", self.lbl_batch)
        stats_layout.addRow("成功:", self.lbl_accepted)
        stats_layout.addRow("重复:", self.lbl_duplicate)
        stats_layout.addRow("失败:", self.lbl_failed)
        stats_layout.addRow("入库:", self.lbl_imported)
        layout.addWidget(stats_box)

        button_row = QHBoxLayout()
        self.btn_copy_url = QPushButton("复制链接")
        self.btn_copy_url.setProperty("class", "SecondaryBtn")
        self.btn_copy_url.clicked.connect(self._copy_url)
        button_row.addWidget(self.btn_copy_url)

        self.btn_stop = QPushButton("停止服务")
        self.btn_stop.setProperty("class", "DangerOutlineBtn")
        self.btn_stop.clicked.connect(self._stop_server)
        button_row.addStretch()
        button_row.addWidget(self.btn_stop)
        layout.addLayout(button_row)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_status)

        self._start_server()

    def _start_server(self):
        try:
            from ..mobile_upload import MobileUploadServer, enumerate_upload_hosts

            self.host_options = enumerate_upload_hosts()
            selected_host = self.host_options[0].host if self.host_options else None
            self.server = MobileUploadServer(
                runtime_dir=RUNTIME_DIR,
                db_path=self.db_path,
                host=selected_host,
                port=0,
                import_on_upload=True,
            )
            self.session = self.server.start()
            self._populate_upload_hosts()
            self.txt_url.setText(self.session.upload_url)
            self.lbl_batch.setText(self.session.batch_id)
            self.lbl_status.setText("请用手机扫描二维码。微信扫码后如文件不好选择，请点击右上角 … 在浏览器打开。\n手机打不开时，确认电脑和手机在同一 Wi-Fi，或切换网络地址。")
            self._render_qr(self.session.upload_url)
            self.timer.start()
        except Exception as exc:
            self.lbl_status.setText(f"上传服务启动失败: {exc}")
            self.btn_stop.setEnabled(False)

    def _populate_upload_hosts(self):
        self.combo_upload_host.blockSignals(True)
        self.combo_upload_host.clear()
        if getattr(self, "host_options", None):
            for option in self.host_options:
                self.combo_upload_host.addItem(option.label, option.host)
        elif self.session:
            self.combo_upload_host.addItem(self.session.host, self.session.host)
        self.combo_upload_host.blockSignals(False)

    def _network_host_changed(self):
        if not self.server or self.combo_upload_host.currentIndex() < 0:
            return
        host = self.combo_upload_host.currentData()
        if not host:
            return
        try:
            self.session = self.server.set_public_host(str(host))
            self.txt_url.setText(self.session.upload_url)
            self._render_qr(self.session.upload_url)
            self.lbl_status.setText("二维码地址已更新。手机打不开时请确认同一 Wi-Fi，或继续切换网络地址。")
        except Exception as exc:
            self.lbl_status.setText(f"切换网络地址失败: {exc}")

    def _render_qr(self, url: str):
        try:
            import qrcode

            image = qrcode.make(url)
            buf = BytesIO()
            image.save(buf, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue(), "PNG")
            self.lbl_qr.setPixmap(pixmap.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            self.lbl_qr.setText("未安装 qrcode 依赖。\n请复制下方链接到手机浏览器打开。")

    def _copy_url(self):
        QApplication.clipboard().setText(self.txt_url.text())
        self.lbl_status.setText("上传链接已复制。")

    def _refresh_status(self):
        if not self.server:
            return
        status = self.server.status()
        self.lbl_accepted.setText(str(status.get("accepted", 0)))
        self.lbl_duplicate.setText(str(status.get("duplicate", 0)))
        self.lbl_failed.setText(str(status.get("failed", 0)))
        self.lbl_imported.setText(str(status.get("imported", 0)))
        total = sum(int(status.get(k, 0) or 0) for k in ("accepted", "duplicate", "failed", "imported"))
        if total and total != self._last_status_total:
            self._last_status_total = total
            self.upload_finished.emit()

    def _stop_server(self):
        if self.server:
            self.server.stop()
            self.server = None
        self.timer.stop()
        self.lbl_status.setText("上传服务已停止，二维码和链接已失效。")
        self.btn_stop.setEnabled(False)

    def closeEvent(self, event):
        self._stop_server()
        event.accept()


class LocalImportWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, import_dir: Path, db_path: Path):
        super().__init__()
        self.import_dir = import_dir
        self.db_path = db_path

    def run(self):
        try:
            from ..services import import_local_directory
            stats = import_local_directory(self.import_dir, self.db_path)
            self.finished.emit(stats)
        except Exception as e:
            self.error.emit(str(e))
        except BaseException as e:
            self.error.emit(str(e))


class EmailScanWorker(QThread):
    log = Signal(str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, db_path: Path):
        super().__init__()
        self.db_path = db_path
        self.summary_logs = []

    def run(self):
        try:
            from ..services import scan_email_and_download

            def gui_log(msg: str):
                self.summary_logs.append(str(msg or ""))
                self.log.emit(msg)

            res = scan_email_and_download(
                db_path=self.db_path,
                log_callback=gui_log
            )
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))
        except BaseException as e:
            self.error.emit(str(e))


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("系统设置")
        self.resize(650, 580)
        self.test_success = False
        self.current_step = 1

        from ..config import load_config_safe, _EMAIL_PROVIDER_PRESETS
        self.cfg = load_config_safe()

        # Tab Widget to isolate Mailbox setup from AI Setup
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)

        self.tab_widget = QTabWidget()
        self.main_layout.addWidget(self.tab_widget)

        # Tab 1: Mailbox Setup Wizard
        self.tab_mailbox = QWidget()
        self._init_mailbox_wizard_tab()
        self.tab_widget.addTab(self.tab_mailbox, "邮箱服务配置")

        # Tab 2: AI Setup Configuration
        self.tab_ai = QWidget()
        self._init_ai_tab()
        self.tab_widget.addTab(self.tab_ai, "AI 辅助分类")

        # Load initial values
        self._load_initial_values()

    def _init_mailbox_wizard_tab(self):
        layout = QVBoxLayout(self.tab_mailbox)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Step Indicator
        self.lbl_step_indicator = QLabel()
        self.lbl_step_indicator.setAlignment(Qt.AlignCenter)
        self.lbl_step_indicator.setProperty("class", "WizardSteps")
        layout.addWidget(self.lbl_step_indicator)

        # Stacked Widget for Steps
        self.step_stack = QStackedWidget()
        layout.addWidget(self.step_stack)

        # Step 1 Widget
        self._init_step1_view()
        # Step 2 Widget
        self._init_step2_view()
        # Step 3 Widget
        self._init_step3_view()

        # Footer Buttons
        footer_layout = QHBoxLayout()
        self.btn_prev = QPushButton("上一步")
        self.btn_prev.clicked.connect(self._goto_prev_step)
        self.btn_prev.setProperty("class", "SecondaryBtn")
        self.btn_prev.setFixedHeight(28)

        self.btn_next = QPushButton("下一步")
        self.btn_next.clicked.connect(self._goto_next_step)
        self.btn_next.setProperty("class", "PrimaryBtn")
        self.btn_next.setFixedHeight(28)

        self.btn_save_wizard = QPushButton("确定保存")
        self.btn_save_wizard.clicked.connect(self._save_mailbox_settings)
        self.btn_save_wizard.setProperty("class", "PrimaryBtn")
        self.btn_save_wizard.setFixedHeight(28)

        self.btn_cancel_wizard = QPushButton("取消")
        self.btn_cancel_wizard.clicked.connect(self.reject)
        self.btn_cancel_wizard.setProperty("class", "SecondaryBtn")
        self.btn_cancel_wizard.setFixedHeight(28)

        footer_layout.addWidget(self.btn_prev)
        footer_layout.addStretch()
        footer_layout.addWidget(self.btn_cancel_wizard)
        footer_layout.addWidget(self.btn_next)
        footer_layout.addWidget(self.btn_save_wizard)
        layout.addLayout(footer_layout)

        # Refresh UI state
        self._update_wizard_ui()

    def _init_step1_view(self):
        step1_widget = QScrollArea()
        step1_widget.setProperty("class", "SettingsScroll")
        step1_widget.setWidgetResizable(True)
        step1_widget.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        scroll_content.setProperty("class", "DialogCanvas")
        v_layout = QVBoxLayout(scroll_content)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(12)

        lbl_intro = QLabel("选择您的邮箱类型：")
        lbl_intro.setProperty("class", "SectionTitle")
        v_layout.addWidget(lbl_intro)

        # Provider cards grid
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        self.provider_group = QButtonGroup(self)
        self.provider_group.setExclusive(True)

        presets = [
            ("qq", "QQ 邮箱", "国内个人首选\n自动识别IMAP"),
            ("netease_163", "163 网易邮箱", "经典个人邮箱\n连接速度极快"),
            ("netease_126", "126 网易邮箱", "网易精品邮\n收发稳定高效"),
            ("gmail", "Gmail", "谷歌邮箱服务\n需海外网络代理"),
            ("outlook", "Outlook", "微软官方邮箱\n支持商务与个人"),
            ("custom", "自定义 IMAP", "支持任意符合协议\n的第三方邮箱服务")
        ]

        self.cards = {}
        self.card_titles = {}
        for idx, (prov_id, title, desc) in enumerate(presets):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(175, 75)
            btn.setProperty("class", "SelectionCard")
            btn_layout = QVBoxLayout(btn)
            btn_layout.setContentsMargins(10, 8, 10, 8)
            btn_layout.setSpacing(2)

            t_lbl = QLabel(title)
            t_lbl.setProperty("class", "SelectionCardTitle")
            t_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            d_lbl = QLabel(desc)
            d_lbl.setProperty("class", "SelectionCardDescription")
            d_lbl.setWordWrap(True)
            d_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)

            btn_layout.addWidget(t_lbl)
            btn_layout.addWidget(d_lbl)

            self.provider_group.addButton(btn)
            self.cards[prov_id] = btn
            self.card_titles[prov_id] = t_lbl
            grid.addWidget(btn, idx // 3, idx % 3)

        self.provider_group.buttonClicked.connect(self._on_provider_card_clicked)
        v_layout.addWidget(grid_widget)

        # Form layout for input fields
        form_group = QGroupBox("邮箱基本配置")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(10)

        self.txt_email = QLineEdit()
        self.txt_email.setPlaceholderText("your_email@example.com")
        self.txt_email.textChanged.connect(self._on_email_text_changed)

        self.txt_months = QLineEdit("3")
        self.txt_months.setPlaceholderText("1-24")

        form_layout.addRow("邮箱地址:", self.txt_email)
        form_layout.addRow("搜索最近 N 个月:", self.txt_months)
        v_layout.addWidget(form_group)

        # Collapsible Advanced Settings
        self.btn_toggle_advanced = QPushButton("显示高级 IMAP 设置 ▼")
        self.btn_toggle_advanced.setProperty("class", "TextBtn")
        self.btn_toggle_advanced.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_advanced.clicked.connect(self._toggle_advanced_settings)
        v_layout.addWidget(self.btn_toggle_advanced)

        self.advanced_group = QGroupBox("高级 IMAP 参数")
        adv_layout = QFormLayout(self.advanced_group)
        adv_layout.setSpacing(8)
        self.txt_imap_server = QLineEdit()
        self.txt_imap_port = QLineEdit()
        adv_layout.addRow("IMAP 服务器:", self.txt_imap_server)
        adv_layout.addRow("IMAP 端口:", self.txt_imap_port)
        v_layout.addWidget(self.advanced_group)

        self.advanced_group.setVisible(False)
        step1_widget.setWidget(scroll_content)
        self.step_stack.addWidget(step1_widget)

    def _init_step2_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(16)

        # Light Info Alert Panel
        alert_box = QFrame()
        alert_box.setProperty("class", "PrivacyPanel")
        alert_layout = QVBoxLayout(alert_box)
        alert_layout.setContentsMargins(12, 12, 12, 12)
        alert_text = QLabel(
            "<b>凭据安全说明</b><br>"
            "您的授权码直接交由 Windows 系统级别的凭据管理器加密存储，不会以明文写入配置，更不会上传至任何第三方服务器。"
        )
        alert_text.setProperty("class", "SectionHint")
        alert_text.setWordWrap(True)
        alert_layout.addWidget(alert_text)
        layout.addWidget(alert_box)

        # Form fields
        form = QFormLayout()
        form.setSpacing(12)

        auth_input_layout = QHBoxLayout()
        self.txt_auth_code = QLineEdit()
        self.txt_auth_code.setEchoMode(QLineEdit.Password)
        self.txt_auth_code.setPlaceholderText("请输入邮箱授权码（非登录密码）")
        self.txt_auth_code.textChanged.connect(self._on_auth_code_changed)

        btn_help = QPushButton("如何获取授权码")
        btn_help.clicked.connect(self._show_auth_code_help)
        btn_help.setProperty("class", "TextBtn")
        btn_help.setCursor(Qt.PointingHandCursor)

        auth_input_layout.addWidget(self.txt_auth_code, 1)
        auth_input_layout.addWidget(btn_help)

        form.addRow("邮箱授权码:", auth_input_layout)
        layout.addLayout(form)

        self.lbl_cred_status = QLabel()
        self.lbl_cred_status.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.lbl_cred_status)
        layout.addStretch()

        self.step_stack.addWidget(widget)

    def _init_step3_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        # Summary box
        sum_box = QGroupBox("邮箱设置摘要")
        sum_form = QFormLayout(sum_box)
        sum_form.setSpacing(8)

        self.lbl_sum_provider = QLabel()
        self.lbl_sum_email = QLabel()
        self.lbl_sum_months = QLabel()
        self.lbl_sum_protocol = QLabel()

        sum_form.addRow("邮箱提供商:", self.lbl_sum_provider)
        sum_form.addRow("邮箱账号:", self.lbl_sum_email)
        sum_form.addRow("检索月份范围:", self.lbl_sum_months)
        sum_form.addRow("接收协议/服务器:", self.lbl_sum_protocol)
        layout.addWidget(sum_box)

        # Verification controls
        test_box = QGroupBox("连接验证测试")
        test_layout = QVBoxLayout(test_box)
        test_layout.setSpacing(10)

        self.lbl_test_result = QLabel("未进行连接测试。")
        self.lbl_test_result.setWordWrap(True)
        self.lbl_test_result.setStyleSheet("color: #6B7280; font-size: 11px;")
        test_layout.addWidget(self.lbl_test_result)

        btn_test_layout = QHBoxLayout()
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(self._test_connection_clicked)
        self.btn_test.setProperty("class", "SecondaryBtn")
        self.btn_test.setFixedSize(120, 28)
        btn_test_layout.addWidget(self.btn_test)
        btn_test_layout.addStretch()
        test_layout.addLayout(btn_test_layout)

        layout.addWidget(test_box)
        layout.addStretch()

        self.step_stack.addWidget(widget)

    def _init_ai_tab(self):
        layout = QVBoxLayout(self.tab_ai)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Config box
        ai_box = QGroupBox("AI 辅助分类配置")
        ai_form = QFormLayout(ai_box)
        ai_form.setSpacing(12)

        self.combo_ai_provider = QComboBox()
        self.combo_ai_provider.addItems(["none", "deepseek", "gemini"])
        self.combo_ai_provider.currentTextChanged.connect(self._on_ai_provider_changed)

        self.txt_ai_model = QComboBox()
        self.txt_ai_model.setEditable(True)
        self.txt_ai_model.lineEdit().setPlaceholderText("请选择或输入模型名称")

        self.lbl_ai_key_status = QLabel()
        self.lbl_ai_key_status.setWordWrap(True)
        self.lbl_ai_key_status.setStyleSheet("font-size: 11px;")

        self.lbl_ai_key_title = QLabel("API Key:")
        self.txt_ai_key = QLineEdit()
        self.txt_ai_key.setEchoMode(QLineEdit.Password)

        ai_form.addRow("AI 分类提供商:", self.combo_ai_provider)
        ai_form.addRow("模型名称:", self.txt_ai_model)
        ai_form.addRow(self.lbl_ai_key_status)
        ai_form.addRow(self.lbl_ai_key_title, self.txt_ai_key)

        lbl_ai_note = QLabel(
            "提示：不配置 AI 也可以正常导入和审核发票（AI 默认关闭）。\n"
            "建议：发票邮件分类推荐使用便宜且快速的模型（例如 deepseek-v4-flash 或 gemini-2.5-flash）。\n"
            "隐私提示：显式启用 AI 时，仅发送脱敏后的邮件主题和发件人；默认不上传发票附件、PDF 文本或生成的 Excel 报表。"
        )
        lbl_ai_note.setStyleSheet("color: #6B7280; font-size: 11px;")
        lbl_ai_note.setWordWrap(True)
        ai_form.addRow(lbl_ai_note)

        layout.addWidget(ai_box)
        layout.addStretch()

        # Dedicated AI Save button
        ai_footer = QHBoxLayout()
        btn_save_ai = QPushButton("保存 AI 配置")
        btn_save_ai.clicked.connect(self._save_ai_settings)
        btn_save_ai.setProperty("class", "PrimaryBtn")
        btn_save_ai.setFixedHeight(28)

        btn_cancel_ai = QPushButton("取消")
        btn_cancel_ai.clicked.connect(self.reject)
        btn_cancel_ai.setProperty("class", "SecondaryBtn")
        btn_cancel_ai.setFixedHeight(28)

        ai_footer.addStretch()
        ai_footer.addWidget(btn_save_ai)
        ai_footer.addWidget(btn_cancel_ai)
        layout.addLayout(ai_footer)

    def _load_initial_values(self):
        # Email settings
        current_provider = self.cfg.get("email", {}).get("provider", "qq")
        self._select_provider_card(current_provider)

        self.txt_email.setText(self.cfg.get("email", {}).get("address", ""))
        self.txt_months.setText(str(self.cfg.get("search", {}).get("months_back", 3)))

        if current_provider == "custom":
            self.advanced_group.setVisible(True)
            self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲")
            self.txt_imap_server.setText(self.cfg.get("imap", {}).get("server", ""))
            self.txt_imap_port.setText(str(self.cfg.get("imap", {}).get("port", 993)))
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(current_provider, _EMAIL_PROVIDER_PRESETS["qq"])
            self.txt_imap_server.setText(preset["server"])
            self.txt_imap_port.setText(str(preset["port"]))

        # AI settings
        ai_prov = self.cfg.get("ai", {}).get("provider", "none")
        self.combo_ai_provider.setCurrentText(ai_prov)
        saved_model = self.cfg.get("ai", {}).get("model", "")
        if saved_model:
            self.txt_ai_model.setCurrentText(saved_model)

        self._update_cred_status_label()

    def _get_selected_provider(self):
        for prov_id, card in self.cards.items():
            if card.isChecked():
                return prov_id
        return "qq"

    def _select_provider_card(self, provider):
        if provider in self.cards:
            self.cards[provider].setChecked(True)
            self._refresh_provider_card_visuals()

    def _refresh_provider_card_visuals(self):
        for provider, title_label in self.card_titles.items():
            title_label.setProperty("selected", self.cards[provider].isChecked())
            title_label.style().unpolish(title_label)
            title_label.style().polish(title_label)

    def _on_provider_card_clicked(self, checked_btn):
        self._refresh_provider_card_visuals()
        provider = self._get_selected_provider()
        if provider == "custom":
            self.advanced_group.setVisible(True)
            self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲")
        else:
            self.advanced_group.setVisible(False)
            self.btn_toggle_advanced.setText("显示高级 IMAP 设置 ▼")
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider)
            if preset:
                self.txt_imap_server.setText(preset["server"])
                self.txt_imap_port.setText(str(preset["port"]))

    def _update_cred_status_label(self):
        from ..credentials import has_auth_code
        email = self.txt_email.text().strip()
        if not email:
            self.lbl_cred_status.setText("🔒 授权码状态：<b>未输入邮箱地址</b>")
            return
        if has_auth_code(email):
            self.lbl_cred_status.setText("🔒 授权码状态：<font color='#10B981'><b>已安全保存到系统凭据管理器</b></font>")
        else:
            self.lbl_cred_status.setText("🔒 授权码状态：<font color='#EF4444'><b>尚未配置 (点击下一步并保存时将自动加密保存)</b></font>")

    def _on_email_text_changed(self):
        email = self.txt_email.text().strip().lower()
        if "@qq.com" in email:
            self._select_provider_card("qq")
        elif "@163.com" in email:
            self._select_provider_card("netease_163")
        elif "@126.com" in email:
            self._select_provider_card("netease_126")
        elif "@gmail.com" in email:
            self._select_provider_card("gmail")
        elif "@outlook.com" in email or "@hotmail.com" in email or "@live.com" in email:
            self._select_provider_card("outlook")
        self._update_cred_status_label()

    def _on_auth_code_changed(self):
        self.test_success = False
        self.lbl_test_result.setText("邮箱授权码已更改，请重新进行连接测试。")
        self.lbl_test_result.setStyleSheet("color: #D97706; font-size: 11px;")

    def _toggle_advanced_settings(self):
        visible = not self.advanced_group.isVisible()
        self.advanced_group.setVisible(visible)
        self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲" if visible else "显示高级 IMAP 设置 ▼")

    def _on_ai_provider_changed(self):
        provider = self.combo_ai_provider.currentText()

        # Populate model items based on provider
        self.txt_ai_model.clear()
        if provider == "deepseek":
            self.txt_ai_model.addItems(["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"])
            self.txt_ai_model.setCurrentText("deepseek-v4-flash")
            self.txt_ai_model.setEnabled(True)
        elif provider == "gemini":
            self.txt_ai_model.addItems(["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"])
            self.txt_ai_model.setCurrentText("gemini-2.5-flash")
            self.txt_ai_model.setEnabled(True)
        else: # none
            self.txt_ai_model.setEnabled(False)

        if provider == "none":
            self.lbl_ai_key_status.setVisible(False)
            self.lbl_ai_key_title.setVisible(False)
            self.txt_ai_key.setVisible(False)
            return

        self.lbl_ai_key_status.setVisible(True)
        self.lbl_ai_key_title.setVisible(True)
        self.txt_ai_key.setVisible(True)

        from ..credentials import has_ai_api_key
        if has_ai_api_key(provider):
            self.lbl_ai_key_status.setText(
                "🔑 API Key 状态：<font color='#10B981'><b>已安全保存到系统凭据管理器</b></font>（输入新值可覆盖，留空则保持不变）"
            )
            self.txt_ai_key.setPlaceholderText("••••••••••••••••")
        else:
            self.lbl_ai_key_status.setText(
                "🔑 API Key 状态：<font color='#EF4444'><b>尚未配置</b></font>"
            )
            self.txt_ai_key.setPlaceholderText("请输入 API Key")

    def _show_auth_code_help(self):
        QMessageBox.information(
            self,
            "如何获取邮箱授权码？",
            "<b>什么是授权码？</b><br>"
            "授权码（或应用专用密码）是专门用于第三方程序读取邮件的专属密码，<b>绝非您的邮箱登录密码</b>，可随时注销。<br><br>"
            "<b>获取步骤：</b><br>"
            "• <b>QQ邮箱：</b><br>"
            "  1. 登录网页版 QQ 邮箱。<br>"
            "  2. 进入「设置」 ➜ 「账号」。<br>"
            "  3. 滚动至「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」。<br>"
            "  4. 开启「POP3/IMAP服务」服务，验证后获取<b>16位独立授权码</b>。<br><br>"
            "• <b>163 / 126 网易邮箱：</b><br>"
            "  1. 登录网页版网易邮箱。<br>"
            "  2. 选择上方「设置」 ➜ 「POP3/SMTP/IMAP」。<br>"
            "  3. 开启「IMAP/SMTP服务」。<br>"
            "  4. 新增授权密码，按手机短信指引获取授权码。<br><br>"
            "• <b>Gmail 邮箱：</b><br>"
            "  1. 登录网页版 Google 账号中心（myaccount.google.com）。<br>"
            "  2. 进入「安全性」 ➜ 「双重验证」并开启。<br>"
            "  3. 搜索并进入「应用专用密码」创建专有密码，获取 <b>16 位专用密码</b>。<br>"
            "  4. 确保在网页版 Gmail 设置 ➜ 「转发和 POP/IMAP」中手动启用了 IMAP 收信。<br><br>"
            "• <b>Outlook / Hotmail 邮箱：</b><br>"
            "  1. 登录网页版微软账号中心 (account.microsoft.com)。<br>"
            "  2. 进入「安全性」 ➜ 「高级安全选项」。<br>"
            "  3. 开启「双重验证」后，在下方生成「应用密码」进行登录。<br><br>"
            "<b>隐私安全说明：</b><br>"
            "您的授权码直接交由 Windows 系统级别的凭据管理器加密存储，不会以明文写入配置，更不会上传至任何第三方服务器。"
        )

    def _goto_next_step(self):
        if self.current_step == 1:
            email = self.txt_email.text().strip()
            if not email:
                QMessageBox.warning(self, "校验提示", "请先填写邮箱地址。")
                return
            provider = self._get_selected_provider()
            if provider == "custom":
                server = self.txt_imap_server.text().strip()
                port = self.txt_imap_port.text().strip()
                if not server or not port:
                    QMessageBox.warning(self, "校验提示", "自定义 IMAP 必须填写服务器和端口。")
                    return
            self.current_step = 2
        elif self.current_step == 2:
            self.current_step = 3

        self._update_wizard_ui()

    def _goto_prev_step(self):
        if self.current_step > 1:
            self.current_step -= 1
            self._update_wizard_ui()

    def _update_wizard_ui(self):
        # Update stack index
        self.step_stack.setCurrentIndex(self.current_step - 1)

        # Update step highlights
        if self.current_step == 1:
            self.lbl_step_indicator.setText('<font color="#2563EB"><b>① 选择邮箱</b></font>  ➜  ② 填写授权码  ➜  ③ 测试并保存')
            self.btn_prev.setEnabled(False)
            self.btn_next.setVisible(True)
            self.btn_save_wizard.setVisible(False)
        elif self.current_step == 2:
            self.lbl_step_indicator.setText('① 选择邮箱  ➜  <font color="#2563EB"><b>② 填写授权码</b></font>  ➜  ③ 测试并保存')
            self.btn_prev.setEnabled(True)
            self.btn_next.setVisible(True)
            self.btn_save_wizard.setVisible(False)
            self._update_cred_status_label()
        elif self.current_step == 3:
            self.lbl_step_indicator.setText('① 选择邮箱  ➜  ② 填写授权码  ➜  <font color="#2563EB"><b>③ 测试并保存</b></font>')
            self.btn_prev.setEnabled(True)
            self.btn_next.setVisible(False)
            self.btn_save_wizard.setVisible(True)
            self._update_summary_fields()

    def _update_summary_fields(self):
        provider = self._get_selected_provider()
        prov_map = {
            "qq": "QQ 邮箱",
            "netease_163": "163 网易邮箱",
            "netease_126": "126 网易邮箱",
            "gmail": "Gmail",
            "outlook": "Outlook",
            "custom": "自定义 IMAP"
        }
        self.lbl_sum_provider.setText(prov_map.get(provider, "QQ 邮箱"))
        self.lbl_sum_email.setText(self.txt_email.text().strip())
        self.lbl_sum_months.setText(f"最近 {self.txt_months.text().strip()} 个月")

        if provider == "custom":
            server = self.txt_imap_server.text().strip()
            port = self.txt_imap_port.text().strip()
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider, _EMAIL_PROVIDER_PRESETS["qq"])
            server = preset["server"]
            port = str(preset["port"])
        self.lbl_sum_protocol.setText(f"IMAP ({server}:{port})")

    def _test_connection_clicked(self):
        email = self.txt_email.text().strip()
        auth_code = self.txt_auth_code.text().strip()

        if not email:
            QMessageBox.warning(self, "校验提示", "请先填写邮箱地址。")
            return

        if not auth_code:
            from ..credentials import get_auth_code
            try:
                auth_code = get_auth_code(email) or ""
            except SystemExit:
                auth_code = ""
            if not auth_code:
                QMessageBox.warning(self, "校验提示", "请先输入邮箱授权码。")
                return

        provider = self._get_selected_provider()
        if provider == "custom":
            server = self.txt_imap_server.text().strip()
            port_str = self.txt_imap_port.text().strip()
            if not server or not port_str:
                QMessageBox.warning(self, "校验提示", "自定义 IMAP 必须填写服务器与端口。")
                return
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider)
            server = preset["server"]
            port_str = str(preset["port"])

        try:
            port = int(port_str)
        except ValueError:
            QMessageBox.warning(self, "校验提示", "IMAP 端口必须是有效的整数。")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.btn_test.setEnabled(False)
        self.btn_test.setText("正在测试...")
        self.lbl_test_result.setStyleSheet("color: #4B5563; font-size: 11px;")
        self.lbl_test_result.setText("正在尝试连接 IMAP 服务器进行登录验证，请稍候...")
        QApplication.processEvents()

        try:
            from ..mail_fetcher import MailFetcher
            fetcher = MailFetcher(address=email, auth_code=auth_code, server=server, port=port)
            fetcher.connect()
            fetcher.disconnect()

            self.test_success = True
            prov_text = self.lbl_sum_provider.text()
            self.lbl_test_result.setStyleSheet("color: #10B981; font-weight: bold; font-size: 11px;")
            self.lbl_test_result.setText(f"✅ 已连接到 {prov_text}，可扫描最近 {self.txt_months.text().strip()} 个月发票邮件。")
        except Exception as e:
            self.test_success = False
            self.lbl_test_result.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 11px;")
            err_msg = str(e).lower()
            if "login failed" in err_msg or "authentication failed" in err_msg or "credential" in err_msg or "invalid credentials" in err_msg or "authori" in err_msg or "登录失败" in err_msg:
                friendly = "❌ 测试连接失败：授权码错误或 IMAP 服务未开启"
            elif "getaddrinfo" in err_msg or "timed out" in err_msg or "timeout" in err_msg or "connection timed out" in err_msg:
                friendly = "❌ 测试连接失败：网络连接失败"
            elif "refused" in err_msg or "connection refused" in err_msg or "wrong port" in err_msg or "socket" in err_msg or "ssl" in err_msg:
                friendly = "❌ 测试连接失败：IMAP服务器/端口配置有误"
            elif "未找到授权码" in err_msg:
                friendly = "❌ 测试连接失败：未找到授权码"
            else:
                friendly = "❌ 测试连接失败：授权码错误或 IMAP 未开启；或网络、服务器、端口配置有误。"
            self.lbl_test_result.setText(friendly)
        finally:
            self.btn_test.setEnabled(True)
            self.btn_test.setText("测试连接")
            QApplication.restoreOverrideCursor()

    def _save_mailbox_settings(self):
        email = self.txt_email.text().strip()
        provider = self._get_selected_provider()
        months_str = self.txt_months.text().strip()

        if provider == "custom":
            imap_server = self.txt_imap_server.text().strip()
            imap_port_str = self.txt_imap_port.text().strip()
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider)
            imap_server = preset["server"]
            imap_port_str = str(preset["port"])

        proposed_cfg = {
            "email": {
                "provider": provider,
                "address": email
            },
            "imap": {
                "server": imap_server,
                "port": imap_port_str
            },
            "search": {
                "months_back": months_str
            },
            "ai": self.cfg.get("ai", {
                "provider": "none",
                "model": "",
                "enabled": False
            })
        }

        from ..config import save_config, validate_config_gui
        try:
            validate_config_gui(proposed_cfg)
        except ValueError as val_err:
            QMessageBox.warning(self, "设置验证失败", str(val_err))
            return

        if not self.test_success:
            reply = QMessageBox.question(
                self,
                "连接未验证",
                "邮箱连接尚未测试成功，是否仍保存？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        # Save credentials to system Keyring
        auth_code = self.txt_auth_code.text().strip()
        if auth_code:
            from ..credentials import set_auth_code
            try:
                set_auth_code(email, auth_code)
                self.parent.write_log(f"💾 [安全凭证] 邮箱 {email} 的授权码凭证已自动保存到 Windows 凭据管理器中。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存凭据失败: {e}")
                return

        # Update configuration
        self.cfg.setdefault("email", {})
        self.cfg.setdefault("imap", {})
        self.cfg.setdefault("search", {})
        self.cfg.setdefault("ai", {})
        self.cfg["email"]["provider"] = provider
        self.cfg["email"]["address"] = email
        self.cfg["email"]["username"] = email
        self.cfg["imap"]["server"] = imap_server
        self.cfg["imap"]["port"] = int(imap_port_str)
        self.cfg["imap"]["ssl"] = True
        self.cfg["search"]["folder"] = "INBOX"
        self.cfg["search"]["months_back"] = int(months_str)

        provider_names = {
            "qq": "QQ 邮箱",
            "netease_163": "163 网易邮箱",
            "netease_126": "126 网易邮箱",
            "gmail": "Gmail",
            "outlook": "Outlook",
            "custom": "自定义 IMAP",
        }
        account = {
            "name": provider_names.get(provider, provider),
            "enabled": True,
            "provider": provider,
            "address": email,
            "username": email,
            "imap": {
                "server": imap_server,
                "port": int(imap_port_str),
                "ssl": True,
            },
            "search": {
                "folder": "INBOX",
                "months_back": int(months_str),
            },
            "mailbox_key": email.lower(),
        }
        raw_accounts = self.cfg.get("email_accounts")
        email_accounts = [
            dict(existing)
            for existing in raw_accounts
            if isinstance(existing, dict)
        ] if isinstance(raw_accounts, list) else []
        match_index = next(
            (
                index
                for index, existing in enumerate(email_accounts)
                if str(existing.get("address") or "").strip().lower() == email.lower()
                or str(existing.get("mailbox_key") or "").strip().lower() == email.lower()
            ),
            None,
        )
        if match_index is None:
            email_accounts.append(account)
        else:
            email_accounts[match_index] = account
        self.cfg["email_accounts"] = email_accounts

        try:
            save_config(self.cfg)
            self.parent.config = load_config_safe()
            self.parent.write_log(f"⚙️ [设置保存] 全局 config.json 邮箱服务配置已成功保存。")
            QMessageBox.information(self, "成功", "邮箱设置已成功保存！")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置文件失败: {e}")

    def _save_ai_settings(self):
        ai_provider = self.combo_ai_provider.currentText()
        ai_model = self.txt_ai_model.currentText().strip()
        ai_key = self.txt_ai_key.text().strip()

        proposed_cfg = {
            "email": self.cfg.get("email", {
                "provider": "qq",
                "address": ""
            }),
            "imap": self.cfg.get("imap", {
                "server": "imap.qq.com",
                "port": 993
            }),
            "search": self.cfg.get("search", {
                "months_back": 3
            }),
            "ai": {
                "provider": ai_provider,
                "model": ai_model
            }
        }

        from ..config import save_config, validate_config_gui
        try:
            validate_config_gui(proposed_cfg)
        except ValueError as val_err:
            QMessageBox.warning(self, "AI 设置验证失败", str(val_err))
            return

        # Save AI API Key to Keyring (only if provider is not "none" and key is provided)
        if ai_provider != "none" and ai_key:
            from ..credentials import set_ai_api_key
            try:
                set_ai_api_key(ai_provider, ai_key)
                self.parent.write_log(f"💾 [安全凭证] AI 提供商 {ai_provider} 的 API Key 已保存到 Windows 凭据管理器中。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存 AI 凭据失败: {e}")
                return

        # Update global config dict
        self.cfg.setdefault("ai", {})
        self.cfg["ai"]["provider"] = ai_provider
        self.cfg["ai"]["model"] = ai_model
        self.cfg["ai"]["enabled"] = (ai_provider != "none")

        try:
            save_config(self.cfg)
            self.parent.config = load_config_safe()
            self.parent.write_log(f"⚙️ [设置保存] 全局 config.json AI 辅助分类配置已成功保存。")
            QMessageBox.information(self, "成功", "AI 分类配置已成功保存！")
            self._on_ai_provider_changed()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存 AI 配置文件失败: {e}")


class StartupSplash(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(400, 220)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Glassmorphic Dark Container
        self.container = QFrame(self)
        self.container.setObjectName("SplashContainer")
        self.container.setStyleSheet("""
            QFrame#SplashContainer {
                background-color: #1F2937;
                border: 1px solid #374151;
                border-radius: 12px;
            }
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(30, 30, 30, 30)
        container_layout.setSpacing(15)

        # App Title
        self.title_label = QLabel("Invoice Hub", self)
        self.title_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self.title_label.setStyleSheet("color: white; border: none; background: transparent;")
        self.title_label.setAlignment(Qt.AlignCenter)
        container_layout.addWidget(self.title_label)

        # Separator line
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #374151; max-height: 1px; border: none;")
        container_layout.addWidget(line)

        # Subtitle / status
        self.status_label = QLabel("正在启动 Invoice Hub...", self)
        self.status_label.setFont(QFont("Segoe UI", 10))
        self.status_label.setStyleSheet("color: #9CA3AF; border: none; background: transparent;")
        self.status_label.setAlignment(Qt.AlignCenter)
        container_layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #374151;
                height: 4px;
                border-radius: 2px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 2px;
            }
        """)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(10)
        container_layout.addWidget(self.progress_bar)

        layout.addWidget(self.container)

        # Center on screen
        self._center()

    def _center(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            x = (geo.width() - self.width()) // 2
            y = (geo.height() - self.height()) // 2
            self.move(x, y)

    def show_message(self, message: str, progress_val: int = None):
        self.status_label.setText(message)
        if progress_val is not None:
            self.progress_bar.setValue(progress_val)
        # Force processing of events to update immediately!
        QApplication.processEvents()


def start_gui_app(db_path: Path, startup_probe: bool = False, app_init_ms: int = 0):
    """QApplication instantiation launcher.

    Args:
        db_path: Path to the SQLite database.
        startup_probe: If True, exit immediately after the first idle event-loop
            cycle (used for CI startup-performance measurement).
        app_init_ms: Pre-measured import-time cost in milliseconds (APP_INIT_MS).
    """
    import time as _time
    import json
    _t_launch = _time.monotonic()
    app = QApplication(sys.argv)

    env_probe = os.environ.get("INVOICE_HUB_STARTUP_PROBE") == "1"
    is_probe = startup_probe or env_probe

    splash = None
    if not is_probe:
        splash = StartupSplash()
        splash.show()
        splash.show_message("正在启动 Invoice Hub...", 15)

    window = InvoiceReviewApp(db_path, splash=splash, startup_probe=is_probe)

    if is_probe:
        main_window_show_ms = 0
        startup_ms = app_init_ms
        db_open_ms = getattr(window, "db_open_ms", 0)
        gui_init_ms = getattr(window, "gui_init_ms", 0)
        first_load_ms = getattr(window, "first_load_ms", 0)
        first_paint_ms = 0
        total_startup_ms = app_init_ms
    else:
        window.show()

        _t_shown = _time.monotonic()
        main_window_show_ms = int((_t_shown - _t_launch) * 1000)
        startup_ms = app_init_ms + main_window_show_ms
        db_open_ms = getattr(window, "db_open_ms", 0)
        gui_init_ms = getattr(window, "gui_init_ms", 0)
        first_load_ms = getattr(window, "first_load_ms", 0)
        first_paint_ms = int((_t_shown - _t_launch) * 1000)
        total_startup_ms = app_init_ms + first_paint_ms

    if is_probe:
        # Emit structured timing metrics to stdout for CI parsing.
        print(f"APP_INIT_MS={app_init_ms}", flush=True)
        print(f"DB_OPEN_MS={db_open_ms}", flush=True)
        print(f"MAIN_WINDOW_SHOW_MS={main_window_show_ms}", flush=True)
        print(f"STARTUP_MS={startup_ms}", flush=True)
        print(f"GUI_INIT_MS={gui_init_ms}", flush=True)
        print(f"FIRST_LOAD_MS={first_load_ms}", flush=True)
        print(f"FIRST_PAINT_MS={first_paint_ms}", flush=True)
        print(f"TOTAL_STARTUP_MS={total_startup_ms}", flush=True)
        _log.info(
            "[startup-probe] APP_INIT_MS=%d  DB_OPEN_MS=%d  MAIN_WINDOW_SHOW_MS=%d  STARTUP_MS=%d  GUI_INIT_MS=%d  FIRST_LOAD_MS=%d  FIRST_PAINT_MS=%d  TOTAL_STARTUP_MS=%d",
            app_init_ms, db_open_ms, main_window_show_ms, startup_ms, gui_init_ms, first_load_ms, first_paint_ms, total_startup_ms,
        )

        probe_file = os.environ.get("INVOICE_HUB_STARTUP_PROBE_FILE")
        if probe_file:
            try:
                metrics_data = {
                    "STARTUP_MS": startup_ms,
                    "APP_INIT_MS": app_init_ms,
                    "DB_OPEN_MS": db_open_ms,
                    "MAIN_WINDOW_SHOW_MS": main_window_show_ms,
                    "GUI_INIT_MS": gui_init_ms,
                    "FIRST_LOAD_MS": first_load_ms,
                    "FIRST_PAINT_MS": first_paint_ms,
                    "TOTAL_STARTUP_MS": total_startup_ms,
                }
                with open(probe_file, "w", encoding="utf-8") as f:
                    json.dump(metrics_data, f, indent=2)
                _log.info("Startup probe metrics written to file: %s", probe_file)
            except Exception as exc:
                _log.error("Failed to write startup probe file: %s", exc)

        os._exit(0)

    sys.exit(app.exec())
