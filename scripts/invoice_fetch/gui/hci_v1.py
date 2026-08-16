"""Invoice Hub HCI v1.0 task-flow contract.

The existing Design System v1.1 remains the visual authority. This module
changes task hierarchy and interaction semantics only:

- Dashboard: show what needs attention and one primary continue action.
- Review: offer a continuous-review focus mode that temporarily retires the list.
- Import: use user-facing sync / re-check language and bounded history actions.

The module is intentionally isolated from ``app.py`` so the large compatibility
window does not gain another page-specific implementation layer.
"""

from __future__ import annotations

import weakref
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
from types import MethodType

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QDialog,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ..review_status import ERROR, TO_REVIEW
from .design_tokens import DESIGN_V1_COLORS
from .date_range_dialog import DateRangeDialog
from .ui_components import SectionCard, make_badge, make_button


def _repolish(widget: QWidget | None) -> None:
    if widget is None:
        return
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _section_ancestor(widget: QWidget | None) -> SectionCard | None:
    current = widget
    while current is not None:
        if isinstance(current, SectionCard):
            return current
        current = current.parentWidget()
    return None


def _checked_mailbox_keys(window) -> list[str]:
    keys: list[str] = []
    for checkbox in list(getattr(window, "mail_account_checkboxes", []) or []):
        if not checkbox.isChecked():
            continue
        key = str(checkbox.property("account_key") or "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


class HciTaskCard(QFrame):
    """Compact actionable task card used by the dashboard."""

    activated = Signal(str)

    def __init__(self, key: str, title: str, state: str = "warning", parent=None):
        super().__init__(parent)
        self.key = key
        self.state = state
        self.setObjectName("HciTaskCard")
        self.setProperty("state", state)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(112)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        self.lbl_title = QLabel(title, self)
        self.lbl_title.setProperty("class", "SectionTitle")
        self.lbl_value = QLabel("—", self)
        self.lbl_value.setProperty("class", "HciTaskMetric")
        self.lbl_hint = QLabel("点击处理 →", self)
        self.lbl_hint.setProperty("class", "SectionHint")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        layout.addStretch(1)
        layout.addWidget(self.lbl_hint)

        colors = DESIGN_V1_COLORS
        if state == "danger":
            surface = colors["danger_surface"]
            border = colors["danger_border"]
            metric = colors["danger_text"]
        elif state == "success":
            surface = colors["success_surface"]
            border = colors["success_border"]
            metric = colors["success_text"]
        else:
            surface = colors["warning_surface"]
            border = colors["warning_border"]
            metric = colors["warning_text"]

        self.setStyleSheet(
            f"""
            QFrame#HciTaskCard {{
                background: {surface};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QFrame#HciTaskCard:hover {{
                border: 1px solid {colors["accent_border"]};
            }}
            QLabel[class="HciTaskMetric"] {{
                color: {metric};
                font-size: 26px;
                font-weight: 700;
                border: none;
                background: transparent;
            }}
            QLabel[class="SectionTitle"], QLabel[class="SectionHint"] {{
                border: none;
                background: transparent;
            }}
            """
        )

    def set_value(self, value: int | str, hint: str | None = None) -> None:
        self.lbl_value.setText(str(value))
        if hint is not None:
            self.lbl_hint.setText(hint)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.key)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit(self.key)
            event.accept()
            return
        super().keyPressEvent(event)


class HistoryRecheckWorker(QThread):
    """Run bounded known-email reprocessing without blocking the Qt event loop."""

    finished_result = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        db_path: Path,
        *,
        since: str,
        until: str | None = None,
        selected_keys: list[str] | None = None,
        only_downloaded: bool = False,
        limit: int = 200,
        parent=None,
    ):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.since = since
        self.until = until
        self.selected_keys = list(selected_keys or [])
        self.only_downloaded = bool(only_downloaded)
        self.limit = int(limit)

    def run(self) -> None:
        try:
            from ..hci_v1_services import recheck_known_email_history

            result = recheck_known_email_history(
                self.db_path,
                since=self.since,
                until=self.until,
                selected_keys=self.selected_keys or None,
                only_downloaded=self.only_downloaded,
                limit=self.limit,
            )
            self.finished_result.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        except BaseException as exc:
            self.failed.emit(str(exc))


