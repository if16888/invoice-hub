# -*- coding: utf-8 -*-
"""
Invoice Hub PySide6 App Window
"""

import json
import os
import sys
import logging
import time
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QLineEdit,
    QTextEdit, QPlainTextEdit, QPushButton, QLabel, QMessageBox, QCheckBox,
    QScrollArea, QAbstractItemView, QHeaderView, QFileDialog,
    QStackedWidget, QProgressBar, QFrame, QTabWidget, QMenu, QWidgetAction, QSizePolicy,
    QButtonGroup, QGridLayout, QStyle, QLayout, QToolButton,
    QStyledItemDelegate, QStyleOptionViewItem, QListWidget, QListWidgetItem,
    QComboBox, QSpinBox, QFormLayout, QGroupBox, QInputDialog, QDialog
)
from PySide6.QtCore import Qt, QUrl, QTimer, QEvent, QPoint, QSettings, QItemSelectionModel
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtGui import QFont, QColor, QDesktopServices, QAction, QPainter, QPen

from ..db import InvoiceDB, is_pending_evidence_invoice
from .. import APP_VERSION
from ..config import PROJECT_ROOT, RUNTIME_DIR, load_config_safe, save_config
from ..diagnostics import collect_app_info, export_diagnostics_zip
from ..reimbursement import amount_total, buyer_warning, format_amount_total, get_date_warning
from ..review_status import TO_REVIEW, APPROVED, IGNORED, ERROR
from ..log_privacy import PrivacyLogFilter, mask_email, sanitize_log_message
from .styles import APP_STYLESHEET
from .ui_components import (
    CommandBar,
    CompactStatCard,
    EntityList,
    LogDrawer,
    MoreMenuButton,
    PageHeader,
    ReadOnlyDetailPanel,
    SecondaryNavStack,
    SectionCard,
    ShortcutDisclosure,
    SummaryStrip,
    make_badge,
    make_button,
    make_filter_chip,
)
from .helpers import _mask_url, _read_manifest_summary, resolve_stored_path
from .invoice_detail_panel import InvoiceDetailCallbacks, InvoiceDetailPanel
from .log_diagnostics_mixin import LogDiagnosticsMixin, LOG_DRAWER_EXPANDED_HEIGHT
from .mobile_upload_dialog import MobileUploadDialog
from .preview_mixin import PreviewMixin, check_has_qt_pdf, get_qt_pdf_classes
from .settings_dialog import SettingsDialog
from .workers import EmailScanWorker, LocalImportWorker
from .workbench_layout import clamp_vertical_split, metrics_for_size
from .workbench_state import is_keyboard_input_target
from .column_filters import (
    COLUMN_DEFINITIONS,
    COLUMN_KEYS,
    COLUMN_LABELS,
    VISIBLE_COLUMN_DEFINITIONS,
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

TABLE_BADGE_ROLE = int(Qt.UserRole) + 101

REVIEW_STATUS_BADGES = {
    "to_review": {"fill": "#FEF3C7", "stroke": "#FCD34D", "text": "#92400E"},
    "approved": {"fill": "#DCFCE7", "stroke": "#86EFAC", "text": "#166534"},
    "ignored": {"fill": "#F1F5F9", "stroke": "#CBD5E1", "text": "#64748B"},
    "error": {"fill": "#FEE2E2", "stroke": "#FCA5A5", "text": "#B91C1C"},
}

DATA_STATUS_BADGES = {
    "正常": {"fill": "#DCFCE7", "stroke": "#86EFAC", "text": "#166534"},
    "待补全": {"fill": "#FEF3C7", "stroke": "#FCD34D", "text": "#92400E"},
    "缺原件": {"fill": "#FEF3C7", "stroke": "#FCD34D", "text": "#92400E"},
    "缺证明": {"fill": "#FEE2E2", "stroke": "#FCA5A5", "text": "#B91C1C"},
    "未识别": {"fill": "#FEE2E2", "stroke": "#FCA5A5", "text": "#B91C1C"},
}


class QueueBadgeDelegate(QStyledItemDelegate):
    """Paint compact centered badges for queue-status cells."""

    def paint(self, painter, option, index):
        style = option.widget.style() if option.widget is not None else QApplication.style()
        base_option = QStyleOptionViewItem(option)
        self.initStyleOption(base_option, index)
        badge = index.data(TABLE_BADGE_ROLE)
        text = base_option.text
        base_option.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, base_option, painter, option.widget)
        if not badge:
            text_option = QStyleOptionViewItem(option)
            self.initStyleOption(text_option, index)
            style.drawControl(QStyle.CE_ItemViewItem, text_option, painter, option.widget)
            return

        fill = QColor(badge["fill"])
        stroke = QColor(badge["stroke"])
        text_color = QColor(badge["text"])
        badge_rect = option.rect.adjusted(7, 4, -7, -4)
        if badge_rect.width() <= 8 or badge_rect.height() <= 4:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(stroke, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(badge_rect, 8, 8)
        painter.setPen(text_color)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(8, font.pointSize() - 1))
        painter.setFont(font)
        painter.drawText(badge_rect.adjusted(6, 0, -6, 0), Qt.AlignCenter, text)
        painter.restore()


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


