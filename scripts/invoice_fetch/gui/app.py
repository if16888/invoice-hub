# -*- coding: utf-8 -*-
"""
Invoice Hub PySide6 App Window
"""

import json
import os
import sys
import logging
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QLineEdit,
    QTextEdit, QPlainTextEdit, QPushButton, QLabel, QMessageBox, QCheckBox,
    QScrollArea, QAbstractItemView, QHeaderView, QFileDialog,
    QStackedWidget, QProgressBar, QFrame, QTabWidget, QMenu, QSizePolicy,
    QButtonGroup, QGridLayout, QStyle, QLayout, QToolButton
)
from PySide6.QtCore import Qt, QUrl, QTimer, QEvent, QPoint
from PySide6.QtGui import QShortcut
from PySide6.QtGui import QFont, QColor, QDesktopServices, QAction

from ..db import InvoiceDB, is_pending_evidence_invoice
from .. import APP_VERSION
from ..config import PROJECT_ROOT, RUNTIME_DIR, load_config_safe, save_config
from ..diagnostics import collect_app_info, export_diagnostics_zip
from ..reimbursement import amount_total, buyer_warning, format_amount_total, get_date_warning
from ..review_status import TO_REVIEW, APPROVED, IGNORED, ERROR
from ..log_privacy import PrivacyLogFilter, mask_email, sanitize_log_message
from .styles import APP_STYLESHEET
from .helpers import _mask_url, _read_manifest_summary, resolve_stored_path
from .invoice_detail_panel import InvoiceDetailCallbacks, InvoiceDetailPanel
from .log_diagnostics_mixin import LogDiagnosticsMixin, LOG_DRAWER_EXPANDED_HEIGHT
from .mobile_upload_dialog import MobileUploadDialog
from .preview_mixin import PreviewMixin, check_has_qt_pdf, get_qt_pdf_classes
from .settings_dialog import SettingsDialog
from .workers import EmailScanWorker, LocalImportWorker
from .column_filters import (
    COLUMN_DEFINITIONS,
    COLUMN_KEYS,
    ColumnFilterPopup,
    apply_column_filters,
    has_active_filters,
    is_filter_active,
    unique_column_values,
)

_log = logging.getLogger("invoice_fetch.gui.app")
_log.addFilter(PrivacyLogFilter())

GITHUB_ISSUES_URL = "https://github.com/if16888/invoice-hub/issues/new/choose"
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


REDOWNLOAD_BUCKETS = (
    "file_restored",
    "metadata_refreshed",
    "duplicate_only",
    "download_failed",
    "no_candidate_link",
)


def _bucket_redownload_status(status: str) -> str:
    status = str(status or "")
    if status == "file_restored":
        return "file_restored"
    if status in {"metadata_refreshed", "manual_required", "recorded"}:
        return "metadata_refreshed"
    if status == "duplicate":
        return "duplicate_only"
    if status == "no_candidate_link":
        return "no_candidate_link"
    return "download_failed"


def _is_file_valid_and_openable(path) -> bool:
    if not path:
        return False
    try:
        if not os.path.exists(path):
            return False
        with open(path, "rb") as f:
            f.read(10)
        return True
    except Exception:
        return False


def _format_redownload_bucket_summary(count: int, buckets: dict, failure_details: list[str] | None = None) -> str:
    failure_details = failure_details or []
    msg = (
        f"已完成 {count} 张发票的重新下载流程！\n\n"
        f"原文件修复成功: {int(buckets.get('file_restored', 0) or 0)} 张\n"
        f"仅刷新元数据/待手动下载: {int(buckets.get('metadata_refreshed', 0) or 0)} 张\n"
        f"仅命中已有重复记录: {int(buckets.get('duplicate_only', 0) or 0)} 张\n"
        f"下载失败: {int(buckets.get('download_failed', 0) or 0)} 张\n"
        f"无候选链接: {int(buckets.get('no_candidate_link', 0) or 0)} 张"
    )
    if int(buckets.get("duplicate_only", 0) or 0) > 0 and int(buckets.get("file_restored", 0) or 0) == 0:
        msg += "\n\n已确认是已有发票，但未恢复原件文件。可能需要手动补充原件或稍后重试。"

    if failure_details:
        msg += "\n\n以下发票仍然失败:\n" + "\n".join(failure_details[:10])
        if len(failure_details) > 10:
            msg += f"\n... 以及其他 {len(failure_details) - 10} 个文件"
    return msg