def _dashboard_counts(window) -> dict[str, int]:
    metrics = {}
    collector = getattr(window, "_collect_overview_metrics", None)
    if callable(collector):
        metrics = collector() or {}

    to_review = int(metrics.get("to_review", 0) or 0)
    error = int(metrics.get("error", 0) or 0)
    missing = 0
    buyer_mismatch = 0

    db = getattr(window, "db", None)
    if db is not None and getattr(db, "is_open", False):
        try:
            invoices = list(db.get_all_invoices(include_deleted=False) or [])
        except Exception:
            invoices = []
        for invoice in invoices:
            status = str(invoice.get("review_status") or TO_REVIEW)
            if status not in {TO_REVIEW, ERROR}:
                continue
            if bool(invoice.get("missing_extra")):
                missing += 1
            warning = getattr(window, "_buyer_warning", None)
            if callable(warning):
                try:
                    if warning(invoice):
                        buyer_mismatch += 1
                except Exception:
                    pass

    missing = max(missing, int(metrics.get("needs_fix", 0) or 0))
    return {
        "to_review": to_review,
        "missing_evidence": missing,
        "buyer_mismatch": buyer_mismatch,
        "parse_error": error,
        "export_ready": int(metrics.get("export_ready", 0) or 0),
    }


def _switch_to_review(window, status: str = TO_REVIEW, *, continuous: bool = False) -> None:
    switcher = getattr(window, "_switch_main_page", None)
    if callable(switcher):
        switcher("review")

    def after_switch() -> None:
        if not isValid(window):
            return
        changer = getattr(window, "_change_filter", None)
        if callable(changer):
            changer(status)
        if continuous:
            enter = getattr(window, "_enter_hci_continuous_review", None)
            if callable(enter):
                QTimer.singleShot(0, enter)

    QTimer.singleShot(0, after_switch)


def _dashboard_task_clicked(window, key: str) -> None:
    if key == "parse_error":
        _switch_to_review(window, ERROR, continuous=False)
        return
    _switch_to_review(window, TO_REVIEW, continuous=True)


def _sync_dashboard_hci(window) -> None:
    if not isValid(window):
        return
    counts = _dashboard_counts(window)
    cards = getattr(window, "hci_dashboard_task_cards", {}) or {}
    if cards:
        cards["to_review"].set_value(
            counts["to_review"], "逐张确认，处理后自动进入下一张 →"
        )
        cards["missing_evidence"].set_value(
            counts["missing_evidence"], "补齐行程单、付款凭证等材料 →"
        )
        cards["buyer_mismatch"].set_value(
            counts["buyer_mismatch"], "确认购买方与默认开票主体 →"
        )
        cards["parse_error"].set_value(
            counts["parse_error"], "查看解析失败或异常记录 →"
        )

    button = getattr(window, "btn_hci_continue_tasks", None)
    if button is not None:
        count = counts["to_review"]
        button.setText(f"继续处理 {count} 张" if count else "查看审核工作台")
        button.setEnabled(True)

    badge = getattr(window, "lbl_hci_task_total", None)
    if badge is not None:
        actionable = counts["to_review"]
        badge.setText(f"{actionable} 张待处理" if actionable else "当前无待审核")

    sync_hint = getattr(window, "lbl_overview_recent_imports", None)
    if sync_hint is not None:
        sync_hint.setText("默认“同步新邮件”只检查上次同步之后的新邮件。")

    health = getattr(window, "lbl_overview_health", None)
    if health is not None:
        health.setText(
            f"可导出 {counts['export_ready']} 组 · "
            f"缺材料 {counts['missing_evidence']} 张 · "
            f"异常 {counts['parse_error']} 张。"
        )


