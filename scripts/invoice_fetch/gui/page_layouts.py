"""Shared page archetype contracts for the desktop product surfaces."""

import weakref
from collections.abc import Callable
from functools import wraps
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLayout, QSizePolicy, QWidget
from shiboken6 import isValid

from ..export_paths import normalize_export_date_prefix, resolve_export_directory
from ..review_status import APPROVED

from .styles import apply_global_design_baseline
from .design_system_v11 import apply_design_system_v11
from .design_tokens import DESIGN_V1_METRICS
from .hci_v1 import (
    schedule_dashboard_hci_closure,
    schedule_dashboard_hci_v1,
    schedule_task_flow_hci_closure,
    schedule_task_flow_hci_v1,
)
from .review_layout import schedule_review_baseline_pipeline
from .review_queue_semantics import schedule_task_flow_review_scope_semantics
from .review_settings_issue_fixes import apply_settings_action_clarity
from .selection_surfaces import schedule_selection_surface_contracts
from .settings_baseline import apply_settings_baseline
from .settings_feedback import apply_settings_feedback_fixes
from .settings_pages_baseline import apply_remaining_settings_baseline
from .settings_refresh_guard import install_settings_refresh_guard
from .settings_status import install_settings_semantic_status_contract
from .semantic_checklist import install_semantic_checklist_contract
from .settings_theme import apply_settings_token_contract
from .ui_components import ChecklistRow

BASELINE_PAGE_MARGIN = DESIGN_V1_METRICS["page_margin"]
BASELINE_SECTION_GAP = DESIGN_V1_METRICS["section_gap"]
WORKSPACE_HORIZONTAL_MARGIN = DESIGN_V1_METRICS["workspace_horizontal_margin"]
WORKSPACE_SECTION_GAP = DESIGN_V1_METRICS["workspace_gap"]


SettingsStage = tuple[str, Callable[[QWidget], None]]

SETTINGS_BASELINE_STAGES: tuple[SettingsStage, ...] = (
    ("golden_page", apply_settings_baseline),
    ("remaining_pages", apply_remaining_settings_baseline),
    # Existing callbacks queued by remaining_pages resolve _normalize_ai only
    # when they run, so install the lifecycle guard before returning to Qt.
    ("refresh_guard", install_settings_refresh_guard),
    ("feedback_closure", apply_settings_feedback_fixes),
    # Token QSS is last among the baseline visual stages and therefore owns
    # final rendering before semantic status labels are normalized.
    ("token_contract", apply_settings_token_contract),
    ("semantic_status", install_settings_semantic_status_contract),
    ("action_clarity", apply_settings_action_clarity),
)


def _settings_pipeline_shutdown_started(page: QWidget | None) -> bool:
    """Return True once the owning window has entered its shutdown lifecycle."""
    if page is None or not isValid(page):
        return True
    try:
        window = page.window()
    except RuntimeError:
        return True
    if window is None or not isValid(window):
        return True
    return bool(getattr(window, "_shutdown_requested", False))


def apply_settings_baseline_pipeline(page: QWidget | None) -> None:
    """Apply all Settings migrations once, in their documented order."""
    if _settings_pipeline_shutdown_started(page):
        return
    if page.property("settingsBaselinePipelineApplied"):
        return

    page.setProperty("settingsBaselinePipelineFailedStage", "")
    completed: list[str] = []
    for name, stage in SETTINGS_BASELINE_STAGES:
        if _settings_pipeline_shutdown_started(page):
            page.setProperty("settingsBaselinePipelineActiveStage", "")
            return
        page.setProperty("settingsBaselinePipelineActiveStage", name)
        try:
            stage(page)
        except Exception:
            page.setProperty("settingsBaselinePipelineFailedStage", name)
            page.setProperty("settingsBaselinePipelineStages", tuple(completed))
            page.setProperty("settingsBaselinePipelineActiveStage", "")
            page.setProperty("settingsBaselinePipelineApplied", False)
            raise
        completed.append(name)

    page.setProperty("settingsBaselinePipelineActiveStage", "")
    page.setProperty("settingsBaselinePipelineStages", tuple(completed))
    page.setProperty("settingsBaselinePipelineApplied", True)