class InvoiceReviewApp(PreviewMixin, LogDiagnosticsMixin, QMainWindow):
    def __init__(self, db_path: Path, splash=None, startup_probe: bool = False):
        # Guard against invalid QFont point size warning (point size <= 0)
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont
        app = QApplication.instance()
        if app:
            f = app.font()
            if f.pointSize() <= 0:
                f.setPointSize(9)
                app.setFont(f)

        super().__init__()
        # Guard main window font as well
        f = self.font()
        if f.pointSize() <= 0:
            f.setPointSize(9)
            self.setFont(f)

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
        self.column_filters: dict[str, dict] = {}
        self._column_filters_load_all = False
        self._column_filter_popup = None
        self._column_filter_header_press_pos: QPoint | None = None
        self._deferred_init_done = False
        self._first_load_notice = None
        self._last_scan_summary = {}
        self._limited_first_load_active = False
        self._limited_first_load_total = 0
        self._select_row_hint = -1  # hint for post-delete row selection

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
        self.btn_import_local.setAutoDefault(False)
        self.btn_import_local.setDefault(False)
        action_layout.addWidget(self.btn_import_local)

        self.btn_mobile_upload = QPushButton("扫码上传")
        self.btn_mobile_upload.clicked.connect(self._mobile_upload_clicked)
        self.btn_mobile_upload.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_mobile_upload.setProperty("class", "ToolbarActionBtn")
        self.btn_mobile_upload.setAutoDefault(False)
        self.btn_mobile_upload.setDefault(False)
        action_layout.addWidget(self.btn_mobile_upload)

        self.btn_scan_email = QPushButton("扫描邮箱")
        self.btn_scan_email.clicked.connect(self._scan_email_clicked)
        self.btn_scan_email.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_scan_email.setProperty("class", "ToolbarActionBtn")
        self.btn_scan_email.setAutoDefault(False)
        self.btn_scan_email.setDefault(False)
        action_layout.addWidget(self.btn_scan_email)

        self.btn_toolbar_export = QPushButton("一键导出")
        self.btn_toolbar_export.clicked.connect(self._export_claim_package)
        self.btn_toolbar_export.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_toolbar_export.setProperty("class", "ToolbarActionBtn")
        self.btn_toolbar_export.setAutoDefault(False)
        self.btn_toolbar_export.setDefault(False)
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
        self.table.setHorizontalHeaderLabels([f"{label} ▾" for _key, label, _kind in COLUMN_DEFINITIONS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.verticalHeader().setMinimumSectionSize(24)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().sectionClicked.connect(self._show_column_filter_popup)
        self.table.horizontalHeader().viewport().installEventFilter(self)
        self._refresh_column_filter_headers()

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

        # Right Column - InvoiceDetailPanel
        self._setup_detail_panel()
        splitter.addWidget(self._detail_panel)
        self._proxy_detail_panel_attrs()
        # Populate category dropdown after proxies are set up
        self._refresh_category_options()

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

    # ── Detail panel wiring ────────────────────────────────────

    def _setup_detail_panel(self):
        cbs = InvoiceDetailCallbacks(
            on_approve_next=lambda: self._set_selected_status(APPROVED),
            on_ignore=lambda: self._set_selected_status(IGNORED),
            on_mark_error=lambda: self._set_selected_status(ERROR),
            on_reset_review=lambda: self._set_selected_status(TO_REVIEW),
            on_delete_or_restore=self._handle_detail_delete_clicked,
            on_open_file=self._open_attachment,
            on_add_attachment=self._add_attachment_manually,
            on_add_evidence=self._add_evidence_manually,
            on_retry_download=self._retry_download_link,
            on_open_evidence=self._open_extra_docs,
            on_copy_number=self._copy_invoice_number,
            on_locate_file=self._locate_attachment_file,
            on_open_dir=self._locate_attachment,
            on_create_claim=self._create_claim,
            on_link_to_claim=self._link_invoices_to_claim,
            on_refresh_claims=self._load_claims,
            on_export_claim=self._export_claim_package,
            on_save_fields=self._save_invoice_fields,
            on_form_dirty=self._mark_invoice_form_dirty,
            on_supporting_doc_changed=self._on_supporting_docs_combo_changed,
            on_claim_combo_changed=self._update_claim_total,
        )
        self._detail_panel = InvoiceDetailPanel(callbacks=cbs)
        self._detail_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _proxy_detail_panel_attrs(self):
        """Proxy commonly-accessed panel attributes for backward compatibility."""
        dp = self._detail_panel
        # Summary card
        self.summary_card = dp.summary_card
        self.lbl_sum_amount = dp.lbl_sum_amount
        self.lbl_sum_status = dp.lbl_sum_status
        self.lbl_sum_date = dp.lbl_sum_date
        self.lbl_sum_number = dp.lbl_sum_number
        self.lbl_sum_seller = dp.lbl_sum_seller
        self.lbl_sum_category = dp.lbl_sum_category
        self.lbl_date_warning = dp.lbl_date_warning
        # Review actions
        self.inline_review_layout = dp.inline_review_layout
        self.btn_app = dp.btn_app
        self.btn_ign = dp.btn_ign
        self.btn_err = dp.btn_err
        self.btn_inline_more = dp.btn_inline_more
        self.inline_more_menu = dp.inline_more_menu
        self.action_inline_reset = dp.action_inline_reset
        self.action_inline_delete = dp.action_inline_delete
        self.action_copy_number = dp.action_copy_number
        self.action_locate_file = dp.action_locate_file
        self.action_open_dir = dp.action_open_dir
        # Compat deprecated
        self.review_actions_section = dp.review_actions_section
        self.lbl_batch_hint = dp.lbl_batch_hint
        self.btn_rev = dp.btn_rev
        self.btn_delete_invoice = dp.btn_delete_invoice
        # Core info
        self.detail_core_section = dp.detail_core_section
        self.invoice_core_grid = dp.invoice_core_grid
        self.txt_number = dp.txt_number
        self.txt_date = dp.txt_date
        self.txt_amount = dp.txt_amount
        self.combo_category = dp.combo_category
        self.txt_seller = dp.txt_seller
        self.txt_buyer = dp.txt_buyer
        # Files
        self.detail_files_section = dp.detail_files_section
        self.txt_path = dp.txt_path
        self.btn_open_file = dp.btn_open_file
        self.btn_add_attachment = dp.btn_add_attachment
        self.btn_retry_download = dp.btn_retry_download
        self.combo_supporting_docs = dp.combo_supporting_docs
        self.btn_open_extra_files = dp.btn_open_extra_files
        self.supporting_doc_items = dp.supporting_doc_items
        # Claim group
        self.claim_setup_section = dp.claim_setup_section
        self.combo_claims = dp.combo_claims
        self.btn_refresh_claims = dp.btn_refresh_claims
        self.btn_add_to_claim = dp.btn_add_to_claim
        self.txt_new_claim = dp.txt_new_claim
        self.btn_create_claim = dp.btn_create_claim
        self.lbl_claim_total = dp.lbl_claim_total
        self.btn_export = dp.btn_export
        self.lbl_export_summary = dp.lbl_export_summary
        # Notes
        self.review_note_section = dp.review_note_section
        self.btn_toggle_note = dp.btn_toggle_note
        self.txt_note = dp.txt_note
        self.lbl_note_summary = dp.lbl_note_summary
        self.btn_new_claim_toggle = dp.btn_new_claim_toggle
        self.new_claim_widget = dp.new_claim_widget
        # More source
        self.btn_more_source = dp.btn_more_source
        self.more_source_widget = dp.more_source_widget
        self.txt_id = dp.txt_id
        self.txt_invoice_date = dp.txt_invoice_date
        self.txt_date_source = dp.txt_date_source
        self.txt_subject = dp.txt_subject
        self.txt_url = dp.txt_url
        self.txt_item_name = dp.txt_item_name
        self.txt_full_path = dp.txt_full_path
        # Bottom
        self.closing_card = dp.closing_card
        self.lbl_closing_desc = dp.lbl_closing_desc
        self.lbl_dirty_hint = dp.lbl_dirty_hint
        self.btn_save_draft = dp.btn_save_draft
        # Stack / scroll
        self.right_stack = dp.right_stack
        self.right_content_widget = dp.right_content_widget
        self.right_empty_widget = dp.right_empty_widget
        self.right_layout = dp.right_layout
        self.right_detail_content = dp.right_detail_content
        self.lbl_right_empty_title = dp.lbl_right_empty_title
        self.lbl_right_empty_desc = dp.lbl_right_empty_desc
        # Delegate methods
        self._update_status_badge = dp._update_status_badge
        self._set_summary_placeholder = dp._set_summary_placeholder
        self._refresh_widget_style = dp._refresh_widget_style
        self._toggle_note_visibility = dp._toggle_note_visibility
        self._toggle_more_source_info = dp._toggle_more_source_info
        # Evidence row (row-style with missing badge)
        self.lbl_evidence_dot = dp.lbl_evidence_dot
        self.lbl_evidence_name = dp.lbl_evidence_name
        self.lbl_evidence_missing = dp.lbl_evidence_missing
        self.btn_add_evidence = dp.btn_add_evidence
        self.update_evidence_row = dp.update_evidence_row

    def _set_right_panel_state(self, has_records: bool):
        if not hasattr(self, "right_stack"):
            return
        target = self.right_content_widget if has_records else self.right_empty_widget
        if self.right_stack.currentWidget() != target:
            self.right_stack.setCurrentWidget(target)

    def _schedule_invoice_reload(self, *_args):
        # Debounce invoice reloads when search/filter controls change.
        self._column_filters_load_all = False
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
        self.column_filters.clear()
        self._column_filters_load_all = False
        self._refresh_column_filter_headers()
        self.current_filter_status = None
        for s, btn in self.filter_buttons.items():
            btn.setChecked(s == "all")
        self._load_invoices()

    def _column_filter_value_getters(self) -> dict:
        return {
            "status": self._get_invoice_display_status,
            "source": self._get_invoice_source,
        }

    def _refresh_column_filter_headers(self):
        if not hasattr(self, "table"):
            return
        for index, (key, label, _kind) in enumerate(COLUMN_DEFINITIONS):
            active = is_filter_active(self.column_filters.get(key))
            marker = "●" if active else "▾"
            item = self.table.horizontalHeaderItem(index)
            if item is None:
                item = QTableWidgetItem()
                self.table.setHorizontalHeaderItem(index, item)
            item.setText(f"{label} {marker}")
            item.setToolTip(self._column_filter_header_tooltip(label, active))

    def _column_filter_header_tooltip(self, label: str, active: bool) -> str:
        if active:
            return f"{label}：已启用列筛选，点击右侧修改"
        return f"{label}：点击列标题右侧筛选"

    def _set_column_filter(self, key: str, spec: dict):
        if key not in COLUMN_KEYS:
            return
        if is_filter_active(spec):
            self.column_filters[key] = dict(spec)
        else:
            self.column_filters.pop(key, None)
        self._column_filters_load_all = False
        self._refresh_column_filter_headers()
        self._load_invoices()

    def _should_open_column_filter_popup(self, section: int) -> bool:
        if not hasattr(self, "table") or section < 0:
            return False
        header = self.table.horizontalHeader()
        press_pos = getattr(self, "_column_filter_header_press_pos", None)
        if press_pos is None:
            return False
        left = header.sectionViewportPosition(section)
        width = header.sectionSize(section)
        local_x = press_pos.x() - left
        if local_x < 0 or local_x > width:
            return False
        marker_left = max(0, width - 30)
        marker_right = width
        return marker_left <= local_x <= marker_right

    def _show_column_filter_popup(self, section: int):
        if section < 0 or section >= len(COLUMN_DEFINITIONS):
            return
        if not self._should_open_column_filter_popup(section):
            self._column_filter_header_press_pos = None
            return
        key, _label, _kind = COLUMN_DEFINITIONS[section]
        try:
            include_deleted = self.chk_show_deleted.isChecked()
            rows = self.db.list_invoices(status=None, limit=None, include_deleted=include_deleted)
        except Exception as exc:
            _log.warning("Unable to load column filter values: %s", exc)
            rows = []
        values = unique_column_values(rows, key, self._column_filter_value_getters())
        popup = ColumnFilterPopup(
            key,
            values,
            self.column_filters.get(key),
            self._set_column_filter,
            self,
        )
        header = self.table.horizontalHeader()
        popup.move(header.viewport().mapToGlobal(QPoint(
            header.sectionViewportPosition(section),
            header.height(),
        )))
        self._column_filter_popup = popup
        popup.show()
        self._column_filter_header_press_pos = None

    def eventFilter(self, obj, event):
        header = self.table.horizontalHeader() if hasattr(self, "table") else None
        if header is not None and obj is header.viewport():
            if event.type() == QEvent.MouseButtonPress:
                self._column_filter_header_press_pos = event.position().toPoint()
        return super().eventFilter(obj, event)

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
            claim_name = self._get_invoice_claim_group(inv)
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

    def _get_invoice_claim_group(self, inv: dict) -> str:
        for key in ("claim_name", "claim_group_name", "claim_group"):
            value = str(inv.get(key) or "").strip()
            if value:
                return value
        return ""

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

    def _buyer_warning(self, inv: dict) -> str:
        cfg = load_config_safe()
        return buyer_warning(inv, cfg.get("reimbursement", {}))

    def _update_save_button_state(self):
        if not self.current_invoice or self._invoice_snapshot is None:
            self._detail_panel.set_dirty_state(False)
            return
        changed = self._get_invoice_form_snapshot() != self._invoice_snapshot
        self._detail_panel.set_dirty_state(changed)

    def _mark_invoice_form_dirty(self):
        if self._suspend_dirty_tracking:
            return
        self._update_save_button_state()






    def _copy_invoice_number(self):
        inv_number = self.txt_number.text().strip()
        if inv_number:
            QApplication.clipboard().setText(inv_number)
            self.statusBar().showMessage(f"已复制发票号码: {inv_number}", 2000)

    # Controller & Data loading

    def _change_filter(self, status):
        # Handle top-bar filter button clicks and update UI checked state.
        self._column_filters_load_all = False
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
        if has_active_filters(self.column_filters):
            self._column_filters_load_all = True
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
        prev_row = self.table.currentRow() if hasattr(self, "table") else -1

        # Determine query limit for first load: if _is_first_load is True and no search text/quick filter is active
        needle = self.txt_search.text().strip().lower() if hasattr(self, "txt_search") else ""
        unlinked_only = self.chk_unlinked.isChecked() if hasattr(self, "chk_unlinked") else False
        needs_fix_only = self.chk_needs_fix.isChecked() if hasattr(self, "chk_needs_fix") else False

        column_filters_active = has_active_filters(self.column_filters)
        is_default_view = not needle and not unlinked_only and not needs_fix_only and not column_filters_active
        limit_val = None
        first_load_limited = False
        if self._is_first_load and is_default_view and self.current_filter_status is None:
            limit_val = 100
            first_load_limited = True

        counts = None
        try:
            include_deleted = self.chk_show_deleted.isChecked() if hasattr(self, "chk_show_deleted") else False
            db_start = time.perf_counter()
            if column_filters_active:
                display_source = self.db.list_invoices(
                    status=None,
                    limit=None,
                    include_deleted=include_deleted,
                )
            else:
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
            elif column_filters_active:
                count_source = display_source
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
        displayed_invoices = apply_column_filters(
            displayed_invoices,
            self.column_filters,
            self._column_filter_value_getters(),
        )
        if column_filters_active:
            count_filtered_invoices = displayed_invoices
            if self.current_filter_status is not None:
                displayed_invoices = [
                    inv for inv in displayed_invoices
                    if (inv.get("review_status") or TO_REVIEW) == self.current_filter_status
                ]
            total_column_matches = len(displayed_invoices)
            if not self._column_filters_load_all and total_column_matches > 100:
                displayed_invoices = displayed_invoices[:100]
                first_load_limited = True
        elif is_default_view and counts is not None:
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
        if column_filters_active:
            total_matching = total_column_matches
        else:
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
                claim_name = self._get_invoice_claim_group(inv)
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
                # Use row hint from delete operation if available, else fall back to row 0
                hint = getattr(self, "_select_row_hint", -1)
                if hint < 0:
                    hint = prev_row
                if hint >= 0:
                    target_row = min(hint, len(self.invoices_list) - 1)
                else:
                    target_row = 0
            # Consume the hint after use so it doesn't affect unrelated reloads
            self._select_row_hint = -1
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
            self.lbl_claim_total.setText("当前报销组 0 张，合计 ¥0.00；当前发票未加入")
            if hasattr(self, "btn_add_to_claim"):
                self.btn_add_to_claim.setText("加入当前发票")
                self.btn_add_to_claim.setEnabled(False)
            if hasattr(self, "btn_export"):
                self.btn_export.setEnabled(False)
            return
        claim_id = self.combo_claims.itemData(claim_idx)
        try:
            invoices = self.db.get_claim_invoices(claim_id)
        except Exception as exc:
            _log.debug("Failed to calculate claim total: %s", exc)
            invoices = []

        txt = self.combo_claims.currentText()
        if ": " in txt:
            group_name = txt.split(": ", 1)[1]
            if " [" in group_name:
                group_name = group_name.split(" [", 1)[0]
        else:
            group_name = txt

        current_invoice_in_group = False
        if getattr(self, "current_invoice", None):
            inv_id = self.current_invoice.get("id")
            if any(i.get("id") == inv_id for i in invoices):
                current_invoice_in_group = True

        from ..reimbursement import amount_total
        count, total, has_missing = amount_total(invoices)
        suffix = "，部分金额缺失" if has_missing else ""
        self.lbl_claim_total.setText(f"{group_name}：{count} 张，合计 ¥{total:.2f}{suffix}；当前发票{'已' if current_invoice_in_group else '未'}加入")
        
        if hasattr(self, "btn_add_to_claim"):
            self.btn_add_to_claim.setText(f"加入到 {group_name}")
            self.btn_add_to_claim.setEnabled(True)
        if hasattr(self, "btn_export"):
            self.btn_export.setEnabled(True)

    def _clear_detail_form(self):
        # Reset right hand details form to generic empty/placeholder state.
        self._suspend_dirty_tracking = True
        self.current_invoice = None
        self._invoice_snapshot = None
        self._detail_panel.clear_detail()
        if hasattr(self, "action_copy_number"):
            self.action_copy_number.setEnabled(False)
            self.action_locate_file.setEnabled(False)
            self.action_open_dir.setEnabled(False)
        self._suspend_dirty_tracking = False

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
            self._detail_panel.set_closing_status()
            return
        inv_num = str(inv.get("invoice_number") or "").strip()
        inv_date = str(inv.get("expense_date") or inv.get("invoice_date") or "").strip()
        seller = str(inv.get("seller_name") or "").strip()
        total_amt = str(inv.get("total_amount") or "").strip()
        status = inv.get("review_status") or "to_review"
        missing = not inv_num or not inv_date or not seller or not total_amt
        self._detail_panel.set_closing_status(
            missing_fields=missing, is_error=(status == "error" and not missing)
        )

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
        self.btn_add_to_claim.setEnabled(True)

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

            # Populate form fields via panel
            date_source_disp = {
                "travel_date": "乘车日期",
                "invoice_date": "开票日期",
                "legacy": "历史数据",
                "service_date": "服务日期",
                "payment_date": "付款日期",
            }.get(date_source, date_source)
            mail_uid = inv.get("mail_uid")
            download_url = str(inv.get("download_url") or "").strip()
            has_file = bool(att_path)
            has_url = bool(download_url)

            self._detail_panel.set_form_fields(
                inv_id=inv_id, number=inv_num, date=display_date,
                invoice_date=inv_date, date_source=date_source_disp,
                seller=seller, buyer=buyer, amount=total_amt, category=category,
                subject=str(inv.get("mail_subject") or ""),
                item_name=str(inv.get("item_name") or ""),
                full_path=att_path,
                url=_mask_url(inv.get("download_url") or ""),
            )
            self._detail_panel.set_attachment_state(
                has_file=has_file, has_url=has_url,
                file_name=Path(att_path).name if att_path else "",
                file_path=att_path,
                can_download=(not att_path and (mail_uid is not None or download_url)),
            )
            self._update_supporting_docs_selector(inv)

            # Note via panel
            note_content = str(inv.get("confirmed_note") or "").strip()
            self._detail_panel.set_note(note_content)

            buyer_check_warning = self._buyer_warning(inv)
            # Update summary card via panel
            self._detail_panel.set_summary(
                amount=total_amt, status=status, date=display_date,
                category=category, seller=seller, number=inv_num,
                buyer_warning=buyer_check_warning,
                date_warning=get_date_warning(inv),
            )
            if buyer_check_warning.startswith("购买方抬头不匹配"):
                # Buyer title risk surfaced near buyer field, not in summary card.
                cfg = load_config_safe()
                expected = str(cfg.get("reimbursement", {}).get("buyer_name") or "").strip()
                self.txt_buyer.setToolTip(f"抬头不匹配 — 期望抬头：{expected}\n实际抬头：{buyer}")
            else:
                self.txt_buyer.setToolTip(buyer if buyer else "")


            if not buyer.strip():
                self.txt_buyer.setPlaceholderText("待补全")
            else:
                self.txt_buyer.setPlaceholderText("")

            date_warn = get_date_warning(inv)
            self.lbl_date_warning.setText(date_warn)
            self.lbl_date_warning.setVisible(bool(date_warn))
            self._update_status_badge(status)

            if hasattr(self, "action_copy_number"):
                has_num = bool(inv_num)
                has_att = bool(att_path)
                self.action_copy_number.setEnabled(has_num)
                self.action_locate_file.setEnabled(has_att)
                self.action_open_dir.setEnabled(has_att)

            self._detail_panel.set_single_selection_state()
            self.btn_open_file.setEnabled(bool(att_path))

            self._invoice_snapshot = self._get_invoice_snapshot(inv)
            self._suspend_dirty_tracking = False
            self._update_save_button_state()

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
            self._detail_panel.set_multi_selection_state(num_selected)
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

    def _capture_selection_row_hint(self) -> int:
        """Return the first valid selected row for post-refresh selection fallback."""
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return -1

        selected_indexes = selection_model.selectedRows(0)
        if not selected_indexes:
            selected_indexes = selection_model.selectedIndexes()

        rows = {
            index.row()
            for index in selected_indexes
            if 0 <= index.row() < len(self.invoices_list)
        }
        return min(rows) if rows else -1

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
        self._select_row_hint = self._capture_selection_row_hint()
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
        redownload_buckets = {key: 0 for key in REDOWNLOAD_BUCKETS}

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
                                    redownload_buckets["file_restored"] += 1
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
                    if download_url or fallback_reason:
                        redownload_buckets["download_failed"] += 1
                    else:
                        redownload_buckets["no_candidate_link"] += 1
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
                    reread_status = getattr(reread_ok, "status", "")
                    if reread_ok:
                        status = reread_status or "recorded"

                        if status == "duplicate":
                            refreshed = self.db.get_invoice(inv_id)
                            refreshed_att_path = refreshed.get("attachment_path") if refreshed else None
                            resolved_path = self._resolve_attachment_path(refreshed_att_path) if refreshed_att_path else None

                            file_ok = _is_file_valid_and_openable(resolved_path)
                            if not file_ok:
                                status = "download_failed"

                        bucket = _bucket_redownload_status(status)
                        redownload_buckets[bucket] += 1
                        if bucket == "file_restored":
                            success_count += 1
                            reread_success_count += 1
                            self.write_log(f"✅ [重新下载] 发票 ID {inv_id} 已通过重新读取邮件修复原文件")
                        elif bucket == "metadata_refreshed":
                            self.write_log(f"ℹ️ [重新下载] 发票 ID {inv_id} 仅刷新元数据或仍需手动下载")
                        elif bucket == "duplicate_only":
                            self.write_log(f"ℹ️ [重新下载] 发票 ID {inv_id} 仅命中已有重复记录")
                        else:
                            reread_failed_count += 1
                            failed_count += 1
                            diagnostics = getattr(downloader, "last_download_diagnostics", {}) or {}
                            attempted = int(diagnostics.get("attempted", 0) or 0)
                            failed = int(diagnostics.get("failed", 0) or 0)
                            if attempted > 0 and failed > 0:
                                fail_reason = "链接下载失败并且未恢复原件"
                            else:
                                fail_reason = "未恢复原件文件"
                            download_failed_files.append(f"发票 ID {inv_id}: {fail_reason}")
                            self.write_log(f"❌ [重新下载] 发票 ID {inv_id} 重新读取邮件后仍未成功恢复原件")
                        continue

                    if reread_status == "no_candidate_link":
                        redownload_buckets["no_candidate_link"] += 1
                        reread_failed_count += 1
                        failed_count += 1
                        download_failed_files.append(f"发票 ID {inv_id}: 无候选下载链接")
                        self.write_log(f"⚠️ [重新下载] 发票 ID {inv_id} 无候选下载链接")
                        continue

                    reread_failed_count += 1
                    failed_count += 1
                    redownload_buckets["download_failed"] += 1
                    download_failed_files.append(f"发票 ID {inv_id}: 重新读取邮件后仍未成功入库")
                    self.write_log(f"⚠️ [重新下载] 发票 ID {inv_id} 重新读取邮件后仍未成功入库")
                except Exception as e:
                    reread_failed_count += 1
                    failed_count += 1
                    redownload_buckets["download_failed"] += 1
                    download_failed_files.append(f"发票 ID {inv_id}: 重新读取邮件失败 ({str(e)})")
                    self.write_log(f"❌ [重新下载] 发票 ID {inv_id} 重新读取邮件失败: {e}")
        finally:
            downloader.close()
            for _, mail_fetcher_cm in mail_fetchers.values():
                mail_fetcher_cm.__exit__(None, None, None)
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()

        self._select_row_hint = self._capture_selection_row_hint()
        self._load_invoices()
        self._load_claims()
        self._on_table_selection_changed()

        msg = _format_redownload_bucket_summary(count, redownload_buckets, download_failed_files)
        if reread_count:
            msg += (
                f"\n\n其中 {reread_count} 张需要重新读取邮件，"
                f"成功修复 {reread_success_count} 张，失败 {reread_failed_count} 张。"
            )
        if no_url_count:
            msg += f"\n\n{no_url_count} 张没有直接下载链接，已尝试从邮件重新读取。"

        if (redownload_buckets.get("download_failed", 0) > 0 or
            (redownload_buckets.get("duplicate_only", 0) > 0 and redownload_buckets.get("file_restored", 0) == 0)):
            QMessageBox.warning(self, "重新下载结果", msg)
        else:
            QMessageBox.information(self, "重新下载结果", msg)
        self.write_log(
            "📥 [重新下载] 完成。"
            f"file_restored={redownload_buckets['file_restored']} "
            f"metadata_refreshed={redownload_buckets['metadata_refreshed']} "
            f"duplicate_only={redownload_buckets['duplicate_only']} "
            f"download_failed={redownload_buckets['download_failed']} "
            f"no_candidate_link={redownload_buckets['no_candidate_link']} "
            f"回读邮件: {reread_success_count}/{reread_count}, 失败: {failed_count}"
        )

    def _delete_selected_invoices(self):
        selected_indexes = self.table.selectionModel().selectedRows(0)
        if not selected_indexes:
            selected_indexes = self.table.selectionModel().selectedIndexes()
        if not selected_indexes:
            return

        # Deduplicate row numbers
        seen_rows = set()
        unique_indexes = []
        for idx in selected_indexes:
            r = idx.row()
            if 0 <= r < len(self.invoices_list) and r not in seen_rows:
                seen_rows.add(r)
                unique_indexes.append(idx)

        if not unique_indexes:
            return

        count = len(unique_indexes)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除选中的 {count} 张发票吗？\n删除后发票将不会显示在列表中，但保留数据库恢复能力。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        success_count = 0
        for idx in unique_indexes:
            inv = self.invoices_list[idx.row()]
            inv_id = inv.get("id")
            if inv_id and self.db.soft_delete_invoice(inv_id):
                success_count += 1

        self.write_log(f"🗑️ [删除发票] 成功删除 {success_count}/{count} 张发票。")
        self.statusBar().showMessage(f"成功删除 {success_count} 张发票", 4000)
        self._select_row_hint = self._capture_selection_row_hint()
        self._load_invoices()
        self._load_claims()

    def _restore_selected_invoices(self):
        selected_indexes = self.table.selectionModel().selectedRows(0)
        if not selected_indexes:
            selected_indexes = self.table.selectionModel().selectedIndexes()
        if not selected_indexes:
            return

        # Deduplicate row numbers
        seen_rows = set()
        unique_indexes = []
        for idx in selected_indexes:
            r = idx.row()
            if 0 <= r < len(self.invoices_list) and r not in seen_rows:
                seen_rows.add(r)
                unique_indexes.append(idx)

        if not unique_indexes:
            return

        count = len(unique_indexes)
        success_count = 0
        for idx in unique_indexes:
            inv = self.invoices_list[idx.row()]
            inv_id = inv.get("id")
            if inv_id and self.db.restore_invoice(inv_id):
                success_count += 1

        self.write_log(f"🔄 [恢复发票] 成功恢复 {success_count}/{count} 张发票。")
        self.statusBar().showMessage(f"成功恢复 {success_count} 张发票", 4000)
        self._select_row_hint = self._capture_selection_row_hint()
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

            from scripts.invoice_fetch.attachment_handler import build_managed_attachment_name
            dest_name = build_managed_attachment_name(
                original_name=src_file.name,
                invoice_date=self.current_invoice.get("invoice_date"),
                expense_date=self.current_invoice.get("expense_date"),
                fallback_date=self.current_invoice.get("mail_date"),
                category=self.current_invoice.get("category"),
                total_amount=self.current_invoice.get("total_amount"),
                invoice_number=self.current_invoice.get("invoice_number"),
                role="原件",
            )
            if not dest_name.lower().endswith(ext):
                dest_name = os.path.splitext(dest_name)[0] + ext

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

    def _add_evidence_manually(self):
        if not self.current_invoice:
            return

        inv_id = self.current_invoice["id"]
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择证明材料",
            "",
            "证明文件 (*.pdf *.ofd *.png *.jpg *.jpeg *.docx *.xlsx *.zip);;所有文件 (*.*)"
        )
        if not file_path:
            return

        try:
            src_file = Path(file_path)
            ext = src_file.suffix.lower()

            date_str = self.current_invoice.get("invoice_date") or self.current_invoice.get("mail_date") or "unknown_date"
            if "-" in date_str:
                date_dir_name = date_str[:10]
            else:
                date_dir_name = "unknown_date"

            dest_dir = RUNTIME_DIR / "attachments" / date_dir_name
            dest_dir.mkdir(parents=True, exist_ok=True)

            from scripts.invoice_fetch.attachment_handler import build_managed_attachment_name
            dest_name = build_managed_attachment_name(
                original_name=src_file.name,
                invoice_date=self.current_invoice.get("invoice_date"),
                expense_date=self.current_invoice.get("expense_date"),
                fallback_date=self.current_invoice.get("mail_date"),
                category=self.current_invoice.get("category"),
                total_amount=self.current_invoice.get("total_amount"),
                invoice_number=self.current_invoice.get("invoice_number"),
                role="证明材料",
            )
            if not dest_name.lower().endswith(ext):
                dest_name = os.path.splitext(dest_name)[0] + ext

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

            rel_path = f"attachments/{date_dir_name}/{dest_path.name}"

            # Append rel_path to invoice's extra_paths and save to DB
            import json
            raw_extra = self.current_invoice.get("extra_paths")
            extra_paths = []
            if raw_extra:
                if isinstance(raw_extra, list):
                    extra_paths = [str(p) for p in raw_extra if p]
                elif isinstance(raw_extra, str):
                    try:
                        parsed = json.loads(raw_extra)
                        if isinstance(parsed, list):
                            extra_paths = [str(p) for p in parsed if p]
                        else:
                            extra_paths = [str(raw_extra)]
                    except Exception:
                        extra_paths = [str(raw_extra)]
                else:
                    extra_paths = [str(raw_extra)]

            # Deduplicate paths
            seen_normalized = {str(p).lower().replace("\\", "/") for p in extra_paths}
            norm_rel_path = rel_path.lower().replace("\\", "/")
            if norm_rel_path not in seen_normalized:
                extra_paths.append(rel_path)

            extra_paths_str = json.dumps(extra_paths, ensure_ascii=False)
            self.db.update_invoice_file_paths(inv_id, extra_paths=extra_paths_str)

            # Update memory state
            self.current_invoice["extra_paths"] = extra_paths_str
            self.current_invoice["has_extra"] = 1
            self.current_invoice["missing_extra"] = 0

            # Refresh GUI and preview
            self._update_detail_fields(self.current_invoice)
            from .helpers import resolve_invoice_documents_with_evidence
            self.current_preview_docs = resolve_invoice_documents_with_evidence(self.current_invoice, self.db, RUNTIME_DIR)
            self.current_preview_index = 0
            self._update_document_preview()
            self._load_invoices()

            _log.info("用户手动补齐证明材料: invoice_id=%s, filename=%s", inv_id, dest_path.name)
            self.statusBar().showMessage("手动补齐证明材料成功", 3000)

        except Exception as e:
            _log.error("手动补齐证明材料失败: %s", e)
            QMessageBox.critical(self, "错误", f"补齐证明材料失败: {e}")

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
                from scripts.invoice_fetch.attachment_handler import build_managed_attachment_name
                dest_name = build_managed_attachment_name(
                    original_name=src_path.name,
                    invoice_date=self.current_invoice.get("invoice_date"),
                    expense_date=self.current_invoice.get("expense_date"),
                    fallback_date=self.current_invoice.get("mail_date"),
                    category=self.current_invoice.get("category"),
                    total_amount=self.current_invoice.get("total_amount"),
                    invoice_number=self.current_invoice.get("invoice_number"),
                    role="原件",
                )
                if not dest_name.lower().endswith(ext):
                    dest_name = os.path.splitext(dest_name)[0] + ext

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
            self._detail_panel.set_dirty_state(False)
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
            if hasattr(self._detail_panel, "new_claim_widget"):
                self._detail_panel.new_claim_widget.setVisible(False)
            if hasattr(self._detail_panel, "btn_new_claim_toggle"):
                self._detail_panel.btn_new_claim_toggle.setVisible(True)
            QMessageBox.information(self, "创建成功", f"已创建并选中报销组“{name}”；当前发票尚未加入。")
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
            self._select_row_hint = self._capture_selection_row_hint()
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
            self._select_row_hint = self._capture_selection_row_hint()
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

        self._set_action_busy(self.btn_toolbar_export, "导出中...")
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
        finally:
            self._clear_action_busy(self.btn_toolbar_export, "一键导出")

    # ── Operations Bar Handlers ───────────────────────────────────────

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

    def _get_toolbar_action_buttons(self) -> list:
        """Return all top-level toolbar action buttons for busy-state management."""
        btns = []
        for attr in ("btn_import_local", "btn_mobile_upload", "btn_scan_email", "btn_toolbar_export"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btns.append(btn)
        return btns

    def _set_action_busy(self, active_btn, busy_text: str):
        """Mark *active_btn* as the running action: show busy text, disable others.

        The active button gets a 'busy' QSS property so it stays visually blue/active,
        while other toolbar buttons are disabled (grey) and cleared of focus.
        """
        active_btn.setProperty("_original_text", active_btn.text())
        active_btn.setText(busy_text)
        # Mark as busy via QSS property (styled as active in CSS)
        active_btn.setProperty("busy", "true")
        active_btn.clearFocus()

        # Save enabled states of all toolbar buttons
        self._toolbar_btn_states = {}
        for btn in self._get_toolbar_action_buttons():
            self._toolbar_btn_states[btn] = btn.isEnabled()

        # Disable all buttons
        for btn in self._get_toolbar_action_buttons():
            btn.setEnabled(False)
            btn.clearFocus()

        # Polish to pick up the new property value in QSS
        active_btn.style().unpolish(active_btn)
        active_btn.style().polish(active_btn)

        # Process events so the visual change renders immediately
        QApplication.processEvents()

    def _clear_action_busy(self, active_btn, original_text: str):
        """Restore all toolbar buttons to their normal enabled state."""
        stored = active_btn.property("_original_text")
        active_btn.setText(stored if stored else original_text)
        active_btn.setProperty("busy", "false")
        active_btn.style().unpolish(active_btn)
        active_btn.style().polish(active_btn)

        # Restore saved states if they exist
        saved_states = getattr(self, "_toolbar_btn_states", {})
        for btn in self._get_toolbar_action_buttons():
            if btn in saved_states:
                btn.setEnabled(saved_states[btn])
            else:
                btn.setEnabled(True)
        self._toolbar_btn_states = {}
        QApplication.processEvents()

    def _import_local_clicked(self):
        """Trigger QFileDialog to choose a directory for invoice importing."""
        folder = QFileDialog.getExistingDirectory(self, "选择本地发票文件夹")
        if not folder:
            return

        path = Path(folder)
        self.write_log(f"📁 [本地导入] 已选择本地文件夹: {path.absolute()}")
        self.statusBar().showMessage(f"正在读取与导入本地发票: {path.name}...")
        self._set_action_busy(self.btn_import_local, "导入中...")

        # Spawn asynchronous thread worker
        self.import_worker = LocalImportWorker(path, self.db_path)
        self.import_worker.finished.connect(self._import_local_finished)
        self.import_worker.error.connect(self._import_local_error)
        self.import_worker.start()

    def _mobile_upload_clicked(self):
        self._set_action_busy(self.btn_mobile_upload, "等待上传...")
        try:
            dialog = MobileUploadDialog(self, self.db_path)
            dialog.upload_finished.connect(self._mobile_upload_finished)
            dialog.exec()
        finally:
            self._clear_action_busy(self.btn_mobile_upload, "扫码上传")

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
        self._clear_action_busy(self.btn_import_local, "导入发票")
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
        self._clear_action_busy(self.btn_import_local, "导入发票")
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
        self._set_action_busy(self.btn_scan_email, "扫描中...")

        # Spawn asynchronous thread worker
        self.scan_worker = EmailScanWorker(self.db_path)
        self.scan_worker.log.connect(
            lambda text: self.write_log(text, mirror_to_file=False)
        )
        self.scan_worker.finished.connect(self._scan_email_finished)
        self.scan_worker.error.connect(self._scan_email_error)
        self.scan_worker.start()

    def _scan_email_finished(self, res: dict):
        self._clear_action_busy(self.btn_scan_email, "扫描邮箱")
        summary = self._build_scan_summary(res, getattr(self.scan_worker, "summary_logs", []))
        self._last_scan_summary = summary

        self.write_log(
            "✅ [邮箱扫描] 完成！"
            f"新增 {summary['new']}，恢复 {summary['restored']}，重复 {summary['duplicates']}，"
            f"链接失败 {summary['link_failed']}，待重试 {summary['pending_retry']}。"
        )
        self.write_log(
            "[扫描摘要] "
            f"rule_excluded={summary['rule_excluded']} "
            f"no_candidate_link={summary['no_candidate_link']} "
            f"download_failed={summary['download_failed']} "
            f"manual_required={summary['manual_review_required']} "
            f"parse_failed={summary['parse_failed']} "
            f"ai_auth_failed={summary['ai_auth_failed']} "
            f"ai_pending_classification={summary['ai_pending_classification']}"
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
        no_candidate_link = int(res.get("no_candidate_link", 0) or 0)
        download_failed = int(res.get("download_failed", 0) or 0)
        parse_failed = int(res.get("parse_failed", 0) or 0)
        link_failed = max(link_failed, no_candidate_link + download_failed + parse_failed)
        failed_summaries = [str(x or "") for x in (res.get("failed_summaries") or [])]
        ai_pending_classification = int(res.get("ai_pending_classification", 0) or 0)
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
            "rule_excluded": int(res.get("rule_excluded", 0) or 0),
            "no_candidate_link": no_candidate_link,
            "download_failed": download_failed,
            "parse_failed": parse_failed,
            "manual_review_required": manual_review_required,
            "pending_retry": max(int(res.get("pending_retry", 0) or 0), pending_retry),
            "failed": int(res.get("failed", res.get("failed_count", 0)) or 0),
            "failed_summaries": failed_summaries[:5],
            "ai_auth_failed": bool(res.get("ai_auth_failed", False)),
            "ai_pending_classification": ai_pending_classification,
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
        ai_pending = int(summary.get("ai_pending_classification", 0) or 0)
        ai_text = ""
        if summary.get("ai_auth_failed"):
            ai_text = f"- AI 已暂停，{ai_pending} 封邮件待分类。\n"
        return (
            "邮箱增量扫描完成。\n\n"
            f"- 扫描邮件头: {summary.get('scanned_headers', 0)} 封\n"
            f"- 新入库邮件头: {summary.get('new_email_headers', 0)} 封\n"
            f"- 判定为发票候选: {summary.get('classified_invoice', 0)} 封\n"
            f"- 成功处理邮件: {summary.get('downloaded_emails', 0)} 封\n"
            f"- 新增记录（发票或待补全材料）: {summary.get('new', 0)} 条\n"
            f"- 恢复软删除: {summary.get('restored', 0)} 条\n"
            f"- 重复已存在: {summary.get('duplicates', 0)} 条\n"
            f"- 规则排除历史误分类: {summary.get('rule_excluded', 0)} 封\n"
            f"- 未找到候选链接: {summary.get('no_candidate_link', 0)} 封\n"
            f"- 链接下载失败: {summary.get('download_failed', 0)} 封\n"
            f"- 需人工确认材料: {summary.get('manual_review_required', 0)} 条\n"
            f"- 下载内容解析失败: {summary.get('parse_failed', 0)} 封\n"
            f"- 待重试: {summary.get('pending_retry', 0)} 封\n"
            f"- 处理失败: {summary.get('failed', 0)} 封\n"
            f"{ai_text}"
            f"失败摘要:\n{failure_text}\n\n"
            "说明：新入库邮件头不等于新增发票；需人工确认材料不是处理失败。\n"
            "如果没有看到预期发票，请清空筛选，或用发票号、购买方、金额搜索。"
        )

    def _scan_email_error(self, err_msg: str):
        self._clear_action_busy(self.btn_scan_email, "扫描邮箱")
        self.write_log(f"❌ [邮箱扫描] 失败: {err_msg}")
        self.statusBar().showMessage("邮箱扫描处理失败！", 4000)
        QMessageBox.critical(self, "错误", f"邮箱扫描执行出错: {err_msg}")

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