def _install_dashboard_refresh(window) -> None:
    if getattr(window, "_hci_dashboard_refresh_installed", False):
        return
    original = getattr(window, "_refresh_overview_page", None)
    if not callable(original):
        return

    @wraps(original)
    def wrapped(self, *args, **kwargs):
        result = original(*args, **kwargs)
        QTimer.singleShot(0, lambda: _sync_dashboard_hci(self))
        return result

    window._refresh_overview_page = MethodType(wrapped, window)
    window._hci_dashboard_refresh_installed = True


def _open_import_sync(window, *, recheck: bool = False) -> None:
    switcher = getattr(window, "_switch_main_page", None)
    if callable(switcher):
        switcher("imports")

    def after_switch() -> None:
        if not isValid(window):
            return
        if recheck:
            button = getattr(window, "btn_hci_import_recheck", None)
            if button is not None and button.menu() is not None:
                button.showMenu()
            return
        button = getattr(window, "btn_import_scan_selected", None)
        if button is not None and button.text() != "补授权码":
            button.click()

    QTimer.singleShot(0, after_switch)


def apply_dashboard_hci_v1(page: QWidget | None) -> None:
    if page is None or not isValid(page) or page.property("hciV1DashboardApplied"):
        return
    window = page.window()
    if page is not getattr(window, "overview_page", None):
        return

    host = getattr(window, "overview_content_host", None)
    layout = host.layout() if host is not None else None
    header = getattr(window, "overview_header", None)
    if layout is None or header is None:
        return

    page.setProperty("hciV1DashboardApplied", True)
    header.set_title("今天需要处理什么")
    header.set_subtitle("把待确认、缺材料和异常集中处理；完成后再准备报销。")

    old_summary = getattr(window, "overview_summary_strip", None)
    if old_summary is not None:
        old_summary.hide()

    task_host = QFrame(host)
    task_host.setObjectName("HciDashboardTaskHost")
    task_layout = QVBoxLayout(task_host)
    task_layout.setContentsMargins(0, 0, 0, 0)
    task_layout.setSpacing(10)

    action_row = QHBoxLayout()
    action_row.setContentsMargins(0, 0, 0, 0)
    action_row.setSpacing(8)
    action_row.addStretch(1)
    window.lbl_hci_task_total = make_badge("—", variant="warning")
    window.btn_hci_continue_tasks = make_button("继续处理", variant="primary")
    window.btn_hci_continue_tasks.clicked.connect(
        lambda: _switch_to_review(window, TO_REVIEW, continuous=True)
    )
    action_row.addWidget(window.lbl_hci_task_total)
    action_row.addWidget(window.btn_hci_continue_tasks)
    task_layout.addLayout(action_row)

    cards_row = QHBoxLayout()
    cards_row.setContentsMargins(0, 0, 0, 0)
    cards_row.setSpacing(12)
    specs = (
        ("to_review", "新票待确认", "warning"),
        ("missing_evidence", "缺证明材料", "warning"),
        ("buyer_mismatch", "购买方异常", "warning"),
        ("parse_error", "解析失败 / 异常", "danger"),
    )
    cards: dict[str, HciTaskCard] = {}
    for key, title, state in specs:
        card = HciTaskCard(key, title, state, task_host)
        card.activated.connect(lambda task_key, w=window: _dashboard_task_clicked(w, task_key))
        cards_row.addWidget(card, 1)
        cards[key] = card
    window.hci_dashboard_task_cards = cards
    task_layout.addLayout(cards_row)

    header_index = layout.indexOf(header)
    layout.insertWidget(max(0, header_index + 1), task_host)
    window.hci_dashboard_task_host = task_host

    left_card = _section_ancestor(getattr(window, "lbl_overview_recent_imports", None))
    if left_card is not None:
        left_card.set_title("收集与同步")
        left_card.set_hint("平时只同步新邮件；需要找回历史记录时再选择重新检查。")
        old_review = getattr(window, "btn_overview_continue_review", None)
        if old_review is not None:
            old_review.hide()

        sync_row = QHBoxLayout()
        sync_row.setContentsMargins(0, 0, 0, 0)
        sync_row.setSpacing(8)
        btn_sync = make_button("同步新邮件", variant="primary")
        btn_sync.clicked.connect(lambda: _open_import_sync(window, recheck=False))
        btn_recheck = make_button("重新检查", variant="secondary")
        btn_recheck.clicked.connect(lambda: _open_import_sync(window, recheck=True))
        sync_row.addWidget(btn_sync)
        sync_row.addWidget(btn_recheck)
        sync_row.addStretch(1)
        left_card.body_layout.addLayout(sync_row)
        window.btn_hci_dashboard_sync = btn_sync
        window.btn_hci_dashboard_recheck = btn_recheck

    right_card = _section_ancestor(getattr(window, "lbl_overview_health", None))
    if right_card is not None:
        right_card.set_title("即将报销")
        right_card.set_hint("先看是否存在阻塞项，再进入报销组与导出。")
        btn_claims = make_button("查看报销组", variant="secondary")
        btn_claims.clicked.connect(lambda: window._switch_main_page("export"))
        right_card.body_layout.addWidget(btn_claims)
        window.btn_hci_open_claims = btn_claims

    activity = getattr(window, "overview_activity_card", None)
    if activity is not None:
        activity.set_title("今天已完成")
        activity.set_hint("保留最近的导入、审核和导出活动，方便快速确认刚刚发生了什么。")

    _install_dashboard_refresh(window)
    _sync_dashboard_hci(window)