def schedule_settings_baseline_pipeline(page: QWidget | None) -> None:
    """Queue one safe callback after Settings controls have been constructed."""
    if page is None or not isValid(page):
        return
    if page.property("settingsBaselinePipelineApplied") or page.property(
        "settingsBaselinePipelineScheduled"
    ):
        return

    page.setProperty("settingsBaselinePipelineScheduled", True)
    page_ref = weakref.ref(page)

    def run_pipeline() -> None:
        target = page_ref()
        if target is None or not isValid(target):
            return
        try:
            if _settings_pipeline_shutdown_started(target):
                return
            apply_settings_baseline_pipeline(target)
        finally:
            if isValid(target):
                target.setProperty("settingsBaselinePipelineScheduled", False)

    QTimer.singleShot(0, run_pipeline)


class _PageLayoutContract:
    archetype = "base"
    maximum_width = 16777215

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        page.setProperty("pageArchetype", cls.archetype)
        layout.setContentsMargins(
            BASELINE_PAGE_MARGIN,
            BASELINE_PAGE_MARGIN,
            BASELINE_PAGE_MARGIN,
            BASELINE_PAGE_MARGIN,
        )
        layout.setSpacing(BASELINE_SECTION_GAP)
        layout.setAlignment(Qt.AlignTop)
        QTimer.singleShot(0, lambda p=page: apply_global_design_baseline(p))
        schedule_selection_surface_contracts(page)
        apply_design_system_v11(page)
        return layout

    @classmethod
    def centered_host(cls, parent: QWidget, content: QWidget) -> QWidget:
        host = QWidget(parent)
        host.setProperty("pageArchetypeHost", cls.archetype)
        host.setMaximumWidth(cls.maximum_width)
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(content, 1, Qt.AlignTop)
        row.addStretch(1)
        return host


class DashboardPageLayout(_PageLayoutContract):
    archetype = "dashboard"
    maximum_width = 1360

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        super().apply(page, layout)
        # Baseline owns geometry; HCI then owns task hierarchy and final closure
        # retires duplicate legacy actions.
        QTimer.singleShot(0, lambda p=page: apply_dashboard_baseline(p))
        schedule_dashboard_hci_v1(page)
        schedule_dashboard_hci_closure(page)
        return layout


class WorkspacePageLayout(_PageLayoutContract):
    archetype = "workspace"

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        super().apply(page, layout)
        layout.setContentsMargins(
            WORKSPACE_HORIZONTAL_MARGIN,
            0,
            WORKSPACE_HORIZONTAL_MARGIN,
            0,
        )
        layout.setSpacing(WORKSPACE_SECTION_GAP)
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        schedule_review_baseline_pipeline(page)
        return layout


class TaskFlowPageLayout(_PageLayoutContract):
    archetype = "task_flow"
    maximum_width = 1440

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        super().apply(page, layout)
        QTimer.singleShot(0, lambda p=page: apply_task_flow_baseline(p))
        schedule_task_flow_hci_v1(page)
        schedule_task_flow_hci_closure(page)
        schedule_task_flow_review_scope_semantics(page)
        return layout


class SettingsPageLayout(_PageLayoutContract):
    archetype = "settings"
    maximum_width = 1120

    @classmethod
    def apply(cls, page: QWidget, layout: QLayout) -> QLayout:
        super().apply(page, layout)
        schedule_settings_baseline_pipeline(page)
        return layout


# ── Dashboard / Task Flow page baseline (merged from business_pages_baseline) ──
# Install the shared component contract before InvoiceReviewApp constructs any
# ChecklistRow instances.  This avoids per-instance monkey patches and prevents
# a transient Unicode/inline-color state during page construction.
install_semantic_checklist_contract(ChecklistRow)


DASHBOARD_MAX_WIDTH = 1360
IMPORT_RESULT_WIDTH = 340
EXPORT_GROUP_WIDTH = 280
EXPORT_CHECK_WIDTH = 360
PRIMARY_MAX_WIDTH = 180


def _content_width_button(button, *, minimum: int = 112, maximum: int = PRIMARY_MAX_WIDTH) -> None:
    if button is None:
        return
    required = button.fontMetrics().horizontalAdvance(button.text()) + 28
    button.setMinimumWidth(max(minimum, required))
    button.setMaximumWidth(max(maximum, required))
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