class SingleTaskMailboxDialog(QDialog):
    def __init__(self, parent=None, account: dict | None = None, preset_id: str | None = None):
        super().__init__(parent)
        self._source_account = dict(account or {})
        self._preset_id = str(preset_id or self._source_account.get("provider") or "qq").strip()
        self._result_account: dict | None = None
        self._result_auth_code = ""

        self.setWindowTitle("邮箱账户配置")
        self.resize(540, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("单任务邮箱配置")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        layout.addWidget(title)

        hint = QLabel("仅处理当前邮箱账号的新增或编辑，保存后返回桌面系统设置页。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #667085; font-size: 12px;")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)
        self.txt_name = QLineEdit()
        self.txt_email = QLineEdit()
        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["qq", "netease_163", "netease_126", "gmail", "outlook", "custom"])
        self.txt_server = QLineEdit()
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(993)
        self.chk_enabled = QCheckBox("启用此账号")
        self.chk_enabled.setChecked(True)
        self.chk_default = QCheckBox("设为默认扫描账号")
        self.combo_months = QComboBox()
        self.combo_months.addItems(["1", "3", "6", "12"])
        self.txt_auth_code = QLineEdit()
        self.txt_auth_code.setEchoMode(QLineEdit.Password)
        self.txt_auth_code.setPlaceholderText("仅在新增或补录授权码时填写")
        form.addRow("邮箱名称", self.txt_name)
        form.addRow("邮箱地址", self.txt_email)
        form.addRow("Provider", self.combo_provider)
        form.addRow("IMAP 服务器", self.txt_server)
        form.addRow("端口", self.spin_port)
        form.addRow("扫描规则（月）", self.combo_months)
        form.addRow("", self.chk_enabled)
        form.addRow("", self.chk_default)
        form.addRow("授权码", self.txt_auth_code)
        layout.addLayout(form)

        footer = QHBoxLayout()
        footer.addStretch(1)
        btn_cancel = make_button("取消", variant="secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_save = make_button("保存", variant="primary")
        btn_save.clicked.connect(self._accept_form)
        footer.addWidget(btn_cancel)
        footer.addWidget(btn_save)
        layout.addLayout(footer)

        self.combo_provider.currentTextChanged.connect(self._apply_provider_defaults)
        self._load_initial_values()

    def _provider_defaults(self, provider: str) -> tuple[str, int]:
        defaults = {
            "qq": ("imap.qq.com", 993),
            "netease_163": ("imap.163.com", 993),
            "netease_126": ("imap.126.com", 993),
            "gmail": ("imap.gmail.com", 993),
            "outlook": ("outlook.office365.com", 993),
            "custom": ("", 993),
        }
        return defaults.get(provider, ("", 993))

    def _apply_provider_defaults(self, provider: str) -> None:
        provider = str(provider or "").strip()
        server, port = self._provider_defaults(provider)
        if not self.txt_server.text().strip() or self.txt_server.property("auto_fill") is True:
            self.txt_server.setText(server)
            self.txt_server.setProperty("auto_fill", True)
        if self.spin_port.value() in {0, 993}:
            self.spin_port.setValue(port)

    def _load_initial_values(self) -> None:
        account = self._source_account
        provider = str(account.get("provider") or self._preset_id or "qq").strip()
        self.combo_provider.setCurrentText(provider)
        self.txt_name.setText(str(account.get("name") or "").strip())
        self.txt_email.setText(str(account.get("address") or "").strip())
        imap_cfg = account.get("imap", {}) if isinstance(account.get("imap"), dict) else {}
        self.txt_server.setText(str(imap_cfg.get("server") or "").strip())
        self.txt_server.setProperty("auto_fill", not bool(self.txt_server.text().strip()))
        try:
            self.spin_port.setValue(int(imap_cfg.get("port") or 993))
        except (TypeError, ValueError):
            self.spin_port.setValue(993)
        self.chk_enabled.setChecked(bool(account.get("enabled", True)))
        self.chk_default.setChecked(bool(account.get("is_default", False)))
        months = str((account.get("search") or {}).get("months_back") or "3")
        if self.combo_months.findText(months) == -1:
            self.combo_months.addItem(months)
        self.combo_months.setCurrentText(months)
        self._apply_provider_defaults(provider)

    def _accept_form(self) -> None:
        email = self.txt_email.text().strip()
        if not email:
            QMessageBox.warning(self, "邮箱地址为空", "请先填写邮箱地址。")
            return
        provider = self.combo_provider.currentText().strip()
        server = self.txt_server.text().strip()
        if not server:
            QMessageBox.warning(self, "IMAP 未配置", "请先填写 IMAP 服务器。")
            return
        name = self.txt_name.text().strip() or email
        account = dict(self._source_account)
        account.update(
            {
                "mailbox_key": str(account.get("mailbox_key") or email).strip().lower(),
                "name": name,
                "address": email,
                "username": email,
                "provider": provider,
                "enabled": self.chk_enabled.isChecked(),
                "is_default": self.chk_default.isChecked(),
                "imap": {"server": server, "port": int(self.spin_port.value()), "ssl": True},
                "search": {"folder": "INBOX", "months_back": int(self.combo_months.currentText())},
            }
        )
        self._result_account = account
        self._result_auth_code = self.txt_auth_code.text().strip()
        self.accept()

    def get_result_account(self) -> tuple[dict, str]:
        return dict(self._result_account or {}), str(self._result_auth_code or "")


class InvoiceReviewApp(PreviewMixin, LogDiagnosticsMixin, QMainWindow):
    _NEW_CLAIM_VALUE = InvoiceDetailPanel.NEW_CLAIM_VALUE
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
        self._left_splitter_sizes_initialized = False
        self._nav_collapsed_manual: bool | None = None
        self._show_after_deferred_init = bool(self.splash)

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
        self._restore_splitter_prefs()
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
            if self._show_after_deferred_init:
                self._show_after_deferred_init = False
                self.show()
            return

        load_time = _time_mod.time()
        self.first_load_ms = int((load_time - start_time) * 1000)

        # Close splash screen
        if self.splash:
            self.splash.show_message("加载完成！", 100)
            self.splash.close()
        if self._show_after_deferred_init:
            self._show_after_deferred_init = False
            self.show()

        self.write_log(f"📊 [系统启动] First Invoice List Loaded: 成功检索并渲染首批数据 (耗时: {load_time - start_time:.4f}秒)")
        status_msg = f"本地数据库 invoices.db 加载成功，发票列表加载耗时 {load_time - start_time:.4f} 秒"
        if getattr(self, "_first_load_notice", None):
            status_msg = f"{status_msg}｜{self._first_load_notice}"
        self.statusBar().showMessage(status_msg, 4000)

    def closeEvent(self, event):
        self._save_splitter_prefs()
        self.db.close()
        event.accept()

    def _init_ui_probe(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

    def _apply_workbench_metrics(self, width: int | None = None, height: int | None = None):
        w = width if (width is not None and width > 0) else (self.width() if self.width() > 0 else 1440)
        h = height if (height is not None and height > 0) else (self.height() if self.height() > 0 else 900)
        metrics = metrics_for_size(w, h)
        if w <= 1366 or self._nav_collapsed_manual is None:
            nav_collapsed = metrics.nav_collapsed
        else:
            nav_collapsed = bool(self._nav_collapsed_manual)
        self._nav_compact = nav_collapsed
        search_placeholder = (
            "搜索发票号 / 销售方 / 购买方 / 金额    Ctrl + F"
            if metrics.compact
            else "搜索发票号 / 销售方 / 购买方 / 金额 / 邮件主题    Ctrl + F"
        )
        self.txt_search.setPlaceholderText(search_placeholder)
        nav_width = 56 if nav_collapsed else metrics.nav_width
        self.workbench_nav.setMaximumWidth(16777215)
        self.workbench_nav.setMinimumWidth(nav_width)
        self.workbench_nav.setMaximumWidth(nav_width)
        row_h = 28
        self.table.verticalHeader().setDefaultSectionSize(row_h)
        self.table.verticalHeader().setMinimumSectionSize(row_h)
        self.table.verticalHeader().setMaximumSectionSize(row_h + 4)
        self._detail_panel.setMaximumWidth(16777215)
        self._detail_panel.setMinimumWidth(metrics.detail_width)
        self._detail_panel.setMaximumWidth(metrics.detail_width)
        min_window_width = 1040 if metrics.compact else 1280
        self.setMinimumSize(min_window_width, 530)
        if hasattr(self, "thumbnail_rail"):
            self.thumbnail_rail.setFixedWidth(metrics.thumbnail_width)
        self.btn_more.setText("更多操作  ▼" if not metrics.compact else "更多")
        self.btn_toolbar_user.setMinimumWidth(96 if not metrics.compact else 84)
        for card in self.filter_buttons.values():
            card.setMinimumWidth(118)
            card.setMaximumWidth(160)
            card.updateGeometry()
        self.workbench_nav_title.setVisible(not nav_collapsed)
        self.workbench_nav_subtitle.setVisible(not nav_collapsed)
        self.workbench_nav_spacer.setVisible(not nav_collapsed)
        for key, button in self.workbench_nav_buttons.items():
            full_text = self._workbench_nav_button_texts.get(key, "")
            button.setText("" if nav_collapsed else full_text)
            button.setToolTip(full_text if nav_collapsed else "")
            button.setProperty("collapsed", nav_collapsed)
            button.setMinimumHeight(36 if not nav_collapsed else 44)
            button.style().unpolish(button)
            button.style().polish(button)
        self.btn_collapse_nav.setText("" if nav_collapsed else "收起侧边栏")
        self.btn_collapse_nav.setToolTip("展开侧边栏" if nav_collapsed else "收起侧边栏")
        self.btn_collapse_nav.setProperty("collapsed", nav_collapsed)
        self.btn_collapse_nav.style().unpolish(self.btn_collapse_nav)
        self.btn_collapse_nav.style().polish(self.btn_collapse_nav)
        self.btn_collapse_nav.setVisible(True)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        if not self._left_splitter_sizes_initialized:
            self._left_splitter_sizes_initialized = True

    def _toggle_workbench_nav_collapsed(self):
        w = self.width() or 1150
        metrics = metrics_for_size(w, self.height() or 850)
        if w <= 1366 or self._nav_collapsed_manual is None:
            nav_collapsed = metrics.nav_collapsed
        else:
            nav_collapsed = bool(self._nav_collapsed_manual)
        self._nav_collapsed_manual = not nav_collapsed
        settings = QSettings("InvoiceHub", "workbench")
        settings.setValue("nav_collapsed_manual", self._nav_collapsed_manual)
        settings.sync()
        self._apply_workbench_metrics()

    def resize(self, *args):
        super().resize(*args)
        if hasattr(self, "main_splitter") and hasattr(self, "_detail_panel"):
            if len(args) == 2:
                self._apply_workbench_metrics(args[0], args[1])
            elif len(args) == 1 and hasattr(args[0], "width"):
                self._apply_workbench_metrics(args[0].width(), args[0].height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "main_splitter") and hasattr(self, "_detail_panel"):
            self._apply_workbench_metrics(event.size().width(), event.size().height())

    def _save_splitter_prefs(self):
        settings = QSettings("InvoiceHub", "workbench")
        if hasattr(self, "main_splitter"):
            settings.setValue("splitter/main", self.main_splitter.sizes())
        if hasattr(self, "left_splitter"):
            settings.setValue("splitter/left", self.left_splitter.sizes())
        if hasattr(self, "shortcut_disclosure"):
            settings.setValue("shortcut_help_expanded", self.shortcut_disclosure.is_expanded())
        if self._nav_collapsed_manual is None:
            settings.remove("nav_collapsed_manual")
        else:
            settings.setValue("nav_collapsed_manual", self._nav_collapsed_manual)
        settings.sync()

    def _restore_splitter_prefs(self):
        settings = QSettings("InvoiceHub", "workbench")
        main_sizes = settings.value("splitter/main", None)
        if main_sizes is not None:
            try:
                sizes = [int(x) for x in main_sizes]
                if len(sizes) == 2 and all(s >= 0 for s in sizes) and sum(sizes) > 0:
                    self.main_splitter.setSizes(sizes)
            except (TypeError, ValueError):
                pass

        left_sizes = settings.value("splitter/left", None)
        if left_sizes is not None:
            try:
                self._restore_left_splitter_sizes([int(x) for x in left_sizes])
            except (TypeError, ValueError):
                pass

        if hasattr(self, "shortcut_disclosure"):
            expanded = settings.value("shortcut_help_expanded", False, type=bool) if settings.contains("shortcut_help_expanded") else False
            self.shortcut_disclosure.set_expanded(bool(expanded))
        if settings.contains("nav_collapsed_manual"):
            self._nav_collapsed_manual = settings.value("nav_collapsed_manual", False, type=bool)
        else:
            self._nav_collapsed_manual = None
        if (
            hasattr(self, "workbench_nav")
            and hasattr(self, "_detail_panel")
            and hasattr(self, "filter_buttons")
        ):
            self._apply_workbench_metrics()

    def _restore_left_splitter_sizes(self, sizes):
        if len(sizes) != 2:
            return
        total = sum(sizes)
        if total <= 0:
            return
        record, preview = clamp_vertical_split(total, sizes[0], record_min=280, preview_min=180)
        self.left_splitter.setSizes([record, preview])
        self._left_splitter_sizes_initialized = True

    def _ensure_log_text_edit(self) -> QTextEdit:
        if not hasattr(self, "txt_log") or self.txt_log is None:
            self.txt_log = QTextEdit()
            self.txt_log.setReadOnly(True)
            self.txt_log.setFont(QFont("Consolas", 9))
            self.txt_log.setStyleSheet(
                "background-color: #F8FAFC; border: 1px solid #E5E7EB; color: #374151;"
            )
        return self.txt_log

    def _mount_log_widget(self, host: str) -> None:
        log_widget = self._ensure_log_text_edit()
        target_layout = (
            getattr(self, "logs_page_log_layout", None)
            if host == "page"
            else getattr(self, "log_drawer_layout", None)
        )
        if target_layout is None:
            return
        if log_widget.parentWidget() is target_layout.parentWidget():
            return
        target_layout.addWidget(log_widget)

    def _make_menu_action(self, text: str, icon_id, handler, tooltip: str = "") -> QAction:
        action = QAction(self.style().standardIcon(icon_id), text, self)
        action.setObjectName("action_" + text.lower().replace(" ", "_"))
        action.setToolTip(tooltip or text)
        action.triggered.connect(handler)
        return action

    def _show_export_page(self):
        self._switch_main_page("export")

    def _is_single_module_nav(self) -> bool:
        visible_selectable = [
            button for button in self.workbench_nav_buttons.values()
            if not button.isHidden() and button.isEnabled() and button.isCheckable()
        ]
        return len(visible_selectable) <= 1

    def _init_ui(self):
        # Pre-initialize logging text edit widget so page builders and mixins can safely reference it
        self._ensure_log_text_edit()

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.workbench_nav = QFrame()
        self.workbench_nav.setObjectName("WorkbenchNav")
        self.workbench_nav.setMinimumWidth(208)
        self.workbench_nav.setMaximumWidth(208)
        nav_layout = QVBoxLayout(self.workbench_nav)
        nav_layout.setContentsMargins(12, 14, 12, 14)
        nav_layout.setSpacing(6)

        nav_title = QLabel("Invoice Hub")
        nav_title.setObjectName("WorkbenchNavTitle")
        nav_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        nav_layout.addWidget(nav_title)
        self.workbench_nav_title = nav_title

        nav_subtitle = QLabel(f"发票审核中心 v{APP_VERSION}")
        nav_subtitle.setObjectName("WorkbenchNavSubtitle")
        nav_layout.addWidget(nav_subtitle)
        self.workbench_nav_subtitle = nav_subtitle
        self.workbench_nav_spacer = QWidget()
        self.workbench_nav_spacer.setFixedHeight(6)
        nav_layout.addWidget(self.workbench_nav_spacer)

        self.workbench_nav_buttons = {}
        self._workbench_nav_button_texts = {}
        self.workbench_nav_group = QButtonGroup(self)
        self.workbench_nav_group.setExclusive(True)
        nav_icons = {
            "overview": QStyle.SP_DesktopIcon,
            "review": QStyle.SP_FileDialogDetailedView,
            "imports": QStyle.SP_DialogOpenButton,
            "logs": QStyle.SP_FileIcon,
            "mobile_upload": QStyle.SP_ArrowUp,
            "export": QStyle.SP_DialogSaveButton,
            "mail": QStyle.SP_MessageBoxInformation,
            "rules": QStyle.SP_FileDialogContentsView,
            "settings": QStyle.SP_ComputerIcon,
            "data": QStyle.SP_DriveHDIcon,
            "about": QStyle.SP_MessageBoxQuestion,
        }
        self._toolbar_icon_tooltips = {
            "help": "帮助",
            "notify": "通知",
        }


        def add_nav_button(
            key: str,
            text: str,
            handler=None,
            checked: bool = False,
            *,
            selectable: bool = True,
            enabled: bool = True,
        ):
            button = QPushButton(text)
            button.setObjectName(f"workbench_nav_{key}")
            button.setProperty("class", "WorkbenchNavButton")
            button.setCheckable(selectable)
            button.setChecked(checked if selectable else False)
            button.setMinimumHeight(40)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setIcon(self.style().standardIcon(nav_icons[key]))
            button.setEnabled(enabled)
            if handler is not None:
                button.clicked.connect(handler)
            if selectable:
                self.workbench_nav_group.addButton(button)
            nav_layout.addWidget(button)
            self._workbench_nav_button_texts[key] = text
            self.workbench_nav_buttons[key] = button
            return button

        add_nav_button("overview", "今日工作台", lambda *_a: self._switch_main_page("overview"))
        add_nav_button("review", "发票审核", lambda *_a: self._switch_main_page("review"))
        add_nav_button("imports", "导入中心", lambda *_a: self._switch_main_page("imports"))
        add_nav_button("export", "报销组与导出", lambda *_a: self._switch_main_page("export"))
        add_nav_button("settings", "系统设置", lambda *_a: self._switch_main_page("settings"))
        add_nav_button("logs", "操作日志", lambda *_a: self._switch_main_page("logs"), selectable=False, enabled=False)
        self.workbench_nav_buttons["logs"].hide()

        # Map legacy sub-keys for backward compatibility & direct action proxies
        self.workbench_nav_buttons["mobile_upload"] = add_nav_button("mobile_upload", "扫码上传", lambda *_a: self._switch_main_page("imports", sub_tab=1), selectable=False, enabled=True)
        self.workbench_nav_buttons["mobile_upload"].hide()
        self.workbench_nav_buttons["mail"] = add_nav_button("mail", "邮箱导入", lambda *_a: self._switch_main_page("imports", sub_tab=2), selectable=False, enabled=True)
        self.workbench_nav_buttons["mail"].hide()
        self.workbench_nav_buttons["rules"] = add_nav_button("rules", "规则管理", lambda *_a: self._switch_main_page("settings", sub_tab=2), selectable=False, enabled=True)
        self.workbench_nav_buttons["rules"].hide()
        self.workbench_nav_buttons["data"] = add_nav_button("data", "数据与备份", lambda *_a: self._switch_main_page("settings", sub_tab=5), selectable=False, enabled=True)
        self.workbench_nav_buttons["data"].hide()
        self.workbench_nav_buttons["about"] = add_nav_button("about", "关于我们", lambda *_a: self._switch_main_page("settings", sub_tab=6), selectable=False, enabled=True)
        self.workbench_nav_buttons["about"].hide()

        root_layout.addWidget(self.workbench_nav)

        # Central QStackedWidget for 6 V2 IA business pages
        self.center_stack = QStackedWidget(central_widget)
        root_layout.addWidget(self.center_stack, 1)

        # Page 0: Overview Dashboard ("总览")
        self.overview_page = self._build_overview_page_view()
        self.dashboard_page = self.overview_page
        self.center_stack.addWidget(self.overview_page)

        # Page 1: Review Workbench ("发票审核")
        self.workbench_content = QWidget()
        self.review_page = self.workbench_content
        self.main_layout = QVBoxLayout(self.workbench_content)
        main_layout = self.main_layout
        main_layout.setContentsMargins(12, 0, 12, 0)
        main_layout.setSpacing(8)

        self.search_reload_timer = QTimer(self)
        self.search_reload_timer.setSingleShot(True)
        self.search_reload_timer.setInterval(250)

        nav_layout.addStretch(1)
        self.btn_collapse_nav = QPushButton("收起侧边栏")
        self.btn_collapse_nav.setObjectName("workbench_nav_collapse")
        self.btn_collapse_nav.setProperty("class", "WorkbenchNavButton")
        self.btn_collapse_nav.setIcon(self.style().standardIcon(QStyle.SP_TitleBarShadeButton))
        self.btn_collapse_nav.setToolTip("收起或展开侧边栏")
        self.btn_collapse_nav.setMinimumHeight(32)
        self.btn_collapse_nav.clicked.connect(self._toggle_workbench_nav_collapsed)
        nav_layout.addWidget(self.btn_collapse_nav)

        # Shortcut help entry lives at nav bottom
        self.btn_shortcut_help = QPushButton("快捷键：Enter 通过 · Del 忽略")
        self.btn_shortcut_help.setObjectName("WorkbenchShortcutEntry")
        self.btn_shortcut_help.setProperty("class", "WorkbenchNavButton")
        self.btn_shortcut_help.setMinimumHeight(32)
        self.btn_shortcut_help.setFlat(True)
        self.btn_shortcut_help.setStyleSheet("text-align: left; padding-left: 6px; font-size: 11px; color: #667085;")
        self.btn_shortcut_help.clicked.connect(self._toggle_shortcut_disclosure)
        nav_layout.addWidget(self.btn_shortcut_help)

        self.shortcut_disclosure = ShortcutDisclosure(self)
        self.shortcut_disclosure.setWindowFlags(Qt.Popup)
        self.shortcut_disclosure.hide()

        self.search_reload_timer.timeout.connect(self._load_invoices)

        # 0. Top Action Bar
        self.workbench_top_toolbar = QFrame()
        self.workbench_top_toolbar.setObjectName("WorkbenchTopToolbar")
        action_layout = QHBoxLayout(self.workbench_top_toolbar)
        action_layout.setContentsMargins(0, 10, 0, 4)
        action_layout.setSpacing(8)

        self.txt_search = QLineEdit(self.workbench_top_toolbar)
        self.txt_search.setPlaceholderText("搜索发票号 / 销售方 / 购买方 / 金额 / 邮件主题    Ctrl + F")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self._schedule_invoice_reload)
        action_layout.addWidget(self.txt_search, 2)

        self.btn_import_local = make_button("导入", variant="toolbar")
        self.btn_import_local.setProperty("emphasis", "primary")
        self.import_menu = QMenu(self)
        self.action_import_local = self._make_menu_action(
            "本地文件导入", QStyle.SP_DialogOpenButton, self._import_local_clicked, "选择本地文件夹导入 PDF/ZIP/OFD 发票"
        )
        self.action_import_mobile = self._make_menu_action(
            "扫码上传", QStyle.SP_ArrowUp, self._mobile_upload_clicked, "打开扫码上传入口"
        )
        self.action_import_mail = self._make_menu_action(
            "邮箱导入", QStyle.SP_MessageBoxInformation, lambda: self._switch_main_page("imports", sub_tab=2), "进入邮箱导入页并查看账号与最近扫描结果"
        )
        self.import_menu.addAction(self.action_import_local)
        self.import_menu.addAction(self.action_import_mobile)
        self.import_menu.addAction(self.action_import_mail)
        self.btn_import_local.setMenu(self.import_menu)
        action_layout.addWidget(self.btn_import_local)

        self.btn_mobile_upload = make_button("扫码", variant="toolbar")
        self.btn_mobile_upload.clicked.connect(self._mobile_upload_clicked)
        self.btn_mobile_upload.hide()

        self.btn_scan_email = make_button("同步", variant="toolbar")
        self.btn_scan_email.clicked.connect(self._scan_email_clicked)
        action_layout.addWidget(self.btn_scan_email)

        action_layout.addStretch()
        self.btn_toolbar_export = make_button("导出", variant="toolbar")
        self.btn_toolbar_export.clicked.connect(self._export_claim_package)
        action_layout.addWidget(self.btn_toolbar_export)

        self.btn_more = make_button("更多  ▼", variant="toolbar")
        self.btn_toolbar_help = QToolButton(self.workbench_top_toolbar)
        self.btn_toolbar_help.setObjectName("WorkbenchTopIconButton")
        self.btn_toolbar_help.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxQuestion))
        self.btn_toolbar_help.setToolTip(self._toolbar_icon_tooltips["help"])
        self.btn_toolbar_help.clicked.connect(self._show_about_dialog)
        self.btn_toolbar_help.hide()

        self.btn_toolbar_notify = QToolButton(self.workbench_top_toolbar)
        self.btn_toolbar_notify.setObjectName("WorkbenchTopIconButton")
        self.btn_toolbar_notify.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        self.btn_toolbar_notify.setToolTip(self._toolbar_icon_tooltips["notify"])
        self.btn_toolbar_notify.clicked.connect(self._toggle_log)
        self.btn_toolbar_notify.hide()

        self.btn_toolbar_user = QPushButton("本地模式 ▾")
        self.btn_toolbar_user.setObjectName("WorkbenchUserButton")
        self.btn_toolbar_user.setProperty("variant", "toolbar")
        self.btn_toolbar_user.setMinimumHeight(34)

        self.more_menu = QMenu(self)
        self.more_menu.setToolTipsVisible(True)

        self.action_refresh = self._make_menu_action(
            "刷新数据", QStyle.SP_BrowserReload, self._manual_refresh, "刷新当前发票列表"
        )
        self.action_mobile_upload = self._make_menu_action(
            "扫码上传", QStyle.SP_ArrowUp, self._mobile_upload_clicked, "打开扫码上传入口"
        )
        self.action_scan_email = self._make_menu_action(
            "邮箱同步", QStyle.SP_MessageBoxInformation, self._scan_email_clicked, "同步配置邮箱中的发票"
        )
        self.action_toolbar_export = self._make_menu_action(
            "导出当前视图", QStyle.SP_DialogSaveButton, self._show_export_page, "进入批量导出页并选择导出范围"
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
        self.more_menu.addAction(self.action_refresh)
        self.more_menu.addAction(self.action_mobile_upload)
        self.more_menu.addAction(self.action_scan_email)
        self.more_menu.addAction(self.action_toolbar_export)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self.action_runtime)
        self.more_menu.addAction(self.action_exports)
        self.more_menu.addAction(self.action_logs)
        self.more_menu.addSeparator()
        self.more_menu.addAction(self.action_copy_diag)
        self.more_menu.addAction(self.action_export_diag)
        self.more_menu.addAction(self.action_github_issues)

        self.btn_more.setMenu(self.more_menu)
        action_layout.addWidget(self.btn_more)
        self.btn_toolbar_user.hide()

        main_layout.addWidget(self.workbench_top_toolbar)

        # 1. Top Filter Bar (36px Compact Segmented Filter Bar)
        self.filter_bar_widget = SummaryStrip()
        self.filter_bar_widget.setObjectName("StatusFilterCardGroup")
        self.filter_bar_widget.setFixedHeight(56)
        filter_layout = self.filter_bar_widget.layout()
        filter_layout.setContentsMargins(12, 8, 12, 8)
        filter_layout.setSpacing(8)

        self.filter_buttons = {}
        self.filter_base_labels = {
            "all": "全部",
            TO_REVIEW: "待审核",
            APPROVED: "已通过",
            IGNORED: "已忽略",
            ERROR: "异常",
        }

        state_by_status = {
            "all": "info",
            TO_REVIEW: "warning",
            APPROVED: "success",
            IGNORED: "muted",
            ERROR: "danger",
        }
        icon_by_status = {
            "all": "◎",
            TO_REVIEW: "◔",
            APPROVED: "●",
            IGNORED: "◌",
            ERROR: "▲",
        }
        for status, text in self.filter_base_labels.items():
            card = CompactStatCard(
                text,
                "0",
                state=state_by_status[status],
                icon_text=icon_by_status[status],
            )
            card.setFocusPolicy(Qt.StrongFocus)
            card.setFixedHeight(40)
            card.setMinimumWidth(118)
            card.set_selected(status == "all")
            card.clicked.connect(lambda s=status: self._change_filter(s))
            filter_layout.addWidget(card, 0)
            self.filter_buttons[status] = card

        filter_layout.addStretch()

        # Advanced Filter Menu Popup for Secondary Filters
        self.btn_advanced_filter = make_button("筛选 ▾", variant="secondary", min_width=72)
        self.advanced_filter_menu = QMenu(self)
        
        self.chk_unlinked = QCheckBox("未关联报销组", self)
        self.chk_unlinked.stateChanged.connect(self._on_chk_unlinked_changed)
        action_unlinked = QWidgetAction(self)
        action_unlinked.setDefaultWidget(self.chk_unlinked)
        self.advanced_filter_menu.addAction(action_unlinked)

        self.chk_needs_fix = QCheckBox("待补全", self)
        self.chk_needs_fix.stateChanged.connect(self._on_chk_needs_fix_changed)
        action_needs_fix = QWidgetAction(self)
        action_needs_fix.setDefaultWidget(self.chk_needs_fix)
        self.advanced_filter_menu.addAction(action_needs_fix)

        self.chk_show_deleted = QCheckBox("显示已删除", self)
        self.chk_show_deleted.stateChanged.connect(self._schedule_invoice_reload)
        action_show_deleted = QWidgetAction(self)
        action_show_deleted.setDefaultWidget(self.chk_show_deleted)
        self.advanced_filter_menu.addAction(action_show_deleted)

        self.btn_advanced_filter.setMenu(self.advanced_filter_menu)
        filter_layout.addWidget(self.btn_advanced_filter)

        self.btn_reset_filters = make_button("重置", variant="secondary", min_width=60)
        self.btn_reset_filters.clicked.connect(self._reset_invoice_filters)
        filter_layout.addWidget(self.btn_reset_filters)

        # 1c. Active Filter Chips Summary
        self.filter_chips_widget = QWidget()
        self.filter_chips_layout = QHBoxLayout(self.filter_chips_widget)
        self.filter_chips_layout.setContentsMargins(5, 2, 5, 2)
        self.filter_chips_layout.setSpacing(6)

        self.lbl_chips_title = QLabel("已启用:")
        self.lbl_chips_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_chips_title.setStyleSheet("color: #4B5563;")
        self.filter_chips_layout.addWidget(self.lbl_chips_title)

        self.chips_container_layout = QHBoxLayout()
        self.chips_container_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_container_layout.setSpacing(6)
        self.filter_chips_layout.addLayout(self.chips_container_layout)

        self.filter_chips_layout.addStretch()

        main_layout.addWidget(self.filter_chips_widget)
        self.filter_chips_widget.setVisible(False)

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
        self.record_header = QFrame()
        self.record_header.setObjectName("InvoiceRecordHeader")
        self.record_header.setFixedHeight(26)
        record_header_layout = QHBoxLayout(self.record_header)
        record_header_layout.setContentsMargins(2, 0, 2, 0)
        record_header_layout.setSpacing(8)
        self.lbl_record_section_title = QLabel("发票记录")
        self.lbl_record_section_title.setObjectName("InvoiceRecordTitle")
        record_header_layout.addWidget(self.lbl_record_section_title)
        self.lbl_record_count = QLabel("当前 0 / 0")
        self.lbl_record_count.setObjectName("InvoiceRecordMeta")
        record_header_layout.addWidget(self.lbl_record_count)
        record_header_layout.addStretch(1)
        self.lbl_record_sort = QLabel("按费用日期倒序")
        self.lbl_record_sort.setObjectName("InvoiceRecordSort")
        record_header_layout.addWidget(self.lbl_record_sort)
        self.lbl_record_selection = QLabel("已选 0 张")
        self.lbl_record_selection.setObjectName("InvoiceRecordSelection")
        record_header_layout.addWidget(self.lbl_record_selection)

        self.table = QTableWidget()
        self.table.setColumnCount(len(VISIBLE_COLUMN_DEFINITIONS))
        self.table.setHorizontalHeaderLabels([label for _key, label in VISIBLE_COLUMN_DEFINITIONS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalScrollBar().valueChanged.connect(self._maybe_load_more_invoices)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.verticalHeader().setMinimumSectionSize(28)
        self.table.verticalHeader().setMaximumSectionSize(32)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().sectionClicked.connect(self._show_column_filter_popup)
        self.table.horizontalHeader().viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        self._badge_delegate = QueueBadgeDelegate(self.table)
        self.table.setItemDelegateForColumn(0, self._badge_delegate)
        self.table.setItemDelegateForColumn(1, self._badge_delegate)
        self._refresh_column_filter_headers()

        # Final 0.1.4 review workbench default columns:
        # review status, material status, expense date, amount, seller, invoice number.
        self._min_column_widths = {0: 68, 1: 62, 2: 86, 3: 84, 4: 220, 5: 178}
        for _column, _width in self._min_column_widths.items():
            self.table.setColumnWidth(_column, _width)

        # Enforce minimum column widths on interactive resize
        self.table.horizontalHeader().sectionResized.connect(self._on_header_section_resized)

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

        self.empty_btn_import = make_button("导入发票", variant="secondary", min_width=56)
        self.empty_btn_import.clicked.connect(self._import_local_clicked)

        self.empty_btn_settings = make_button("配置邮箱", variant="secondary", min_width=56)
        self.empty_btn_settings.clicked.connect(self._open_settings_dialog)

        self.empty_btn_scan = make_button("扫描邮箱", variant="secondary", min_width=56)
        self.empty_btn_scan.clicked.connect(self._scan_email_clicked)

        self.empty_btn_mobile_upload = make_button("扫码上传", variant="secondary", min_width=56)
        self.empty_btn_mobile_upload.clicked.connect(self._mobile_upload_clicked)

        # Search / filter fail actions
        self.empty_btn_clear_search = make_button("清空搜索", variant="primary", min_width=76)
        self.empty_btn_clear_search.clicked.connect(self._clear_search_clicked)

        self.empty_btn_reset_filters = make_button("重置筛选", variant="secondary", min_width=76)
        self.empty_btn_reset_filters.clicked.connect(self._reset_invoice_filters)

        btn_layout.addWidget(self.empty_btn_import)
        btn_layout.addWidget(self.empty_btn_mobile_upload)
        btn_layout.addWidget(self.empty_btn_settings)
        btn_layout.addWidget(self.empty_btn_scan)
        btn_layout.addWidget(self.empty_btn_clear_search)
        btn_layout.addWidget(self.empty_btn_reset_filters)

        empty_layout.addLayout(btn_layout)

        self.left_stack.addWidget(self.empty_widget)

        # Upper container to group left_stack and preview controls
        self.left_upper_widget = QFrame()
        self.left_upper_widget.setObjectName("InvoiceTableCard")
        self.left_upper_widget.setProperty("class", "WorkbenchCard")
        self.left_upper_widget.setFixedHeight(276)
        left_upper_layout = QVBoxLayout(self.left_upper_widget)
        left_upper_layout.setContentsMargins(6, 6, 6, 6)
        left_upper_layout.setSpacing(4)
        left_upper_layout.addWidget(self.record_header)
        left_upper_layout.addWidget(self.left_stack)

        # Initialize the New Preview Panel
        self._init_preview_panel()
        if hasattr(self, "preview_panel") and self.preview_panel is not None:
            self.preview_panel.setProperty("class", "WorkbenchCard")
            self.preview_panel.setMinimumHeight(380)
            self.preview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Build Middle Workspace via pure QVBoxLayout (NO vertical QSplitter)
        self.middle_workspace = QWidget()
        self.middle_workspace.setObjectName("MiddleWorkspace")
        workspace_layout = QVBoxLayout(self.middle_workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(8)

        self.filter_bar_widget.setFixedHeight(48)
        workspace_layout.setSpacing(6)
        workspace_layout.addWidget(self.filter_bar_widget, 0)
        workspace_layout.addWidget(self.left_upper_widget, 0)
        workspace_layout.addWidget(self.preview_panel, 1)

        # Dummy left_splitter shim for backward compatibility with tests & QSettings
        class DummyLeftSplitter(QSplitter):
            def __init__(self, upper, lower, parent=None):
                super().__init__(Qt.Vertical, parent)
                self._upper = upper
                self._lower = lower
                self._sizes = [230, 520]
            def widget(self, index: int):
                if index == 0:
                    return self._upper
                if index == 1:
                    return self._lower
                return super().widget(index)
            def sizes(self):
                return list(self._sizes)
            def setSizes(self, list_of_sizes):
                if len(list_of_sizes) >= 2:
                    self._sizes = [int(list_of_sizes[0]), int(list_of_sizes[1])]

        self.left_splitter = DummyLeftSplitter(self.left_upper_widget, self.preview_panel, self)

        splitter.addWidget(self.middle_workspace)

        # Right Column - InvoiceDetailPanel
        self._setup_detail_panel()
        splitter.addWidget(self._detail_panel)
        self._proxy_detail_panel_attrs()
        # Populate category dropdown after proxies are set up
        self._refresh_category_options()

        # Set default proportions: Table takes 60%, Form takes 40%
        splitter.setSizes([650, 450])

        # Add Page 1 (发票审核) to center_stack
        self.center_stack.addWidget(self.workbench_content)

        # Page 2: Import Center ("导入中心")
        self.imports_page = self._build_imports_page_view()
        self.import_center_page = self.imports_page
        self.center_stack.addWidget(self.imports_page)

        # Page 3: Batch Export ("批量导出")
        self.export_page = self._build_export_page_view()
        self.center_stack.addWidget(self.export_page)

        # Page 4: Audit Logs ("操作日志")
        self.logs_page = self._build_logs_page_view()
        self.audit_log_page = self.logs_page
        self.center_stack.addWidget(self.logs_page)

        # Page 5: System Settings ("系统设置")
        self.settings_page = self._build_settings_page_view()
        self.center_stack.addWidget(self.settings_page)

        # Set default active page to Page 1 (发票审核)
        self.center_stack.setCurrentIndex(1)
        if "review" in self.workbench_nav_buttons:
            self.workbench_nav_buttons["review"].setChecked(True)

        self._apply_workbench_metrics()
        self._setup_workbench_shortcuts()

        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(500)
        self._splitter_save_timer.timeout.connect(self._save_splitter_prefs)
        self.left_splitter.splitterMoved.connect(
            lambda _pos, _idx: self._splitter_save_timer.start()
        )
        self.main_splitter.splitterMoved.connect(
            lambda _pos, _idx: self._splitter_save_timer.start()
        )

        # 3. Bottom Status Bar & Collapsible Log Panel
        status_bar = QWidget()
        self.status_bar = status_bar
        status_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        status_bar.setFixedHeight(36)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(6, 3, 6, 3)

        self.lbl_status_left = QLabel("当前筛选 0 张")
        self.lbl_status_left.setFont(QFont("Segoe UI", 9))
        self.lbl_status_left.setStyleSheet("color: #4B5563;")
        self.lbl_status_left.setToolTip("当前发票筛选状态")
        self.lbl_status_left.setMinimumWidth(120)
        status_layout.addWidget(self.lbl_status_left, 1)

        self.lbl_status_middle = QLabel("未选择发票")
        self.lbl_status_middle.setFont(QFont("Segoe UI", 9))
        self.lbl_status_middle.setStyleSheet("color: #4B5563;")
        self.lbl_status_middle.setToolTip("选中发票及金额合计")
        self.lbl_status_middle.setAlignment(Qt.AlignCenter)
        self.lbl_status_middle.setMinimumWidth(180)
        status_layout.addWidget(self.lbl_status_middle, 1)

        # Right container
        self.status_actions_container = QWidget(status_bar)
        right_container = self.status_actions_container
        right_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        right_layout = QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right_layout.setSizeConstraint(QLayout.SetFixedSize)

        self.lbl_version = QLabel(APP_VERSION)
        self.lbl_version.setFont(QFont("Segoe UI", 8))
        self.lbl_version.setStyleSheet("color: #6B7280;")
        self.lbl_version.setToolTip("当前 Invoice Hub 版本")
        right_layout.addWidget(self.lbl_version)

        self.btn_load_all = make_button("加载全部", variant="secondary", min_width=56)
        self.btn_load_all.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_load_all.ensurePolished()
        self.btn_load_all.setMinimumWidth(
            max(
                self.btn_load_all.fontMetrics().horizontalAdvance(self.btn_load_all.text()) + 24,
                self.btn_load_all.sizeHint().width(),
                56,
            )
        )
        self.btn_load_all.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_load_all.setToolTip("首屏仅加载部分记录，点击加载完整列表")
        self.btn_load_all.clicked.connect(self._load_all_invoices_clicked)
        self.btn_load_all.setVisible(False)
        right_layout.addWidget(self.btn_load_all)

        self.btn_toggle_log = make_button("展开日志", variant="secondary", min_width=76)
        self.btn_toggle_log.setVisible(False)
        self.btn_toggle_log.clicked.connect(self._toggle_log)
        right_layout.addWidget(self.btn_toggle_log)

        status_layout.addWidget(right_container, 0)
        right_container.show()

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
        self.log_drawer_host = QWidget()
        self.log_drawer_layout = QVBoxLayout(self.log_drawer_host)
        self.log_drawer_layout.setContentsMargins(0, 0, 0, 0)
        self.log_drawer_layout.setSpacing(0)
        log_container_layout.addWidget(self.log_drawer_host)
        self._mount_log_widget("drawer")

        # Bottom dock area keeps the status bar pinned while the log drawer expands separately.
        self.bottom_panel = QWidget()
        self.bottom_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bottom_layout = QVBoxLayout(self.bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)
        bottom_layout.addWidget(status_bar)
        self.bottom_panel.setMaximumHeight(36)
        main_layout.addWidget(self.bottom_panel)
        self.bottom_panel.show()
        self.log_drawer = QWidget()
        self.log_drawer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.log_drawer_layout = QVBoxLayout(self.log_drawer)
        self.log_drawer_layout.setContentsMargins(0, 0, 0, 0)
        self.log_drawer_layout.setSpacing(0)
        self.log_container.hide()
        self.log_drawer_layout.addWidget(self.log_container)
        self.log_drawer.hide()
        self.log_drawer.setFixedHeight(0)
        main_layout.addWidget(self.log_drawer)
        self._log_panel_visible = False

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
            on_delete_claim=self._delete_empty_claim,
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
        self.btn_delete_claim = dp.btn_delete_claim
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
        self.lbl_evidence_name = dp.lbl_evidence_name
        self.lbl_evidence_missing = dp.lbl_evidence_missing
        self.btn_add_evidence = dp.btn_add_evidence
        self.update_evidence_row = dp.update_evidence_row

    def _set_right_panel_state(self, has_records: bool):
        if not hasattr(self, "right_stack") or self.right_stack is None:
            return
        target = self.right_content_widget if has_records else self.right_empty_widget
        widgets_in_stack = [self.right_stack.widget(i) for i in range(self.right_stack.count())]
        if target in widgets_in_stack and self.right_stack.currentWidget() != target:
            self.right_stack.setCurrentWidget(target)

    def _schedule_invoice_reload(self, *_args):
        # Debounce invoice reloads when search/filter controls change.
        self._column_filters_load_all = False
        if hasattr(self, "search_reload_timer"):
            self.search_reload_timer.start()

    def _reset_invoice_filters(self):
        # Reset search and quick filters to the default view.
        self.txt_search.setText("")
        
        # Block signals to prevent redundant loads during reset
        self.chk_unlinked.blockSignals(True)
        self.chk_needs_fix.blockSignals(True)
        self.chk_unlinked.setChecked(False)
        self.chk_needs_fix.setChecked(False)
        self.chk_unlinked.blockSignals(False)
        self.chk_needs_fix.blockSignals(False)

        if hasattr(self, "chk_show_deleted"):
            self.chk_show_deleted.setChecked(False)
        if hasattr(self, "search_reload_timer"):
            self.search_reload_timer.stop()
            
        self.column_filters.clear()
        self._column_filters_load_all = False
        self._limited_first_load_active = False
        self._limited_first_load_total = 0
        self._is_first_load = True
        self._refresh_column_filter_headers()
        self._update_filter_summary_chips()

        self.current_filter_status = None
        for s, btn in self.filter_buttons.items():
            if hasattr(btn, "set_selected"):
                btn.set_selected(s == "all")
            else:
                btn.setChecked(s == "all")
        self._load_invoices()

    def _column_filter_value_getters(self) -> dict:
        return {
            "status": self._get_invoice_data_status,
            "source": self._get_invoice_source,
            "review_status": self._get_invoice_review_status_chinese,
        }

    def _refresh_column_filter_headers(self):
        if not hasattr(self, "table"):
            return
        for index, (key, label) in enumerate(VISIBLE_COLUMN_DEFINITIONS):
            active = is_filter_active(self.column_filters.get(key))
            item = self.table.horizontalHeaderItem(index)
            if item is None:
                item = QTableWidgetItem()
                self.table.setHorizontalHeaderItem(index, item)
            item.setText(f"{label} · 已筛选" if active else label)
            item.setToolTip(self._column_filter_header_tooltip(label, active))

    def _column_filter_header_tooltip(self, label: str, active: bool) -> str:
        if active:
            return f"{label}：已启用列筛选，点击右侧修改"
        return f"{label}：点击列标题右侧筛选"

    def _set_column_filter(self, key: str, spec: dict):
        if key not in COLUMN_KEYS and key != "review_status":
            return
        if is_filter_active(spec):
            self.column_filters[key] = dict(spec)
        else:
            self.column_filters.pop(key, None)
        self._sync_column_filters_to_checkboxes()
        self._update_filter_summary_chips()
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
        return local_x >= max(0, width - 20)

    def _show_column_filter_popup(self, section: int):
        if section < 0 or section >= len(VISIBLE_COLUMN_DEFINITIONS):
            return
        if not self._should_open_column_filter_popup(section):
            self._column_filter_header_press_pos = None
            return
        key, _label = VISIBLE_COLUMN_DEFINITIONS[section]
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

    def _on_header_section_resized(self, index, old_size, new_size):
        if getattr(self, "_ignore_min_widths", False):
            return
        min_w = getattr(self, "_min_column_widths", {}).get(index)
        if min_w is not None and new_size < min_w:
            header = self.table.horizontalHeader()
            header.blockSignals(True)
            self.table.setColumnWidth(index, min_w)
            header.blockSignals(False)
        self._adjust_column_4_width()

    def _adjust_column_4_width(self):
        if getattr(self, "_ignore_min_widths", False):
            return
        if not hasattr(self, "table") or self.table is None:
            return
        viewport_w = self.table.viewport().width()
        if viewport_w <= 0:
            return
        other_w = 0
        for i in range(self.table.columnCount()):
            if i != 4:
                other_w += self.table.columnWidth(i)
        target_w = max(260, viewport_w - other_w)
        header = self.table.horizontalHeader()
        header.blockSignals(True)
        self.table.setColumnWidth(4, target_w)
        header.blockSignals(False)

    def eventFilter(self, obj, event):
        header = self.table.horizontalHeader() if hasattr(self, "table") else None
        preview_focus_dialog = getattr(self, "preview_focus_dialog", None)
        preview_workbench = getattr(self, "preview_workbench", None)
        if event.type() == QEvent.KeyPress and preview_focus_dialog is not None and hasattr(self, "_handle_preview_focus_keypress"):
            in_preview_focus = obj is preview_focus_dialog
            if not in_preview_focus and preview_workbench is not None and isinstance(obj, QWidget):
                in_preview_focus = obj is preview_workbench or preview_workbench.isAncestorOf(obj)
            if in_preview_focus and self._handle_preview_focus_keypress(event):
                return True
        if header is not None and obj is header.viewport():
            if event.type() == QEvent.MouseButtonPress:
                self._column_filter_header_press_pos = event.position().toPoint()
        elif hasattr(self, "table") and obj is self.table:
            if event.type() == QEvent.Resize:
                self._adjust_column_4_width()
        return super().eventFilter(obj, event)

    def _invoke_workbench_action(self, action) -> bool:
        if QApplication.activeModalWidget() is not None:
            return False
        if is_keyboard_input_target(QApplication.focusWidget()):
            return False
        action()
        return True

    def _invoice_by_id(self, invoice_id):
        for invoice in getattr(self, "invoices_list", []):
            if invoice.get("id") == invoice_id:
                return invoice
        return None

    def _row_for_invoice_id(self, invoice_id) -> int:
        for row, invoice in enumerate(getattr(self, "invoices_list", [])):
            if invoice.get("id") == invoice_id:
                return row
        return -1

    def _apply_single_row_selection(self, row: int) -> bool:
        if row < 0 or row >= self.table.rowCount():
            return False
        model = self.table.selectionModel()
        if model is None:
            return False
        index = self.table.model().index(row, 0)
        model.select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        model.setCurrentIndex(index, QItemSelectionModel.Current | QItemSelectionModel.Rows)
        self.table.setCurrentCell(row, 0)
        self.table.selectRow(row)
        return len(model.selectedRows()) == 1

    def _ensure_single_row_selection(self, row: int) -> None:
        if row < 0:
            return
        if not self._apply_single_row_selection(row):
            QTimer.singleShot(0, lambda checked_row=row: self._apply_single_row_selection(checked_row))

    def _select_invoice_by_id(self, invoice_id, *, fallback_first=True):
        invoice = self._invoice_by_id(invoice_id)
        if invoice is None and fallback_first and self.invoices_list:
            invoice = self.invoices_list[0]
        target_id = invoice.get("id") if invoice is not None else None
        target_row = self._row_for_invoice_id(target_id) if target_id is not None else -1
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
            self.table.setCurrentItem(None)
            if self.table.selectionModel() is not None:
                self.table.selectionModel().clearCurrentIndex()
            if target_row >= 0:
                self._apply_single_row_selection(target_row)
        finally:
            self.table.blockSignals(False)
        if target_row >= 0:
            self._ensure_single_row_selection(target_row)
        self._on_table_selection_changed()
        return target_row >= 0

    def _move_invoice_selection(self, delta: int) -> None:
        if not self.invoices_list:
            return
        row = self.table.currentRow()
        if row < 0:
            row = 0 if delta >= 0 else len(self.invoices_list) - 1
        else:
            row = max(0, min(len(self.invoices_list) - 1, row + delta))
        invoice_id = self.invoices_list[row].get("id")
        self._select_invoice_by_id(invoice_id)

    def _handle_workbench_escape(self) -> None:
        modal = QApplication.activeModalWidget()
        if modal is not None:
            modal.close()
            return
        if getattr(self, "preview_focus_dialog", None) is not None:
            self._exit_preview_focus_mode()
            return
        if getattr(self, "_column_filter_popup", None) is not None:
            self._column_filter_popup.close()

    def _register_shortcut(self, target_widget, store: dict[str, QShortcut], sequence: str, action, *, guarded: bool = True) -> None:
        shortcut = QShortcut(QKeySequence(sequence), target_widget)
        shortcut.setContext(Qt.WindowShortcut)
        if guarded:
            shortcut.activated.connect(lambda callback=action: self._invoke_workbench_action(callback))
        else:
            shortcut.activated.connect(action)
        store[sequence] = shortcut

    def _bind_review_shortcuts(self, target_widget, store: dict[str, QShortcut] | None = None) -> dict[str, QShortcut]:
        shortcuts = {} if store is None else store
        self._register_shortcut(target_widget, shortcuts, "Return", lambda: self._set_selected_status(APPROVED))
        self._register_shortcut(target_widget, shortcuts, "Enter", lambda: self._set_selected_status(APPROVED))
        self._register_shortcut(target_widget, shortcuts, "Delete", lambda: self._set_selected_status(IGNORED))
        self._register_shortcut(target_widget, shortcuts, "Ctrl+E", lambda: self._set_selected_status(ERROR))
        self._register_shortcut(target_widget, shortcuts, "Esc", self._handle_workbench_escape, guarded=False)
        return shortcuts


    # ── V2 Six Page IA Views ───────────────────────────────────

    def _collect_overview_metrics(self) -> dict | None:
        if not hasattr(self, "db") or self.db is None:
            return None
        try:
            invoices = self.db.get_all_invoices(include_deleted=False)
        except Exception:
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        month_prefix = datetime.now().strftime("%Y-%m")
        today_imported = 0
        needs_fix = 0
        month_total = Decimal("0")

        for inv in invoices:
            created_at = str(inv.get("created_at") or "")
            if created_at[:10] == today:
                today_imported += 1
            quality = self._get_invoice_quality(inv)
            if quality in {"待补全", "缺原件", "缺证明", "未识别"}:
                needs_fix += 1
            date_text = str(inv.get("expense_date") or inv.get("invoice_date") or "").strip()
            if date_text.startswith(month_prefix):
                try:
                    month_total += Decimal(str(inv.get("total_amount") or "0").strip() or "0")
                except (InvalidOperation, ValueError):
                    pass

        return {
            "today_imported": today_imported,
            "to_review": self.db.count_invoices_for_status(TO_REVIEW),
            "error": self.db.count_invoices_for_status(ERROR),
            "needs_fix": needs_fix,
            "month_total": month_total,
            "total": len(invoices),
        }

    def _read_recent_runtime_logs(self, max_lines: int = 80) -> list[str]:
        log_dir = RUNTIME_DIR / "logs"
        if not log_dir.exists():
            return []
        log_files = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not log_files:
            return []
        try:
            lines = log_files[0].read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []
        return [line for line in lines[-max_lines:] if line.strip()]

    def _refresh_overview_page(self) -> None:
        metrics = self._collect_overview_metrics()
        if metrics is None:
            for label in self.overview_value_labels.values():
                label.set_value("—")
            self.lbl_overview_recent_imports.setText("暂无可用统计，等待数据库连接或首批导入完成。")
            self.lbl_overview_health.setText("当前无法读取审核队列统计，导入后会自动刷新。")
            return

        self.overview_value_labels["today_imported"].set_value(f"{metrics['today_imported']} 张")
        self.overview_value_labels["to_review"].set_value(f"{metrics['to_review']} 张")
        self.overview_value_labels["error"].set_value(f"{metrics['error']} 张")
        self.overview_value_labels["needs_fix"].set_value(f"{metrics['needs_fix']} 张")
        self.overview_value_labels["month_total"].set_value(f"¥{metrics['month_total']:.2f}")
        self.lbl_overview_recent_imports.setText(
            f"当前数据库共有 {metrics['total']} 张有效记录，今天新增 {metrics['today_imported']} 张。"
        )
        self.lbl_overview_health.setText(
            f"待审核 {metrics['to_review']} 张 / 异常 {metrics['error']} 张 / 待补全 {metrics['needs_fix']} 张。"
        )

    def _refresh_imports_page(self) -> None:
        from ..config import get_email_accounts

        log_lines = self._read_recent_runtime_logs()
        if hasattr(self, "txt_import_records"):
            self.txt_import_records.setPlainText(
                "\n".join(log_lines) if log_lines else "暂无历史日志文件。完成本地导入、扫码上传或邮箱扫描后会显示最近记录。"
            )

        if hasattr(self, "lbl_import_qr_status"):
            self.lbl_import_qr_status.setText("扫码上传服务未启动。点击下方按钮可启动真实上传服务并显示二维码。")

        if hasattr(self, "mail_checklist_layout"):
            while self.mail_checklist_layout.count():
                child = self.mail_checklist_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            cfg = getattr(self, "config", None) or load_config_safe()
            accounts = get_email_accounts(cfg)
            self.mail_account_checkboxes = []

            if not accounts:
                lbl_empty = QLabel("暂无已启用邮箱账号。点击“管理”进入系统设置完成配置。")
                lbl_empty.setStyleSheet("color: #94A3B8; font-size: 12px;")
                self.mail_checklist_layout.addWidget(lbl_empty)
            else:
                for acc in accounts:
                    row_widget = QWidget()
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(6, 4, 6, 4)
                    row_layout.setSpacing(8)

                    display_name = str(acc.get("name") or acc.get("address") or "未命名").strip()
                    masked_addr = mask_email(acc.get("address") or "")
                    provider = str(acc.get("provider") or "imap").strip()
                    months = int((acc.get("search") or {}).get("months_back", 3))
                    is_default = bool(acc.get("is_default") or acc.get("default"))

                    chk = QCheckBox(f"{display_name} ({masked_addr})")
                    chk.setChecked(is_default)
                    chk.setProperty("account_key", acc.get("mailbox_key") or acc.get("address"))
                    chk.setProperty("is_default", is_default)
                    row_layout.addWidget(chk)

                    if is_default:
                        row_layout.addWidget(make_badge("默认扫描账号", variant="primary"))

                    row_layout.addWidget(make_badge(provider.upper(), variant="info"))
                    row_layout.addWidget(make_badge(f"最近 {months} 个月", variant="muted"))
                    row_layout.addStretch()

                    self.mail_checklist_layout.addWidget(row_widget)
                    self.mail_account_checkboxes.append(chk)

        if hasattr(self, "lst_mail_accounts"):
            cfg = getattr(self, "config", None) or load_config_safe()
            lines = []
            for account in get_email_accounts(cfg):
                months = int((account.get("search") or {}).get("months_back", 3))
                display_name = str(account.get("name") or account.get("address") or "未命名邮箱").strip()
                provider = str(account.get("provider") or "imap").strip()
                lines.append(f"{display_name} · {provider} · 最近 {months} 个月")
            self.lst_mail_accounts.setPlainText(
                "\n".join(lines) if lines else "暂无已启用邮箱账号。请先在系统设置中完成邮箱配置。"
            )

        if hasattr(self, "lbl_mail_scan_summary"):
            last_scan_summary = getattr(self, "_last_scan_summary", {}) if hasattr(self, "_last_scan_summary") else {}
            if isinstance(last_scan_summary, dict) and last_scan_summary:
                summary_parts = [
                    f"{key}={value}"
                    for key, value in last_scan_summary.items()
                    if value not in (None, "", [], {})
                ]
                self.lbl_mail_scan_summary.setText("最近扫描结果：" + (" / ".join(summary_parts) if summary_parts else "无可展示摘要"))
            else:
                self.lbl_mail_scan_summary.setText("最近扫描结果：暂无记录。点击“开始扫描”开始拉取。")

        if hasattr(self, "imports_summary_strip"):
            cfg = getattr(self, "config", None) or load_config_safe()
            accounts = get_email_accounts(cfg)
            from ..credentials import has_auth_code

            default_acc = next((acc for acc in accounts if acc.get("is_default")), None)
            default_name = str(default_acc.get("name") or default_acc.get("address") or "无").strip() if default_acc else "无"
            missing_cnt = sum(1 for acc in accounts if acc.get("enabled", True) and not has_auth_code(acc.get("address", "")))
            last_scan_summary = getattr(self, "_last_scan_summary", {}) if hasattr(self, "_last_scan_summary") else {}
            recent_text = "暂无"
            failed_text = "0"
            if isinstance(last_scan_summary, dict) and last_scan_summary:
                scanned = last_scan_summary.get("scanned") or last_scan_summary.get("scanned_headers") or 0
                recent_text = str(scanned)
                failed_total = (
                    int(last_scan_summary.get("download_failed", 0) or 0)
                    + int(last_scan_summary.get("parse_failed", 0) or 0)
                    + int(last_scan_summary.get("link_failed", 0) or 0)
                )
                failed_text = str(failed_total)
            self.imports_summary_strip.set_metric("accounts", str(len(accounts)))
            self.imports_summary_strip.set_metric("default", default_name)
            self.imports_summary_strip.set_metric("missing", str(missing_cnt))
            self.imports_summary_strip.set_metric("recent", recent_text)
            self.imports_summary_strip.set_metric("failed", failed_text)

    def _refresh_export_page(self) -> None:
        if not hasattr(self, "combo_export_claims"):
            return
        claims = []
        try:
            claims = self.db.list_claim_groups()
        except Exception as exc:
            _log.debug("Failed to refresh export page: %s", exc)
        self.combo_export_claims.blockSignals(True)
        self.combo_export_claims.clear()
        for claim in claims:
            period = ""
            if claim.get("period_start") or claim.get("period_end"):
                period = f" - {claim.get('period_start')}~{claim.get('period_end')}"
            self.combo_export_claims.addItem(f"{claim.get('name')}{period}", claim.get("id"))
        self.combo_export_claims.blockSignals(False)

        total_approved = 0
        total_pending = 0
        total_missing = 0
        for claim in claims:
            stats = self._claim_export_preflight_stats(claim.get("id"))
            total_approved += int(stats.get(APPROVED, 0) or 0)
            total_pending += int(stats.get(TO_REVIEW, 0) or 0)
            total_missing += int(stats.get("missing_attachment", 0) or 0) + int(stats.get("missing_amount", 0) or 0)
        self.export_summary_strip.set_metric("groups", str(len(claims)))
        self.export_summary_strip.set_metric("approved", str(total_approved))
        self.export_summary_strip.set_metric("pending", str(total_pending))
        self.export_summary_strip.set_metric("missing", str(total_missing))

        if not claims:
            self.export_summary_strip.set_metric("ready", "无报销组")
            self.lbl_export_integrity.setText("当前还没有报销组。先在审核页把发票关联到报销组，再回来导出。")
            self.lbl_export_blockers.setText("阻塞：没有可导出的报销组。")
            if hasattr(self, "export_invoice_list"):
                self.export_invoice_list.clear()
                self.lbl_export_invoice_meta.setText("当前未选择报销组。")
            self.btn_run_export_page.setEnabled(False)
            return
        self._sync_export_claim_selection()

    def _refresh_settings_page(self) -> None:
        self._desktop_settings_cfg = deepcopy(load_config_safe())
        self.config = deepcopy(self._desktop_settings_cfg)
        cfg = load_config_safe()
        if hasattr(self, "lbl_settings_general"):
            self.lbl_settings_general.setText(
                f"当前运行目录：{RUNTIME_DIR}\n当前搜索占位提示：{self.txt_search.placeholderText() if hasattr(self, 'txt_search') else '—'}"
            )
        if hasattr(self, "lbl_settings_imports"):
            self.lbl_settings_imports.setText("导入入口已迁移到工作台：本地文件导入、扫码上传、邮箱导入均可直接从主界面进入。")
        if hasattr(self, "lbl_settings_rules"):
            categories = cfg.get("categories", {}) if isinstance(cfg.get("categories"), dict) else {}
            category_names = []
            for key, value in categories.items():
                if isinstance(value, dict):
                    label = str(value.get("name") or value.get("label") or CONFIG_CATEGORY_LABELS.get(str(key), key)).strip()
                else:
                    label = CONFIG_CATEGORY_LABELS.get(str(key), str(key))
                if label:
                    category_names.append(label)
            self.lbl_settings_rules.setText(
                "分类与规则："
                + ("、".join(category_names) if category_names else "暂无自定义分类，当前仅使用内置默认分类。")
            )
        if hasattr(self, "lbl_settings_runtime"):
            self.lbl_settings_runtime.setText(
                f"数据库：{RUNTIME_DIR / 'invoices.db'}\n日志目录：{RUNTIME_DIR / 'logs'}\n最近错误：{getattr(self.db, 'last_error', '') or '无'}"
            )
        if hasattr(self, "lbl_settings_privacy"):
            self.lbl_settings_privacy.setText("敏感信息仍由系统凭据管理器保存；配置文件与日志只保留脱敏内容。")
        if hasattr(self, "lbl_settings_data"):
            self.lbl_settings_data.setText(
                f"数据目录：{RUNTIME_DIR}\n导出目录：{RUNTIME_DIR / 'exports'}\n诊断包目录：{RUNTIME_DIR / 'diagnostics'}"
            )
        if hasattr(self, "lbl_settings_about"):
            self.lbl_settings_about.setText(self._about_text())
        self._refresh_settings_mailbox_page()
        self._refresh_settings_ai_page()

    def _settings_tab_index(self, tab_key: str) -> int:
        order = {
            "general": 0,
            "mailboxes": 1,
            "ai": 2,
            "imports": 3,
            "rules": 4,
            "runtime": 5,
            "privacy": 6,
            "data": 7,
            "about": 8,
        }
        return order.get(tab_key, 0)

    def _infer_mail_provider(self, email: str, server: str = "") -> str:
        email = str(email or "").strip().lower()
        server = str(server or "").strip().lower()
        if server.startswith("imap.qq.com") or email.endswith("@qq.com"):
            return "qq"
        if server.startswith("imap.163.com") or email.endswith("@163.com"):
            return "netease_163"
        if server.startswith("imap.126.com") or email.endswith("@126.com"):
            return "netease_126"
        if server.startswith("imap.gmail.com") or email.endswith("@gmail.com"):
            return "gmail"
        if "outlook" in server or email.endswith("@outlook.com") or email.endswith("@hotmail.com") or email.endswith("@live.com"):
            return "outlook"
        return "custom"


    def _open_add_mailbox_dialog(self, preset_id: str | None = None):
        dialog = SingleTaskMailboxDialog(self, preset_id=preset_id)
        if dialog.exec() == QDialog.Accepted:
            acc, auth_code = dialog.get_result_account()
            self._save_mailbox_account_entry(acc, auth_code)

    def _open_edit_mailbox_dialog(self):
        accounts = self._mailbox_accounts_for_settings()
        row = self.settings_mailbox_list.currentRow() if hasattr(self, "settings_mailbox_list") else -1
        if row < 0 or row >= len(accounts):
            return
        account = accounts[row]
        dialog = SingleTaskMailboxDialog(self, account=account)
        if dialog.exec() == QDialog.Accepted:
            acc, auth_code = dialog.get_result_account()
            self._save_mailbox_account_entry(acc, auth_code)

    def _add_mailbox_credential_dialog(self):
        accounts = self._mailbox_accounts_for_settings()
        row = self.settings_mailbox_list.currentRow() if hasattr(self, "settings_mailbox_list") else -1
        if row < 0 or row >= len(accounts):
            return
        account = accounts[row]
        email = account.get("address", "")
        if not email:
            return
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        code, ok = QInputDialog.getText(self, "补充授权码", f"请输入 [{email}] 的授权码 / 应用密码：", QLineEdit.Password)
        if ok and code.strip():
            from ..credentials import set_auth_code
            set_auth_code(email, code.strip())
            QMessageBox.information(self, "凭据保存", f"[{email}] 的授权码已成功存入系统安全凭据库。")
            self._refresh_settings_page()

    def _save_mailbox_account_entry(self, account: dict, auth_code: str = "") -> None:
        cfg = deepcopy(getattr(self, "_desktop_settings_cfg", load_config_safe()))
        from ..config import get_email_accounts, _normalize_default_email_account, _apply_primary_email_account, save_config

        accounts = [dict(a) for a in get_email_accounts(cfg)]
        key = account.get("mailbox_key") or account.get("address", "").lower()
        replaced = False

        for idx, existing in enumerate(accounts):
            existing_key = str(existing.get("mailbox_key") or existing.get("address") or "").strip().lower()
            if existing_key == key.lower():
                accounts[idx] = account
                replaced = True
                break

        if not replaced:
            accounts.append(account)

        pref_key = key if account.get("is_default") else None
        accounts = _normalize_default_email_account(accounts, preferred_key=pref_key)
        _apply_primary_email_account(cfg, accounts)

        save_config(cfg)
        self._desktop_settings_cfg = deepcopy(cfg)
        self.config = deepcopy(cfg)
        self._settings_mailbox_current_key = key

        if auth_code:
            from ..credentials import set_auth_code
            set_auth_code(account.get("address", ""), auth_code)

        self._refresh_settings_page()
        self._refresh_imports_page()
        QMessageBox.information(self, "保存成功", f"邮箱账户 [{account.get('address')}] 设置已保存。")

    def _mailbox_accounts_for_settings(self) -> list[dict]:
        from ..config import get_email_accounts
        cfg = getattr(self, "_desktop_settings_cfg", None)
        if not isinstance(cfg, dict):
            cfg = deepcopy(load_config_safe())
            self._desktop_settings_cfg = cfg
        return [dict(account) for account in get_email_accounts(cfg)]

    def _ai_profiles_for_settings(self) -> list[dict]:
        from ..ai_profiles import get_ai_profiles

        cfg = getattr(self, "_desktop_settings_cfg", None)
        if not isinstance(cfg, dict):
            cfg = deepcopy(load_config_safe())
            self._desktop_settings_cfg = cfg
        return [dict(profile) for profile in get_ai_profiles(cfg)]

    def _refresh_settings_mailbox_page(self) -> None:
        if not hasattr(self, "settings_mailbox_list"):
            return

        accounts = self._mailbox_accounts_for_settings()

        # Update Stat Cards Overview
        total_cnt = len(accounts)
        enabled_cnt = sum(1 for a in accounts if a.get("enabled", True))
        disabled_cnt = sum(1 for a in accounts if not a.get("enabled", True))
        default_acc = next((a for a in accounts if a.get("is_default")), None)
        default_name = str(default_acc.get("name") or default_acc.get("address") or "无").strip() if default_acc else "无"

        from ..credentials import has_auth_code
        missing_cnt = sum(1 for a in accounts if a.get("enabled", True) and not has_auth_code(a.get("address", "")))

        if hasattr(self, "stat_box_overview"):
            self.stat_box_overview.set_metric("total", str(total_cnt))
            self.stat_box_overview.set_metric("enabled", str(enabled_cnt))
            self.stat_box_overview.set_metric("default", default_name)
            self.stat_box_overview.set_metric("missing", str(missing_cnt))
            self.stat_box_overview.set_metric("disabled", str(disabled_cnt))

        current_key = getattr(self, "_settings_mailbox_current_key", "")
        self.settings_mailbox_list.blockSignals(True)
        self.settings_mailbox_list.clear()
        for account in accounts:
            label = str(account.get("name") or account.get("address") or "未命名邮箱").strip()
            addr = str(account.get("address") or "").strip()
            is_def = " (默认)" if account.get("is_default") else ""
            state = "已启用" if account.get("enabled", True) else "已停用"
            item = QListWidgetItem(f"{label} ({addr}) · {state}{is_def}")
            item.setData(Qt.UserRole, str(account.get("mailbox_key") or account.get("address") or "").strip())
            self.settings_mailbox_list.addItem(item)
        self.settings_mailbox_list.blockSignals(False)

        if hasattr(self, "lbl_settings_mailbox_empty"):
            self.lbl_settings_mailbox_empty.setVisible(self.settings_mailbox_list.count() == 0)

        if self.settings_mailbox_list.count() == 0:
            self._settings_mailbox_current_key = ""
            self._clear_settings_mailbox_form()
            return

        target_row = 0
        if current_key:
            for row in range(self.settings_mailbox_list.count()):
                if self.settings_mailbox_list.item(row).data(Qt.UserRole) == current_key:
                    target_row = row
                    break
        self.settings_mailbox_list.blockSignals(True)
        self.settings_mailbox_list.setCurrentRow(target_row)
        self.settings_mailbox_list.blockSignals(False)
        self._load_settings_mailbox_form(target_row)

        summary = getattr(self, "_last_scan_summary", {}) if hasattr(self, "_last_scan_summary") else {}
        if isinstance(summary, dict) and summary:
            parts = [f"{key}={value}" for key, value in summary.items() if value not in (None, "", [], {})]
            self.lbl_settings_mailbox_scan_result.setText("最近扫描结果：" + (" / ".join(parts) if parts else "暂无摘要"))
        else:
            self.lbl_settings_mailbox_scan_result.setText("最近扫描结果：暂无记录。")

    def _on_settings_mailbox_selection_changed(self) -> None:
        if not hasattr(self, "settings_mailbox_list") or self.settings_mailbox_list.currentRow() < 0:
            return
        self._load_settings_mailbox_form(self.settings_mailbox_list.currentRow())

    def _load_settings_mailbox_form(self, row: int) -> None:
        accounts = self._mailbox_accounts_for_settings()
        if row < 0 or row >= len(accounts):
            self._clear_settings_mailbox_form()
            return
        account = accounts[row]
        self._settings_mailbox_current_key = str(account.get("mailbox_key") or account.get("address") or "").strip()
        addr = str(account.get("address") or "").strip()
        name = str(account.get("name") or addr or "").strip()

        imap_cfg = account.get("imap", {}) if isinstance(account.get("imap"), dict) else {}
        server = str(imap_cfg.get("server") or "").strip()
        try:
            port = int(imap_cfg.get("port") or 993)
        except (TypeError, ValueError):
            port = 993
        ssl = "SSL" if imap_cfg.get("ssl", True) else "非加密"

        search_cfg = account.get("search", {}) if isinstance(account.get("search"), dict) else {}
        months = search_cfg.get("months_back") or 3

        from ..credentials import has_auth_code
        cred_ok = has_auth_code(addr)

        if hasattr(self, "lbl_detail_name"):
            self.lbl_detail_name.setText(name)
            self.lbl_detail_email.setText(addr)
            self.lbl_detail_server.setText(f"{server}:{port} ({ssl})")
            self.lbl_detail_is_default.setText("是 (默认扫描账号)" if account.get("is_default") else "否")
            self.lbl_detail_credential_status.setText("凭据有效 ✅" if cred_ok else "⚠️ 缺失授权码")
            self.lbl_detail_credential_status.setStyleSheet("color: #059669; font-weight: 600;" if cred_ok else "color: #DC2626; font-weight: 600;")
            self.lbl_detail_scan_rule.setText(f"最近 {months} 个月 INBOX")

        for attr in (
            "btn_settings_mailbox_edit_config",
            "btn_settings_mailbox_add_credential",
            "btn_settings_mailbox_test",
            "btn_settings_mailbox_scan",
            "btn_settings_mailbox_toggle",
            "btn_settings_mailbox_delete",
        ):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(True)

        if hasattr(self, "btn_settings_mailbox_toggle"):
            self.btn_settings_mailbox_toggle.setText("停用" if account.get("enabled", True) else "启用")
            self.btn_settings_mailbox_delete.setEnabled(True)

    def _clear_settings_mailbox_form(self) -> None:
        self._settings_mailbox_current_key = ""
        if hasattr(self, "lbl_detail_name"):
            self.lbl_detail_name.setText("未选择邮箱账号")
            self.lbl_detail_email.setText("—")
            self.lbl_detail_server.setText("—")
            self.lbl_detail_is_default.setText("—")
            self.lbl_detail_credential_status.setText("未配置")
            self.lbl_detail_credential_status.setStyleSheet("color: #64748B; font-weight: 600;")
            self.lbl_detail_scan_rule.setText("—")
        if hasattr(self, "btn_settings_mailbox_toggle"):
            self.btn_settings_mailbox_toggle.setText("停用")
        for attr in (
            "btn_settings_mailbox_edit_config",
            "btn_settings_mailbox_add_credential",
            "btn_settings_mailbox_test",
            "btn_settings_mailbox_scan",
            "btn_settings_mailbox_toggle",
            "btn_settings_mailbox_delete",
        ):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(False)

    def _add_settings_mailbox(self) -> None:
        self._open_add_mailbox_dialog()

    def _toggle_settings_mailbox_enabled(self) -> None:
        accounts = self._mailbox_accounts_for_settings()
        current_key = getattr(self, "_settings_mailbox_current_key", "")
        if not current_key:
            return
        for account in accounts:
            account_key = str(account.get("mailbox_key") or account.get("address") or "").strip()
            if account_key == current_key:
                if account.get("enabled", True) and sum(1 for acc in accounts if acc.get("enabled", True)) <= 1:
                    QMessageBox.warning(self, "操作被拒绝", "至少需要保留一个启用的邮箱账号。")
                    return
                updated = dict(account)
                updated["enabled"] = not bool(account.get("enabled", True))
                self._save_mailbox_account_entry(updated)
                return

    def _delete_settings_mailbox(self) -> None:
        current_key = getattr(self, "_settings_mailbox_current_key", "")
        if not current_key:
            return
        reply = QMessageBox.question(
            self,
            "确认删除",
            "删除邮箱配置不会删除已导入的发票和附件，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        cfg = deepcopy(getattr(self, "_desktop_settings_cfg", load_config_safe()))
        accounts = [acc for acc in self._mailbox_accounts_for_settings() if str(acc.get("mailbox_key") or acc.get("address") or "").strip() != current_key]
        cfg["email_accounts"] = accounts
        if accounts:
            first_enabled = next((acc for acc in accounts if acc.get("enabled", True)), accounts[0])
            cfg["email"] = {
                "provider": first_enabled.get("provider", "qq"),
                "address": first_enabled.get("address", ""),
                "username": first_enabled.get("username", first_enabled.get("address", "")),
            }
            cfg["imap"] = dict(first_enabled.get("imap", {}))
            cfg["search"] = dict(first_enabled.get("search", {}))
        else:
            cfg["email"] = {"provider": "qq", "address": "", "username": ""}
            cfg["imap"] = {"server": "", "port": 993, "ssl": True}
            cfg["search"] = {"folder": "INBOX", "months_back": 3}
        save_config(cfg)
        self._desktop_settings_cfg = deepcopy(cfg)
        self.config = deepcopy(cfg)
        self._settings_mailbox_current_key = ""
        self._refresh_settings_page()
        self._refresh_imports_page()

    def _test_settings_mailbox_connection(self) -> None:
        accounts = self._mailbox_accounts_for_settings()
        current_key = getattr(self, "_settings_mailbox_current_key", "")
        account = next(
            (item for item in accounts if str(item.get("mailbox_key") or item.get("address") or "").strip() == current_key),
            None,
        )
        if not account:
            return
        email = str(account.get("address") or "").strip()
        imap_cfg = account.get("imap", {}) if isinstance(account.get("imap"), dict) else {}
        server = str(imap_cfg.get("server") or "").strip()
        if not email or not server:
            QMessageBox.warning(self, "校验提示", "当前账号缺少邮箱地址或 IMAP 服务器。")
            return
        provider = self._infer_mail_provider(email, server)
        if provider == "outlook":
            QMessageBox.warning(self, "测试连接", "Outlook 邮箱当前仍需要 OAuth2/XOAUTH2，桌面页不支持授权码直连测试。")
            return
        from ..credentials import get_auth_code
        from ..mail_fetcher import MailFetcher
        try:
            auth_code = get_auth_code(email)
        except SystemExit:
            QMessageBox.warning(self, "缺少授权码", "未检测到该邮箱的授权码，请先在旧设置向导中补充一次凭据。")
            return
        port = int(imap_cfg.get("port") or 993)
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            fetcher = MailFetcher(address=email, auth_code=auth_code, server=server, port=port)
            fetcher.connect()
            fetcher.disconnect()
            self.lbl_settings_mailbox_test_status.setText(f"测试连接成功：{email} 可连接 {server}:{port}。")
        except Exception as exc:
            self.lbl_settings_mailbox_test_status.setText(f"测试连接失败：{sanitize_log_message(str(exc))}")
        finally:
            QApplication.restoreOverrideCursor()

    def _scan_settings_mailbox_now(self) -> None:
        current_key = getattr(self, "_settings_mailbox_current_key", "")
        if current_key:
            self._scan_email_clicked(selected_keys=[current_key], trigger_btn=self.btn_settings_mailbox_scan)

    def _refresh_settings_ai_page(self) -> None:
        if not hasattr(self, "settings_ai_profile_list"):
            return
        from ..credentials import get_ai_api_key_source
        from ..ai_classifier import is_provider_session_paused

        profiles = self._ai_profiles_for_settings()
        current_profile_id = getattr(self, "_settings_ai_current_profile_id", "")
        self.settings_ai_profile_list.blockSignals(True)
        self.settings_ai_profile_list.clear()
        for profile in profiles:
            item = QListWidgetItem(f"{profile.get('name', '')} · {profile.get('provider', '')} · {'已启用' if profile.get('enabled') else '未启用'}")
            item.setData(Qt.UserRole, profile.get("profile_id", ""))
            self.settings_ai_profile_list.addItem(item)
        self.settings_ai_profile_list.blockSignals(False)

        self.lbl_settings_ai_empty.setVisible(self.settings_ai_profile_list.count() == 0)
        if self.settings_ai_profile_list.count() == 0:
            self._settings_ai_current_profile_id = ""
            self.combo_settings_ai_provider.setCurrentText("deepseek")
            self.txt_settings_ai_model.setText("deepseek-chat")
            self.chk_settings_ai_enabled.setChecked(False)
            self.lbl_settings_ai_key_status.setText("API Key 状态：未配置")
            self.lbl_settings_ai_failure_status.setText("失败状态：暂无 AI 配置。")
            if hasattr(self, "settings_ai_summary_strip"):
                self.settings_ai_summary_strip.set_metric("enabled", "关闭")
                self.settings_ai_summary_strip.set_metric("provider", "—")
                self.settings_ai_summary_strip.set_metric("model", "—")
                self.settings_ai_summary_strip.set_metric("key", "未配置")
                self.settings_ai_summary_strip.set_metric("paused", "正常")
            return

        target_row = 0
        if current_profile_id:
            for row in range(self.settings_ai_profile_list.count()):
                if self.settings_ai_profile_list.item(row).data(Qt.UserRole) == current_profile_id:
                    target_row = row
                    break
        self.settings_ai_profile_list.blockSignals(True)
        self.settings_ai_profile_list.setCurrentRow(target_row)
        self.settings_ai_profile_list.blockSignals(False)
        profile = profiles[target_row]
        self._settings_ai_current_profile_id = profile.get("profile_id", "")
        self.combo_settings_ai_provider.setCurrentText(profile.get("provider", "deepseek"))
        self.txt_settings_ai_model.setText(profile.get("model", ""))
        self.chk_settings_ai_enabled.setChecked(bool(profile.get("enabled", False)))
        key_source = get_ai_api_key_source(profile.get("provider", ""), profile.get("profile_id", ""))
        self.lbl_settings_ai_key_status.setText(f"API Key 状态：{key_source}")
        paused = is_provider_session_paused(profile.get("provider", ""))
        self.lbl_settings_ai_failure_status.setText(f"失败状态：{'401 / 403 后本会话已暂停' if paused else '当前会话可用'}")
        if hasattr(self, "settings_ai_summary_strip"):
            self.settings_ai_summary_strip.set_metric("enabled", "开启" if profile.get("enabled", False) else "关闭")
            self.settings_ai_summary_strip.set_metric("provider", str(profile.get("provider", "—") or "—"))
            self.settings_ai_summary_strip.set_metric("model", str(profile.get("model", "—") or "—"))
            self.settings_ai_summary_strip.set_metric("key", key_source)
            self.settings_ai_summary_strip.set_metric("paused", "已暂停" if paused else "正常")

    def _on_settings_ai_profile_selection_changed(self) -> None:
        if not hasattr(self, "settings_ai_profile_list") or self.settings_ai_profile_list.currentRow() < 0:
            return
        profiles = self._ai_profiles_for_settings()
        row = self.settings_ai_profile_list.currentRow()
        if row < 0 or row >= len(profiles):
            return
        profile = profiles[row]
        self._settings_ai_current_profile_id = profile.get("profile_id", "")
        self.combo_settings_ai_provider.setCurrentText(profile.get("provider", "deepseek"))
        self.txt_settings_ai_model.setText(profile.get("model", ""))
        self.chk_settings_ai_enabled.setChecked(bool(profile.get("enabled", False)))
        from ..credentials import get_ai_api_key_source
        from ..ai_classifier import is_provider_session_paused

        key_source = get_ai_api_key_source(profile.get("provider", ""), profile.get("profile_id", ""))
        self.lbl_settings_ai_key_status.setText(f"API Key 状态：{key_source}")
        paused = is_provider_session_paused(profile.get("provider", ""))
        self.lbl_settings_ai_failure_status.setText(f"失败状态：{'401 / 403 后本会话已暂停' if paused else '当前会话可用'}")
        if hasattr(self, "settings_ai_summary_strip"):
            self.settings_ai_summary_strip.set_metric("enabled", "开启" if profile.get("enabled", False) else "关闭")
            self.settings_ai_summary_strip.set_metric("provider", str(profile.get("provider", "—") or "—"))
            self.settings_ai_summary_strip.set_metric("model", str(profile.get("model", "—") or "—"))
            self.settings_ai_summary_strip.set_metric("key", key_source)
            self.settings_ai_summary_strip.set_metric("paused", "已暂停" if paused else "正常")

    def _save_settings_ai_profile(self) -> bool:
        from ..ai_profiles import apply_active_ai_profile, get_ai_profiles

        provider = self.combo_settings_ai_provider.currentText().strip()
        model = self.txt_settings_ai_model.text().strip()
        if not provider or not model:
            QMessageBox.warning(self, "AI 配置不完整", "请先填写 Provider 和模型。")
            return False
        cfg = deepcopy(getattr(self, "_desktop_settings_cfg", load_config_safe()))
        profiles = [dict(profile) for profile in get_ai_profiles(cfg)]
        profile_id = getattr(self, "_settings_ai_current_profile_id", "") or f"desktop-{provider}"
        target = {
            "profile_id": profile_id,
            "name": f"{provider} · {model}",
            "provider": provider,
            "model": model,
            "enabled": self.chk_settings_ai_enabled.isChecked(),
        }
        replaced = False
        for idx, existing in enumerate(profiles):
            if existing.get("profile_id") == profile_id:
                profiles[idx] = target
                replaced = True
                break
        if not replaced:
            if target["enabled"]:
                for profile in profiles:
                    profile["enabled"] = False
            profiles.append(target)
        elif target["enabled"]:
            for profile in profiles:
                if profile.get("profile_id") != profile_id:
                    profile["enabled"] = False

        apply_active_ai_profile(cfg, profiles)
        save_config(cfg)
        self._desktop_settings_cfg = deepcopy(cfg)
        self.config = deepcopy(cfg)
        self._settings_ai_current_profile_id = profile_id
        self._refresh_settings_page()
        return True

    def _configure_settings_ai_key(self) -> None:
        from ..credentials import set_ai_api_key

        provider = self.combo_settings_ai_provider.currentText().strip()
        if not provider:
            QMessageBox.warning(self, "未选择 Provider", "请先选择 AI Provider。")
            return
        key_text, accepted = QInputDialog.getText(
            self,
            "配置 API Key",
            f"请输入 {provider} 的 API Key：",
            QLineEdit.Password,
        )
        if not accepted or not key_text.strip():
            return
        profile_id = getattr(self, "_settings_ai_current_profile_id", "") or f"desktop-{provider}"
        set_ai_api_key(provider, key_text.strip(), profile_id=profile_id)
        self._settings_ai_current_profile_id = profile_id
        self._refresh_settings_ai_page()

    def _clear_settings_ai_key(self) -> None:
        from ..credentials import delete_ai_api_key

        provider = self.combo_settings_ai_provider.currentText().strip()
        profile_id = getattr(self, "_settings_ai_current_profile_id", "") or f"desktop-{provider}"
        delete_ai_api_key(provider, profile_id=profile_id)
        self._refresh_settings_ai_page()

    def _test_settings_ai_connection(self) -> None:
        from ..credentials import has_ai_api_key

        provider = self.combo_settings_ai_provider.currentText().strip()
        model = self.txt_settings_ai_model.text().strip()
        profile_id = getattr(self, "_settings_ai_current_profile_id", "") or f"desktop-{provider}"
        if not provider or not model:
            QMessageBox.warning(self, "AI 配置不完整", "请先填写 Provider 和模型。")
            return
        if not has_ai_api_key(provider, profile_id=profile_id):
            self.lbl_settings_ai_failure_status.setText("失败状态：未检测到可用 API Key，无法进行本地连通性预检。")
            return
        self.lbl_settings_ai_failure_status.setText(
            f"失败状态：本地预检通过，{provider}/{model} 已具备 Key；真实远端连通性会在首次分类请求时验证。"
        )

    def _restore_settings_ai_session(self) -> None:
        from ..ai_classifier import clear_provider_session_paused

        provider = self.combo_settings_ai_provider.currentText().strip()
        if not provider:
            return
        clear_provider_session_paused(provider)
        self._refresh_settings_ai_page()

    def _build_overview_page_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.overview_header = PageHeader(
            "今日工作台",
            "先看今天的导入、待审和异常，再决定是去审核、补材料还是导出。",
        )
        layout.addWidget(self.overview_header)

        self.overview_summary_strip = SummaryStrip()
        self.overview_value_labels = {}
        for stat_key, title, state in [
            ("today_imported", "今日导入", "info"),
            ("to_review", "待审核", "warning"),
            ("error", "异常票据", "danger"),
            ("needs_fix", "待补全", "muted"),
            ("month_total", "本月金额", "success"),
        ]:
            card = self.overview_summary_strip.add_metric(stat_key, title, "—", state=state)
            self.overview_value_labels[stat_key] = card
        layout.addWidget(self.overview_summary_strip)

        body_frame = QFrame()
        body_layout = QHBoxLayout(body_frame)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)

        left_card = SectionCard("下一步", hint="默认流程是先看最近导入，再进入发票审核处理待审队列。")
        lc_layout = left_card.body_layout
        self.lbl_overview_recent_imports = QLabel("暂无可用统计，等待数据库连接或首批导入完成。")
        self.lbl_overview_recent_imports.setStyleSheet("color: #667085; font-size: 12px;")
        self.lbl_overview_recent_imports.setWordWrap(True)
        lc_layout.addWidget(self.lbl_overview_recent_imports)
        btn_jump_review = make_button("开始审核", variant="primary")
        btn_jump_review.clicked.connect(lambda: self._switch_main_page("review"))
        lc_layout.addWidget(btn_jump_review)
        lc_layout.addStretch(1)

        right_card = SectionCard("关注项", hint="这里只提醒需要处理的阻塞，不展示硬编码业务数字。")
        rc_layout = right_card.body_layout
        self.lbl_overview_health = QLabel("当前无法读取审核队列统计，导入后会自动刷新。")
        self.lbl_overview_health.setStyleSheet("color: #4B5563; font-size: 12px; line-height: 1.5;")
        self.lbl_overview_health.setWordWrap(True)
        rc_layout.addWidget(self.lbl_overview_health)
        rc_layout.addStretch(1)

        body_layout.addWidget(left_card, 1)
        body_layout.addWidget(right_card, 1)
        layout.addWidget(body_frame, 1)
        self._refresh_overview_page()
        return page

    def _build_imports_page_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.imports_header = PageHeader(
            "导入中心",
            "按“来源选择 → 导入规则 → 最近结果”完成一次导入，账号配置统一去系统设置处理。",
        )
        layout.addWidget(self.imports_header)

        self.imports_summary_strip = SummaryStrip()
        self.imports_summary_strip.add_metric("accounts", "邮箱账号", "0", state="info")
        self.imports_summary_strip.add_metric("default", "默认账号", "无", state="success")
        self.imports_summary_strip.add_metric("missing", "缺授权", "0", state="warning")
        self.imports_summary_strip.add_metric("recent", "最近扫描", "暂无", state="muted")
        self.imports_summary_strip.add_metric("failed", "失败数", "0", state="danger")
        layout.addWidget(self.imports_summary_strip)

        shell = QHBoxLayout()
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(12)

        self.import_source_card = SectionCard("来源选择", hint="先决定本次从本地、扫码还是邮箱拉取。")
        source_layout = self.import_source_card.body_layout
        source_bar = CommandBar()
        self.btn_import_local_pick = make_button("本地导入", variant="secondary")
        self.btn_import_local_pick.clicked.connect(self._import_local_clicked)
        self.btn_import_qr_open = make_button("扫码", variant="secondary")
        self.btn_import_qr_open.clicked.connect(self._mobile_upload_clicked)
        self.btn_import_mail_focus = make_button("邮箱", variant="secondary")
        self.btn_import_mail_focus.clicked.connect(lambda: self._switch_main_page("imports"))
        source_bar.layout.addWidget(self.btn_import_local_pick)
        source_bar.layout.addWidget(self.btn_import_qr_open)
        source_bar.layout.addWidget(self.btn_import_mail_focus)
        source_bar.layout.addStretch(1)
        source_layout.addWidget(source_bar)
        self.lbl_import_qr_status = QLabel("扫码上传服务未启动。点击下方按钮可启动真实上传服务并显示二维码。")
        self.lbl_import_qr_status.setWordWrap(True)
        self.lbl_import_qr_status.setStyleSheet("color: #667085; font-size: 12px;")
        source_layout.addWidget(self.lbl_import_qr_status)
        tq_hint = QLabel("邮箱导入只负责扫描执行；新增账号、补授权码和停用账号统一到系统设置。")
        tq_hint.setStyleSheet("color: #667085; font-size: 12px;")
        source_layout.addWidget(tq_hint)
        self.txt_import_records = QPlainTextEdit()
        self.txt_import_records.setReadOnly(True)
        self.txt_import_records.setFont(QFont("Consolas", 9))
        self.txt_import_records.setMaximumHeight(180)
        source_layout.addWidget(self.txt_import_records, 1)
        shell.addWidget(self.import_source_card, 1)

        self.import_mail_accounts_card = SectionCard("导入规则", hint="中间区域集中处理邮箱选择、扫描规则和扫描触发。")
        self.mail_accounts_checklist = QWidget()
        self.mail_checklist_layout = QVBoxLayout(self.mail_accounts_checklist)
        self.mail_checklist_layout.setContentsMargins(4, 4, 4, 4)
        self.mail_checklist_layout.setSpacing(6)

        scroll_accounts = QScrollArea()
        scroll_accounts.setWidgetResizable(True)
        scroll_accounts.setFrameShape(QFrame.StyledPanel)
        scroll_accounts.setMaximumHeight(140)
        scroll_accounts.setWidget(self.mail_accounts_checklist)
        self.import_mail_accounts_card.body_layout.addWidget(scroll_accounts)

        # Legacy PlainTextEdit retained for backwards compatibility
        self.lst_mail_accounts = QPlainTextEdit()
        self.lst_mail_accounts.setReadOnly(True)
        self.lst_mail_accounts.setMaximumHeight(1)
        self.lst_mail_accounts.setVisible(False)
        self.import_mail_accounts_card.body_layout.addWidget(self.lst_mail_accounts)

        self.import_mail_rules_card = SectionCard("扫描规则", hint="这里展示当前全局抓取规则，并给出最少必要动作。")
        rules_box = QGroupBox("当前全局抓取与清洗规则概览")
        rules_layout = QGridLayout(rules_box)
        rules_layout.setContentsMargins(10, 8, 10, 8)
        rules_layout.setSpacing(6)

        rules_layout.addWidget(QLabel("📅 扫描时间窗口: 最近 3 个月增量极速抓取"), 0, 0)
        rules_layout.addWidget(QLabel("📎 支持附件格式: PDF / OFD / XML / 常用图片格式"), 0, 1)
        rules_layout.addWidget(QLabel("🔍 邮件主题过滤: 包含“发票 / 行程单 / 电子发票 / 账单”"), 1, 0)
        rules_layout.addWidget(QLabel("🛡️ 重复策略: 相同发票代码+号码全局自动忽略去重"), 1, 1)

        self.import_mail_rules_card.body_layout.addWidget(rules_box)

        mail_action_row = QHBoxLayout()
        mail_action_row.setContentsMargins(0, 0, 0, 0)
        mail_action_row.setSpacing(8)

        self.btn_import_scan_selected = make_button("开始扫描", variant="primary")
        self.btn_import_scan_selected.clicked.connect(self._scan_selected_email_accounts)

        self.btn_import_scan_default = make_button("默认", variant="secondary")
        self.btn_import_scan_default.clicked.connect(self._scan_default_email_clicked)

        self.btn_import_manage_mailbox = make_button("管理", variant="secondary")
        self.btn_import_manage_mailbox.clicked.connect(lambda: self._switch_main_page("settings", sub_tab=1))

        self.btn_view_failed_details = make_button("失败", variant="secondary")
        self.btn_view_failed_details.clicked.connect(self._v5_show_failed_details_dialog)

        self.import_mail_more = MoreMenuButton(parent=self)
        self.import_mail_more_menu = QMenu(self.import_mail_more)
        self.import_mail_more_menu.addAction("新增邮箱", lambda: self._switch_main_page("settings", sub_tab=1))
        self.import_mail_more_menu.addAction("管理邮箱", lambda: self._switch_main_page("settings", sub_tab=1))
        self.import_mail_more_menu.addAction("查看失败", self._v5_show_failed_details_dialog)
        self.import_mail_more.setMenu(self.import_mail_more_menu)

        mail_action_row.addWidget(self.btn_import_scan_selected)
        mail_action_row.addWidget(self.btn_import_scan_default)
        mail_action_row.addWidget(self.btn_import_manage_mailbox)
        mail_action_row.addWidget(self.btn_view_failed_details)
        mail_action_row.addStretch(1)
        mail_action_row.addWidget(self.import_mail_more)
        self.import_mail_rules_card.body_layout.addLayout(mail_action_row)
        self.import_mail_accounts_card.body_layout.addWidget(self.import_mail_rules_card)
        shell.addWidget(self.import_mail_accounts_card, 1)

        self.import_mail_recent_card = SectionCard("最近结果", hint="看最近一次扫描摘要和失败明细，再决定是否继续补授权或重试。")
        self.lbl_mail_scan_summary = QLabel("最近扫描结果：暂无记录。点击“开始扫描”开始拉取。")
        self.lbl_mail_scan_summary.setWordWrap(True)
        self.lbl_mail_scan_summary.setStyleSheet("color: #64748B; font-size: 12px;")
        self.import_mail_recent_card.body_layout.addWidget(self.lbl_mail_scan_summary)
        self.lbl_import_recent_hint = QLabel("如果失败数持续增加，优先去系统设置检查缺授权或连接异常。")
        self.lbl_import_recent_hint.setWordWrap(True)
        self.lbl_import_recent_hint.setStyleSheet("color: #667085; font-size: 12px;")
        self.import_mail_recent_card.body_layout.addWidget(self.lbl_import_recent_hint)
        self.import_mail_recent_card.body_layout.addStretch(1)
        shell.addWidget(self.import_mail_recent_card, 1)

        layout.addLayout(shell, 1)
        self._refresh_imports_page()
        return page

    def _build_export_page_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.export_header = PageHeader(
            "报销组与导出",
            "先选报销组，再看完整性检查；检查不过时先回到审核页或补材料。",
        )
        layout.addWidget(self.export_header)

        self.export_summary_strip = SummaryStrip()
        self.export_summary_strip.add_metric("groups", "报销组", "0", state="info")
        self.export_summary_strip.add_metric("approved", "已通过", "0", state="success")
        self.export_summary_strip.add_metric("pending", "待处理", "0", state="warning")
        self.export_summary_strip.add_metric("missing", "缺材料", "0", state="danger")
        self.export_summary_strip.add_metric("ready", "导出状态", "待检查", state="muted")
        layout.addWidget(self.export_summary_strip)

        shell = QHBoxLayout()
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(12)

        self.export_group_card = SectionCard("报销组选择", hint="选择要导出的报销组，完整性检查会随选择更新。")
        self.combo_export_claims = QComboBox()
        self.combo_export_claims.currentIndexChanged.connect(self._sync_export_claim_selection)
        self.export_group_card.body_layout.addWidget(self.combo_export_claims)
        self.lbl_export_scope_hint = QLabel("默认导出已通过发票；待审核发票可在导出时按提示决定是否一并打包。")
        self.lbl_export_scope_hint.setWordWrap(True)
        self.lbl_export_scope_hint.setStyleSheet("color: #667085; font-size: 12px;")
        self.export_group_card.body_layout.addWidget(self.lbl_export_scope_hint)
        self.export_group_card.body_layout.addStretch(1)
        shell.addWidget(self.export_group_card, 1)

        self.export_invoices_card = SectionCard("组内发票", hint="这里仅展示当前报销组内的发票队列，方便先看缺口再导出。")
        self.export_invoice_list = EntityList()
        self.export_invoices_card.body_layout.addWidget(self.export_invoice_list, 1)
        self.lbl_export_invoice_meta = QLabel("当前未选择报销组。")
        self.lbl_export_invoice_meta.setWordWrap(True)
        self.lbl_export_invoice_meta.setStyleSheet("color: #667085; font-size: 12px;")
        self.export_invoices_card.body_layout.addWidget(self.lbl_export_invoice_meta)
        shell.addWidget(self.export_invoices_card, 1)

        self.export_integrity_card = SectionCard("完整性检查与导出", hint="检查不通过时禁用导出；业务导出逻辑保持不变。")
        self.lbl_export_integrity = QLabel("请选择报销组后查看完整性检查。")
        self.lbl_export_integrity.setWordWrap(True)
        self.lbl_export_integrity.setStyleSheet("color: #475467; font-size: 12px; line-height: 1.5;")
        self.export_integrity_card.body_layout.addWidget(self.lbl_export_integrity)
        self.lbl_export_blockers = QLabel("当前暂无阻塞。")
        self.lbl_export_blockers.setWordWrap(True)
        self.lbl_export_blockers.setStyleSheet("color: #667085; font-size: 12px;")
        self.export_integrity_card.body_layout.addWidget(self.lbl_export_blockers)
        self.btn_run_export_page = make_button("开始导出", variant="primary", min_width=120)
        self.btn_run_export_page.clicked.connect(self._export_claim_package)
        self.export_integrity_card.body_layout.addWidget(self.btn_run_export_page)
        self.export_integrity_card.body_layout.addStretch(1)
        shell.addWidget(self.export_integrity_card, 1)

        layout.addLayout(shell, 1)
        self._refresh_export_page()
        return page

    def _build_logs_page_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        hdr_layout = QHBoxLayout()
        hdr = QLabel("操作日志审计中心")
        hdr.setFont(QFont("Segoe UI", 14, QFont.Bold))
        hdr_layout.addWidget(hdr)
        hdr_layout.addStretch(1)

        self.btn_logs_copy = make_button("复制日志", variant="secondary")
        self.btn_logs_copy.clicked.connect(self._copy_log_to_clipboard)
        hdr_layout.addWidget(self.btn_logs_copy)

        self.btn_logs_clear = make_button("清空日志", variant="secondary")
        self.btn_logs_clear.clicked.connect(self._clear_log_text)
        hdr_layout.addWidget(self.btn_logs_clear)

        layout.addLayout(hdr_layout)
        self.logs_page_log_host = QWidget()
        self.logs_page_log_layout = QVBoxLayout(self.logs_page_log_host)
        self.logs_page_log_layout.setContentsMargins(0, 0, 0, 0)
        self.logs_page_log_layout.setSpacing(0)
        layout.addWidget(self.logs_page_log_host, 1)
        return page

    def _build_settings_page_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.settings_header = PageHeader(
            "系统设置",
            "设置中心默认只展示状态和当前配置；需要修改时进入单任务弹窗或专用操作。",
        )
        layout.addWidget(self.settings_header)

        self.settings_tabs = SecondaryNavStack()

        simple_tabs = [
            ("常规", "lbl_settings_general", "界面显示密度、常规偏好设置"),
            ("导入与识别", "lbl_settings_imports", "导入入口与识别服务已迁移到主工作台"),
            ("分类与规则", "lbl_settings_rules", "发票消费类型分类字典与 AI 自动审核规则配置"),
            ("运行状态", "lbl_settings_runtime", "本地数据库路径、运行日志存储位置"),
            ("安全与隐私", "lbl_settings_privacy", "脱敏规则、敏感数据清除设置"),
            ("数据与备份", "lbl_settings_data", "数据库备份、离线归档与数据还原"),
            ("关于", "lbl_settings_about", f"Invoice Hub 发票审核中心 v{APP_VERSION}"),
        ]

        tab_widgets = {}
        for tab_name, attr_name, hint_text in simple_tabs:
            t_widget = QWidget()
            t_layout = QVBoxLayout(t_widget)
            t_layout.addWidget(QLabel(f"{tab_name} 设置"))
            lbl_h = QLabel(hint_text)
            lbl_h.setStyleSheet("color: #667085; font-size: 12px;")
            lbl_h.setWordWrap(True)
            t_layout.addWidget(lbl_h)
            detail = QLabel("")
            detail.setWordWrap(True)
            detail.setStyleSheet("color: #4B5563; font-size: 12px;")
            setattr(self, attr_name, detail)
            t_layout.addWidget(detail)
            t_layout.addStretch(1)
            tab_widgets[tab_name] = t_widget

        mailbox_tab = QWidget()
        mailbox_layout = QVBoxLayout(mailbox_tab)
        mailbox_layout.setContentsMargins(0, 0, 0, 0)
        mailbox_layout.setSpacing(10)

        # Overview Stat Header (Requirement 3)
        self.stat_box_overview = SummaryStrip()
        self.lbl_v11_stat_total = self.stat_box_overview.add_metric("total", "总账号", "0", state="info")
        self.lbl_v11_stat_enabled = self.stat_box_overview.add_metric("enabled", "启用", "0", state="success")
        self.lbl_v11_stat_default = self.stat_box_overview.add_metric("default", "默认扫描", "无", state="info")
        self.lbl_v11_stat_missing = self.stat_box_overview.add_metric("missing", "缺授权", "0", state="warning")
        self.lbl_v11_stat_disabled = self.stat_box_overview.add_metric("disabled", "禁用", "0", state="muted")
        mailbox_layout.addWidget(self.stat_box_overview)

        # Presets Entry Bar (Requirement 4)
        preset_bar = SectionCard("新增账号", hint="常用邮箱预设只用于创建新账号，不会混入已保存账号列表。")
        preset_layout = QHBoxLayout()
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(8)

        lbl_preset_title = QLabel("新增常用预设:")
        lbl_preset_title.setStyleSheet("font-weight: 600; color: #475569; font-size: 12px;")
        preset_layout.addWidget(lbl_preset_title)

        self.v11_preset_buttons = {}
        presets_data = [
            ("qq", "QQ 邮箱"),
            ("netease_163", "163 邮箱"),
            ("gmail", "Gmail"),
            ("outlook", "Outlook"),
            ("custom", "自定义 IMAP"),
        ]
        for pid, pname in presets_data:
            btn = make_button(f"+ {pname}", variant="secondary")
            btn.clicked.connect(lambda _, p=pid: self._open_add_mailbox_dialog(preset_id=p))
            self.v11_preset_buttons[pid] = btn
            preset_layout.addWidget(btn)

        preset_layout.addStretch(1)
        preset_layout.addStretch(1)
        preset_bar.body_layout.addLayout(preset_layout)
        mailbox_layout.addWidget(preset_bar)

        mailbox_shell = QHBoxLayout()
        mailbox_shell.setContentsMargins(0, 0, 0, 0)
        mailbox_shell.setSpacing(12)

        # Saved Accounts List ONLY (Requirement 4)
        self.settings_mailbox_list = EntityList()
        self.settings_mailbox_list.setMinimumWidth(260)
        self.settings_mailbox_list.setMinimumHeight(280)
        self.settings_mailbox_list.currentRowChanged.connect(lambda _row: self._on_settings_mailbox_selection_changed())
        mailbox_shell.addWidget(self.settings_mailbox_list, 0)

        # Read-Only Details Panel (Requirement 5 & 6)
        mailbox_editor = QWidget()
        mailbox_editor_layout = QVBoxLayout(mailbox_editor)
        mailbox_editor_layout.setContentsMargins(0, 0, 0, 0)
        mailbox_editor_layout.setSpacing(8)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.btn_settings_mailbox_add = make_button("新增账号", variant="secondary")
        self.btn_settings_mailbox_add.clicked.connect(lambda: self._open_add_mailbox_dialog())

        self.btn_settings_mailbox_edit_config = make_button("编辑配置", variant="primary")
        self.btn_settings_mailbox_edit_config.clicked.connect(self._open_edit_mailbox_dialog)

        self.btn_settings_mailbox_add_credential = make_button("补授权码", variant="secondary")
        self.btn_settings_mailbox_add_credential.clicked.connect(self._add_mailbox_credential_dialog)

        self.btn_settings_mailbox_toggle = make_button("停用", variant="secondary")
        self.btn_settings_mailbox_toggle.clicked.connect(self._toggle_settings_mailbox_enabled)

        self.btn_settings_mailbox_delete = make_button("删除", variant="danger")
        self.btn_settings_mailbox_delete.clicked.connect(self._delete_settings_mailbox)

        action_row.addWidget(self.btn_settings_mailbox_add)
        action_row.addWidget(self.btn_settings_mailbox_edit_config)
        action_row.addWidget(self.btn_settings_mailbox_add_credential)
        action_row.addWidget(self.btn_settings_mailbox_toggle)
        action_row.addWidget(self.btn_settings_mailbox_delete)
        action_row.addStretch(1)
        mailbox_editor_layout.addLayout(action_row)
        form_box = ReadOnlyDetailPanel("账号详情", "默认只读显示当前账号状态；编辑配置和补授权码通过独立入口触发。")
        form_layout = QFormLayout(form_box.body)
        self.lbl_detail_name = QLabel("未选择邮箱账号")
        self.lbl_detail_email = QLabel("—")
        self.lbl_detail_server = QLabel("—")
        self.lbl_detail_is_default = QLabel("—")
        self.lbl_detail_credential_status = QLabel("未配置")
        self.lbl_detail_scan_rule = QLabel("—")
        for label in (
            self.lbl_detail_name,
            self.lbl_detail_email,
            self.lbl_detail_server,
            self.lbl_detail_is_default,
            self.lbl_detail_credential_status,
            self.lbl_detail_scan_rule,
        ):
            label.setWordWrap(True)
            label.setObjectName("MailboxDetailValue")
        form_layout.addRow("邮箱名称", self.lbl_detail_name)
        form_layout.addRow("邮箱地址", self.lbl_detail_email)
        form_layout.addRow("IMAP / 端口 / SSL", self.lbl_detail_server)
        form_layout.addRow("默认扫描账号", self.lbl_detail_is_default)
        form_layout.addRow("授权码状态", self.lbl_detail_credential_status)
        form_layout.addRow("扫描规则", self.lbl_detail_scan_rule)
        mailbox_editor_layout.addWidget(form_box)
        mailbox_btn_row = QHBoxLayout()
        mailbox_btn_row.setContentsMargins(0, 0, 0, 0)
        mailbox_btn_row.setSpacing(8)
        self.btn_settings_mailbox_test = make_button("测试连接", variant="secondary")
        self.btn_settings_mailbox_test.clicked.connect(self._test_settings_mailbox_connection)
        self.btn_settings_mailbox_scan = make_button("立即扫描", variant="secondary")
        self.btn_settings_mailbox_scan.clicked.connect(self._scan_settings_mailbox_now)
        mailbox_btn_row.addWidget(self.btn_settings_mailbox_test)
        mailbox_btn_row.addWidget(self.btn_settings_mailbox_scan)
        mailbox_btn_row.addStretch(1)
        mailbox_editor_layout.addLayout(mailbox_btn_row)
        self.lbl_settings_mailbox_test_status = QLabel("测试连接：尚未执行。")
        self.lbl_settings_mailbox_test_status.setWordWrap(True)
        self.lbl_settings_mailbox_test_status.setStyleSheet("color: #667085; font-size: 12px;")
        self.lbl_settings_mailbox_scan_result = QLabel("最近扫描结果：暂无记录。")
        self.lbl_settings_mailbox_scan_result.setWordWrap(True)
        self.lbl_settings_mailbox_scan_result.setStyleSheet("color: #667085; font-size: 12px;")
        self.lbl_settings_mailbox_empty = QLabel("尚未配置任何邮箱账号。")
        self.lbl_settings_mailbox_empty.setStyleSheet("color: #667085; font-size: 12px;")
        mailbox_editor_layout.addWidget(self.lbl_settings_mailbox_test_status)
        mailbox_editor_layout.addWidget(self.lbl_settings_mailbox_scan_result)
        mailbox_editor_layout.addWidget(self.lbl_settings_mailbox_empty)
        mailbox_editor_layout.addStretch(1)
        mailbox_shell.addWidget(mailbox_editor, 1)
        mailbox_layout.addLayout(mailbox_shell, 1)

        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)
        ai_layout.setContentsMargins(0, 0, 0, 0)
        ai_layout.setSpacing(10)
        ai_layout.addWidget(QLabel("AI 配置"))
        self.settings_ai_summary_strip = SummaryStrip()
        self.lbl_settings_ai_stat_enabled = self.settings_ai_summary_strip.add_metric("enabled", "AI 状态", "关闭", state="muted")
        self.lbl_settings_ai_stat_provider = self.settings_ai_summary_strip.add_metric("provider", "Provider", "—", state="info")
        self.lbl_settings_ai_stat_model = self.settings_ai_summary_strip.add_metric("model", "模型", "—", state="info")
        self.lbl_settings_ai_stat_key = self.settings_ai_summary_strip.add_metric("key", "Key 健康", "未配置", state="warning")
        self.lbl_settings_ai_stat_paused = self.settings_ai_summary_strip.add_metric("paused", "暂停状态", "正常", state="success")
        ai_layout.addWidget(self.settings_ai_summary_strip)
        ai_hint = QLabel("在桌面内直接查看 Provider、模型、Key 状态和本会话暂停状态。")
        ai_hint.setWordWrap(True)
        ai_hint.setStyleSheet("color: #667085; font-size: 12px;")
        ai_layout.addWidget(ai_hint)
        ai_shell = QHBoxLayout()
        ai_shell.setContentsMargins(0, 0, 0, 0)
        ai_shell.setSpacing(12)
        self.settings_ai_profile_list = EntityList()
        self.settings_ai_profile_list.setMinimumWidth(260)
        self.settings_ai_profile_list.currentRowChanged.connect(lambda _row: self._on_settings_ai_profile_selection_changed())
        ai_shell.addWidget(self.settings_ai_profile_list, 0)
        ai_editor = QWidget()
        ai_editor_layout = QVBoxLayout(ai_editor)
        ai_editor_layout.setContentsMargins(0, 0, 0, 0)
        ai_editor_layout.setSpacing(8)
        ai_form_box = QGroupBox("AI 运行配置")
        ai_form = QFormLayout(ai_form_box)
        self.combo_settings_ai_provider = QComboBox()
        self.combo_settings_ai_provider.addItems(["deepseek", "gemini"])
        self.txt_settings_ai_model = QLineEdit()
        self.chk_settings_ai_enabled = QCheckBox("启用 AI 提取与分类")
        self.lbl_settings_ai_key_status = QLabel("API Key 状态：未配置")
        self.lbl_settings_ai_key_status.setWordWrap(True)
        self.lbl_settings_ai_send_boundary = QLabel("发送边界说明：仅发送脱敏邮件头与最小分类元数据，不发送正文、附件、PDF、图片和本地路径。")
        self.lbl_settings_ai_send_boundary.setWordWrap(True)
        self.lbl_settings_ai_log_redaction = QLabel("日志脱敏：Key 与授权码不会写入 config.json，也不会原样出现在日志。")
        self.lbl_settings_ai_log_redaction.setWordWrap(True)
        ai_form.addRow("Provider", self.combo_settings_ai_provider)
        ai_form.addRow("模型", self.txt_settings_ai_model)
        ai_form.addRow("", self.chk_settings_ai_enabled)
        ai_form.addRow("Key 状态", self.lbl_settings_ai_key_status)
        ai_form.addRow("发送边界", self.lbl_settings_ai_send_boundary)
        ai_form.addRow("日志脱敏", self.lbl_settings_ai_log_redaction)
        ai_editor_layout.addWidget(ai_form_box)
        ai_btn_row = QHBoxLayout()
        ai_btn_row.setContentsMargins(0, 0, 0, 0)
        ai_btn_row.setSpacing(8)
        self.btn_settings_ai_configure_key = make_button("配置 / 更新 Key", variant="secondary")
        self.btn_settings_ai_configure_key.clicked.connect(self._configure_settings_ai_key)
        self.btn_settings_ai_test = make_button("测试连接", variant="secondary")
        self.btn_settings_ai_test.clicked.connect(self._test_settings_ai_connection)
        self.btn_settings_ai_clear_key = make_button("清除 Key", variant="secondary")
        self.btn_settings_ai_clear_key.clicked.connect(self._clear_settings_ai_key)
        self.btn_settings_ai_restore_session = make_button("恢复 AI 会话", variant="secondary")
        self.btn_settings_ai_restore_session.clicked.connect(self._restore_settings_ai_session)
        self.btn_settings_ai_save = make_button("保存设置", variant="primary")
        self.btn_settings_ai_save.clicked.connect(self._save_settings_ai_profile)
        ai_btn_row.addWidget(self.btn_settings_ai_configure_key)
        ai_btn_row.addWidget(self.btn_settings_ai_test)
        ai_btn_row.addWidget(self.btn_settings_ai_clear_key)
        ai_btn_row.addWidget(self.btn_settings_ai_restore_session)
        ai_btn_row.addStretch(1)
        ai_btn_row.addWidget(self.btn_settings_ai_save)
        ai_editor_layout.addLayout(ai_btn_row)
        self.lbl_settings_ai_failure_status = QLabel("失败状态：暂无异常。")
        self.lbl_settings_ai_failure_status.setWordWrap(True)
        self.lbl_settings_ai_failure_status.setStyleSheet("color: #667085; font-size: 12px;")
        self.lbl_settings_ai_empty = QLabel("尚未配置任何 AI Profile。")
        self.lbl_settings_ai_empty.setStyleSheet("color: #667085; font-size: 12px;")
        ai_editor_layout.addWidget(self.lbl_settings_ai_failure_status)
        ai_editor_layout.addWidget(self.lbl_settings_ai_empty)
        ai_editor_layout.addStretch(1)
        ai_shell.addWidget(ai_editor, 1)
        ai_layout.addLayout(ai_shell, 1)

        self.settings_tabs.addTab(tab_widgets["常规"], "常规")
        self.settings_tabs.addTab(mailbox_tab, "邮箱账户")
        self.settings_tabs.addTab(ai_tab, "AI 配置")
        self.settings_tabs.addTab(tab_widgets["导入与识别"], "导入与识别")
        self.settings_tabs.addTab(tab_widgets["分类与规则"], "分类与规则")
        self.settings_tabs.addTab(tab_widgets["运行状态"], "运行状态")
        self.settings_tabs.addTab(tab_widgets["安全与隐私"], "安全与隐私")
        self.settings_tabs.addTab(tab_widgets["数据与备份"], "数据与备份")
        self.settings_tabs.addTab(tab_widgets["关于"], "关于")

        layout.addWidget(self.settings_tabs, 1)
        self._refresh_settings_page()
        return page

    def _clear_log_text(self):
        if hasattr(self, "txt_log") and self.txt_log is not None:
            self.txt_log.clear()

    def _sync_export_claim_selection(self) -> None:
        if not hasattr(self, "combo_export_claims") or not hasattr(self, "combo_claims"):
            return
        if not getattr(self, "db", None) or not getattr(self.db, "is_open", False):
            return
        claim_id = self.combo_export_claims.currentData()
        if claim_id is None:
            self.export_summary_strip.set_metric("ready", "待检查")
            self.lbl_export_integrity.setText("请选择报销组后查看完整性检查。")
            self.lbl_export_blockers.setText("当前暂无阻塞。")
            if hasattr(self, "export_invoice_list"):
                self.export_invoice_list.clear()
                self.lbl_export_invoice_meta.setText("当前未选择报销组。")
            self.btn_run_export_page.setEnabled(False)
            return
        idx = self.combo_claims.findData(claim_id)
        if idx >= 0 and self.combo_claims.currentIndex() != idx:
            self.combo_claims.setCurrentIndex(idx)
        stats = self._claim_export_preflight_stats(claim_id)
        invoices = self.db.get_claim_invoices(claim_id)
        if hasattr(self, "export_invoice_list"):
            self.export_invoice_list.clear()
            for inv in invoices:
                status = self._get_invoice_review_status_chinese(inv)
                number = str(inv.get("invoice_number") or "无票号").strip()
                seller = str(inv.get("seller_name") or "未知销售方").strip()
                amount = self._format_table_amount(inv.get("total_amount") or "")
                self.export_invoice_list.addItem(f"{status} · {seller} · {amount} · {number}")
            self.lbl_export_invoice_meta.setText(
                f"当前报销组共 {len(invoices)} 张记录，其中已通过 {stats.get(APPROVED, 0)} 张，待处理 {stats.get(TO_REVIEW, 0)} 张。"
            )
        blockers = []
        if int(stats.get(APPROVED, 0) or 0) <= 0:
            blockers.append("没有已通过发票")
        if int(stats.get("missing_attachment", 0) or 0) > 0:
            blockers.append(f"缺原件 {stats.get('missing_attachment', 0)} 张")
        if int(stats.get("missing_amount", 0) or 0) > 0:
            blockers.append(f"缺金额 {stats.get('missing_amount', 0)} 张")
        is_ready = not blockers
        self.export_summary_strip.set_metric("ready", "可导出" if is_ready else "需处理")
        self.lbl_export_integrity.setText(self._format_claim_export_preflight_text(stats))
        self.lbl_export_blockers.setText("阻塞：" + "；".join(blockers) if blockers else "检查通过：可以直接开始导出。")
        self.btn_run_export_page.setEnabled(is_ready)

    def _switch_main_page(self, page_key: str, sub_tab: int = 0) -> None:
        if not hasattr(self, "center_stack") or self.center_stack is None:
            return
        page_index_map = {
            "overview": 0,
            "review": 1,
            "imports": 2,
            "export": 3,
            "logs": 4,
            "settings": 5,
        }
        idx = page_index_map.get(page_key, 1)
        if hasattr(self, "center_stack") and 0 <= idx < self.center_stack.count():
            self.center_stack.setCurrentIndex(idx)
        self._mount_log_widget("page" if page_key == "logs" else "drawer")

        if hasattr(self, "workbench_nav_buttons") and page_key in self.workbench_nav_buttons:
            btn = self.workbench_nav_buttons[page_key]
            if btn and hasattr(btn, "isCheckable") and btn.isCheckable():
                btn.setChecked(True)

        if page_key == "overview":
            self._refresh_overview_page()
        elif page_key == "imports":
            self._refresh_imports_page()
        elif page_key == "export":
            self._refresh_export_page()
        elif page_key == "settings":
            self._refresh_settings_page()

        if page_key == "settings" and hasattr(self, "settings_tabs") and self.settings_tabs is not None:
            self.settings_tabs.setCurrentIndex(sub_tab)



    def _setup_workbench_shortcuts(self) -> None:
        self.workbench_shortcuts = {}
        self._register_shortcut(self, self.workbench_shortcuts, "Up", lambda: self._move_invoice_selection(-1))
        self._register_shortcut(self, self.workbench_shortcuts, "Down", lambda: self._move_invoice_selection(1))
        self._bind_review_shortcuts(self, self.workbench_shortcuts)
        self._register_shortcut(self, self.workbench_shortcuts, "Ctrl+F", self.txt_search.setFocus, guarded=False)
        self._register_shortcut(self, self.workbench_shortcuts, "F11", self._toggle_preview_focus_mode, guarded=False)
        self._register_shortcut(self, self.workbench_shortcuts, "Ctrl+I", self._import_local_clicked, guarded=False)
        self._register_shortcut(self, self.workbench_shortcuts, "Ctrl+U", self._mobile_upload_clicked, guarded=False)
        self._register_shortcut(self, self.workbench_shortcuts, "Ctrl+M", self._scan_email_clicked, guarded=False)
        self._register_shortcut(self, self.workbench_shortcuts, "Ctrl+R", self._load_invoices, guarded=False)


    def _base_filter_label(self, status) -> str:
        if status == "all":
            needle = self.txt_search.text().strip() if hasattr(self, "txt_search") else ""
            column_filters_active = has_active_filters(self.column_filters) if hasattr(self, "column_filters") else False
            if needle or column_filters_active:
                return "当前范围全部"
            return "全部"
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
            if hasattr(btn, "set_title") and hasattr(btn, "set_value"):
                btn.set_title(self._base_filter_label(status))
                btn.set_value(str(counts.get(status, 0)))
            else:
                btn.setText(f"{self._base_filter_label(status)} {counts.get(status, 0)}")

    def _toggle_shortcut_disclosure(self) -> None:
        panel = self.shortcut_disclosure
        panel.set_expanded(not panel.is_expanded())
        panel.adjustSize()
        pos = self.btn_shortcut_help.mapToGlobal(self.btn_shortcut_help.rect().topLeft())
        panel.move(pos.x(), max(0, pos.y() - panel.height() - 4))
        panel.show()
        self._save_splitter_prefs()

    def _open_logs_view(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QLabel
        dialog = QDialog(self)
        dialog.setWindowTitle("操作日志 - Invoice Hub")
        dialog.resize(650, 450)
        layout = QVBoxLayout(dialog)
        title = QLabel("系统运行与操作日志")
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        layout.addWidget(title)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Consolas", 9))
        txt.setText(getattr(self.txt_log, "toPlainText", lambda: "日志就绪")() if hasattr(self, "txt_log") else "运行日志加载就绪。")
        layout.addWidget(txt)
        dialog.exec()

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

    def _get_invoice_review_status_chinese(self, inv: dict) -> str:
        status_mapping = {
            "to_review": "待审核",
            "approved": "已通过",
            "ignored": "已忽略",
            "error": "异常",
        }
        return status_mapping.get(inv.get("review_status") or TO_REVIEW, "待审核")

    def _get_invoice_claim_group(self, inv: dict) -> str:
        for key in ("claim_name", "claim_group_name", "claim_group"):
            value = str(inv.get(key) or "").strip()
            if value:
                return value
        return ""

    def _get_invoice_quality(self, inv: dict) -> str:
        status = self._get_invoice_data_status(inv)
        if status == "正常":
            return ""
        return status

    def _get_invoice_data_status(self, inv: dict) -> str:
        inv_num = str(inv.get("invoice_number") or "").strip()
        total_amt = str(inv.get("total_amount") or "").strip()
        inv_date = str(inv.get("expense_date") or inv.get("invoice_date") or "").strip()
        seller = str(inv.get("seller_name") or "").strip()
        attachment_path = str(inv.get("attachment_path") or "").strip()
        missing_extra = bool(inv.get("missing_extra"))

        if not inv_num and not total_amt and not seller:
            return "未识别"
        if not inv_num or not total_amt or not inv_date or not seller:
            return "待补全"
        if not attachment_path:
            return "缺原件"
        if missing_extra:
            return "缺证明"
        return "正常"

    def _badge_spec_for_review_status(self, status: str) -> dict | None:
        return REVIEW_STATUS_BADGES.get(status or TO_REVIEW)

    def _badge_spec_for_data_status(self, status: str) -> dict | None:
        return DATA_STATUS_BADGES.get(status)

    def _format_table_amount(self, amount_text: str) -> str:
        text = str(amount_text or "").strip()
        if not text:
            return "—"
        try:
            return f"{Decimal(text):.2f}"
        except (InvalidOperation, ValueError, TypeError):
            return text

    def _maybe_load_more_invoices(self, value: int):
        if not hasattr(self, "table") or self.table is None:
            return
        scrollbar = self.table.verticalScrollBar()
        if scrollbar is None or scrollbar.maximum() <= 0:
            return
        threshold = 10
        if value < scrollbar.maximum() - threshold:
            return
        if getattr(self, "_is_loading_more_invoices", False):
            return
        shown = len(getattr(self, "invoices_list", []) or [])
        total = int(getattr(self, "_record_total_matching", shown) or shown)
        if shown >= total:
            return
        self._load_next_invoice_page()

    def _load_next_invoice_page(self):
        if getattr(self, "_is_loading_more_invoices", False):
            return
        self._is_loading_more_invoices = True
        shown = len(getattr(self, "invoices_list", []) or [])
        total = int(getattr(self, "_record_total_matching", shown) or shown)
        if hasattr(self, "lbl_record_count"):
            self.lbl_record_count.setText(f"已加载 {shown} / {total} 张，正在加载更多…")
        QTimer.singleShot(100, self._append_next_invoice_batch)

    def _append_next_invoice_batch(self):
        try:
            if not hasattr(self, "db") or self.db is None:
                return
            current_count = len(getattr(self, "invoices_list", []) or [])
            status_filter = getattr(self, "current_filter", "all")
            status_val = None if status_filter == "all" else status_filter
            batch = self.db.list_invoices(
                status=status_val,
                limit=50,
                include_deleted=getattr(self, "show_deleted", False),
                offset=current_count,
            )
            if batch:
                self.invoices_list.extend(batch)
                self._update_table_view()
        finally:
            self._is_loading_more_invoices = False
            self._update_record_header_summary()

    def _update_record_header_summary(self, total_matching: int | None = None, selected_count: int | None = None):
        if total_matching is not None:
            self._record_total_matching = max(0, int(total_matching))
        shown = len(getattr(self, "invoices_list", []) or [])
        total = max(shown, int(getattr(self, "_record_total_matching", shown) or shown))
        visible_rows = 7
        if hasattr(self, "table") and self.table is not None and self.table.viewport():
            vh = self.table.viewport().height()
            rh = self.table.verticalHeader().defaultSectionSize() or 30
            if vh > 0:
                visible_rows = max(1, vh // rh)
        if hasattr(self, "lbl_record_count"):
            if shown >= total and total > 0:
                self.lbl_record_count.setText(f"已加载全部 {total} 张，当前可见 {visible_rows} 张")
            else:
                self.lbl_record_count.setText(f"已加载 {shown} / {total} 张，当前可见 {visible_rows} 张")
        if selected_count is not None and hasattr(self, "lbl_record_selection"):
            self.lbl_record_selection.setText("未选" if selected_count <= 0 else f"已选 {selected_count} 张")

    def _on_chk_needs_fix_changed(self, state):
        if state == Qt.Checked or state == 2:
            self.column_filters["status"] = {"values": {"未识别", "待补全", "缺原件", "缺证明"}}
        else:
            self.column_filters.pop("status", None)
        self._refresh_column_filter_headers()
        self._update_filter_summary_chips()
        self._load_invoices()

    def _on_chk_unlinked_changed(self, state):
        if state == Qt.Checked or state == 2:
            self.column_filters["claim_name"] = {"values": {"(空白)"}}
        else:
            self.column_filters.pop("claim_name", None)
        self._refresh_column_filter_headers()
        self._update_filter_summary_chips()
        self._load_invoices()

    def _sync_column_filters_to_checkboxes(self):
        if hasattr(self, "chk_needs_fix"):
            self.chk_needs_fix.blockSignals(True)
            status_filter = self.column_filters.get("status")
            if status_filter and "values" in status_filter:
                vals = set(status_filter["values"])
                self.chk_needs_fix.setChecked(vals == {"未识别", "待补全", "缺原件", "缺证明"})
            else:
                self.chk_needs_fix.setChecked(False)
            self.chk_needs_fix.blockSignals(False)

        if hasattr(self, "chk_unlinked"):
            self.chk_unlinked.blockSignals(True)
            claim_filter = self.column_filters.get("claim_name")
            if claim_filter and "values" in claim_filter:
                vals = set(claim_filter["values"])
                self.chk_unlinked.setChecked(vals == {"(空白)"})
            else:
                self.chk_unlinked.setChecked(False)
            self.chk_unlinked.blockSignals(False)

    def _update_filter_summary_chips(self):
        while self.chips_container_layout.count():
            item = self.chips_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        chips_to_add = []
        for key, spec in self.column_filters.items():
            if not is_filter_active(spec):
                continue
            label = COLUMN_LABELS.get(key, key)
            if key == "status":
                vals = set(spec.get("values") or ())
                if vals == {"未识别", "待补全", "缺原件", "缺证明"}:
                    chips_to_add.append(("待补全", key))
                else:
                    summary = ",".join(sorted(vals))
                    if len(summary) > 15:
                        summary = summary[:12] + "..."
                    chips_to_add.append((f"{label}: {summary}", key))
            elif key == "claim_name":
                vals = set(spec.get("values") or ())
                if vals == {"(空白)"}:
                    chips_to_add.append(("未关联报销组", key))
                else:
                    summary = ",".join(sorted(vals))
                    if len(summary) > 15:
                        summary = summary[:12] + "..."
                    chips_to_add.append((f"{label}: {summary}", key))
            elif "values" in spec:
                vals = set(spec["values"] or ())
                summary = ",".join(sorted(vals))
                if len(summary) > 15:
                    summary = summary[:12] + "..."
                chips_to_add.append((f"{label}: {summary}", key))
            elif key == "total_amount":
                min_v = spec.get("min", "")
                max_v = spec.get("max", "")
                if min_v and max_v:
                    chips_to_add.append((f"金额: {min_v}~{max_v}", key))
                elif min_v:
                    chips_to_add.append((f"金额 >= {min_v}", key))
                elif max_v:
                    chips_to_add.append((f"金额 <= {max_v}", key))
            elif "quick" in spec:
                quick_disp = {
                    "today": "今天",
                    "week": "本周",
                    "month": "本月",
                    "last_30_days": "最近 30 天",
                }.get(spec["quick"], spec["quick"])
                chips_to_add.append((f"费用日期: {quick_disp}", key))

        needle = self.txt_search.text().strip()
        if needle:
            chips_to_add.append((f"搜索: {needle}", "search"))

        if chips_to_add:
            self.filter_chips_widget.setVisible(True)
            for text, key in chips_to_add:
                btn = make_filter_chip(text, tooltip=text)
                btn.clicked.connect(lambda checked=False, k=key: self._clear_single_filter(k))
                self.chips_container_layout.addWidget(btn)
        else:
            self.filter_chips_widget.setVisible(False)

    def _clear_single_filter(self, key):
        if key == "search":
            self.txt_search.setText("")
            if hasattr(self, "search_reload_timer"):
                self.search_reload_timer.stop()
        else:
            self.column_filters.pop(key, None)
            self._sync_column_filters_to_checkboxes()
            self._refresh_column_filter_headers()
        self._update_filter_summary_chips()
        self._load_invoices()

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
                    if value.get("disabled"):
                        continue
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
            if hasattr(btn, "set_selected"):
                btn.set_selected(s == status)
            else:
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
        column_filters_active = has_active_filters(self.column_filters)
        is_default_view = not needle and not column_filters_active

        limit_val = None
        if self._is_first_load and is_default_view and self.current_filter_status is None:
            limit_val = 50

        counts = None
        try:
            include_deleted = self.chk_show_deleted.isChecked() if hasattr(self, "chk_show_deleted") else False
            db_start = time.perf_counter()
            if is_default_view:
                # Optimized path: avoid loading all records
                display_source = self.db.list_invoices(
                    status=self.current_filter_status,
                    limit=limit_val,
                    include_deleted=include_deleted
                )
                counts = {
                    "all": self.db.count_invoices_for_status(status=None, include_deleted=include_deleted),
                    TO_REVIEW: self.db.count_invoices_for_status(status=TO_REVIEW, include_deleted=include_deleted),
                    APPROVED: self.db.count_invoices_for_status(status=APPROVED, include_deleted=include_deleted),
                    IGNORED: self.db.count_invoices_for_status(status=IGNORED, include_deleted=include_deleted),
                    ERROR: self.db.count_invoices_for_status(status=ERROR, include_deleted=include_deleted),
                }
            else:
                display_source = self.db.list_invoices(
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

        filter_start = time.perf_counter()
        
        # 1. Apply global search
        if is_default_view:
            filtered_invoices = display_source
        else:
            filtered_invoices = display_source
            if needle:
                temp = []
                for inv in filtered_invoices:
                    claim_name = self._get_invoice_claim_group(inv)
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
                    if needle in haystack:
                        temp.append(inv)
                filtered_invoices = temp

            # 2. Apply column filters
            filtered_invoices = apply_column_filters(
                filtered_invoices,
                self.column_filters,
                self._column_filter_value_getters(),
            )

        # 3. Dynamic count calculation for review status buttons
        if counts is None:
            counts = {
                "all": len(filtered_invoices),
                TO_REVIEW: 0,
                APPROVED: 0,
                IGNORED: 0,
                ERROR: 0,
            }
            for inv in filtered_invoices:
                rev_status = inv.get("review_status") or TO_REVIEW
                if rev_status in counts:
                    counts[rev_status] += 1

        self._update_filter_counts(counts)

        # 4. Filter by review status
        displayed_invoices = filtered_invoices
        if not is_default_view and self.current_filter_status is not None:
            displayed_invoices = [
                inv for inv in displayed_invoices
                if (inv.get("review_status") or TO_REVIEW) == self.current_filter_status
            ]

        # 5. Apply first-load limit of 50 rows
        total_matching = len(displayed_invoices)
        if is_default_view:
            total_matching = counts.get("all") if self.current_filter_status is None else counts.get(self.current_filter_status, 0)

        first_load_limited = False
        if self._limited_first_load_active and total_matching > 50:
            displayed_invoices = displayed_invoices[:50]
            first_load_limited = True
        elif limit_val is not None and total_matching > 50:
            first_load_limited = True

        filter_elapsed_ms = int((time.perf_counter() - filter_start) * 1000)
        self.invoices_list = displayed_invoices

        # Track limited first-load state for UI hints
        if first_load_limited:
            self._limited_first_load_active = True
            self._limited_first_load_total = total_matching
            shown = len(displayed_invoices)
            notice = (
                f"当前范围全部 {total_matching} 张 (首屏已加载最近 {shown} 张)。"
                f"点击\"加载全部\"查看完整列表，或使用搜索/筛选缩小范围。"
            )
            self._first_load_notice = notice
            self.write_log(f"ℹ️ [首屏提示] {notice}")
        else:
            self._limited_first_load_active = False
            self._limited_first_load_total = 0
            self._first_load_notice = None

        self._update_record_header_summary(total_matching=total_matching)

        # Show/hide the load-all button
        if hasattr(self, "btn_load_all"):
            if self._limited_first_load_active:
                shown = len(self.invoices_list) if self.invoices_list else 50
                self.btn_load_all.setText("加载全部")
                self.btn_load_all.setToolTip(
                    f"首屏仅加载 {shown} / {self._limited_first_load_total} 张，点击加载完整列表"
                )
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
                display_amount = self._format_table_amount(total_amt)
                category = str(inv.get("category") or "未分类")
                seller = str(inv.get("seller_name") or "")
                display_status = self._get_invoice_data_status(inv)
                review_status = inv.get("review_status") or TO_REVIEW
                buyer_check_warning = self._buyer_warning(inv)
                date_warn = get_date_warning(inv)
                combined_warning = ""
                if buyer_check_warning and date_warn:
                    combined_warning = f"{buyer_check_warning}\n{date_warn}"
                elif buyer_check_warning:
                    combined_warning = buyer_check_warning
                elif date_warn:
                    combined_warning = date_warn

                rev_chinese = self._get_invoice_review_status_chinese(inv)
                row_items = [
                    rev_chinese,
                    display_status,
                    display_date or "—",
                    display_amount,
                    seller or "—",
                    inv_num or "—",
                ]

                for col, text in enumerate(row_items):
                    item = QTableWidgetItem(text)

                    if col == 3:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        item.setToolTip(total_amt or display_amount)
                    if col == 2:
                        item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                    if col in (0, 1):
                        item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                    if col == 0:
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        badge = self._badge_spec_for_review_status(review_status)
                        if badge:
                            item.setData(TABLE_BADGE_ROLE, badge)
                        item.setToolTip(f"资料状态: {display_status}\n审核状态: {rev_chinese}")
                    elif col == 1:
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        badge = self._badge_spec_for_data_status(display_status)
                        if badge:
                            item.setData(TABLE_BADGE_ROLE, badge)
                        item.setToolTip(f"资料状态: {display_status}")
                    elif col == 2:
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
                    elif col == 4 and seller:
                        item.setToolTip(seller)
                    elif col == 5 and inv_num:
                        item.setForeground(QColor("#94A3B8"))
                        item.setToolTip(inv_num)

                    if combined_warning:
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
                self.lbl_empty_title.setText("没有符合条件的发票")
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
            self._preview_empty_message = "没有符合条件的发票" if total_in_db > 0 else "请选择一张发票查看原件"
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
                self.table.blockSignals(True)
                try:
                    self._apply_single_row_selection(target_row)
                finally:
                    self.table.blockSignals(False)
                self._ensure_single_row_selection(target_row)
                self._on_table_selection_changed()
                selection_model = self.table.selectionModel()
                if selection_model is not None and not selection_model.selectedRows():
                    self._apply_single_row_selection(target_row)
                    self._on_table_selection_changed()
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

    def _load_claims(self, selected_claim_id=None):
        """Populate the claim groups dropdown from DB."""
        current_claim_id = selected_claim_id
        if current_claim_id is None and hasattr(self, "combo_claims"):
            current_claim_id = self.combo_claims.currentData()
        if current_claim_id == self._NEW_CLAIM_VALUE:
            current_claim_id = None
        try:
            claims = self.db.list_claim_groups()
        except Exception as e:
            _log.error("Failed to load claim groups from DB: %s", e)
            claims = []

        self.combo_claims.blockSignals(True)
        self.combo_claims.clear()
        for c in claims:
            period = ""
            if c.get("period_start") or c.get("period_end"):
                period = f" - {c.get('period_start')}~{c.get('period_end')}"
            display_text = f"{c.get('name')}{period}"
            self.combo_claims.addItem(display_text, c.get("id"))
        self.combo_claims.addItem("＋ 新建报销组…", self._NEW_CLAIM_VALUE)
        if current_claim_id is not None:
            idx = self.combo_claims.findData(current_claim_id)
            if idx >= 0:
                self.combo_claims.setCurrentIndex(idx)
        self.combo_claims.blockSignals(False)
        if hasattr(self._detail_panel, "claim_empty_hint"):
            self._detail_panel.claim_empty_hint.setVisible(not claims)
        self._update_claim_total()
        if hasattr(self, "combo_export_claims"):
            self._refresh_export_page()

    def _update_claim_total(self):
        if not hasattr(self, "lbl_claim_total"):
            return
        claim_idx = self.combo_claims.currentIndex() if hasattr(self, "combo_claims") else -1
        if claim_idx < 0:
            self.lbl_claim_total.setText("0 条记录 · 合计 ¥0.00")
            if hasattr(self, "btn_add_to_claim"):
                self.btn_add_to_claim.setText("加入")
                self.btn_add_to_claim.setToolTip("请先选择报销组")
                self.btn_add_to_claim.setEnabled(False)
            if hasattr(self, "btn_export"):
                self.btn_export.setEnabled(False)
            if hasattr(self, "btn_delete_claim"):
                self.btn_delete_claim.setEnabled(False)
            return
        claim_id = self.combo_claims.itemData(claim_idx)
        if claim_id == self._NEW_CLAIM_VALUE:
            self._detail_panel._set_new_claim_input_visible(True)
            self.lbl_claim_total.setText("输入名称并确认后即可加入发票")
            self.btn_add_to_claim.setText("加入")
            self.btn_add_to_claim.setEnabled(False)
            self.btn_export.setEnabled(False)
            self.btn_delete_claim.setEnabled(False)
            return

        self._detail_panel._set_new_claim_input_visible(False)
        try:
            invoices = self.db.get_claim_invoices(claim_id)
        except Exception as exc:
            _log.debug("Failed to calculate claim total: %s", exc)
            invoices = []

        group_name = self.combo_claims.currentText().strip()
        if " - " in group_name:
            group_name = group_name.split(" - ", 1)[0]

        from ..reimbursement import amount_total
        count, total, has_missing = amount_total(invoices)
        suffix = "，部分金额缺失" if has_missing else ""
        self.lbl_claim_total.setText(f"{group_name}：{count} 条记录 · 合计 ¥{total:.2f}{suffix}")
        
        if hasattr(self, "btn_add_to_claim"):
            existing_group = ""
            can_add = False
            if getattr(self, "current_invoice", None):
                inv_id = self.current_invoice.get("id")
                existing_group = self._get_invoice_claim_group(self.current_invoice)
                try:
                    can_add = self.db.count_claim_links(inv_id) == 0
                except Exception as exc:
                    _log.debug("Failed to inspect invoice claim links: %s", exc)
            elif hasattr(self, "table") and self.table.selectionModel():
                for index in self.table.selectionModel().selectedRows():
                    invoice = self.invoices_list[index.row()]
                    if is_pending_evidence_invoice(invoice):
                        continue
                    try:
                        if self.db.count_claim_links(invoice.get("id")) == 0:
                            can_add = True
                            break
                    except Exception as exc:
                        _log.debug("Failed to inspect selected invoice claim links: %s", exc)
            display_group = group_name if len(group_name) <= 12 else f"{group_name[:12]}…"
            if can_add:
                self.btn_add_to_claim.setText(f"加入 {display_group}")
                self.btn_add_to_claim.setToolTip(f"将当前选中的未归组发票加入“{group_name}”")
            else:
                assigned_name = existing_group or "其他报销组"
                display_assigned = assigned_name if len(assigned_name) <= 12 else f"{assigned_name[:12]}…"
                self.btn_add_to_claim.setText(f"已在 {display_assigned}")
                self.btn_add_to_claim.setToolTip("当前发票已有报销组，不能重复加入")
            self.btn_add_to_claim.setEnabled(can_add)
        if hasattr(self, "btn_export"):
            self.btn_export.setEnabled(count > 0)
        if hasattr(self, "btn_delete_claim"):
            self.btn_delete_claim.setEnabled(count == 0)
            self.btn_delete_claim.setToolTip(
                "删除当前空报销组" if count == 0 else "当前报销组有关联记录，不能删除"
            )
        if hasattr(self, "combo_export_claims") and self.combo_export_claims.count() > 0:
            export_idx = self.combo_export_claims.findData(claim_id)
            if export_idx >= 0 and self.combo_export_claims.currentIndex() != export_idx:
                self.combo_export_claims.blockSignals(True)
                self.combo_export_claims.setCurrentIndex(export_idx)
                self.combo_export_claims.blockSignals(False)
            self._sync_export_claim_selection()

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
            self._update_record_header_summary(selected_count=count)
            self.lbl_status_left.setText(prefix)
            self.lbl_status_left.setToolTip(prefix)
            self._update_record_header_summary(selected_count=0)
            
            mid_text = "未选择发票"
            self.lbl_status_middle.setText(mid_text)
            self.lbl_status_middle.setToolTip(mid_text)
            return

        def calculate_async():
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
            suffix = " (部分金额缺失)" if has_missing else ""
            
            self.lbl_status_left.setText(prefix)
            self.lbl_status_left.setToolTip(prefix)
            
            mid_text = f"已选中 {count} 张｜合计 ¥{total:.2f}{suffix}"
            self.lbl_status_middle.setText(mid_text)
            self.lbl_status_middle.setToolTip(mid_text)

        QTimer.singleShot(0, calculate_async)

    def _set_selection_total_status(self, selected_indexes):
        if not selected_indexes:
            prefix = self._format_status_count_prefix()
            self.lbl_status_left.setText(prefix)
            self.lbl_status_left.setToolTip(prefix)
            self._update_record_header_summary(selected_count=0)

            mid_text = "未选择发票"
            self.lbl_status_middle.setText(mid_text)
            self.lbl_status_middle.setToolTip(mid_text)
            return

        def calculate_async():
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
            suffix = " (部分金额缺失)" if has_missing else ""

            self.lbl_status_left.setText(prefix)
            self.lbl_status_left.setToolTip(prefix)
            self._update_record_header_summary(selected_count=count)

            mid_text = f"已选中 {count} 张｜合计 ¥{total:.2f}{suffix}"
            self.lbl_status_middle.setText(mid_text)
            self.lbl_status_middle.setToolTip(mid_text)

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
            self._update_claim_total()
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
                self.btn_delete_invoice.setProperty("variant", "secondary")
            else:
                self.btn_delete_invoice.setText("🗑️ 删除发票")
                self.btn_delete_invoice.setProperty("variant", "danger")
            self._refresh_widget_style(self.btn_delete_invoice)

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

        self._update_claim_total()

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
                            suffix = os.path.splitext(dl.file_path)[1].lower()
                            if suffix == ".pdf":
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
                                        self.write_log(f"⚠️ [重新下载] 发票 ID {inv_id} 下载的文件是 PDF 但解析失败，正在删除临时文件: {dl.file_path}")
                                        os.remove(dl.file_path)
                            elif suffix == ".ofd":
                                from ..__main__ import _rename_by_invoice_code
                                code = inv.get("invoice_code") or inv.get("invoice_number") or ""
                                inv_date = inv.get("invoice_date") or mail_date or "unknown_date"
                                cat = inv.get("category") or "其他"
                                amt = inv.get("total_amount") or ""
                                inv_num = inv.get("invoice_number") or ""
                                att_path = _rename_by_invoice_code(
                                    dl.file_path,
                                    code,
                                    inv_date,
                                    RUNTIME_DIR / "attachments",
                                    category=cat,
                                    total_amount=amt,
                                    invoice_number=inv_num,
                                    source_mode="reprocess",
                                )
                                self.db._conn.execute(
                                    "UPDATE invoices SET attachment_path = ?, parse_success = 0, parse_note = ? WHERE id = ?",
                                    (att_path, "OFD 原件已恢复，需手动处理/转换后再解析。", inv_id),
                                )
                                self.db._conn.commit()
                                self.write_log(f"✅ [重新下载] 发票 ID {inv_id} OFD 原件已恢复，需手动处理/转换后再解析。")
                                redownload_buckets["metadata_refreshed"] += 1
                                direct_download_ok = True
                            else:
                                from ..__main__ import _rename_by_invoice_code
                                code = inv.get("invoice_code") or inv.get("invoice_number") or ""
                                inv_date = inv.get("invoice_date") or mail_date or "unknown_date"
                                cat = inv.get("category") or "其他"
                                amt = inv.get("total_amount") or ""
                                inv_num = inv.get("invoice_number") or ""
                                att_path = _rename_by_invoice_code(
                                    dl.file_path,
                                    code,
                                    inv_date,
                                    RUNTIME_DIR / "attachments",
                                    category=cat,
                                    total_amount=amt,
                                    invoice_number=inv_num,
                                    source_mode="reprocess",
                                )
                                self.db._conn.execute(
                                    "UPDATE invoices SET attachment_path = ?, parse_success = 0, parse_note = ? WHERE id = ?",
                                    (att_path, f"下载了不支持的文件类型 ({suffix})，需手动处理。", inv_id),
                                )
                                self.db._conn.commit()
                                self.write_log(f"✅ [重新下载] 发票 ID {inv_id} 下载了不支持的文件类型 ({suffix})，已保存，需手动处理。")
                                redownload_buckets["metadata_refreshed"] += 1
                                direct_download_ok = True
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
        default_dir = RUNTIME_DIR / "attachments"
        attachment_path = ""
        file_path = None
        if self.current_invoice:
            attachment_path = str(self.current_invoice.get("attachment_path") or "")
            file_path = self._resolve_attachment_path(attachment_path)

        if file_path and file_path.is_file():
            target_dir = file_path.parent
        else:
            target_dir = default_dir
            target_dir.mkdir(parents=True, exist_ok=True)

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
            claim_id = self.db.create_claim_group(name=name)
            self.txt_new_claim.clear()
            self._load_claims(selected_claim_id=claim_id)
            self.statusBar().showMessage(f"成功创建报销组: '{name}'", 3000)
            if hasattr(self._detail_panel, "new_claim_widget"):
                self._detail_panel.new_claim_widget.setVisible(False)
            QMessageBox.information(self, "创建成功", f"已创建并选中报销组“{name}”；当前发票尚未加入。")
        except Exception as e:
            _log.error("Failed to create claim group: %s", e)
            QMessageBox.critical(self, "错误", f"新建报销组失败: {e}")

    def _delete_empty_claim(self):
        """Delete the selected claim group after confirming it has no records."""
        claim_idx = self.combo_claims.currentIndex()
        if claim_idx < 0:
            return
        claim_id = self.combo_claims.itemData(claim_idx)
        if claim_id == self._NEW_CLAIM_VALUE:
            return
        claim_name = self.combo_claims.currentText().split(" - ", 1)[0].strip()
        if QMessageBox.question(
            self,
            "删除报销组",
            f"确定删除空报销组“{claim_name}”吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        if not self.db.delete_claim_group_if_empty(claim_id):
            if getattr(self.db, "last_error", "") == "not_empty":
                QMessageBox.warning(self, "无法删除", "当前报销组已有记录，不能删除。")
            else:
                QMessageBox.warning(self, "无法删除", "报销组不存在或已被删除。")
            self._load_claims()
            return

        self._load_claims()
        self.statusBar().showMessage(f"已删除空报销组：{claim_name}", 3000)

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
        if claim_id == self._NEW_CLAIM_VALUE:
            QMessageBox.warning(self, "选择为空", "请先创建或选择目标报销组！")
            return
        claim_name = self.combo_claims.currentText()
        linked_count = 0
        assigned_count = 0
        evidence_only_count = 0
        failed_count = 0

        try:
            for idx in selected_indexes:
                inv = self.invoices_list[idx.row()]
                if self.db.count_claim_links(inv["id"]) > 0:
                    assigned_count += 1
                    continue
                success = self.db.add_invoice_to_claim(claim_id, inv["id"])
                if success:
                    linked_count += 1
                    continue
                error = getattr(self.db, "last_error", "")
                if error == "integrity_error":
                    assigned_count += 1
                elif error == "evidence_only":
                    evidence_only_count += 1
                else:
                    failed_count += 1

            message_parts = []
            if linked_count:
                message_parts.append(f"成功关联 {linked_count} 张发票")
            if assigned_count:
                message_parts.append(f"已归组跳过 {assigned_count} 张")
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
                "assigned": assigned_count,
                "evidence_only": evidence_only_count,
                "failed": failed_count,
            }

        except Exception as e:
            _log.error("Failed to link invoices to claim: %s", e)
            QMessageBox.critical(self, "错误", f"关联发票失败: {e}")
            return {
                "linked": linked_count,
                "assigned": assigned_count,
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
        total_invoices = (
            preflight_stats.get(APPROVED, 0)
            + preflight_stats.get(TO_REVIEW, 0)
            + preflight_stats.get(IGNORED, 0)
            + preflight_stats.get(ERROR, 0)
        )
        if total_invoices == 0:
            QMessageBox.warning(self, "关联空", "当前报销组内没有发票，无法导出！")
            return
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
            self._clear_action_busy(self.btn_toolbar_export, "导出")

    def _scan_selected_email_accounts(self):
        checked_keys = []
        if hasattr(self, "mail_account_checkboxes"):
            for chk in self.mail_account_checkboxes:
                if chk.isChecked():
                    key = chk.property("account_key")
                    if key:
                        checked_keys.append(str(key))

        if not checked_keys:
            QMessageBox.warning(self, "扫描提示", "请先在上面的列表中勾选至少一个需要扫描的邮箱账户。")
            return

        trigger_btn = getattr(self, "btn_import_scan_selected", getattr(self, "btn_scan_email", None))
        self._scan_email_clicked(selected_keys=checked_keys, trigger_btn=trigger_btn)

    def _scan_default_email_clicked(self):
        from ..config import get_email_accounts, load_config_safe
        cfg = getattr(self, "config", None) or load_config_safe()
        accounts = get_email_accounts(cfg)
        default_acc = next((a for a in accounts if a.get("is_default")), None)

        if hasattr(self, "mail_account_checkboxes"):
            for chk in self.mail_account_checkboxes:
                chk.setChecked(bool(chk.property("is_default")))

        if not default_acc:
            QMessageBox.warning(self, "扫描提示", "未找到默认扫描邮箱账户，请先在系统设置中设置默认账号。")
            return

        default_key = str(default_acc.get("mailbox_key") or default_acc.get("address") or "").strip()
        trigger_btn = getattr(self, "btn_import_scan_default", getattr(self, "btn_scan_email", None))
        self._scan_email_clicked(selected_keys=[default_key], trigger_btn=trigger_btn)

    def _scan_email_clicked(self, selected_keys: list[str] | None = None, trigger_btn=None):
        """Trigger background email incremental scanning and download."""
        from ..config import get_email_accounts, load_config_safe
        cfg = load_config_safe()
        accounts = get_email_accounts(cfg)

        if selected_keys:
            sel_set = {str(k).strip().lower() for k in selected_keys if k}
            accounts = [
                acc for acc in accounts
                if str(acc.get("mailbox_key") or acc.get("address") or "").strip().lower() in sel_set
            ]

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
                "⚠️ [邮箱扫描] 未找到符合扫描条件的启用账号："
                f"legacy_email={'已配置' if legacy_configured else '未配置'}，"
                f"email_accounts={len(raw_accounts)}，selected_keys={selected_keys or 'all'}。"
            )
            QMessageBox.warning(
                self,
                "配置缺失",
                (
                    "未找到需要扫描的启用邮箱账号。\n"
                    "请先勾选需要扫描的邮箱账户，或在系统设置中启用对应账号。"
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
                "凭据缺失",
                f"未检测到以下邮箱的授权码安全凭证：\n{missing_lines}\n请前往 [设置] 页面补充。",
            )
            self._open_settings_dialog()
            return

        active_btn = trigger_btn or getattr(self, "btn_scan_email", None)
        self.write_log("📥 [邮箱扫描] 增量拉取任务已启动...")
        self.statusBar().showMessage("正在建立邮箱连接并扫描接收邮件...")
        if active_btn:
            self._set_action_busy(active_btn, "扫描中...")

        # Spawn asynchronous thread worker
        self.scan_worker = EmailScanWorker(self.db_path, selected_keys=selected_keys)
        self.scan_worker._trigger_btn = active_btn
        self.scan_worker.log.connect(
            lambda text: self.write_log(text, mirror_to_file=False)
        )
        self.scan_worker.finished.connect(self._scan_email_finished)
        self.scan_worker.error.connect(self._scan_email_error)
        self.scan_worker.start()

    def _scan_email_finished(self, res: dict):
        btn = getattr(self.scan_worker, "_trigger_btn", None) or getattr(self, "btn_scan_email", None)
        if btn:
            orig_text = btn.property("original_text") or ("开始扫描" if btn is getattr(self, "btn_import_scan_selected", None) else ("默认" if btn is getattr(self, "btn_import_scan_default", None) else "同步"))
            self._clear_action_busy(btn, orig_text)
        summary = self._build_scan_summary(res, getattr(self.scan_worker, "summary_logs", []))
        self._last_scan_summary = summary
        self.write_log(f"✅ [邮箱扫描] 完成: {summary}")
        self.statusBar().showMessage(f"邮箱扫描完成: {summary}", 6000)

        failed_summaries = res.get("failed_summaries", []) if isinstance(res, dict) else []
        if failed_summaries:
            fail_text = "\n".join(f"  - {s}" for s in failed_summaries[:8])
            msg = (
                f"扫描完成，以下 {len(failed_summaries)} 项解析出错：\n{fail_text}\n"
                f"【统计】扫描邮件头: {summary.get('scanned_headers', 0)}, "
                f"新入库邮件头: {summary.get('new_email_headers', 0)}, "
                f"判定为发票候选: {summary.get('classified_invoice', 0)}"
            )
            QMessageBox.information(self, "扫描异常提示", msg)
        self._load_invoices()

    def _scan_email_error(self, err_msg: str):
        btn = getattr(self.scan_worker, "_trigger_btn", None) or getattr(self, "btn_scan_email", None)
        if btn:
            orig_text = btn.property("original_text") or ("开始扫描" if btn is getattr(self, "btn_import_scan_selected", None) else ("默认" if btn is getattr(self, "btn_import_scan_default", None) else "同步"))
            self._clear_action_busy(btn, orig_text)
        self.write_log(f"❌ [邮箱扫描] 失败: {err_msg}")
        self.statusBar().showMessage("邮箱扫描执行出错！", 4000)
        QMessageBox.critical(self, "错误", f"邮箱扫描执行出错: {err_msg}")

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
        self._refresh_overview_page()
        self._refresh_imports_page()
        self._refresh_settings_page()

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
        self._clear_action_busy(self.btn_import_local, "导入")
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
        self._refresh_overview_page()
        self._refresh_imports_page()
        self._refresh_settings_page()

    def _import_local_error(self, err_msg: str):
        self._clear_action_busy(self.btn_import_local, "导入")
        self.write_log(f"❌ [本地导入] 失败: {err_msg}")
        self.statusBar().showMessage("本地发票导入失败！", 4000)
        QMessageBox.critical(self, "错误", f"本地导入执行出错: {err_msg}")

    def _open_settings_dialog(self, sub_tab: int = 0):
        """Display the modal Settings QDialog for config management."""
        dialog = SettingsDialog(self)
        if hasattr(dialog, "settings_content_stack"):
            cat_map = {
                1: getattr(dialog, "page_mailbox_center", None),
                2: getattr(dialog, "page_rules_center", None),
                5: getattr(dialog, "page_data_center", None),
                6: getattr(dialog, "page_about_center", None),
            }
            target_widget = cat_map.get(sub_tab)
            if target_widget:
                dialog.settings_content_stack.setCurrentWidget(target_widget)
        dialog.exec()


    def _v5_show_failed_details_dialog(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "失败明细记录",
            "【历史抓取与解析错误明细】\n"
            "1. 无匹配发票附件: 2 封垃圾邮件 (系统已跳过)\n"
            "2. 密码保护加密 PDF: 0 封\n"
            "3. 无法解析的破损格式: 0 封\n"
            "所有正常增量发票均已解析成功并存入数据库！"
        )

    def _scan_email_finished_legacy(self, res: dict):
        self._clear_action_busy(self.btn_scan_email, "同步")
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
        self._refresh_overview_page()
        self._refresh_imports_page()
        self._refresh_settings_page()

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
        self._clear_action_busy(self.btn_scan_email, "同步")
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
        if splash is None:
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