def _review_progress_text(window) -> str:
    metrics = _dashboard_counts(window)
    remaining = metrics["to_review"]
    initial = int(getattr(window, "_hci_review_initial_total", 0) or 0)
    if initial <= 0:
        initial = remaining
    processed = max(0, initial - remaining)
    current = min(initial, processed + 1) if remaining > 0 else initial
    if initial <= 0:
        return "当前没有待审核发票"
    if remaining <= 0:
        return f"{initial} / {initial} · 本轮已完成"
    return f"{current} / {initial} · 当前还剩 {remaining} 张待审核"


def _sync_review_hci(window) -> None:
    if not isValid(window):
        return
    label = getattr(window, "lbl_hci_review_progress", None)
    if label is not None:
        label.setText(_review_progress_text(window))

    detail = getattr(window, "_detail_panel", None)
    shortcut = getattr(window, "lbl_hci_review_shortcuts", None)
    if shortcut is not None and detail is not None:
        missing = bool((getattr(window, "current_invoice", None) or {}).get("missing_extra"))
        shortcut.setText(
            "Enter 通过并下一张 · E 添加材料 · G 加入报销组"
            + (" · 当前还缺证明材料" if missing else "")
        )


def _enter_hci_continuous_review(window) -> None:
    page = getattr(window, "review_page", None)
    if page is None or not isValid(page):
        return
    if page.property("hciContinuousReview"):
        _sync_review_hci(window)
        return

    changer = getattr(window, "_change_filter", None)
    if callable(changer):
        changer(TO_REVIEW)

    page.setProperty("hciContinuousReview", True)
    counts = _dashboard_counts(window)
    window._hci_review_initial_total = counts["to_review"]

    header = getattr(window, "review_header", None)
    if header is not None:
        window._hci_review_header_restore = (
            header.lbl_title.text(),
            header.lbl_subtitle.text(),
        )
        header.set_title("连续审核")
        header.set_subtitle("把列表暂时退到后台，减少视线跳转；一张正常票只需一次确认。")

    upper = getattr(window, "left_upper_widget", None)
    filter_bar = getattr(window, "filter_bar_widget", None)
    window._hci_review_visibility_restore = {
        "upper": upper.isVisible() if upper is not None else True,
        "filter": filter_bar.isVisible() if filter_bar is not None else True,
    }
    if upper is not None:
        upper.hide()
    if filter_bar is not None:
        filter_bar.hide()

    bar = getattr(window, "hci_review_mode_bar", None)
    if bar is not None:
        bar.setProperty("active", True)
        getattr(window, "btn_hci_enter_review").hide()
        getattr(window, "lbl_hci_review_progress").show()
        getattr(window, "btn_hci_exit_review").show()
        getattr(window, "lbl_hci_review_shortcuts").show()
        _repolish(bar)

    preview = getattr(window, "preview_panel", None)
    if preview is not None:
        preview.setProperty("hciContinuousReview", True)
        _repolish(preview)
    detail = getattr(window, "_detail_panel", None)
    if detail is not None:
        detail.setProperty("hciContinuousReview", True)
        _repolish(detail)

    _sync_review_hci(window)