def apply_dashboard_baseline(page: QWidget) -> None:
    if page is None or page.property("dashboardBaselineApplied"):
        return
    window = page.window()
    if page is not getattr(window, "overview_page", None):
        return
    page.setProperty("dashboardBaselineApplied", True)

    host = getattr(window, "overview_content_host", None)
    if host is not None:
        # The centered parent row supplies the preferred width. A hard
        # 960px minimum overflows the default 1150x850 client area after
        # the navigation rail and page margins are applied.
        host.setMinimumWidth(0)
        host.setMaximumWidth(DASHBOARD_MAX_WIDTH)
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    review_button = None
    for button in page.findChildren(QWidget):
        if hasattr(button, "text") and callable(button.text) and button.text() in {"开始审核", "继续审核"}:
            review_button = button
            break
    if review_button is not None:
        review_button.setText("继续审核")
        _content_width_button(review_button, minimum=120)
        window.btn_overview_continue_review = review_button

    activity = getattr(window, "overview_activity_card", None)
    if activity is not None:
        activity.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)


def _flatten_nested_surface(widget: QWidget | None, object_name: str) -> None:
    if widget is None:
        return
    widget.setObjectName(object_name)
    widget.setProperty("class", "SubtleSection")
    widget.setStyleSheet(
        "QFrame { background: transparent; border: none; border-radius: 0; }"
        "QLabel { background: transparent; border: none; }"
    )
    layout = widget.layout()
    if layout is not None:
        layout.setContentsMargins(0, 0, 0, 0)


def apply_import_baseline(page: QWidget) -> None:
    if page is None or page.property("importBaselineApplied"):
        return
    window = page.window()
    if page is not getattr(window, "imports_page", None):
        return
    page.setProperty("importBaselineApplied", True)

    source = getattr(window, "import_source_card", None)
    if source is not None:
        # The source selector is the full top row of the import workspace.
        # A fixed sidebar width clips its three horizontally arranged cards.
        source.setMinimumWidth(0)
        source.setMaximumWidth(16777215)
        source.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    task = getattr(window, "import_task_stack", None)
    if task is not None:
        task.setMaximumWidth(900)
        task.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    result = getattr(window, "import_mail_recent_card", None)
    if result is not None:
        result.setFixedWidth(IMPORT_RESULT_WIDTH)
        result.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)

    _flatten_nested_surface(getattr(window, "import_rules_detail", None), "ImportRulesSubtleSection")
    command = getattr(window, "import_mail_command_bar", None)
    if command is not None:
        command.setStyleSheet("QFrame#CommandBar { background: transparent; border: none; }")
        if command.layout is not None:
            command.layout.setContentsMargins(0, 4, 0, 0)

    _content_width_button(getattr(window, "btn_import_scan_selected", None), minimum=112)
    _content_width_button(getattr(window, "btn_import_local_task", None), minimum=112)


def _export_naming_state(invoices: list[dict]) -> tuple[str, str]:
    """Return filename readiness using the same date rule as the exporter.

    Real export names are ``date-prefix + original filename``.  Seller is not a
    naming input, and the exporter resolves dates in this order:
    invoice_date, expense_date, mail_date, then ``unknown-date``.
    """
    approved = [
        invoice
        for invoice in invoices
        if str(invoice.get("review_status") or "").strip() == APPROVED
    ]
    if not approved:
        return "等待可导出发票", "muted"

    fallback_count = 0
    for invoice in approved:
        raw_date = (
            invoice.get("invoice_date")
            or invoice.get("expense_date")
            or invoice.get("mail_date")
            or ""
        )
        if normalize_export_date_prefix(raw_date) == "unknown-date":
            fallback_count += 1

    if fallback_count:
        return f"{fallback_count} 张将使用 unknown-date 前缀", "warning"
    return f"{len(approved)} 张使用日期前缀 + 原文件名", "success"


def _sync_export_naming_check(window) -> None:
    row = getattr(window, "export_check_naming", None)
    group_list = getattr(window, "export_group_list", None)
    db = getattr(window, "db", None)
    if row is None or group_list is None or db is None or not getattr(db, "is_open", False):
        return

    current_item = group_list.currentItem()
    claim_id = current_item.data(Qt.UserRole) if current_item is not None else None
    if claim_id is None:
        row.set_value("等待选择报销组", state="muted")
        return

    try:
        invoices = db.get_claim_invoices(claim_id)
    except Exception:
        row.set_value("暂时无法检查", state="warning")
        return

    text, state = _export_naming_state(list(invoices or []))
    row.set_value(text, state=state)


