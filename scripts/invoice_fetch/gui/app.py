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
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QTableWidget, QTableWidgetItem, QLineEdit,
    QTextEdit, QPlainTextEdit, QPushButton, QLabel, QMessageBox, QCheckBox,
    QScrollArea, QAbstractItemView, QHeaderView, QFileDialog,
    QStackedWidget, QProgressBar, QFrame, QTabWidget, QMenu, QWidgetAction, QSizePolicy,
    QButtonGroup, QGridLayout, QStyle, QLayout, QBoxLayout, QToolButton,
    QStyledItemDelegate, QStyleOptionViewItem, QListWidget, QListWidgetItem,
    QComboBox, QSpinBox, QFormLayout, QGroupBox, QInputDialog, QDialog
)
from PySide6.QtCore import Qt, QUrl, QTimer, QEvent, QPoint, QItemSelectionModel
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtGui import QFont, QColor, QDesktopServices, QAction, QPainter, QPen

from ..db import InvoiceDB, is_pending_evidence_invoice
from .. import APP_VERSION
from ..config import PROJECT_ROOT, RUNTIME_DIR, load_config_safe, save_config
from ..export_paths import resolve_export_directory
from ..diagnostics import collect_app_info, export_diagnostics_zip
from ..reimbursement import amount_total, buyer_warning, format_amount_total, get_date_warning
from ..review_status import TO_REVIEW, APPROVED, IGNORED, ERROR
from ..log_privacy import PrivacyLogFilter, mask_email, sanitize_log_message
from .styles import (
    APP_STYLESHEET,
    PAGE_MARGIN,
    SECTION_GAP,
    SIDEBAR_COLLAPSED_WIDTH,
    SIDEBAR_EXPANDED_WIDTH,
)
from .ui_components import (
    CommandBar,
    ActivityTimeline,
    ChecklistRow,
    CompactFieldRow,
    CompactStatCard,
    DangerZone,
    ElidedTextLabel,
    EntityList,
    EmptyStateCard,
    LogDrawer,
    PageStateStack,
    MoreMenuButton,
    ReadOnlyDetailPanel,
    SelectableSourceCard,
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
from .mobile_upload_session import MobileUploadSessionController, MobileUploadSessionPanel
from .design_tokens import DESIGN_V1_COLORS
from .api_key_dialog import ApiKeyDialog
from .icon_provider import IconProvider
from .page_layouts import DashboardPageLayout, SettingsPageLayout, TaskFlowPageLayout, WorkspacePageLayout
from .ui.components import SegmentControl, PageHeader
from .preview_mixin import PreviewMixin, check_has_qt_pdf, get_qt_pdf_classes
from .workers import EmailScanWorker, ExportMigrationWorker, LocalImportWorker
from .workbench_layout import clamp_vertical_split, metrics_for_size
from .workbench_settings import (
    migrate_legacy_workbench_settings,
    sync_workbench_settings,
    workbench_settings,
)
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


@dataclass(frozen=True)
class ReviewViewState:
    """Single source of truth for review counts and selection state."""

    query_total: int
    loaded_count: int
    visible_count: int
    selected_count: int
    has_current_invoice: bool
    is_empty_result: bool
    active_filter: str
    search_text: str


@dataclass
class ImportActivity:
    """Business-facing import outcome kept separate from diagnostic logs."""

    occurred_at: datetime
    source: str
    batch_id: str = ""
    scanned: int = 0
    added: int = 0
    duplicates: int = 0
    failed: int = 0

def _v1_badge(kind: str) -> dict[str, str]:
    c = DESIGN_V1_COLORS
    return {
        "warning": {"fill": c["warning_surface"], "stroke": c["warning_border"], "text": c["warning_text"]},
        "success": {"fill": c["success_surface"], "stroke": c["success_border"], "text": c["success_text"]},
        "muted": {"fill": c["muted_surface"], "stroke": c["muted_border"], "text": c["muted_text"]},
        "danger": {"fill": c["danger_surface"], "stroke": c["danger_border"], "text": c["danger_text"]},
    }[kind]


REVIEW_STATUS_BADGES = {
    "to_review": _v1_badge("warning"), "approved": _v1_badge("success"),
    "ignored": _v1_badge("muted"), "error": _v1_badge("danger"),
}

DATA_STATUS_BADGES = {
    "正常": _v1_badge("success"), "待补全": _v1_badge("warning"),
    "缺原件": _v1_badge("warning"), "缺证明": _v1_badge("danger"),
    "未识别": _v1_badge("danger"),
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
        hint.setProperty("role", "hint")
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


class SingleTaskAiProfileDialog(QDialog):
    def __init__(self, parent=None, profile: dict | None = None):
        super().__init__(parent)
        self._source_profile = dict(profile or {})
        self._result_profile: dict | None = None

        self.setWindowTitle("AI 配置")
        self.resize(520, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("单任务 AI 配置")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        layout.addWidget(title)

        hint = QLabel("默认页面只读展示 Provider、模型、Key 和会话状态；需要修改时通过这个弹窗单独编辑。")
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)
        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["deepseek", "gemini", "openai"])
        self.txt_model = QLineEdit()
        self.chk_enabled = QCheckBox("启用 AI 提取与分类")
        form.addRow("Provider", self.combo_provider)
        form.addRow("模型", self.txt_model)
        form.addRow("", self.chk_enabled)
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

        provider = str(self._source_profile.get("provider") or "deepseek").strip()
        model = str(self._source_profile.get("model") or "").strip()
        enabled = bool(self._source_profile.get("enabled", False))
        self.combo_provider.setCurrentText(provider)
        self.txt_model.setText(model)
        self.chk_enabled.setChecked(enabled)

    def _accept_form(self) -> None:
        provider = self.combo_provider.currentText().strip()
        model = self.txt_model.text().strip()
        if not provider or not model:
            QMessageBox.warning(self, "AI 配置不完整", "请先填写 Provider 和模型。")
            return
        profile = dict(self._source_profile)
        profile.update(
            {
                "profile_id": str(profile.get("profile_id") or f"desktop-{provider}").strip(),
                "name": str(profile.get("name") or f"{provider} · {model}").strip(),
                "provider": provider,
                "model": model,
                "enabled": self.chk_enabled.isChecked(),
            }
        )
        self._result_profile = profile
        self.accept()

    def get_result_profile(self) -> dict:
        return dict(self._result_profile or {})


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
        self._export_dir = resolve_export_directory(self.config)
        self._legacy_exports = (
            PROJECT_ROOT / "exports"
            if getattr(sys, "frozen", False)
            else PROJECT_ROOT / ".invoice-hub-no-legacy-exports"
        )
        self._export_migration = None
        self._export_migration_worker = None
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
        self._import_activities: list[ImportActivity] = []
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
        self._scan_stage_display = "准备连接"
        self._scan_stage_counts = {}
        self._scan_elapsed_timer = QTimer(self)
        self._scan_elapsed_timer.timeout.connect(self._refresh_scan_elapsed)
        self._restore_splitter_prefs()
        self._start_export_migration()
        init_time = _time_mod.time()
        self.gui_init_ms = int((init_time - db_time) * 1000)

        # Startup responsiveness logs
        self.write_log(f"⚡ [系统启动] GUI Import/Load Start: 正在初始化界面主框架...")
        self.write_log(f"💾 [系统启动] DB Open Complete: 成功打开本地 SQLite 数据库 (耗时: {db_time - start_time:.4f}秒)")
        self.write_log(f"🎨 [系统启动] GUI Init Complete: UI 工作流外壳与部件构建完成 (耗时: {init_time - db_time:.4f}秒)")

        # Register deferred load
        QTimer.singleShot(50, self._deferred_init)

    def _start_export_migration(self):
        """Start legacy export migration after the main window is constructed."""
        if not self._legacy_exports.is_dir():
            return
        worker = ExportMigrationWorker(
            self._legacy_exports,
            self._export_dir,
            parent=self,
        )
        self._export_migration_worker = worker
        worker.progress.connect(self._export_migration_progress)
        worker.finished.connect(self._export_migration_finished)
        worker.error.connect(self._export_migration_error)
        self.statusBar().showMessage("正在迁移旧导出文件…", 4000)
        worker.start()

    def _export_migration_progress(self, progress: dict):
        processed = int(progress.get("processed", 0) or 0)
        total = int(progress.get("total", 0) or 0)
        copied = int(progress.get("copied", 0) or 0)
        conflicts = int(progress.get("conflicts", 0) or 0)
        failed = int(progress.get("failed", 0) or 0)
        self.statusBar().showMessage(
            f"正在迁移旧导出文件：{processed}/{total}，已复制 {copied}，"
            f"冲突 {conflicts}，失败 {failed}",
            4000,
        )

    def _export_migration_finished(self, result):
        self._export_migration = result
        if result.failures or result.source_remains:
            message = "旧导出目录迁移未完成，源文件已保留。"
        else:
            message = (
                f"旧导出目录迁移完成：处理 {result.processed}/{result.total}，"
                f"复制 {result.copied}，冲突 {result.conflicts}。"
            )
        self.statusBar().showMessage(message, 8000)
        if result.attempted:
            QTimer.singleShot(0, self._show_export_migration_result)

    def _export_migration_error(self, message: str):
        self.statusBar().showMessage(f"旧导出目录迁移失败：{message}", 8000)

    def _show_export_migration_result(self):
        result = self._export_migration
        if result is None:
            return
        if result.failures or result.source_remains:
            QMessageBox.warning(
                self,
                "旧导出目录迁移未完成",
                "部分旧导出文件未能迁移，源文件已保留。\n"
                f"旧目录: {result.source}\n新目录: {result.destination}\n"
                "请确认目录权限或磁盘空间后重启应用重试。",
            )
        elif result.copied or result.conflicts:
            QMessageBox.information(
                self,
                "导出目录已迁移",
                f"已将 {result.copied + result.conflicts} 个旧导出文件安全迁移到用户文档目录。\n"
                f"新目录: {result.destination}",
            )

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
        controller = getattr(self, "mobile_upload_controller", None)
        if controller is not None and not controller.shutdown():
            self._close_pending = True
            self.statusBar().showMessage("正在停止手机上传服务，请稍候…")
            event.ignore()
            return
        self._close_pending = False

        migration_worker = getattr(self, "_export_migration_worker", None)
        if migration_worker is not None and migration_worker.isRunning():
            self.statusBar().showMessage("正在完成旧导出文件迁移，请稍候…")
            # Migration copies into a private temporary file and only exposes a
            # verified target at the end.  Wait cooperatively instead of
            # terminating the worker while a destination file is being written.
            migration_worker.wait()
            if migration_worker.result is not None:
                self._export_migration = migration_worker.result

        scan_worker = getattr(self, "scan_worker", None)
        is_scan_running = getattr(scan_worker, "isRunning", None)
        if callable(is_scan_running) and is_scan_running():
            scan_worker.request_cancel()
            scan_worker.wait()
        self._save_splitter_prefs()
        self.db.close()
        event.accept()

    def _retry_close_after_mobile_shutdown(self):
        if getattr(self, "_close_pending", False):
            QTimer.singleShot(0, self.close)

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
        nav_width = SIDEBAR_COLLAPSED_WIDTH if nav_collapsed else metrics.nav_width
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
            # In the icon-only rail a focused inactive button is visually
            # indistinguishable from a second selected page.  Keep collapsed
            # navigation mouse-only and let the checked tile be the sole page
            # indicator; expanded navigation remains available in the Tab
            # focus chain with its normal focus treatment.
            button.setFocusPolicy(Qt.NoFocus if nav_collapsed else Qt.TabFocus)
            button.setProperty("collapsed", nav_collapsed)
            button.setMinimumHeight(36 if not nav_collapsed else 44)
            button.style().unpolish(button)
            button.style().polish(button)
        self.btn_collapse_nav.setText("" if nav_collapsed else "收起侧边栏")
        self.btn_collapse_nav.setToolTip("展开侧边栏" if nav_collapsed else "收起侧边栏")
        self.btn_collapse_nav.setIcon(IconProvider.icon("expand" if nav_collapsed else "collapse"))
        self.btn_collapse_nav.setProperty("collapsed", nav_collapsed)
        self.btn_collapse_nav.style().unpolish(self.btn_collapse_nav)
        self.btn_collapse_nav.style().polish(self.btn_collapse_nav)
        self.btn_collapse_nav.setVisible(True)
        help_text = self.btn_shortcut_help.accessibleName() or self.btn_shortcut_help.text()
        collapse_tip = self.btn_collapse_nav.toolTip()
        self.btn_shortcut_help.setAccessibleName(help_text)
        self.btn_shortcut_help.setToolTip(help_text)
        self.btn_shortcut_help.setText("" if nav_collapsed else help_text)
        self.btn_collapse_nav.setAccessibleName(collapse_tip)
        if nav_collapsed:
            self.btn_shortcut_help.setFixedSize(40, 40)
            self.btn_collapse_nav.setFixedSize(40, 40)
        else:
            self.btn_shortcut_help.setMinimumSize(0, 32)
            self.btn_shortcut_help.setMaximumSize(16777215, 16777215)
            self.btn_collapse_nav.setMinimumSize(0, 32)
            self.btn_collapse_nav.setMaximumSize(16777215, 16777215)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        if hasattr(self, "imports_shell_layout"):
            if w < 1200:
                self.imports_shell_layout.setDirection(QBoxLayout.TopToBottom)
                self.import_source_card.body_layout.setDirection(QBoxLayout.LeftToRight)
                self.import_task_stack.setMaximumWidth(16777215)
                self.import_source_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
                self.import_mail_recent_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
                self.import_source_card.setMinimumWidth(0)
                self.import_source_card.setMaximumWidth(16777215)
                self.import_mail_recent_card.setMinimumWidth(0)
                self.import_mail_recent_card.setMaximumWidth(16777215)
            else:
                self.imports_shell_layout.setDirection(QBoxLayout.LeftToRight)
                self.import_source_card.body_layout.setDirection(QBoxLayout.TopToBottom)
                self.import_task_stack.setMaximumWidth(900)
                self.import_source_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
                self.import_mail_recent_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
                source_width = 250 if w >= 1440 else 220
                recent_width = 350 if w >= 1440 else 300
                self.import_source_card.setFixedWidth(source_width)
                self.import_mail_recent_card.setFixedWidth(recent_width)
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
        settings = workbench_settings()
        settings.setValue("nav_collapsed_manual", self._nav_collapsed_manual)
        sync_workbench_settings(settings)
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
        settings = workbench_settings()
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
        sync_workbench_settings(settings)

    def _restore_splitter_prefs(self):
        settings = workbench_settings()
        migrate_legacy_workbench_settings(settings)
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
            self.txt_log.setObjectName("LogView")
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
        self.workbench_nav.setMinimumWidth(SIDEBAR_EXPANDED_WIDTH)
        self.workbench_nav.setMaximumWidth(SIDEBAR_EXPANDED_WIDTH)
        nav_layout = QVBoxLayout(self.workbench_nav)
        nav_layout.setContentsMargins(12, 14, 12, 14)
        nav_layout.setSpacing(6)

        nav_title = QLabel("Invoice Hub")
        nav_title.setObjectName("WorkbenchNavTitle")
        nav_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        nav_layout.addWidget(nav_title)
        self.workbench_nav_title = nav_title

        nav_subtitle = QLabel("个人报销工作台")
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
            "overview": "dashboard", "review": "review", "imports": "import",
            "logs": "info", "mobile_upload": "mobile", "export": "export",
            "mail": "mail", "rules": "settings", "settings": "settings",
            "data": "local_file", "about": "help",
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
            # Keep mouse navigation visually single-state.  With StrongFocus a
            # previously clicked item retained Qt's focus ring while the newly
            # selected page showed its checked state, which looked like two
            # active sidebar entries.  TabFocus preserves keyboard navigation
            # without assigning focus on a mouse click.
            button.setFocusPolicy(Qt.TabFocus)
            button.setCheckable(selectable)
            button.setChecked(checked if selectable else False)
            button.setMinimumHeight(40)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setIcon(IconProvider.icon(nav_icons[key]))
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
        WorkspacePageLayout.apply(self.workbench_content, main_layout)
        main_layout.setContentsMargins(12, 0, 12, 0)
        main_layout.setSpacing(8)

        self.review_header = PageHeader(
            "发票审核",
            "逐张确认原件、状态和报销组，处理完成后再进入导出。",
        )
        main_layout.addWidget(self.review_header)

        self.search_reload_timer = QTimer(self)
        self.search_reload_timer.setSingleShot(True)
        self.search_reload_timer.setInterval(250)

        nav_layout.addStretch(1)
        self.btn_collapse_nav = QPushButton("收起侧边栏")
        self.btn_collapse_nav.setObjectName("workbench_nav_collapse")
        self.btn_collapse_nav.setProperty("class", "WorkbenchNavButton")
        self.btn_collapse_nav.setIcon(IconProvider.icon("collapse"))
        self.btn_collapse_nav.setToolTip("收起或展开侧边栏")
        self.btn_collapse_nav.setMinimumHeight(32)
        self.btn_collapse_nav.clicked.connect(self._toggle_workbench_nav_collapsed)
        nav_layout.addWidget(self.btn_collapse_nav)

        # Keep help progressive; shortcut details no longer occupy the rail.
        self.btn_shortcut_help = QPushButton("帮助")
        self.btn_shortcut_help.setObjectName("WorkbenchShortcutEntry")
        self.btn_shortcut_help.setProperty("class", "WorkbenchNavButton")
        self.btn_shortcut_help.setIcon(IconProvider.icon("help"))
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
        self.import_menu = QMenu(self)
        self.action_import_local = self._make_menu_action(
            "本地文件导入", QStyle.SP_DialogOpenButton, self._import_local_clicked, "选择本地文件夹导入 PDF/ZIP/OFD 发票"
        )
        self.action_import_mobile = self._make_menu_action(
            "扫码上传", QStyle.SP_ArrowUp, self._mobile_upload_clicked, "进入导入中心并选择手机扫码"
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
            "扫码上传", QStyle.SP_ArrowUp, self._mobile_upload_clicked, "进入导入中心并选择手机扫码"
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

        self.status_segment_control = SegmentControl(self.filter_base_labels, "all")
        self.status_segment_control.changed.connect(self._change_filter)
        filter_layout.addWidget(self.status_segment_control, 1)
        self.filter_buttons = self.status_segment_control.buttons

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
        self.lbl_chips_title.setProperty("role", "status")
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
        self.lbl_empty_title.setProperty("role", "emphasis")
        empty_layout.addWidget(self.lbl_empty_title)

        self.lbl_guide = QLabel(
            "您可以执行以下操作以加载发票数据：\n\n"
            "  1. 点击“导入发票”选择本地文件夹导入 PDF/ZIP 发票；\n"
            "  2. 点击“配置邮箱”配置您的邮箱，然后点击“扫描邮箱”开始增量同步；\n"
            "  3. 点击“扫码上传”，用手机上传 PDF/OFD、相册图片或拍照材料。"
        )
        self.lbl_guide.setFont(QFont("Segoe UI", 10))
        self.lbl_guide.setProperty("role", "guide")
        self.lbl_guide.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        empty_layout.addWidget(self.lbl_guide)

        # Onboarding Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.setAlignment(Qt.AlignCenter)

        self.empty_btn_import = make_button("导入发票", variant="secondary", min_width=56)
        self.empty_btn_import.clicked.connect(self._import_local_clicked)

        self.empty_btn_settings = make_button("配置邮箱", variant="secondary", min_width=56)
        self.empty_btn_settings.clicked.connect(lambda: self._switch_main_page("settings", sub_tab=1))

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
        self.lbl_status_left.setProperty("role", "status")
        self.lbl_status_left.setToolTip("当前发票筛选状态")
        self.lbl_status_left.setMinimumWidth(120)
        status_layout.addWidget(self.lbl_status_left, 1)

        self.lbl_status_middle = QLabel("未选择发票")
        self.lbl_status_middle.setFont(QFont("Segoe UI", 9))
        self.lbl_status_middle.setProperty("role", "status")
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
        self.lbl_version.setProperty("role", "caption")
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
        lbl_log_title.setProperty("role", "strong")

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

    def _review_view_state(self, total_matching: int | None = None, selected_count: int | None = None) -> ReviewViewState:
        loaded = len(getattr(self, "invoices_list", []) or [])
        visible = self.table.rowCount() if hasattr(self, "table") else loaded
        query_total = max(visible, int(total_matching if total_matching is not None else getattr(self, "_record_total_matching", loaded) or loaded))
        if selected_count is None:
            selected_count = len(self.table.selectionModel().selectedRows()) if hasattr(self, "table") and self.table.selectionModel() else 0
        search_text = self.txt_search.text().strip() if hasattr(self, "txt_search") else ""
        active_filter = str(getattr(self, "current_filter_status", None) or "all")
        return ReviewViewState(query_total, loaded, visible, int(selected_count), bool(getattr(self, "current_invoice", None)), visible == 0, active_filter, search_text)

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
        paging = getattr(self, "review_paging", None)
        if delta > 0 and row == len(self.invoices_list) - 1 and paging is not None and paging.has_more() and not paging.loading:
            paging.pending_row = row + 1
            paging.load_next_page()
            if row + 1 < len(self.invoices_list):
                self._select_invoice_by_id(self.invoices_list[row + 1].get("id"))
            paging.pending_row = -1
            return
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
        export_ready = 0

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

        try:
            for claim in self.db.list_claim_groups():
                stats = self._claim_export_preflight_stats(
                    claim.get("id"),
                    include_to_review=False,
                )
                if (
                    int(stats.get(APPROVED, 0) or 0)
                    and not int(stats.get("missing_attachment", 0) or 0)
                    and not int(stats.get("missing_amount", 0) or 0)
                    and not int(stats.get("missing_extra", 0) or 0)
                    and not int(stats.get("unavailable_extra", 0) or 0)
                ):
                    export_ready += 1
        except Exception:
            export_ready = 0

        return {
            "today_imported": today_imported,
            "to_review": self.db.count_invoices_for_status(TO_REVIEW),
            "error": self.db.count_invoices_for_status(ERROR),
            "needs_fix": needs_fix,
            "month_total": month_total,
            "export_ready": export_ready,
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
        integer_keys = ("today_imported", "to_review", "error", "needs_fix", "export_ready", "total")
        if (
            metrics is None
            or any(not isinstance(metrics.get(key), int) for key in integer_keys)
            or not isinstance(metrics.get("month_total"), Decimal)
        ):
            retry = make_button("重试", variant="secondary")
            retry.clicked.connect(self._refresh_overview_page)
            self.overview_state_stack.show_error("无法读取工作台数据", retry=retry)
            for label in self.overview_value_labels.values():
                label.set_value("—")
            return

        if metrics["total"] == 0:
            action = make_button("开始导入", variant="primary")
            action.clicked.connect(lambda: self._switch_main_page("imports"))
            self.overview_state_stack.show_empty(
                "还没有发票", "先从本地、邮箱或手机导入第一张发票。", action=action
            )
            return

        self.overview_state_stack.show_content()

        self.overview_value_labels["to_review"].set_value(f"{metrics['to_review']} 张")
        self.overview_value_labels["error"].set_value(f"{metrics['error']} 张")
        self.overview_value_labels["needs_fix"].set_value(f"{metrics['needs_fix']} 张")
        self.overview_value_labels["export_ready"].set_value(f"{metrics['export_ready']} 组")
        self.lbl_overview_recent_imports.setText(
            f"继续审核 {metrics['to_review']} 张发票。"
        )
        self.lbl_overview_health.setText(
            f"待审核 {metrics['to_review']} 张 / 异常 {metrics['error']} 张 / 待补全 {metrics['needs_fix']} 张。"
        )
        if hasattr(self, "lbl_overview_next_actions"):
            if metrics["to_review"] > 0:
                self.lbl_overview_next_actions.setText("建议顺序：优先清待审核，再回头处理异常和待补全。")
            elif metrics["needs_fix"] > 0 or metrics["error"] > 0:
                self.lbl_overview_next_actions.setText("审核队列已经清空，下一步优先补材料或处理异常。")
            else:
                self.lbl_overview_next_actions.setText("当前队列较干净，可以直接检查报销组并准备导出。")
        if hasattr(self, "lbl_overview_export_hint"):
            self.lbl_overview_export_hint.setText(
                f"缺材料 {metrics['needs_fix']} 张 · 异常 {metrics['error']} 张 · 可导出 {metrics['export_ready']} 组。"
            )
        if hasattr(self, "overview_timeline"):
            self.overview_timeline.clear()
            last_scan = getattr(self, "_last_scan_summary", {}) or {}
            if last_scan:
                self.overview_timeline.add_entry("最近", "邮箱扫描", self._format_scan_result_for_people(last_scan).replace("最近扫描：", ""))
            else:
                self.overview_timeline.add_entry("今天", "待办更新", f"新增 {metrics['today_imported']} 张 · 待审核 {metrics['to_review']} 张")
            self.overview_timeline.add_entry("当前", "报销组", f"可导出 {metrics['export_ready']} 组 · 本月 ¥{metrics['month_total']:.2f}")

    def _select_import_source(self, source: str) -> None:
        """Select an import task; business actions stay inside that task."""
        self._set_import_source_selected(source)

    def _set_import_source_selected(self, source: str) -> None:
        self._selected_import_source = source
        for key, card in getattr(self, "import_source_cards", {}).items():
            card.set_selected(key == source)
        if hasattr(self, "import_task_stack"):
            task_page = getattr(self, "_import_task_pages", {}).get(source)
            if task_page is not None:
                self.import_task_stack.setCurrentWidget(task_page)

    def _run_import_primary_action(self) -> None:
        """Keep the import page primary action truthful for the chosen account."""
        if self.btn_import_scan_selected.text() == "补授权码":
            self._switch_main_page("settings", sub_tab=1)
            return
        self._scan_selected_email_accounts()

    def _record_import_activity(
        self,
        source: str,
        *,
        scanned: int = 0,
        added: int = 0,
        duplicates: int = 0,
        failed: int = 0,
        batch_id: str = "",
    ) -> None:
        """Record a structured import outcome for the in-session result surface."""
        normalized_batch = str(batch_id or "").strip()
        if normalized_batch:
            existing = next(
                (activity for activity in self._import_activities if activity.batch_id == normalized_batch),
                None,
            )
            if existing is not None:
                existing.occurred_at = datetime.now()
                existing.scanned = max(0, int(scanned or 0))
                existing.added = max(0, int(added or 0))
                existing.duplicates = max(0, int(duplicates or 0))
                existing.failed = max(0, int(failed or 0))
                self._import_activities.remove(existing)
                self._import_activities.insert(0, existing)
                return
        self._import_activities.insert(
            0,
            ImportActivity(
                occurred_at=datetime.now(),
                source=source,
                batch_id=normalized_batch,
                scanned=max(0, int(scanned or 0)),
                added=max(0, int(added or 0)),
                duplicates=max(0, int(duplicates or 0)),
                failed=max(0, int(failed or 0)),
            ),
        )
        del self._import_activities[10:]

    @staticmethod
    def _format_import_activity(activity: ImportActivity) -> tuple[str, str, str]:
        source_labels = {
            "mail": "邮箱扫描",
            "local": "本地导入",
            "mobile": "手机扫码",
        }
        summary_parts = []
        if activity.scanned:
            summary_parts.append(f"扫描 {activity.scanned} 封")
        summary_parts.append(f"新增 {activity.added} 条")
        summary_parts.append(f"重复 {activity.duplicates} 条")
        summary_parts.append(f"失败 {activity.failed} 条")
        state = "danger" if activity.failed else "success"
        return (
            activity.occurred_at.strftime("%H:%M"),
            source_labels.get(activity.source, "导入"),
            " · ".join(summary_parts),
        )

    def _refresh_imports_page(self) -> None:
        from ..config import get_email_accounts

        if hasattr(self, "import_recent_state_stack"):
            activities = list(getattr(self, "_import_activities", []))
            if activities:
                self.import_recent_state_stack.show_content()
            else:
                self.import_recent_state_stack.show_empty(
                    "本次运行还没有导入记录",
                    "完成一次本地导入、邮箱扫描或手机上传后，结果会显示在这里。",
                )
            if hasattr(self, "import_recent_timeline"):
                self.import_recent_timeline.clear()
                for activity in activities[:3]:
                    when, title, summary = self._format_import_activity(activity)
                    self.import_recent_timeline.add_entry(
                        when,
                        title,
                        summary,
                        state="danger" if activity.failed else "success",
                    )

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

        if hasattr(self, "lbl_mail_scan_summary"):
            last_scan_summary = getattr(self, "_last_scan_summary", {}) if hasattr(self, "_last_scan_summary") else {}
            if isinstance(last_scan_summary, dict) and last_scan_summary:
                scanned = int(last_scan_summary.get("scanned") or last_scan_summary.get("scanned_headers") or 0)
                new_items = int(last_scan_summary.get("new", 0) or 0)
                restored = int(last_scan_summary.get("restored", 0) or 0)
                duplicates = int(last_scan_summary.get("duplicates", 0) or 0)
                failed_total = (
                    int(last_scan_summary.get("download_failed", 0) or 0)
                    + int(last_scan_summary.get("parse_failed", 0) or 0)
                    + int(last_scan_summary.get("link_failed", 0) or 0)
                )
                self.lbl_mail_scan_summary.setText(
                    f"扫描 {scanned} 封 · 新增 {new_items} 条 · 重复 {duplicates} 条 · 失败 {failed_total} 条"
                )
                if hasattr(self, "lbl_import_recent_status"):
                    if failed_total > 0:
                        self.lbl_import_recent_status.setText("当前有失败项，建议先查看失败明细，再决定是否补授权或重试。")
                    else:
                        self.lbl_import_recent_status.setText("最近一次扫描没有明显阻塞，可以继续拉取或切到审核页处理新增记录。")
            else:
                self.lbl_mail_scan_summary.setText("最近扫描结果：暂无记录。点击“开始扫描”开始拉取。")
                if hasattr(self, "lbl_import_recent_status"):
                    self.lbl_import_recent_status.setText("当前没有失败项，也没有待补授权提醒。")

        if hasattr(self, "btn_import_scan_selected"):
            cfg = getattr(self, "config", None) or load_config_safe()
            accounts = get_email_accounts(cfg)
            from ..credentials import has_auth_code

            default_acc = next((acc for acc in accounts if acc.get("is_default")), None)
            default_requires_auth = bool(default_acc and not has_auth_code(default_acc.get("address", "")))
            if hasattr(self, "btn_import_scan_selected"):
                self.btn_import_scan_selected.setText("补授权码" if default_requires_auth else "开始扫描")
                self.btn_import_scan_selected.setToolTip("先补充默认邮箱授权码" if default_requires_auth else "扫描选中的邮箱账号")
            if hasattr(self, "import_mail_accounts_card") and default_acc:
                default_label = str(default_acc.get("name") or default_acc.get("address") or "邮箱扫描").strip()
                self.import_mail_accounts_card.set_title(default_label)
                self.import_mail_accounts_card.set_hint(
                    "默认账号需要授权码" if default_requires_auth else "默认账号已就绪，可直接开始扫描。"
                )
    @staticmethod
    def _format_scan_result_for_people(summary: dict) -> str:
        """Turn internal scan counters into one product-facing summary line."""
        scanned = int(summary.get("scanned") or summary.get("scanned_headers") or 0)
        new_items = int(summary.get("new", 0) or 0)
        duplicates = int(summary.get("duplicates", 0) or 0)
        failed = sum(
            int(summary.get(key, 0) or 0)
            for key in ("download_failed", "parse_failed", "link_failed")
        )
        return f"最近扫描：扫描 {scanned} 封 · 新增 {new_items} 条 · 重复 {duplicates} 条 · 失败 {failed} 条"

    def _refresh_export_page(self) -> None:
        if not hasattr(self, "export_group_list"):
            return
        claims = []
        try:
            claims = self.db.list_claim_groups()
        except Exception as exc:
            _log.debug("Failed to refresh export page: %s", exc)
        current_claim_id = self.export_group_list.currentItem().data(Qt.UserRole) if self.export_group_list.currentItem() else None
        self.export_group_list.blockSignals(True)
        self.export_group_list.clear()

        total_approved = 0
        total_pending = 0
        total_missing = 0
        for claim in claims:
            stats = self._claim_export_preflight_stats(claim.get("id"))
            approved_stats = self._claim_export_preflight_stats(
                claim.get("id"),
                include_to_review=False,
            )
            total_approved += int(stats.get(APPROVED, 0) or 0)
            total_pending += int(stats.get(TO_REVIEW, 0) or 0)
            total_missing += (
                int(stats.get("missing_attachment", 0) or 0)
                + int(stats.get("missing_amount", 0) or 0)
                + int(stats.get("missing_extra", 0) or 0)
                + int(stats.get("unavailable_extra", 0) or 0)
            )
            invoices = self.db.get_claim_invoices(claim.get("id"))
            count, total, _has_missing = amount_total(invoices)
            displayed_missing = (
                int(stats.get("missing_attachment", 0) or 0)
                + int(stats.get("missing_amount", 0) or 0)
                + int(stats.get("missing_extra", 0) or 0)
                + int(stats.get("unavailable_extra", 0) or 0)
            )
            approved_blockers = (
                int(approved_stats.get("missing_attachment", 0) or 0)
                + int(approved_stats.get("missing_amount", 0) or 0)
                + int(approved_stats.get("missing_extra", 0) or 0)
                + int(approved_stats.get("unavailable_extra", 0) or 0)
            )
            ready = int(approved_stats.get(APPROVED, 0) or 0) > 0 and approved_blockers == 0
            subtitle = f"{count} 张发票 · ¥{Decimal(str(total)).quantize(Decimal('0.00'))}"
            meta = f"完整性缺口 {displayed_missing}"
            badge = "可导出" if ready else "待补齐"
            self.export_group_list.add_entity_row(
                title=str(claim.get("name") or "未命名报销组").strip(),
                subtitle=subtitle,
                status_badge=badge,
                meta=meta,
                user_data=claim.get("id"),
            )
        self.export_group_list.blockSignals(False)
        self.export_summary_strip.set_metric("groups", str(len(claims)))
        self.export_summary_strip.set_metric("approved", str(total_approved))
        self.export_summary_strip.set_metric("pending", str(total_pending))
        self.export_summary_strip.set_metric("missing", str(total_missing))

        if not claims:
            self.export_empty_state.setVisible(True)
            self.export_invoices_card.setVisible(False)
            self.export_integrity_card.setVisible(False)
            self.export_summary_strip.set_metric("ready", "无报销组")
            if hasattr(self, "export_check_approved"):
                for row in (
                    self.export_check_approved,
                    self.export_check_pending,
                    self.export_check_missing_attach,
                    self.export_check_missing_amount,
                    self.export_check_missing_extra,
                    self.export_check_unavailable_extra,
                    self.export_check_dir,
                ):
                    row.set_value("—", None)
            if hasattr(self, "lbl_export_action_hint"):
                self.lbl_export_action_hint.setText("先在审核页关联报销组，完整性检查才会生效。")
            if hasattr(self, "export_invoice_list"):
                self.export_invoice_list.clear()
                self.lbl_export_invoice_meta.setText("当前未选择报销组。")
            self.btn_run_export_page.setEnabled(False)
            return
        self.export_empty_state.setVisible(False)
        self.export_invoices_card.setVisible(True)
        self.export_integrity_card.setVisible(True)
        target_row = 0
        if current_claim_id is not None:
            for row in range(self.export_group_list.count()):
                if self.export_group_list.item(row).data(Qt.UserRole) == current_claim_id:
                    target_row = row
                    break
        self.export_group_list.blockSignals(True)
        self.export_group_list.setCurrentRow(target_row)
        self.export_group_list.blockSignals(False)
        self._sync_export_claim_selection()

    def _refresh_settings_page(self) -> None:
        self._desktop_settings_cfg = deepcopy(load_config_safe())
        self.config = deepcopy(self._desktop_settings_cfg)
        db_file = RUNTIME_DIR / "invoices.db"
        db_size = db_file.stat().st_size if db_file.exists() else 0
        backup_dir = RUNTIME_DIR / "backups"
        last_scan = "暂无记录"
        if getattr(self, "_last_scan_summary", None):
            last_scan = self._format_scan_result_for_people(self._last_scan_summary).replace("最近扫描：", "")
        if hasattr(self, "lbl_settings_runtime"):
            self.lbl_settings_runtime.setText(
                f"数据库：{db_file}\n日志目录：{RUNTIME_DIR / 'logs'}\n"
                f"最近扫描：{last_scan}\n最近错误：{getattr(self.db, 'last_error', '') or '无'}"
            )
        if hasattr(self, "lbl_settings_privacy"):
            self.lbl_settings_privacy.setText("敏感信息仍由系统凭据管理器保存；配置文件与日志只保留脱敏内容。")
        if hasattr(self, "lbl_settings_data"):
            self.lbl_settings_data.setText(
                f"数据库大小：{db_size / 1024 / 1024:.1f} MB\n"
                "数据目录：本机应用数据目录\n"
                "备份目录：本机受保护备份目录\n"
                "导出目录：本机导出目录（可通过下方按钮打开）"
            )
        if hasattr(self, "lbl_settings_about"):
            self.lbl_settings_about.setText(self._about_text())
        self._refresh_settings_mailbox_page()
        self._refresh_settings_ai_page()

    def _settings_tab_index(self, tab_key: str) -> int:
        order = {
            "mailboxes": 0,
            "ai": 1,
            "runtime": 2,
            "privacy": 3,
            "data": 4,
            "about": 5,
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
        from ..credentials import has_auth_code
        missing_cnt = sum(1 for a in accounts if a.get("enabled", True) and not has_auth_code(a.get("address", "")))

        if hasattr(self, "stat_box_overview"):
            self.stat_box_overview.set_metric("total", str(total_cnt))
            self.stat_box_overview.set_metric("enabled", str(enabled_cnt))
            self.stat_box_overview.set_metric("missing", str(missing_cnt))

        current_key = getattr(self, "_settings_mailbox_current_key", "")
        self.settings_mailbox_list.blockSignals(True)
        self.settings_mailbox_list.clear()
        for account in accounts:
            label = str(account.get("name") or account.get("address") or "未命名邮箱").strip()
            addr = str(account.get("address") or "").strip()
            enabled = bool(account.get("enabled", True))
            has_credential = has_auth_code(addr)
            state = "已停用" if not enabled else ("缺授权" if not has_credential else "正常")
            item = self.settings_mailbox_list.add_entity_row(
                title=label,
                subtitle=mask_email(addr),
                status_badge=state,
                meta="默认" if account.get("is_default") else "",
                user_data=str(account.get("mailbox_key") or addr).strip(),
            )
        self.settings_mailbox_list.blockSignals(False)

        if hasattr(self, "lbl_settings_mailbox_empty"):
            self.lbl_settings_mailbox_empty.setVisible(False)
        has_accounts = self.settings_mailbox_list.count() > 0
        if hasattr(self, "mailbox_detail_surface"):
            self.mailbox_detail_surface.setVisible(has_accounts)
        if hasattr(self, "settings_mailbox_empty_state"):
            self.settings_mailbox_empty_state.setVisible(not has_accounts)

        if not has_accounts:
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
            self.lbl_settings_mailbox_scan_result.setText(self._format_scan_result_for_people(summary))
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
            self.lbl_detail_name.setToolTip(name)
            self.lbl_detail_email.setToolTip(addr)
            self.lbl_detail_server.setText(server or "—")
            self.lbl_detail_port_security.setText(f"{port} · {ssl}")
            self.lbl_detail_is_default.setText("是 (默认扫描账号)" if account.get("is_default") else "否")
            self.lbl_detail_credential_status.setText("已安全保存" if cred_ok else "需要授权")
            self.lbl_detail_credential_status.setStyleSheet("color: #059669; font-weight: 600;" if cred_ok else "color: #DC2626; font-weight: 600;")
            self.lbl_detail_scan_folder.setText(str(search_cfg.get("folder") or "INBOX"))
            self.lbl_detail_scan_range.setText(f"最近 {months} 个月")
            self.lbl_detail_attachment_types.setText("PDF / OFD / XML / 图片")
            self.lbl_detail_header_name.setText(name)
            self.lbl_detail_header_email.setText(mask_email(addr))
            self.lbl_detail_header_name.setToolTip(name)
            self.lbl_detail_header_email.setToolTip(addr)
            self.lbl_detail_header_status.setText("已停用" if not account.get("enabled", True) else ("需要授权" if not cred_ok else "正常"))

        enabled = bool(account.get("enabled", True))
        self.btn_settings_mailbox_add_credential.setVisible(enabled and not cred_ok)
        self.btn_settings_mailbox_test.setVisible(enabled and cred_ok)
        self.btn_settings_mailbox_scan.setVisible(enabled and cred_ok)
        self.btn_settings_mailbox_edit_config.setVisible(True)
        self.btn_settings_mailbox_toggle.setVisible(not enabled)
        self.settings_mailbox_more.setVisible(True)
        self.settings_mailbox_more_update_credential.setVisible(enabled)
        self.settings_mailbox_more_toggle.setVisible(enabled or not enabled)
        self.settings_mailbox_more_delete.setVisible(True)

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
            self.settings_mailbox_more_toggle.setText(self.btn_settings_mailbox_toggle.text())

        # There is one contextual primary action: repair credentials first,
        # otherwise scan the selected account.
        for button in (self.btn_settings_mailbox_add_credential, self.btn_settings_mailbox_scan):
            button.setProperty("variant", "secondary")
            button.style().unpolish(button)
            button.style().polish(button)
        primary = self.btn_settings_mailbox_toggle if not enabled else (self.btn_settings_mailbox_add_credential if not cred_ok else self.btn_settings_mailbox_scan)
        primary.setProperty("variant", "primary")
        primary.style().unpolish(primary)
        primary.style().polish(primary)

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
            self.lbl_detail_port_security.setText("—")
            self.lbl_detail_scan_folder.setText("—")
            self.lbl_detail_scan_range.setText("—")
            self.lbl_detail_attachment_types.setText("—")
            self.lbl_detail_header_name.setText("未选择邮箱账号")
            self.lbl_detail_header_email.setText("—")
            self.lbl_detail_header_status.setText("未配置")
        if hasattr(self, "mailbox_detail_surface"):
            self.mailbox_detail_surface.setVisible(False)
        if hasattr(self, "settings_mailbox_empty_state"):
            self.settings_mailbox_empty_state.setVisible(True)
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
        for button in (self.btn_settings_mailbox_add_credential, self.btn_settings_mailbox_test, self.btn_settings_mailbox_scan, self.btn_settings_mailbox_edit_config, self.btn_settings_mailbox_toggle):
            button.setVisible(False)
        self.settings_mailbox_more.setVisible(False)

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
            QMessageBox.warning(self, "缺少授权码", "未检测到该邮箱的授权码，请在系统设置的邮箱账户页补充凭据。")
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
            provider = str(profile.get("provider") or "—").strip()
            model = str(profile.get("model") or "—").strip()
            key_source = get_ai_api_key_source(provider, profile.get("profile_id", ""))
            self.settings_ai_profile_list.add_entity_row(
                title=str(profile.get("name") or f"{provider} · {model}").strip(),
                subtitle=f"{provider} · {model}",
                status_badge="已启用" if profile.get("enabled") else "未启用",
                meta=key_source,
                user_data=profile.get("profile_id", ""),
            )
        self.settings_ai_profile_list.blockSignals(False)

        # Dynamic visibility: show the list only when there are multiple profiles
        # so the user can switch between them.  Single-profile and no-profile
        # views stay clean without the list widget.
        multi_profile = self.settings_ai_profile_list.count() > 1
        self.settings_ai_profile_list.setVisible(multi_profile)

        self.lbl_settings_ai_empty.setVisible(False)
        if hasattr(self, "settings_ai_empty_state"):
            self.settings_ai_empty_state.setVisible(self.settings_ai_profile_list.count() == 0)
        if self.settings_ai_profile_list.count() == 0:
            self.settings_ai_detail_panel.setVisible(False)
            self.btn_settings_ai_edit.setVisible(True)
            self.btn_settings_ai_edit.setProperty("variant", "primary")
            self.btn_settings_ai_configure_key.setVisible(False)
            self.btn_settings_ai_test.setVisible(False)
            self.settings_ai_more.setVisible(False)
            self._settings_ai_current_profile_id = ""
            self.lbl_settings_ai_provider.setText("—")
            self.lbl_settings_ai_model.setText("—")
            self.lbl_settings_ai_enabled.setText("关闭")
            self.lbl_settings_ai_session_state.setText("无可用会话")
            self.lbl_settings_ai_key_status.setText("API Key 状态：未配置")
            self.lbl_settings_ai_validation_status.setText("尚未校验本地配置")
            self.lbl_settings_ai_failure_status.setText("失败状态：暂无 AI 配置。")
            if hasattr(self, "settings_ai_summary_strip"):
                self.settings_ai_summary_strip.set_metric("enabled", "关闭")
                self.settings_ai_summary_strip.set_metric("provider", "—")
                self.settings_ai_summary_strip.set_metric("model", "—")
                self.settings_ai_summary_strip.set_metric("key", "未配置")
                self.settings_ai_summary_strip.set_metric("paused", "正常")
            return

        self.settings_ai_detail_panel.setVisible(True)
        self.btn_settings_ai_edit.setVisible(True)
        self.btn_settings_ai_edit.setProperty("variant", "secondary")
        self.btn_settings_ai_configure_key.setVisible(True)
        self.btn_settings_ai_test.setVisible(True)
        self.btn_settings_ai_test.setProperty("variant", "primary")
        self.settings_ai_more.setVisible(True)

        target_row = 0
        if current_profile_id:
            for row in range(self.settings_ai_profile_list.count()):
                if self.settings_ai_profile_list.item(row).data(Qt.UserRole) == current_profile_id:
                    target_row = row
                    break
        self.settings_ai_profile_list.blockSignals(True)
        self.settings_ai_profile_list.setCurrentRow(target_row)
        self.settings_ai_profile_list.blockSignals(False)
        self._on_settings_ai_profile_selection_changed()

    def _on_settings_ai_profile_selection_changed(self) -> None:
        if not hasattr(self, "settings_ai_profile_list") or self.settings_ai_profile_list.currentRow() < 0:
            return
        profiles = self._ai_profiles_for_settings()
        row = self.settings_ai_profile_list.currentRow()
        if row < 0 or row >= len(profiles):
            return
        profile = profiles[row]
        self._settings_ai_current_profile_id = profile.get("profile_id", "")
        from ..credentials import get_ai_api_key_source
        from ..ai_classifier import is_provider_session_paused

        provider = str(profile.get("provider") or "—")
        model = str(profile.get("model") or "—")
        key_source = get_ai_api_key_source(profile.get("provider", ""), profile.get("profile_id", ""))
        self.lbl_settings_ai_key_status.setText(f"API Key 状态：{key_source}")
        self.lbl_settings_ai_validation_status.setText("已配置，尚未重新校验")
        paused = is_provider_session_paused(profile.get("provider", ""))
        self.lbl_settings_ai_provider.setText(provider)
        self.lbl_settings_ai_model.setText(model)
        self.lbl_settings_ai_enabled.setText("开启" if profile.get("enabled", False) else "关闭")
        self.lbl_settings_ai_session_state.setText("已暂停" if paused else "正常")
        self.lbl_settings_ai_failure_status.setText(f"失败状态：{'401 / 403 后本会话已暂停' if paused else '当前会话可用'}")
        if hasattr(self, "settings_ai_summary_strip"):
            self.settings_ai_summary_strip.set_metric("enabled", "开启" if profile.get("enabled", False) else "关闭")
            self.settings_ai_summary_strip.set_metric("provider", provider)
            self.settings_ai_summary_strip.set_metric("model", model)
            self.settings_ai_summary_strip.set_metric("key", key_source)
            self.settings_ai_summary_strip.set_metric("paused", "已暂停" if paused else "正常")

    def _current_settings_ai_profile(self) -> dict | None:
        profile_id = getattr(self, "_settings_ai_current_profile_id", "")
        for profile in self._ai_profiles_for_settings():
            if profile.get("profile_id", "") == profile_id:
                return dict(profile)
        return None

    def _open_edit_ai_profile_dialog(self) -> None:
        profile = self._current_settings_ai_profile()
        if profile is None:
            profile = {
                "profile_id": "desktop-deepseek",
                "name": "deepseek · deepseek-chat",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "enabled": False,
            }
        dialog = SingleTaskAiProfileDialog(self, profile=profile)
        if dialog.exec() != QDialog.Accepted:
            return
        edited = dialog.get_result_profile()
        if not edited:
            return
        from ..ai_profiles import apply_active_ai_profile, get_ai_profiles

        cfg = deepcopy(getattr(self, "_desktop_settings_cfg", load_config_safe()))
        profiles = [dict(item) for item in get_ai_profiles(cfg)]
        profile_id = str(edited.get("profile_id") or "").strip()
        replaced = False
        for idx, existing in enumerate(profiles):
            if existing.get("profile_id") == profile_id:
                profiles[idx] = edited
                replaced = True
                break
        if not replaced:
            profiles.append(edited)
        if edited.get("enabled"):
            for entry in profiles:
                entry["enabled"] = entry.get("profile_id") == profile_id
        apply_active_ai_profile(cfg, profiles)
        save_config(cfg)
        self._desktop_settings_cfg = deepcopy(cfg)
        self.config = deepcopy(cfg)
        self._settings_ai_current_profile_id = profile_id
        self._refresh_settings_page()

    def _save_settings_ai_profile(self) -> bool:
        self._open_edit_ai_profile_dialog()
        return True

    def _configure_settings_ai_key(self) -> None:
        from ..credentials import has_ai_api_key, set_ai_api_key

        current = self._current_settings_ai_profile() or {}
        provider = str(current.get("provider") or "").strip()
        if not provider:
            QMessageBox.warning(self, "未选择 Provider", "请先选择 AI Provider。")
            return
        profile_id = str(current.get("profile_id") or getattr(self, "_settings_ai_current_profile_id", "") or f"desktop-{provider}")
        dialog = ApiKeyDialog(provider, self, has_existing_key=has_ai_api_key(provider, profile_id=profile_id))
        if dialog.exec() != QDialog.Accepted:
            return
        set_ai_api_key(provider, dialog.key_text(), profile_id=profile_id)
        self._settings_ai_current_profile_id = profile_id
        self._refresh_settings_ai_page()
        if dialog.save_and_test:
            self._test_settings_ai_connection()

    def _clear_settings_ai_key(self) -> None:
        from ..credentials import delete_ai_api_key

        current = self._current_settings_ai_profile() or {}
        provider = str(current.get("provider") or "").strip()
        if not provider:
            return
        profile_id = str(current.get("profile_id") or getattr(self, "_settings_ai_current_profile_id", "") or f"desktop-{provider}")
        delete_ai_api_key(provider, profile_id=profile_id)
        self._refresh_settings_ai_page()

    def _validate_settings_ai_configuration(self) -> None:
        from ..credentials import has_ai_api_key

        current = self._current_settings_ai_profile() or {}
        provider = str(current.get("provider") or "").strip()
        model = str(current.get("model") or "").strip()
        profile_id = str(current.get("profile_id") or getattr(self, "_settings_ai_current_profile_id", "") or f"desktop-{provider}")
        if not provider or not model:
            QMessageBox.warning(self, "AI 配置不完整", "请先通过“编辑配置”补全 Provider 和模型。")
            return
        if not has_ai_api_key(provider, profile_id=profile_id):
            self.lbl_settings_ai_failure_status.setText("失败状态：未检测到可用 API Key，无法进行本地连通性预检。")
            return
        self.lbl_settings_ai_validation_status.setText("已验证本地配置；远端连接将在首次使用时确认")
        self.lbl_settings_ai_failure_status.setText(
            f"已验证本地配置：{provider}/{model} 的 Key 已安全保存。远端连接将在首次使用时确认。"
        )

    def _test_settings_ai_connection(self) -> None:
        """Backward-compatible alias for local-only AI configuration validation."""
        self._validate_settings_ai_configuration()

    def _restore_settings_ai_session(self) -> None:
        from ..ai_classifier import clear_provider_session_paused

        current = self._current_settings_ai_profile() or {}
        provider = str(current.get("provider") or "").strip()
        if not provider:
            return
        clear_provider_session_paused(provider)
        self._refresh_settings_ai_page()

    def _pause_settings_ai_session(self) -> None:
        from ..ai_classifier import pause_provider_session
        current = self._current_settings_ai_profile() or {}
        provider = str(current.get("provider") or "").strip()
        if provider:
            pause_provider_session(provider)
            self._refresh_settings_ai_page()

    def _disable_settings_ai(self) -> None:
        from ..ai_profiles import apply_active_ai_profile, get_ai_profiles
        current = self._current_settings_ai_profile() or {}
        profile_id = str(current.get("profile_id") or "")
        if not profile_id:
            return
        cfg = deepcopy(getattr(self, "_desktop_settings_cfg", load_config_safe()))
        profiles = [dict(item) for item in get_ai_profiles(cfg)]
        for profile in profiles:
            if profile.get("profile_id") == profile_id:
                profile["enabled"] = False
        apply_active_ai_profile(cfg, profiles)
        save_config(cfg)
        self._desktop_settings_cfg = deepcopy(cfg)
        self.config = deepcopy(cfg)
        self._refresh_settings_ai_page()

    def _build_overview_page_view(self) -> QWidget:
        page = QWidget()
        outer_layout = QVBoxLayout(page)
        DashboardPageLayout.apply(page, outer_layout)
        self.overview_content_host = QWidget(page)
        self.overview_content_host.setMaximumWidth(1360)
        self.overview_content_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(self.overview_content_host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SECTION_GAP)
        outer_layout.addWidget(self.overview_content_host, 0, Qt.AlignTop | Qt.AlignHCenter)
        outer_layout.addStretch(1)

        self.overview_header = PageHeader(
            "今日工作台",
            "先看今天的导入、待审和异常，再决定是去审核、补材料还是导出。",
        )
        layout.addWidget(self.overview_header)

        self.overview_summary_strip = SummaryStrip()
        self.overview_value_labels = {}
        for stat_key, title, state in [
            ("to_review", "待审核", "warning"),
            ("needs_fix", "缺材料", "warning"),
            ("error", "异常", "danger"),
            ("export_ready", "可导出组", "success"),
        ]:
            card = self.overview_summary_strip.add_metric(stat_key, title, "—", state=state)
            self.overview_value_labels[stat_key] = card
        layout.addWidget(self.overview_summary_strip)

        body_frame = QFrame()
        body_layout = QHBoxLayout(body_frame)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)

        left_card = SectionCard("下一步", eyebrow="今天最重要", hint="优先处理新导入和待审核发票。")
        lc_layout = left_card.body_layout
        self.lbl_overview_recent_imports = QLabel("继续审核待处理发票。")
        self.lbl_overview_recent_imports.setStyleSheet("color: #667085; font-size: 12px;")
        self.lbl_overview_recent_imports.setWordWrap(True)
        lc_layout.addWidget(self.lbl_overview_recent_imports)
        self.lbl_overview_next_actions = QLabel("系统会保留当前进度，并在处理完成后自动进入下一张。")
        self.lbl_overview_next_actions.setStyleSheet("color: #475467; font-size: 12px; line-height: 1.5;")
        self.lbl_overview_next_actions.setWordWrap(True)
        lc_layout.addWidget(self.lbl_overview_next_actions)
        btn_jump_review = make_button("开始审核", variant="primary")
        btn_jump_review.clicked.connect(lambda: self._switch_main_page("review"))
        lc_layout.addWidget(btn_jump_review)

        right_card = SectionCard("关注项", hint="只显示会阻塞审核或导出的事项。")
        rc_layout = right_card.body_layout
        self.lbl_overview_health = QLabel("当前无法读取审核队列统计，导入后会自动刷新。")
        self.lbl_overview_health.setStyleSheet("color: #4B5563; font-size: 12px; line-height: 1.5;")
        self.lbl_overview_health.setWordWrap(True)
        rc_layout.addWidget(self.lbl_overview_health)
        self.lbl_overview_export_hint = QLabel("若今天已有报销组且检查通过，可直接去“报销组与导出”打包。")
        self.lbl_overview_export_hint.setStyleSheet("color: #667085; font-size: 12px;")
        self.lbl_overview_export_hint.setWordWrap(True)
        rc_layout.addWidget(self.lbl_overview_export_hint)

        body_layout.addWidget(left_card, 3)
        body_layout.addWidget(right_card, 2)
        self.overview_state_stack = PageStateStack()
        self.overview_state_stack.set_content(body_frame)
        layout.addWidget(self.overview_state_stack, 0)
        self.overview_activity_card = SectionCard("最近活动")
        self.overview_timeline = ActivityTimeline()
        self.overview_activity_card.body_layout.addWidget(self.overview_timeline)
        layout.addWidget(self.overview_activity_card, 0)
        layout.addStretch(1)
        self._refresh_overview_page()
        return page

    def _build_imports_page_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        TaskFlowPageLayout.apply(page, layout)

        self.imports_header = PageHeader(
            "导入中心",
            "按“来源选择 → 执行任务 → 查看本次结果”完成一次导入，账号配置统一去系统设置处理。",
        )
        layout.addWidget(self.imports_header)

        shell = QHBoxLayout()
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(12)
        shell.setAlignment(Qt.AlignTop)
        shell.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.import_source_card = SectionCard("来源选择", hint="选择这次导入的来源。")
        self.import_source_card.setMinimumWidth(260)
        self.import_source_card.setMaximumWidth(300)
        self.import_source_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        source_layout = self.import_source_card.body_layout
        self.import_source_cards = {
            "mail": SelectableSourceCard("mail", "邮箱", "扫描已配置的发票邮箱。"),
            "local": SelectableSourceCard("local", "本地文件", "导入 PDF、OFD、XML 或压缩包。"),
            "mobile": SelectableSourceCard("mobile", "手机扫码", "从手机上传原件或材料。"),
        }
        for source_card in self.import_source_cards.values():
            source_card.clicked.connect(self._select_import_source)
            source_layout.addWidget(source_card)
        self._selected_import_source = "mail"
        self._set_import_source_selected("mail")
        source_layout.addStretch(1)
        shell.addWidget(self.import_source_card, 0)
        shell.setAlignment(self.import_source_card, Qt.AlignTop)

        self.import_mail_accounts_card = SectionCard("邮箱扫描", hint="选择来源、查看当前规则并执行扫描。")
        self.import_mail_accounts_card.lbl_title.setText("邮箱扫描")
        self.import_mail_accounts_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
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

        self.import_rules_detail = ReadOnlyDetailPanel("当前规则", "当前生效的扫描范围和去重策略。")
        self.lbl_import_rule_time_range = self.import_rules_detail.add_row("时间范围", "最近 3 个月增量抓取")
        self.lbl_import_rule_attachment_types = self.import_rules_detail.add_row("附件类型", "PDF / OFD / XML / 常用图片")
        self.lbl_import_rule_subject_filter = self.import_rules_detail.add_row("主题过滤", "发票 / 行程单 / 电子发票 / 账单")
        self.lbl_import_rule_duplicate = self.import_rules_detail.add_row("重复处理", "按发票代码与号码自动去重")
        self.lbl_import_rule_failure = self.import_rules_detail.add_row("失败处理", "失败记录汇总到最近结果，可直接查看失败明细")
        self.import_mail_accounts_card.body_layout.addWidget(self.import_rules_detail)

        mail_action_row = QHBoxLayout()
        mail_action_row.setContentsMargins(0, 0, 0, 0)
        mail_action_row.setSpacing(8)

        self.btn_import_scan_selected = make_button("开始扫描", variant="primary")
        self.btn_import_scan_selected.clicked.connect(self._run_import_primary_action)

        self.btn_import_scan_default = make_button("扫默认", variant="secondary")
        self.btn_import_scan_default.clicked.connect(self._scan_default_email_clicked)

        self.btn_import_scan_cancel = make_button("取消扫描", variant="secondary")
        self.btn_import_scan_cancel.setVisible(False)
        self.btn_import_scan_cancel.clicked.connect(self._cancel_email_scan_clicked)
        self.lbl_import_scan_status = QLabel("扫描状态：未开始")
        self.lbl_import_scan_status.setObjectName("importScanStatus")

        self.import_mail_more = MoreMenuButton(parent=self)
        self.import_mail_more_menu = QMenu(self.import_mail_more)
        self.import_mail_more_menu.addAction("管理邮箱", lambda: self._switch_main_page("settings", sub_tab=1))
        self.import_mail_more_menu.addAction("失败明细", self._v5_show_failed_details_dialog)
        self.import_mail_more.setMenu(self.import_mail_more_menu)

        self.import_mail_command_bar = CommandBar()
        self.import_mail_command_bar.set_actions(
            primary_action=self.btn_import_scan_selected,
            secondary_actions=[
                self.btn_import_scan_default,
                self.btn_import_scan_cancel,
            ],
            more_menu=self.import_mail_more,
        )
        self.import_mail_accounts_card.body_layout.addWidget(self.import_mail_command_bar)
        self.import_mail_accounts_card.body_layout.addWidget(self.lbl_import_scan_status)

        self.import_local_task_card = SectionCard(
            "本地导入",
            hint="选择文件或文件夹后，按当前规则完成导入。",
        )
        self.import_local_task_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.import_local_types = CompactFieldRow("支持类型", "PDF / OFD / XML / 图片 / ZIP")
        self.import_local_processing = CompactFieldRow("处理", "自动识别、自动去重，冲突项进入待审核")
        self.import_local_task_card.body_layout.addWidget(self.import_local_types)
        self.import_local_task_card.body_layout.addWidget(self.import_local_processing)
        self.btn_import_local_task = make_button("选择文件", variant="primary")
        self.btn_import_local_task.clicked.connect(self._import_local_clicked)
        self.import_local_task_card.body_layout.addWidget(self.btn_import_local_task)

        self.import_mobile_task_card = SectionCard(
            "手机扫码",
            hint="启动上传服务后，可从手机提交原件或证明材料。",
        )
        self.import_mobile_task_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.mobile_upload_controller = MobileUploadSessionController(self.db_path, self)
        self.mobile_upload_panel = MobileUploadSessionPanel(self.mobile_upload_controller)
        self.mobile_upload_controller.upload_received.connect(self._mobile_upload_finished)
        self.mobile_upload_controller.stopped.connect(self._retry_close_after_mobile_shutdown)
        self.import_mobile_task_card.body_layout.addWidget(self.mobile_upload_panel)

        self.import_task_stack = QStackedWidget()
        self.import_task_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.import_task_stack.setMaximumWidth(900)
        self._import_task_pages = {
            "mail": self.import_mail_accounts_card,
            "local": self.import_local_task_card,
            "mobile": self.import_mobile_task_card,
        }
        for task_page in self._import_task_pages.values():
            self.import_task_stack.addWidget(task_page)
        self.import_task_stack.setCurrentWidget(self.import_mail_accounts_card)
        shell.addWidget(self.import_task_stack, 1)
        shell.setAlignment(self.import_task_stack, Qt.AlignTop)

        self.import_mail_recent_card = SectionCard("本次运行", hint="显示本次启动应用后的最近 3 个导入批次。")
        self.import_mail_recent_card.setMinimumWidth(360)
        self.import_mail_recent_card.setMaximumWidth(420)
        self.import_mail_recent_card.setMaximumHeight(320)
        self.import_mail_recent_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        self.import_recent_content = QWidget()
        self.import_recent_content_layout = QVBoxLayout(self.import_recent_content)
        self.import_recent_content_layout.setContentsMargins(0, 0, 0, 0)
        self.import_recent_state_stack = PageStateStack()
        self.import_recent_state_stack.setMaximumHeight(180)
        self.import_recent_state_stack.set_empty_object_name("ImportRecentEmptyState")
        self.import_recent_timeline = ActivityTimeline()
        self.import_recent_content_layout.addWidget(self.import_recent_timeline)
        self.import_recent_state_stack.set_content(self.import_recent_content)
        self.import_mail_recent_card.body_layout.addWidget(self.import_recent_state_stack)
        shell.addWidget(self.import_mail_recent_card, 0)
        shell.setAlignment(self.import_mail_recent_card, Qt.AlignTop)

        self.imports_workspace_host = QWidget()
        self.imports_workspace_host.setMaximumWidth(1440)
        self.imports_workspace_host.setLayout(shell)
        workspace_row = QHBoxLayout()
        workspace_row.setContentsMargins(0, 0, 0, 0)
        workspace_row.addStretch(1)
        workspace_row.addWidget(self.imports_workspace_host, 1)
        workspace_row.addStretch(1)
        layout.addLayout(workspace_row, 0)
        layout.addStretch(1)
        self.imports_shell_layout = shell
        self._refresh_imports_page()
        return page

    def _build_export_page_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        TaskFlowPageLayout.apply(page, layout)

        self.export_header = PageHeader(
            "报销组与导出",
            "先选报销组，再看完整性检查；检查不过时先回到审核页或补材料。",
        )
        layout.addWidget(self.export_header)

        self.export_summary_strip = SummaryStrip()
        self.export_summary_strip.add_metric("groups", "报销组", "0", state="info")
        self.export_summary_strip.add_metric("approved", "已通过", "0", state="success")
        self.export_summary_strip.add_metric("pending", "待处理", "0", state="warning")
        self.export_summary_strip.add_metric("missing", "完整性缺口", "0", state="danger")
        self.export_summary_strip.add_metric("ready", "导出状态", "待检查", state="muted")
        layout.addWidget(self.export_summary_strip)

        shell = QHBoxLayout()
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(12)
        shell.setAlignment(Qt.AlignTop)

        self.export_group_card = SectionCard("报销组", hint="左侧按组查看发票数、金额和完整性缺口；检查会随选择更新。")
        self.export_group_card.setFixedWidth(300)
        self.export_group_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        self.export_empty_state = EmptyStateCard(
            "还没有报销组",
            "在审核页将发票加入报销组后，即可检查并导出。",
        )
        self.export_empty_state.setVisible(False)
        self.export_group_card.body_layout.addWidget(self.export_empty_state)
        self.export_group_list = EntityList()
        self.export_group_list.currentRowChanged.connect(self._sync_export_claim_selection)
        self.export_group_card.body_layout.addWidget(self.export_group_list, 1)
        self.lbl_export_scope_hint = QLabel("默认导出已通过发票；待审核发票可在导出时按提示决定是否一并打包。")
        self.lbl_export_scope_hint.setWordWrap(True)
        self.lbl_export_scope_hint.setStyleSheet("color: #667085; font-size: 12px;")
        self.export_group_card.body_layout.addWidget(self.lbl_export_scope_hint)
        shell.addWidget(self.export_group_card, 0)

        self.export_invoices_card = SectionCard("组内发票", hint="这里仅展示当前报销组内的发票队列，方便先看缺口再导出。")
        self.export_invoices_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.export_invoice_list = EntityList()
        self.export_invoices_card.body_layout.addWidget(self.export_invoice_list, 1)
        self.lbl_export_invoice_meta = QLabel("当前未选择报销组。")
        self.lbl_export_invoice_meta.setWordWrap(True)
        self.lbl_export_invoice_meta.setStyleSheet("color: #667085; font-size: 12px;")
        self.export_invoices_card.body_layout.addWidget(self.lbl_export_invoice_meta)
        shell.addWidget(self.export_invoices_card, 1)

        self.export_integrity_card = SectionCard("完整性检查与导出", hint="检查不通过时禁用导出；业务导出逻辑保持不变。")
        self.export_integrity_card.setMinimumWidth(360)
        self.export_integrity_card.setMaximumWidth(400)
        self.export_integrity_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)

        # Structured ChecklistRow preflight items (replaces long text labels)
        self.export_check_approved = ChecklistRow("已通过发票", "—")
        self.export_check_pending = ChecklistRow("待处理", "—")
        self.export_check_missing_attach = ChecklistRow("缺原件", "—")
        self.export_check_missing_amount = ChecklistRow("缺金额", "—")
        self.export_check_missing_extra = ChecklistRow("缺补充材料", "—")
        self.export_check_unavailable_extra = ChecklistRow("材料不可用", "—")
        self.export_check_dir = ChecklistRow("导出目录", "未设置")
        self.export_integrity_card.body_layout.addWidget(self.export_check_approved)
        self.export_integrity_card.body_layout.addWidget(self.export_check_pending)
        self.export_integrity_card.body_layout.addWidget(self.export_check_missing_attach)
        self.export_integrity_card.body_layout.addWidget(self.export_check_missing_amount)
        self.export_integrity_card.body_layout.addWidget(self.export_check_missing_extra)
        self.export_integrity_card.body_layout.addWidget(self.export_check_unavailable_extra)
        self.export_integrity_card.body_layout.addWidget(self.export_check_dir)

        # Keep legacy label references for backward compatibility with tests
        # that rely on lbl_export_integrity / lbl_export_blockers attributes.
        self.lbl_export_integrity = self.export_check_approved  # compat alias
        self.lbl_export_blockers = QLabel("")  # hidden; updates via _sync_export_claim_selection
        self.lbl_export_blockers.setVisible(False)

        self.lbl_export_action_hint = QLabel("未选报销组或检查未通过时，导出会保持禁用。")
        self.lbl_export_action_hint.setWordWrap(True)
        self.lbl_export_action_hint.setStyleSheet("color: #475467; font-size: 12px;")
        self.export_integrity_card.body_layout.addWidget(self.lbl_export_action_hint)
        self.btn_run_export_page = make_button("导出报销包", variant="primary", min_width=120)
        self.btn_run_export_page.clicked.connect(self._export_claim_package)
        self.export_integrity_card.body_layout.addWidget(self.btn_run_export_page)
        shell.addWidget(self.export_integrity_card, 0)

        layout.addLayout(shell, 0)
        layout.addStretch(1)
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
        SettingsPageLayout.apply(page, layout)

        self.settings_header = PageHeader(
            "系统设置",
            "设置中心默认只展示状态和当前配置；需要修改时进入单任务弹窗或专用操作。",
        )
        layout.addWidget(self.settings_header)

        self.settings_tabs = SecondaryNavStack()

        def build_info_page(title: str, hint: str, attr_name: str) -> QWidget:
            """Create a compact, actionable read-only settings page."""
            widget = QWidget()
            page_layout = QVBoxLayout(widget)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(12)
            panel = ReadOnlyDetailPanel(title, hint)
            detail = QLabel("—")
            detail.setWordWrap(True)
            detail.setProperty("class", "DetailValue")
            setattr(self, attr_name, detail)
            panel.add_row("当前状态", detail)
            page_layout.addWidget(panel)
            return widget

        runtime_tab = build_info_page("运行状态", "查看本地运行状态和诊断入口。", "lbl_settings_runtime")
        runtime_actions = CommandBar()
        runtime_actions.set_actions(
            secondary_actions=[
                make_button("打开数据目录", variant="secondary"),
                make_button("打开日志目录", variant="secondary"),
                make_button("复制诊断摘要", variant="secondary"),
            ]
        )
        runtime_actions.secondary_actions[0].clicked.connect(lambda: self._open_local_path(RUNTIME_DIR))
        runtime_actions.secondary_actions[1].clicked.connect(self._open_logs_directory)
        runtime_actions.secondary_actions[2].clicked.connect(self._copy_diagnostic_info)
        runtime_tab.layout().addWidget(runtime_actions)

        privacy_tab = build_info_page("安全与隐私", "默认本地处理；凭据由系统凭据管理器保存。", "lbl_settings_privacy")
        privacy_actions = CommandBar()
        privacy_actions.set_actions(secondary_actions=[make_button("导出脱敏诊断包", variant="secondary")])
        privacy_actions.secondary_actions[0].clicked.connect(self._export_diagnostics_package)
        privacy_tab.layout().addWidget(privacy_actions)

        data_tab = build_info_page("数据与备份", "查看数据位置并管理可安全导出的诊断信息。", "lbl_settings_data")
        data_actions = CommandBar()
        data_actions.set_actions(
            secondary_actions=[
                make_button("打开数据目录", variant="secondary"),
                make_button("打开导出目录", variant="secondary"),
                make_button("导出脱敏诊断包", variant="secondary"),
            ]
        )
        data_actions.secondary_actions[0].clicked.connect(lambda: self._open_local_path(RUNTIME_DIR))
        data_actions.secondary_actions[1].clicked.connect(self._open_exports_directory)
        data_actions.secondary_actions[2].clicked.connect(self._export_diagnostics_package)
        data_tab.layout().addWidget(data_actions)

        about_tab = build_info_page("关于", "本地优先的个人报销工作台。", "lbl_settings_about")
        about_actions = CommandBar()
        about_actions.set_actions(secondary_actions=[make_button("复制诊断摘要", variant="secondary")])
        about_actions.secondary_actions[0].clicked.connect(self._copy_diagnostic_info)
        about_tab.layout().addWidget(about_actions)

        mailbox_tab = QWidget()
        mailbox_layout = QVBoxLayout(mailbox_tab)
        mailbox_layout.setContentsMargins(0, 0, 0, 0)
        mailbox_layout.setSpacing(10)

        mailbox_title_row = QHBoxLayout()
        mailbox_title_row.setContentsMargins(0, 0, 0, 0)
        mailbox_title_row.setSpacing(8)
        mailbox_title_row.addWidget(QLabel("邮箱账户"))
        mailbox_title_row.addStretch(1)
        self.btn_settings_mailbox_add = QToolButton(mailbox_tab)
        self.btn_settings_mailbox_add.setText("新增账号")
        self.btn_settings_mailbox_add.setProperty("variant", "secondary")
        self.btn_settings_mailbox_add.setPopupMode(QToolButton.InstantPopup)
        add_menu = QMenu(self.btn_settings_mailbox_add)
        for preset_id, provider_name in (
            ("qq", "QQ 邮箱"),
            ("netease_163", "163 邮箱"),
            ("gmail", "Gmail"),
            ("outlook", "Outlook"),
            ("custom", "自定义 IMAP"),
        ):
            add_menu.addAction(provider_name, lambda _checked=False, p=preset_id: self._open_add_mailbox_dialog(preset_id=p))
        self.btn_settings_mailbox_add.setMenu(add_menu)
        mailbox_title_row.addWidget(self.btn_settings_mailbox_add)
        mailbox_layout.addLayout(mailbox_title_row)

        mailbox_shell = QHBoxLayout()
        mailbox_shell.setContentsMargins(0, 0, 0, 0)
        mailbox_shell.setSpacing(16)

        # Saved Accounts List ONLY (Requirement 4)
        self.settings_mailbox_list = EntityList()
        self.settings_mailbox_list.setFixedWidth(280)
        self.settings_mailbox_list.setMinimumHeight(280)
        self.settings_mailbox_list.currentRowChanged.connect(lambda _row: self._on_settings_mailbox_selection_changed())
        mailbox_shell.addWidget(self.settings_mailbox_list, 0)

        # Read-Only Details Panel (Requirement 5 & 6)
        mailbox_editor = QWidget()
        mailbox_editor.setMinimumWidth(560)
        mailbox_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        mailbox_editor_layout = QVBoxLayout(mailbox_editor)
        mailbox_editor_layout.setContentsMargins(0, 0, 0, 0)
        mailbox_editor_layout.setSpacing(8)

        # ── Action buttons (defined early, added to layout at the bottom) ──
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.btn_settings_mailbox_edit_config = make_button("编辑", variant="secondary")
        self.btn_settings_mailbox_edit_config.clicked.connect(self._open_edit_mailbox_dialog)

        self.btn_settings_mailbox_add_credential = make_button("补授权码", variant="secondary")
        self.btn_settings_mailbox_add_credential.clicked.connect(self._add_mailbox_credential_dialog)

        self.btn_settings_mailbox_test = make_button("测试连接", variant="secondary")
        self.btn_settings_mailbox_test.clicked.connect(self._test_settings_mailbox_connection)
        self.btn_settings_mailbox_scan = make_button("立即扫描", variant="secondary")
        self.btn_settings_mailbox_scan.clicked.connect(self._scan_settings_mailbox_now)
        self.btn_settings_mailbox_toggle = make_button("停用", variant="secondary")
        self.btn_settings_mailbox_toggle.setParent(mailbox_editor)
        self.btn_settings_mailbox_toggle.setVisible(False)
        self.btn_settings_mailbox_toggle.clicked.connect(self._toggle_settings_mailbox_enabled)

        self.btn_settings_mailbox_delete = make_button("删除", variant="danger")
        self.btn_settings_mailbox_delete.setParent(mailbox_editor)
        self.btn_settings_mailbox_delete.setVisible(False)
        self.btn_settings_mailbox_delete.clicked.connect(self._delete_settings_mailbox)

        action_row.addWidget(self.btn_settings_mailbox_add_credential)
        action_row.addWidget(self.btn_settings_mailbox_test)
        action_row.addWidget(self.btn_settings_mailbox_scan)
        action_row.addWidget(self.btn_settings_mailbox_edit_config)
        action_row.addWidget(self.btn_settings_mailbox_toggle)
        self.settings_mailbox_more = MoreMenuButton(parent=mailbox_editor)
        self.settings_mailbox_more.setToolTip("更多账号操作")
        self.settings_mailbox_more_menu = QMenu(self.settings_mailbox_more)
        self.settings_mailbox_more_update_credential = self.settings_mailbox_more_menu.addAction("更新授权码", self._add_mailbox_credential_dialog)
        self.settings_mailbox_more_menu.addSeparator()
        self.settings_mailbox_more_toggle = self.settings_mailbox_more_menu.addAction(self.btn_settings_mailbox_toggle.text(), self._toggle_settings_mailbox_enabled)
        self.settings_mailbox_more_menu.addSeparator()
        self.settings_mailbox_more_delete = self.settings_mailbox_more_menu.addAction("删除", self._delete_settings_mailbox)
        self.settings_mailbox_more.setMenu(self.settings_mailbox_more_menu)
        action_row.addWidget(self.settings_mailbox_more)
        action_row.addStretch(1)

        # ── Single detail surface: sections are headings + field rows, not nested cards ──
        self.mailbox_detail_surface = QFrame(mailbox_editor)
        self.mailbox_detail_surface.setObjectName("MailboxDetailSurface")
        self.mailbox_detail_surface.setProperty("class", "MailboxDetailSurface")
        surface_layout = QVBoxLayout(self.mailbox_detail_surface)
        surface_layout.setContentsMargins(16, 14, 16, 14)
        surface_layout.setSpacing(10)

        def add_detail_section(title: str, rows: list[tuple[str, QWidget]]):
            if surface_layout.count():
                divider = QFrame(self.mailbox_detail_surface)
                divider.setFrameShape(QFrame.HLine)
                divider.setProperty("class", "SectionDivider")
                surface_layout.addWidget(divider)
            heading = QLabel(title, self.mailbox_detail_surface)
            heading.setProperty("class", "SectionTitle")
            surface_layout.addWidget(heading)
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(8)
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            for key, value in rows:
                form.addRow(key, value)
                label = form.labelForField(value)
                if label is not None:
                    label.setMinimumWidth(104)
                    label.setProperty("class", "DetailFieldKey")
            surface_layout.addLayout(form)

        self.mailbox_detail_surface_layout = surface_layout

        # Account header
        self.lbl_detail_header_name = ElidedTextLabel("未选择邮箱账号", self.mailbox_detail_surface)
        self.lbl_detail_header_email = ElidedTextLabel("—", self.mailbox_detail_surface)
        self.lbl_detail_header_status = QLabel("未配置", self.mailbox_detail_surface)
        for label in (self.lbl_detail_header_name, self.lbl_detail_header_email):
            label.setToolTip(label.text())
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)
        header_layout.addWidget(self.lbl_detail_header_name)
        header_layout.addWidget(self.lbl_detail_header_email)
        header_layout.addWidget(self.lbl_detail_header_status)
        surface_layout.addLayout(header_layout)

        self.lbl_detail_name = ElidedTextLabel("未选择邮箱账号", self.mailbox_detail_surface)
        # ElidedTextLabel for long names/addresses/server strings that must not wrap
        self.lbl_detail_email = ElidedTextLabel("—", self.mailbox_detail_surface)
        self.lbl_detail_server = ElidedTextLabel("—", self.mailbox_detail_surface)
        self.lbl_detail_port_security = ElidedTextLabel("—", self.mailbox_detail_surface)
        self.lbl_detail_is_default = QLabel("—", self.mailbox_detail_surface)
        self.lbl_detail_credential_status = QLabel("未配置", self.mailbox_detail_surface)
        self.lbl_detail_scan_folder = ElidedTextLabel("—", self.mailbox_detail_surface)
        self.lbl_detail_scan_range = ElidedTextLabel("—", self.mailbox_detail_surface)
        self.lbl_detail_attachment_types = ElidedTextLabel("PDF / OFD / XML / 图片", self.mailbox_detail_surface)
        self.lbl_detail_scan_rule = self.lbl_detail_scan_range  # compatibility alias
        for label in (
            self.lbl_detail_is_default,
            self.lbl_detail_credential_status,
            self.lbl_detail_scan_rule,
        ):
            label.setWordWrap(True)
            label.setObjectName("MailboxDetailValue")
        for label in (self.lbl_detail_name, self.lbl_detail_email, self.lbl_detail_server):
            label.setObjectName("MailboxDetailValue")
        add_detail_section("基本信息", [("邮箱名称", self.lbl_detail_name), ("邮箱地址", self.lbl_detail_email), ("默认账号", self.lbl_detail_is_default)])
        add_detail_section("连接与授权", [("IMAP", self.lbl_detail_server), ("端口与安全", self.lbl_detail_port_security), ("授权状态", self.lbl_detail_credential_status)])
        add_detail_section("扫描规则", [("文件夹", self.lbl_detail_scan_folder), ("时间范围", self.lbl_detail_scan_range), ("附件类型", self.lbl_detail_attachment_types)])
        # Status labels: value-only, no repeated field-name prefix
        self.lbl_settings_mailbox_test_status = QLabel("尚未执行。")
        self.lbl_settings_mailbox_test_status.setWordWrap(True)
        self.lbl_settings_mailbox_test_status.setStyleSheet("color: #667085; font-size: 12px;")
        self.lbl_settings_mailbox_scan_result = QLabel("暂无记录。")
        self.lbl_settings_mailbox_scan_result.setWordWrap(True)
        self.lbl_settings_mailbox_scan_result.setStyleSheet("color: #667085; font-size: 12px;")
        self.lbl_settings_mailbox_empty = QLabel("尚未配置任何邮箱账号。")
        self.lbl_settings_mailbox_empty.setStyleSheet("color: #667085; font-size: 12px;")
        self.settings_mailbox_empty_state = EmptyStateCard(
            "还没有邮箱账号",
            "添加一个邮箱账号后即可扫描发票。",
        )
        self.settings_mailbox_empty_state.setVisible(False)
        self.lbl_settings_mailbox_empty.setVisible(False)
        add_detail_section("最近运行", [("连接测试", self.lbl_settings_mailbox_test_status), ("最近扫描", self.lbl_settings_mailbox_scan_result)])
        mailbox_editor_layout.addWidget(self.lbl_settings_mailbox_empty)
        mailbox_editor_layout.addWidget(self.settings_mailbox_empty_state)
        mailbox_editor_layout.addWidget(self.mailbox_detail_surface, 1)
        # ── Action footer: placed after all detail sections ──
        mailbox_editor_layout.addLayout(action_row)
        mailbox_shell.addWidget(mailbox_editor, 1)
        mailbox_layout.addLayout(mailbox_shell, 1)

        ai_tab = QWidget()
        ai_layout = QVBoxLayout(ai_tab)
        ai_layout.setContentsMargins(0, 0, 0, 0)
        ai_layout.setSpacing(10)
        # One active profile is supported today. Keep the list only as a hidden
        # compatibility data source, never as a second visible surface.
        self.settings_ai_profile_list = EntityList(ai_tab)
        self.settings_ai_profile_list.setVisible(False)
        self.settings_ai_profile_list.currentRowChanged.connect(lambda _row: self._on_settings_ai_profile_selection_changed())
        ai_editor = QWidget()
        ai_editor_layout = QVBoxLayout(ai_editor)
        ai_editor_layout.setContentsMargins(0, 0, 0, 0)
        ai_editor_layout.setSpacing(8)
        self.settings_ai_detail_panel = ReadOnlyDetailPanel(
            "AI 配置详情",
            hint="默认只读展示 Provider、模型、Key 健康和会话状态；编辑配置统一进入单任务弹窗。",
        )
        self.lbl_settings_ai_provider = self.settings_ai_detail_panel.add_row("Provider", "—")
        self.lbl_settings_ai_model = self.settings_ai_detail_panel.add_row("模型", "—")
        self.lbl_settings_ai_enabled = self.settings_ai_detail_panel.add_row("启用状态", "关闭")
        self.lbl_settings_ai_session_state = self.settings_ai_detail_panel.add_row("会话状态", "无可用会话")
        self.lbl_settings_ai_key_status = self.settings_ai_detail_panel.add_row("Key 来源", "API Key 状态：未配置")
        self.lbl_settings_ai_validation_status = self.settings_ai_detail_panel.add_row("最近校验", "尚未校验本地配置")
        self.lbl_settings_ai_send_boundary = self.settings_ai_detail_panel.add_row(
            "隐私边界",
            "仅发送脱敏邮件头与最小分类元数据，不发送正文、附件、PDF、图片和本地路径。",
        )
        self.lbl_settings_ai_log_redaction = self.settings_ai_detail_panel.add_row(
            "日志脱敏",
            "Key 与授权码不会写入 config.json，也不会原样出现在日志。",
        )
        ai_editor_layout.addWidget(self.settings_ai_detail_panel)
        ai_btn_row = QHBoxLayout()
        ai_btn_row.setContentsMargins(0, 0, 0, 0)
        ai_btn_row.setSpacing(8)
        self.btn_settings_ai_edit = make_button("编辑配置", variant="secondary")
        self.btn_settings_ai_edit.clicked.connect(self._open_edit_ai_profile_dialog)
        self.btn_settings_ai_configure_key = make_button("更新 Key", variant="secondary")
        self.btn_settings_ai_configure_key.clicked.connect(self._configure_settings_ai_key)
        self.btn_settings_ai_test = make_button("校验配置", variant="secondary")
        self.btn_settings_ai_test.setToolTip("仅校验本地 Provider、模型和 API Key 配置；远端连接将在首次使用时确认。")
        self.btn_settings_ai_test.clicked.connect(self._validate_settings_ai_configuration)
        self.btn_settings_ai_clear_key = make_button("清除 Key", variant="secondary")
        self.btn_settings_ai_clear_key.setParent(ai_editor)
        self.btn_settings_ai_clear_key.setVisible(False)
        self.btn_settings_ai_clear_key.clicked.connect(self._clear_settings_ai_key)
        self.btn_settings_ai_restore_session = make_button("恢复会话", variant="secondary")
        self.btn_settings_ai_restore_session.setParent(ai_editor)
        self.btn_settings_ai_restore_session.setVisible(False)
        self.btn_settings_ai_restore_session.clicked.connect(self._restore_settings_ai_session)
        ai_btn_row.addWidget(self.btn_settings_ai_edit)
        ai_btn_row.addWidget(self.btn_settings_ai_configure_key)
        ai_btn_row.addWidget(self.btn_settings_ai_test)
        self.settings_ai_more = MoreMenuButton(parent=ai_editor)
        self.settings_ai_more.setToolTip("更多 AI 操作")
        self.settings_ai_more_menu = QMenu(self.settings_ai_more)
        self.settings_ai_more_menu.addAction("恢复会话", self._restore_settings_ai_session)
        self.settings_ai_more_menu.addAction("暂停当前会话", self._pause_settings_ai_session)
        self.settings_ai_more_menu.addAction("禁用 AI", self._disable_settings_ai)
        self.settings_ai_more_menu.addSeparator()
        self.settings_ai_more_menu.addAction("清除 Key", self._clear_settings_ai_key)
        self.settings_ai_more.setMenu(self.settings_ai_more_menu)
        ai_btn_row.addWidget(self.settings_ai_more)
        ai_btn_row.addStretch(1)
        ai_editor_layout.addLayout(ai_btn_row)
        self.lbl_settings_ai_failure_status = QLabel("失败状态：暂无异常。")
        self.lbl_settings_ai_failure_status.setWordWrap(True)
        self.lbl_settings_ai_failure_status.setStyleSheet("color: #667085; font-size: 12px;")
        self.lbl_settings_ai_empty = QLabel("尚未配置任何 AI Profile。")
        self.lbl_settings_ai_empty.setStyleSheet("color: #667085; font-size: 12px;")
        self.settings_ai_empty_state = EmptyStateCard(
            "还没有 AI Profile",
            "配置 Provider 后即可查看 AI 提取与分类状态。",
        )
        self.settings_ai_empty_state.setVisible(False)
        self.lbl_settings_ai_empty.setVisible(False)
        ai_editor_layout.addWidget(self.lbl_settings_ai_failure_status)
        ai_editor_layout.addWidget(self.lbl_settings_ai_empty)
        ai_editor_layout.addWidget(self.settings_ai_empty_state)
        ai_layout.addWidget(ai_editor)
        ai_layout.addStretch(1)

        self.settings_tabs.addTab(mailbox_tab, "邮箱账户")
        self.settings_tabs.addTab(ai_tab, "AI 配置")
        self.settings_tabs.addTab(runtime_tab, "运行状态")
        self.settings_tabs.addTab(privacy_tab, "安全与隐私")
        self.settings_tabs.addTab(data_tab, "数据与备份")
        self.settings_tabs.addTab(about_tab, "关于")

        self.settings_tabs.setMaximumWidth(1120)
        settings_row = QHBoxLayout()
        settings_row.setContentsMargins(0, 0, 0, 0)
        settings_row.addStretch(1)
        settings_row.addWidget(self.settings_tabs, 1, Qt.AlignTop)
        settings_row.addStretch(1)
        layout.addLayout(settings_row, 0)
        layout.addStretch(1)
        self._refresh_settings_page()
        return page

    def _clear_log_text(self):
        if hasattr(self, "txt_log") and self.txt_log is not None:
            self.txt_log.clear()

    def _sync_export_claim_selection(self) -> None:
        if not hasattr(self, "export_group_list"):
            return
        if not getattr(self, "db", None) or not getattr(self.db, "is_open", False):
            return
        current_item = self.export_group_list.currentItem()
        claim_id = current_item.data(Qt.UserRole) if current_item is not None else None
        if claim_id is None:
            self.export_summary_strip.set_metric("ready", "待检查")
            # Reset ChecklistRows to neutral
            if hasattr(self, "export_check_approved"):
                self.export_check_approved.set_value("—", None)
                self.export_check_pending.set_value("—", None)
                self.export_check_missing_attach.set_value("—", None)
                self.export_check_missing_amount.set_value("—", None)
                self.export_check_missing_extra.set_value("—", None)
                self.export_check_unavailable_extra.set_value("—", None)
                self.export_check_dir.set_value("—", None)
            if hasattr(self, "lbl_export_action_hint"):
                self.lbl_export_action_hint.setText("先选左侧报销组，再确认组内发票和完整性检查。")
            if hasattr(self, "export_invoice_list"):
                self.export_invoice_list.clear()
                self.lbl_export_invoice_meta.setText("当前未选择报销组。")
            self.btn_run_export_page.setEnabled(False)
            return
        if hasattr(self, "combo_claims"):
            idx = self.combo_claims.findData(claim_id)
            if idx >= 0 and self.combo_claims.currentIndex() != idx:
                self.combo_claims.setCurrentIndex(idx)
        stats = self._claim_export_preflight_stats(claim_id)
        approved_stats = self._claim_export_preflight_stats(
            claim_id,
            include_to_review=False,
        )
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

        approved_cnt = int(stats.get(APPROVED, 0) or 0)
        pending_cnt = int(stats.get(TO_REVIEW, 0) or 0)
        missing_attach = int(stats.get("missing_attachment", 0) or 0)
        missing_amount = int(stats.get("missing_amount", 0) or 0)
        missing_extra = int(stats.get("missing_extra", 0) or 0)
        unavailable_extra = int(stats.get("unavailable_extra", 0) or 0)

        # Export directory check
        export_dir = getattr(self, "_export_dir", None) or resolve_export_directory(self.config)
        dir_ok = True

        blockers = []
        if int(approved_stats.get(APPROVED, 0) or 0) <= 0:
            blockers.append("没有已通过发票")
        approved_missing_attach = int(approved_stats.get("missing_attachment", 0) or 0)
        approved_missing_amount = int(approved_stats.get("missing_amount", 0) or 0)
        approved_missing_extra = int(approved_stats.get("missing_extra", 0) or 0)
        approved_unavailable_extra = int(approved_stats.get("unavailable_extra", 0) or 0)
        if approved_missing_attach > 0:
            blockers.append(f"缺原件 {approved_missing_attach} 张")
        if approved_missing_amount > 0:
            blockers.append(f"缺金额 {approved_missing_amount} 张")
        if approved_missing_extra > 0:
            blockers.append(f"缺补充材料 {approved_missing_extra} 张")
        if approved_unavailable_extra > 0:
            blockers.append(f"材料不可用 {approved_unavailable_extra} 张")

        is_ready = not blockers and dir_ok

        # Update ChecklistRows
        if hasattr(self, "export_check_approved"):
            self.export_check_approved.set_value(f"{approved_cnt} 张", ok=approved_cnt > 0)
            self.export_check_pending.set_value(f"{pending_cnt} 张", ok=pending_cnt == 0)
            self.export_check_missing_attach.set_value(
                "无" if missing_attach == 0 else f"{missing_attach} 张",
                ok=missing_attach == 0,
            )
            self.export_check_missing_amount.set_value(
                "无" if missing_amount == 0 else f"{missing_amount} 张",
                ok=missing_amount == 0,
            )
            self.export_check_missing_extra.set_value(
                "无" if missing_extra == 0 else f"{missing_extra} 张",
                ok=missing_extra == 0,
            )
            self.export_check_unavailable_extra.set_value(
                "无" if unavailable_extra == 0 else f"{unavailable_extra} 张",
                ok=unavailable_extra == 0,
            )
            self.export_check_dir.set_value(
                str(export_dir) if dir_ok else "未设置", ok=dir_ok
            )

        self.export_summary_strip.set_metric("ready", "可导出" if is_ready else "需处理")
        if hasattr(self, "lbl_export_action_hint"):
            if is_ready:
                pending_scope_issues = (
                    missing_attach
                    + missing_amount
                    + missing_extra
                    + unavailable_extra
                    - approved_missing_attach
                    - approved_missing_amount
                    - approved_missing_extra
                    - approved_unavailable_extra
                )
                if pending_scope_issues > 0:
                    self.lbl_export_action_hint.setText(
                        "已通过发票可导出；若包含待处理发票，将按所选范围再次检查材料。"
                    )
                else:
                    self.lbl_export_action_hint.setText("导出会沿用现有业务逻辑；当前报销组已可直接导出。")
            else:
                self.lbl_export_action_hint.setText(
                    "阻塞：" + "；".join(blockers) if blockers else "请先设置导出目录。"
                )
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
                # Do not rely solely on QButtonGroup's auto-exclusive timing:
                # page switches can be triggered programmatically while a
                # mouse click is still being delivered. Explicitly clear the
                # other selectable entries so the sidebar always has exactly
                # one active page.
                for key, candidate in self.workbench_nav_buttons.items():
                    if key != page_key and candidate.isCheckable():
                        candidate.setChecked(False)
                btn.setChecked(True)
                # A mouse click can leave focus on the button even when the
                # navigation rail is collapsed. The checked state is the page
                # indicator there, so clear the transient focus ring.
                btn.clearFocus()

        if page_key == "overview":
            self._refresh_overview_page()
        elif page_key == "imports":
            self._refresh_imports_page()
        elif page_key == "export":
            self._refresh_export_page()
        elif page_key == "settings":
            self._refresh_settings_page()

        if page_key == "settings" and hasattr(self, "settings_tabs") and self.settings_tabs is not None:
            # Legacy numeric targets came from the old SettingsDialog. Preserve
            # their intent while exposing only real in-window setting pages.
            legacy_targets = {0: 0, 1: 0, 2: 1, 5: 4, 6: 5}
            self.settings_tabs.setCurrentIndex(legacy_targets.get(sub_tab, 0))



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
        paging = getattr(self, "review_paging", None)
        if paging is not None and not getattr(self, "_paging_append_in_progress", False):
            self._paging_append_in_progress = True
            try:
                return paging.append_next_batch()
            finally:
                self._paging_append_in_progress = False
        return self._append_next_invoice_batch_impl()

    def _append_next_invoice_batch_impl(self):
        selected_id = None
        selected_row = self.table.currentRow() if hasattr(self, "table") else -1
        advance_to_next_row = selected_row == len(getattr(self, "invoices_list", []) or []) - 1
        if 0 <= selected_row < len(getattr(self, "invoices_list", []) or []):
            selected_id = self.invoices_list[selected_row].get("id")
        try:
            if not hasattr(self, "db") or self.db is None:
                return
            current_count = len(getattr(self, "invoices_list", []) or [])
            total = int(getattr(self, "_record_total_matching", current_count) or current_count)
            self._review_page_limit = min(total, max(50, current_count + 50))
            self._limited_first_load_active = False
            self._is_first_load = False
            self._load_invoices()
            target_row = selected_row + 1 if advance_to_next_row else -1
            if target_row < 0 and selected_id is not None:
                target_row = next((row for row, invoice in enumerate(self.invoices_list) if invoice.get("id") == selected_id), -1)
            if 0 <= target_row < len(self.invoices_list):
                self._ensure_single_row_selection(target_row)
        finally:
            self._is_loading_more_invoices = False
            self._update_record_header_summary()

    def _update_record_header_summary(self, total_matching: int | None = None, selected_count: int | None = None):
        if total_matching is not None:
            self._record_total_matching = max(0, int(total_matching))
        state = self._review_view_state(total_matching=total_matching, selected_count=selected_count)
        if hasattr(self, "lbl_record_count"):
            if state.visible_count == 0 and (state.search_text or state.active_filter != "all"):
                count_text = "当前筛选 0 张"
            elif state.loaded_count < state.query_total:
                count_text = f"已加载 {state.loaded_count} / 共 {state.query_total} 张"
            else:
                count_text = f"当前筛选 {state.visible_count} 张"
            self.lbl_record_count.setText(count_text)
        if selected_count is not None and hasattr(self, "lbl_record_selection"):
            self.lbl_record_selection.setText("未选" if state.selected_count <= 0 else f"已选 {state.selected_count} 张")

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
        # Every review surface must evaluate against the same in-memory
        # profile. Reloading from disk here made the table and detail warning
        # disagree until an unrelated selection event refreshed the panel.
        cfg = getattr(self, "config", None) or load_config_safe()
        return buyer_warning(inv, cfg)

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
        if is_default_view and self.current_filter_status is None:
            limit_val = max(50, int(getattr(self, "_review_page_limit", 50))) if hasattr(self, "_review_page_limit") else (50 if self._is_first_load else None)

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
        if (self._limited_first_load_active or (self._is_first_load and total_matching > 50 and not getattr(self, "_column_filters_load_all", False))) and total_matching > 50:
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
                f"滚动到底部或在最后一行按 ↓ 自动加载下一批，也可使用搜索/筛选缩小范围。"
            )
            self._first_load_notice = notice
            self.write_log(f"ℹ️ [首屏提示] {notice}")
        else:
            self._limited_first_load_active = False
            self._limited_first_load_total = 0
            self._first_load_notice = None

        self._update_record_header_summary(total_matching=total_matching)

        # Show/hide the load-all button
        if getattr(self, "btn_load_all", None) is not None:
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
            self._set_right_panel_state(False)
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
        self._update_record_header_summary(total_matching=total_matching)
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
            if hasattr(self._detail_panel, "lbl_claim_assignment"):
                self._detail_panel.lbl_claim_assignment.set_value("未关联报销组")
                self._detail_panel.btn_claim_assignment.setText("选择")
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
            if hasattr(self._detail_panel, "lbl_claim_assignment"):
                self._detail_panel.lbl_claim_assignment.set_value("未关联报销组")
                self._detail_panel.btn_claim_assignment.setText("选择")
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
        if hasattr(self._detail_panel, "lbl_claim_assignment"):
            self._detail_panel.lbl_claim_assignment.set_value(group_name)
            self._detail_panel.btn_claim_assignment.setText("更换")

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
        self._set_right_panel_state(False)
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
            self._on_table_selection_changed()
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

            self.db.update_invoice_file_paths(inv_id, extra_paths=extra_paths)
            self.db.update_invoice_extra_flags(
                inv_id,
                has_extra=True,
                missing_extra=False,
            )

            extra_paths_str = json.dumps(extra_paths, ensure_ascii=False)

            # Update memory state
            self.current_invoice["extra_paths"] = extra_paths_str
            self.current_invoice["has_extra"] = 1
            self.current_invoice["missing_extra"] = 0

            # Refresh GUI and preview
            self._on_table_selection_changed()
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
            self._on_table_selection_changed()
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
        exports_dir = getattr(self, "_export_dir", None) or resolve_export_directory(self.config)
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
                self._ensure_single_row_selection(current_row)
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
                            self._ensure_single_row_selection(candidate_row)
                            self.current_invoice = candidate
                            self._invoice_snapshot = self._get_invoice_snapshot(candidate)
                            break
                    else:
                        if next_select_row < 0:
                            next_select_row = 0
                        elif next_select_row >= num_rows:
                            next_select_row = num_rows - 1
                        self._ensure_single_row_selection(next_select_row)
                        self.current_invoice = self.invoices_list[next_select_row]
                        self._invoice_snapshot = self._get_invoice_snapshot(self.current_invoice)
                else:
                    if next_select_row < 0:
                        next_select_row = 0
                    elif next_select_row >= num_rows:
                        next_select_row = num_rows - 1
                    self._ensure_single_row_selection(next_select_row)
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

    def _claim_export_preflight_stats(
        self,
        claim_id: int,
        *,
        include_to_review: bool = True,
    ) -> dict:
        return self._claim_export_preflight_stats_for_range(
            claim_id,
            include_to_review=include_to_review,
        )

    def _claim_export_preflight_stats_for_range(
        self,
        claim_id: int,
        *,
        include_to_review: bool,
    ) -> dict:
        """Calculate preflight stats for the selected export status range."""
        from ..claim_export import summarize_extra_material_issues

        invoices = self.db.get_claim_invoices(claim_id)
        material_statuses = {APPROVED}
        if include_to_review:
            material_statuses.add(TO_REVIEW)
        stats = {
            APPROVED: 0,
            TO_REVIEW: 0,
            IGNORED: 0,
            ERROR: 0,
            "missing_attachment": 0,
            "missing_amount": 0,
            "missing_extra": 0,
            "unavailable_extra": 0,
        }
        material_invoices = []
        for inv in invoices:
            if is_pending_evidence_invoice(inv):
                continue
            status = inv.get("review_status") or TO_REVIEW
            if status in (APPROVED, TO_REVIEW, IGNORED, ERROR):
                stats[status] += 1
            if status in material_statuses:
                material_invoices.append(inv)
                if not str(inv.get("attachment_path") or "").strip():
                    stats["missing_attachment"] += 1
                if not str(inv.get("total_amount") or "").strip():
                    stats["missing_amount"] += 1
        stats.update(summarize_extra_material_issues(material_invoices, RUNTIME_DIR))
        return stats

    def _format_claim_export_preflight_text(self, stats: dict) -> str:
        return (
            "导出检查\n"
            f"已通过发票：{stats.get(APPROVED, 0)} 张\n"
            f"待处理：{stats.get(TO_REVIEW, 0)} 张\n"
            f"缺原件：{stats.get('missing_attachment', 0)} 张\n"
            f"缺金额：{stats.get('missing_amount', 0)} 张\n"
            f"缺补充材料：{stats.get('missing_extra', 0)} 张\n"
            f"材料不可用：{stats.get('unavailable_extra', 0)} 张\n"
            "已忽略和异常发票不会进入报销包。"
        )

    def _claim_export_material_blocker_text(self, stats: dict) -> str:
        blockers = []
        missing_extra = int(stats.get("missing_extra", 0) or 0)
        unavailable_extra = int(stats.get("unavailable_extra", 0) or 0)
        if missing_extra:
            blockers.append(f"缺补充材料 {missing_extra} 张")
        if unavailable_extra:
            blockers.append(f"补充材料不可用 {unavailable_extra} 张")
        if not blockers:
            return ""
        return "导出已阻断：" + "；".join(blockers) + "。请补齐材料后重试。"

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
        selected_stats = self._claim_export_preflight_stats(
            claim_id,
            include_to_review=include_to_review,
        )
        material_blocker = self._claim_export_material_blocker_text(selected_stats)
        if material_blocker:
            QMessageBox.warning(self, "导出已阻断", material_blocker)
            return

        self._set_action_busy(self.btn_toolbar_export, "导出中...")
        try:
            # Trigger standard package exporter
            from ..claim_export import export_claim_package
            cfg = load_config_safe()
            configured_export_dir = getattr(self, "_export_dir", None) or resolve_export_directory(cfg)
            export_dir = export_claim_package(
                db=self.db,
                claim_id=claim_id,
                project_root=PROJECT_ROOT,
                runtime_dir=RUNTIME_DIR,
                include_to_review=include_to_review,
                reimbursement_config=cfg.get("reimbursement", {}),
                export_root=Path(configured_export_dir),
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
                relative_export_dir = Path(export_dir).relative_to(Path(configured_export_dir)).as_posix()
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
            self._switch_main_page("settings", sub_tab=1)
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
            self._switch_main_page("settings", sub_tab=1)
            return

        active_btn = trigger_btn or getattr(self, "btn_scan_email", None)
        self.write_log("📥 [邮箱扫描] 增量拉取任务已启动...")
        self.statusBar().showMessage("正在建立邮箱连接并扫描接收邮件...")
        self._scan_started_at = time.monotonic()
        self._scan_stage_display = "准备连接"
        self._scan_stage_counts = {}
        if hasattr(self, "lbl_import_scan_status"):
            self.lbl_import_scan_status.setText("扫描状态：准备连接（已耗时 0 秒）")
        if hasattr(self, "btn_import_scan_cancel"):
            self.btn_import_scan_cancel.setVisible(True)
            self.btn_import_scan_cancel.setEnabled(True)
        if hasattr(self, "_scan_elapsed_timer"):
            self._scan_elapsed_timer.start(500)
        if active_btn:
            self._set_action_busy(active_btn, "扫描中...")

        # Spawn asynchronous thread worker
        self.scan_worker = EmailScanWorker(self.db_path, selected_keys=selected_keys)
        self.scan_worker._trigger_btn = active_btn
        self.scan_worker.log.connect(
            lambda text: self.write_log(text, mirror_to_file=False)
        )
        self.scan_worker.stage.connect(self._scan_stage_updated)
        self.scan_worker.finished.connect(self._scan_email_finished)
        self.scan_worker.error.connect(self._scan_email_error)
        self.scan_worker.start()

    def _scan_stage_updated(self, event: dict):
        if not isinstance(event, dict):
            return
        labels = {
            "connect": "连接",
            "tls": "TLS 握手",
            "authenticate": "认证",
            "query": "查询",
            "download": "下载",
            "parse": "解析",
            "save": "保存",
            "complete": "完成",
            "failed": "失败",
            "cancelled": "已取消",
        }
        stage_name = labels.get(str(event.get("stage") or ""), str(event.get("stage") or "处理中"))
        elapsed = int(event.get("elapsed_ms") or 0) / 1000
        counts = event.get("counts") or {}
        self._scan_stage_display = stage_name
        self._scan_stage_counts = dict(counts)
        count_text = ""
        if counts:
            count_text = " · " + ", ".join(f"{k}={v}" for k, v in counts.items())
        text = f"扫描状态：{stage_name}（已耗时 {elapsed:.1f} 秒{count_text}）"
        if hasattr(self, "lbl_import_scan_status"):
            self.lbl_import_scan_status.setText(text)
        self.statusBar().showMessage(text, 2500)

    def _refresh_scan_elapsed(self):
        if not getattr(self, "_scan_started_at", None):
            return
        elapsed = time.monotonic() - self._scan_started_at
        count_text = ""
        if self._scan_stage_counts:
            count_text = " · " + ", ".join(
                f"{k}={v}" for k, v in self._scan_stage_counts.items()
            )
        text = f"扫描状态：{self._scan_stage_display}（已耗时 {elapsed:.1f} 秒{count_text}）"
        if hasattr(self, "lbl_import_scan_status"):
            self.lbl_import_scan_status.setText(text)

    def _cancel_email_scan_clicked(self):
        worker = getattr(self, "scan_worker", None)
        if worker is None or not worker.isRunning():
            return
        self.btn_import_scan_cancel.setEnabled(False)
        self.btn_import_scan_cancel.setText("正在取消…")
        self.statusBar().showMessage("正在关闭邮箱连接并取消扫描…", 4000)
        worker.request_cancel()

    def _finish_scan_ui(self, cancelled: bool = False):
        worker = getattr(self, "scan_worker", None)
        btn = getattr(worker, "_trigger_btn", None) if worker else None
        if btn:
            orig_text = btn.property("original_text") or (
                "开始扫描" if btn is getattr(self, "btn_import_scan_selected", None)
                else ("默认" if btn is getattr(self, "btn_import_scan_default", None) else "同步")
            )
            self._clear_action_busy(btn, orig_text)
        if hasattr(self, "btn_import_scan_selected"):
            self.btn_import_scan_selected.setEnabled(True)
        if hasattr(self, "btn_import_scan_default"):
            self.btn_import_scan_default.setEnabled(True)
        if hasattr(self, "_scan_elapsed_timer"):
            self._scan_elapsed_timer.stop()
        if hasattr(self, "btn_import_scan_cancel"):
            self.btn_import_scan_cancel.setVisible(False)
            self.btn_import_scan_cancel.setEnabled(False)
            self.btn_import_scan_cancel.setText("取消扫描")
        if cancelled and hasattr(self, "lbl_import_scan_status"):
            elapsed = time.monotonic() - getattr(self, "_scan_started_at", time.monotonic())
            self.lbl_import_scan_status.setText(f"扫描状态：已取消（耗时 {elapsed:.1f} 秒）")

    def _scan_email_finished(self, res: dict):
        cancelled = bool(isinstance(res, dict) and res.get("cancelled"))
        self._finish_scan_ui(cancelled=cancelled)
        if cancelled:
            self.write_log("⏹ [邮箱扫描] 用户已取消，当前邮箱事务保持一致，未开始后续邮箱。")
            self.statusBar().showMessage("邮箱扫描已取消", 4000)
            return
        btn = getattr(self.scan_worker, "_trigger_btn", None) or getattr(self, "btn_scan_email", None)
        if btn:
            orig_text = btn.property("original_text") or ("开始扫描" if btn is getattr(self, "btn_import_scan_selected", None) else ("默认" if btn is getattr(self, "btn_import_scan_default", None) else "同步"))
            self._clear_action_busy(btn, orig_text)
        summary = self._build_scan_summary(res, getattr(self.scan_worker, "summary_logs", []))
        self._last_scan_summary = summary
        self._record_import_activity(
            "mail",
            scanned=summary.get("scanned") or summary.get("scanned_headers") or 0,
            added=summary.get("new") or summary.get("new_email_headers") or 0,
            duplicates=summary.get("duplicates") or 0,
            failed=(
                int(summary.get("download_failed", 0) or 0)
                + int(summary.get("parse_failed", 0) or 0)
                + int(summary.get("link_failed", 0) or 0)
            ),
        )
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
        self._finish_scan_ui(cancelled=False)
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
        if active_btn is None or not hasattr(active_btn, "property"):
            return
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
        self._switch_main_page("imports")
        self._set_import_source_selected("mobile")

    def _mobile_upload_finished(self, result: dict):
        added = int(result.get("imported", result.get("added", 0)) or 0)
        duplicates = int(result.get("duplicate", result.get("duplicates", 0)) or 0)
        failed = int(result.get("failed", 0) or 0)
        scanned = int(result.get("accepted", 0) or 0) + duplicates + failed
        if added or duplicates or failed:
            self._record_import_activity(
                "mobile", scanned=scanned, added=added,
                duplicates=duplicates, failed=failed,
                batch_id=str(result.get("batch_id") or ""),
            )
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
        self._record_import_activity(
            "local",
            added=added,
            duplicates=duplicates,
            failed=failed,
        )
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
        """Deprecated compatibility proxy for the former modal settings center.

        The in-window settings page is the single authoritative surface.  Keep
        this method for old callbacks only; it must never create SettingsDialog.
        """
        self._switch_main_page("settings", sub_tab=sub_tab)


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