def _exit_hci_continuous_review(window) -> None:
    page = getattr(window, "review_page", None)
    if page is None or not isValid(page) or not page.property("hciContinuousReview"):
        return
    page.setProperty("hciContinuousReview", False)

    header = getattr(window, "review_header", None)
    restore = getattr(window, "_hci_review_header_restore", None)
    if header is not None:
        if restore:
            header.set_title(restore[0])
            header.set_subtitle(restore[1])
        else:
            header.set_title("发票审核")
            header.set_subtitle("逐张确认原件、状态和报销组，处理完成后再进入导出。")

    visibility = getattr(window, "_hci_review_visibility_restore", {}) or {}
    upper = getattr(window, "left_upper_widget", None)
    filter_bar = getattr(window, "filter_bar_widget", None)
    if upper is not None:
        upper.setVisible(bool(visibility.get("upper", True)))
    if filter_bar is not None:
        filter_bar.setVisible(bool(visibility.get("filter", True)))

    bar = getattr(window, "hci_review_mode_bar", None)
    if bar is not None:
        bar.setProperty("active", False)
        getattr(window, "btn_hci_enter_review").show()
        getattr(window, "lbl_hci_review_progress").hide()
        getattr(window, "btn_hci_exit_review").hide()
        getattr(window, "lbl_hci_review_shortcuts").hide()
        _repolish(bar)