def _sync_export_directory_state(window) -> None:
    """Show configuration truth without claiming the directory was verified.

    The exporter remains authoritative for runtime filesystem failures.  This
    row only states that an output location is configured/resolved; it does not
    imply that the directory currently exists or is writable.
    """
    row = getattr(window, "export_check_dir", None)
    if row is None:
        return

    try:
        export_dir = Path(getattr(window, "_export_dir", None) or resolve_export_directory(window.config))
    except Exception:
        row.set_value("无法解析导出位置", state="warning")
        return

    row.set_value("已设置（导出时验证）", state="muted")
    row.lbl_value.setToolTip(str(export_dir))


def _schedule_export_checks(window) -> None:
    window_ref = weakref.ref(window)

    def run() -> None:
        target = window_ref()
        if target is not None and isValid(target):
            _sync_export_naming_check(target)
            _sync_export_directory_state(target)

    QTimer.singleShot(0, run)


def _install_export_naming_refresh(window, page: QWidget) -> None:
    if page.property("exportNamingRefreshInstalled"):
        return
    page.setProperty("exportNamingRefreshInstalled", True)

    group_list = getattr(window, "export_group_list", None)
    if group_list is not None:
        group_list.currentRowChanged.connect(
            lambda _row: _schedule_export_checks(window)
        )

    for method_name in ("_sync_export_claim_selection", "_refresh_export_page"):
        original = getattr(window, method_name, None)
        if original is None:
            continue

        @wraps(original)
        def wrapped(*args, __original=original, **kwargs):
            result = __original(*args, **kwargs)
            _schedule_export_checks(window)
            return result

        setattr(window, method_name, wrapped)


def apply_export_baseline(page: QWidget) -> None:
    if page is None or page.property("exportBaselineApplied"):
        return
    window = page.window()
    if page is not getattr(window, "export_page", None):
        return
    page.setProperty("exportBaselineApplied", True)

    group = getattr(window, "export_group_card", None)
    if group is not None:
        group.setFixedWidth(EXPORT_GROUP_WIDTH)
        group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
    invoices = getattr(window, "export_invoices_card", None)
    if invoices is not None:
        invoices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    integrity = getattr(window, "export_integrity_card", None)
    if integrity is not None:
        integrity.setFixedWidth(EXPORT_CHECK_WIDTH)
        integrity.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)

    # Pending invoices are excluded by default rather than blocking an export.
    # Preserve the existing boolean call site but render false as a warning.
    pending = getattr(window, "export_check_pending", None)
    if pending is not None:
        pending.setProperty("falseState", "warning")

    if integrity is not None and not hasattr(window, "export_check_naming"):
        naming = ChecklistRow("文件命名", "等待选择报销组", ok=None)
        naming.setObjectName("ExportNamingChecklistRow")
        hint = getattr(window, "lbl_export_action_hint", None)
        index = integrity.body_layout.indexOf(hint) if hint is not None else -1
        if index >= 0:
            integrity.body_layout.insertWidget(index, naming)
        else:
            integrity.body_layout.addWidget(naming)
        window.export_check_naming = naming

    _install_export_naming_refresh(window, page)

    # The page may have refreshed before this zero-delay baseline ran.  Re-run
    # the complete preflight now so no previously calculated row is reset to a
    # neutral state and the pending-row warning contract takes effect.
    sync = getattr(window, "_sync_export_claim_selection", None)
    if callable(sync):
        sync()
    else:
        _sync_export_naming_check(window)
        _sync_export_directory_state(window)

    _content_width_button(getattr(window, "btn_run_export_page", None), minimum=128)


def apply_task_flow_baseline(page: QWidget) -> None:
    """Dispatch Task Flow normalization after the page has been assigned."""
    window = page.window()
    if page is getattr(window, "imports_page", None):
        apply_import_baseline(page)
    elif page is getattr(window, "export_page", None):
        apply_export_baseline(page)