def apply_review_hci_v1(page: QWidget | None) -> None:
    if page is None or not isValid(page) or page.property("hciV1ReviewApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    layout = getattr(window, "main_layout", None)
    header = getattr(window, "review_header", None)
    if layout is None or header is None:
        return

    page.setProperty("hciV1ReviewApplied", True)
    bar = QFrame(page)
    bar.setObjectName("HciReviewModeBar")
    bar.setProperty("class", "WorkbenchCard")
    bar_layout = QHBoxLayout(bar)
    bar_layout.setContentsMargins(12, 8, 12, 8)
    bar_layout.setSpacing(8)

    btn_enter = make_button("连续审核", variant="primary")
    progress = QLabel("", bar)
    progress.setProperty("class", "SectionTitle")
    shortcuts = QLabel("Enter 通过并下一张 · E 添加材料 · G 加入报销组", bar)
    shortcuts.setProperty("class", "SectionHint")
    btn_exit = make_button("退出连续审核", variant="secondary")

    progress.hide()
    shortcuts.hide()
    btn_exit.hide()
    bar_layout.addWidget(btn_enter)
    bar_layout.addWidget(progress)
    bar_layout.addStretch(1)
    bar_layout.addWidget(shortcuts)
    bar_layout.addWidget(btn_exit)

    header_index = layout.indexOf(header)
    layout.insertWidget(max(0, header_index + 1), bar)

    window.hci_review_mode_bar = bar
    window.btn_hci_enter_review = btn_enter
    window.lbl_hci_review_progress = progress
    window.lbl_hci_review_shortcuts = shortcuts
    window.btn_hci_exit_review = btn_exit
    window._enter_hci_continuous_review = MethodType(
        lambda self: _enter_hci_continuous_review(self), window
    )
    window._exit_hci_continuous_review = MethodType(
        lambda self: _exit_hci_continuous_review(self), window
    )

    btn_enter.clicked.connect(window._enter_hci_continuous_review)
    btn_exit.clicked.connect(window._exit_hci_continuous_review)

    table = getattr(window, "table", None)
    if table is not None:
        table.currentCellChanged.connect(
            lambda *_args, w=window: QTimer.singleShot(0, lambda: _sync_review_hci(w))
        )

    detail = getattr(window, "_detail_panel", None)
    if detail is not None:
        shortcut_e = QShortcut(QKeySequence("E"), page)
        shortcut_e.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut_e.activated.connect(
            lambda d=detail, p=page: (
                d.btn_add_evidence.click()
                if p.property("hciContinuousReview")
                and hasattr(d, "btn_add_evidence")
                and d.btn_add_evidence.isEnabled()
                else None
            )
        )
        shortcut_g = QShortcut(QKeySequence("G"), page)
        shortcut_g.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut_g.activated.connect(
            lambda d=detail, p=page: (
                d.btn_add_to_claim.click()
                if p.property("hciContinuousReview")
                and hasattr(d, "btn_add_to_claim")
                and d.btn_add_to_claim.isEnabled()
                else None
            )
        )
        window._hci_shortcut_e = shortcut_e
        window._hci_shortcut_g = shortcut_g


def _restore_import_sync_label(window) -> None:
    button = getattr(window, "btn_import_scan_selected", None)
    if button is None:
        return
    if button.text() != "补授权码" and not button.property("busy"):
        button.setText("同步新邮件")
        button.setToolTip("只检查上次同步之后的新邮件")


def _install_import_label_refresh(window) -> None:
    if getattr(window, "_hci_import_label_refresh_installed", False):
        return
    for name in ("_refresh_imports_page", "_refresh_mailbox_task_page"):
        original = getattr(window, name, None)
        if not callable(original):
            continue

        @wraps(original)
        def wrapped(self, *args, __original=original, **kwargs):
            result = __original(*args, **kwargs)
            QTimer.singleShot(0, lambda: _restore_import_sync_label(self))
            return result

        setattr(window, name, MethodType(wrapped, window))
    window._hci_import_label_refresh_installed = True


def _history_recheck_finished(window, result: dict) -> None:
    from .hci_v1_closure import _render_history_recheck_terminal

    _render_history_recheck_terminal(window, result)
    worker = getattr(window, "_hci_history_worker", None)
    if worker is not None:
        worker.deleteLater()
    window._hci_history_worker = None
    _release_history_operation(window, worker)

    button = getattr(window, "btn_hci_import_recheck", None)
    if button is not None:
        button.setEnabled(True)
        button.setText("重新检查 ▾")

    processed = int(result.get("processed_emails", 0) or 0)
    added = int(result.get("added_or_restored", 0) or 0)
    recent = getattr(window, "import_mail_recent_card", None)
    if recent is not None:
        suffix = "（达到本次 200 封上限）" if result.get("limit_reached") else ""
        recent.set_hint(
            f"重新检查完成：处理 {processed} 封已知邮件，新增或恢复 {added} 条记录{suffix}。"
        )

    recorder = getattr(window, "_record_import_activity", None)
    if callable(recorder):
        try:
            recorder("邮箱重新检查", scanned=processed, added=added)
        except TypeError:
            pass

    for name in ("_load_invoices", "_refresh_overview_page", "_refresh_imports_page"):
        callback = getattr(window, name, None)
        if callable(callback):
            try:
                callback()
            except Exception:
                pass

    review_button = getattr(window, "btn_hci_import_review_result", None)
    if review_button is not None:
        review_button.setText(f"去审核 {added} 张" if added else "查看审核工作台")
        review_button.show()


def _history_recheck_failed(window, message: str) -> None:
    from .hci_v1_closure import _render_history_recheck_failed

    _render_history_recheck_failed(window, message)
    worker = getattr(window, "_hci_history_worker", None)
    if worker is not None:
        worker.deleteLater()
    window._hci_history_worker = None
    _release_history_operation(window, worker)
    button = getattr(window, "btn_hci_import_recheck", None)
    if button is not None:
        button.setEnabled(True)
        button.setText("重新检查 ▾")
    QMessageBox.critical(window, "重新检查失败", str(message or "未知错误"))


def _start_history_recheck(
    window,
    *,
    since: str,
    until: str | None = None,
    only_downloaded: bool = False,
) -> None:
    if getattr(window, "_hci_history_worker", None) is not None:
        QMessageBox.information(window, "正在处理", "历史邮件正在重新检查，请等待当前任务完成。")
        return

    selected_keys = _checked_mailbox_keys(window)
    mode_text = "只重新处理已下载过的已知附件" if only_downloaded else "重新检查已知邮件"
    answer = QMessageBox.question(
        window,
        "确认重新检查",
        f"{mode_text}\n范围：{since} 至 {until or '今天'}\n\n"
        "不会执行全库重置；已通过或已加入报销组的发票默认跳过。"
        "本次最多处理 200 封已知邮件。",
    )
    if answer != QMessageBox.Yes:
        return

    db_path = getattr(getattr(window, "db", None), "_path", None)
    if not db_path:
        QMessageBox.critical(window, "无法重新检查", "当前数据库路径不可用。")
        return

    begin_operation = getattr(window, "_try_begin_data_operation", None)
    if callable(begin_operation) and not begin_operation("历史记录重检"):
        return

    try:
        worker = HistoryRecheckWorker(
            Path(db_path),
            since=since,
            until=until,
            selected_keys=selected_keys or None,
            only_downloaded=only_downloaded,
            limit=200,
            parent=window,
        )
    except Exception:
        _release_history_operation(window)
        raise
    window._hci_history_worker = worker
    window._hci_history_operation_token = worker
    button = getattr(window, "btn_hci_import_recheck", None)
    if button is not None:
        button.setEnabled(False)
        button.setText("重新检查中…")
    review_button = getattr(window, "btn_hci_import_review_result", None)
    if review_button is not None:
        review_button.hide()

    recent = getattr(window, "import_mail_recent_card", None)
    if recent is not None:
        recent.set_hint("正在重新检查已知邮件；不会清空全部扫描历史。")

    worker.finished_result.connect(lambda result, w=window: _history_recheck_finished(w, result))
    worker.failed.connect(lambda message, w=window: _history_recheck_failed(w, message))
    # The result/error signals release the gate after UI cleanup.  The native
    # QThread finished signal is a final safety net for an unexpected worker
    # exit that emits neither application signal.
    worker.finished.connect(
        lambda w=window, worker=worker: _release_history_operation(w, worker)
    )
    try:
        worker.start()
        from .hci_v1_closure import _begin_scan_presentation

        _begin_scan_presentation(window, "query")
    except Exception:
        window._hci_history_worker = None
        _release_history_operation(window, worker)
        worker.deleteLater()
        raise


def _release_history_operation(window, worker=None) -> None:
    token = getattr(window, "_hci_history_operation_token", None)
    if worker is not None and token is not worker:
        return
    window._hci_history_operation_token = None
    end_operation = getattr(window, "_end_data_operation", None)
    if callable(end_operation):
        end_operation("历史记录重检")


def _start_recent_30_day_recheck(window) -> None:
    since = (date.today() - timedelta(days=30)).isoformat()
    _start_history_recheck(window, since=since)


def _start_known_attachment_reprocess(window) -> None:
    since = (date.today() - timedelta(days=30)).isoformat()
    _start_history_recheck(window, since=since, only_downloaded=True)


def _start_custom_range_recheck(window) -> None:
    dialog = DateRangeDialog(window)
    if dialog.exec() != QDialog.Accepted:
        return
    since, until = dialog.date_range()
    _start_history_recheck(window, since=since, until=until)


def apply_import_hci_v1(page: QWidget | None) -> None:
    if page is None or not isValid(page) or page.property("hciV1ImportApplied"):
        return
    window = page.window()
    if page is not getattr(window, "imports_page", None):
        return

    primary = getattr(window, "btn_import_scan_selected", None)
    command = getattr(window, "import_mail_command_bar", None)
    if primary is None or command is None:
        return

    page.setProperty("hciV1ImportApplied", True)
    header = getattr(window, "imports_header", None)
    if header is not None:
        header.set_subtitle("从本地文件、手机或邮箱收集票据；邮箱默认只同步新邮件。")

    _restore_import_sync_label(window)

    legacy_default = getattr(window, "btn_import_scan_default", None)
    if legacy_default is not None:
        legacy_default.hide()

    recheck = make_button("重新检查 ▾", variant="secondary")
    menu = QMenu(recheck)
    menu.addAction("重新检查最近 30 天", lambda: _start_recent_30_day_recheck(window))
    menu.addAction("重新检查指定时间范围", lambda: _start_custom_range_recheck(window))
    menu.addSeparator()
    menu.addAction("重新处理最近 30 天已知附件", lambda: _start_known_attachment_reprocess(window))
    recheck.setMenu(menu)
    recheck.setToolTip("用于找回误删记录或重新处理以前已知的邮件")
    window.btn_hci_import_recheck = recheck

    cancel = getattr(window, "btn_import_scan_cancel", None)
    secondaries = [recheck]
    if cancel is not None:
        secondaries.append(cancel)
    command.set_actions(
        primary_action=primary,
        secondary_actions=secondaries,
        more_menu=getattr(window, "import_mail_more", None),
    )

    recent = getattr(window, "import_mail_recent_card", None)
    if recent is not None:
        recent.set_title("同步结果")
        recent.set_hint("同步结束后会说明检查范围、找到多少票据，以及下一步可以做什么。")
        review_result = make_button("去审核", variant="primary")
        review_result.clicked.connect(
            lambda: _switch_to_review(window, TO_REVIEW, continuous=True)
        )
        review_result.hide()
        recent.body_layout.addWidget(review_result, 0, Qt.AlignRight)
        window.btn_hci_import_review_result = review_result

    _install_import_label_refresh(window)


def apply_task_flow_hci_v1(page: QWidget | None) -> None:
    if page is None or not isValid(page):
        return
    window = page.window()
    if page is getattr(window, "imports_page", None):
        apply_import_hci_v1(page)


def schedule_dashboard_hci_v1(page: QWidget | None) -> None:
    if page is None or not isValid(page):
        return
    page_ref = weakref.ref(page)

    def run() -> None:
        target = page_ref()
        if target is not None and isValid(target):
            apply_dashboard_hci_v1(target)

    QTimer.singleShot(0, run)


def schedule_task_flow_hci_v1(page: QWidget | None) -> None:
    if page is None or not isValid(page):
        return
    page_ref = weakref.ref(page)

    def run() -> None:
        target = page_ref()
        if target is not None and isValid(target):
            apply_task_flow_hci_v1(target)

    QTimer.singleShot(0, run)


__all__ = [
    "HciTaskCard",
    "HistoryRecheckWorker",
    "DateRangeDialog",
    "apply_dashboard_hci_v1",
    "apply_import_hci_v1",
    "apply_review_hci_v1",
    "apply_task_flow_hci_v1",
    "schedule_dashboard_hci_v1",
    "schedule_task_flow_hci_v1",
]
