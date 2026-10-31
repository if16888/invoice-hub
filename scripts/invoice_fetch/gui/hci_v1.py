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

import time
import weakref
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
from types import MethodType

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QDialog,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ..review_status import ERROR, TO_REVIEW
from .design_tokens import DESIGN_V1_COLORS
from .date_range_dialog import DateRangeDialog
from .ui_components import SectionCard, make_badge, make_button
from .workbench_state import is_keyboard_input_target


class ResponsiveTaskCardRow(QWidget):
    """Keep dashboard task cards inside the available client width."""

    # Four columns remain the normal desktop presentation. Below that,
    # two columns avoid the single-row minimum-width pressure; very narrow
    # clients use one column so the action cluster and cards never overflow.
    _FOUR_COLUMN_MIN_WIDTH = 900
    _TWO_COLUMN_MIN_WIDTH = 680

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HciDashboardTaskCards")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._cards: list[HciTaskCard] = []
        self._column_count = 0
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(12)
        self._layout.setVerticalSpacing(12)

    def add_card(self, card: HciTaskCard) -> None:
        if card is None or card in self._cards:
            return
        self._cards.append(card)
        card.setParent(self)
        self._relayout_cards()

    def column_count(self) -> int:
        return self._column_count

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_cards()

    def _relayout_cards(self) -> None:
        width = max(0, self.contentsRect().width())
        if width >= self._FOUR_COLUMN_MIN_WIDTH:
            columns = 4
        elif width >= self._TWO_COLUMN_MIN_WIDTH:
            columns = 2
        else:
            columns = 1
        if columns == self._column_count and self._layout.count() == len(self._cards):
            return

        self._column_count = columns
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self)
        for column in range(4):
            self._layout.setColumnStretch(column, 0)
        for column in range(columns):
            self._layout.setColumnStretch(column, 1)
        for index, card in enumerate(self._cards):
            self._layout.addWidget(card, index // columns, index % columns)
        self._layout.invalidate()
        self.setMinimumHeight(self._layout.minimumSize().height())
        self.updateGeometry()

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
                font-size: 22px;
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


def _dashboard_counts(window, metrics=None) -> dict[str, int]:
    supplied_metrics = metrics is not None
    metrics = metrics or {}
    collector = getattr(window, "_collect_overview_metrics", None)
    if callable(collector) and not supplied_metrics:
        metrics = collector() or {}

    to_review = int(metrics.get("to_review", 0) or 0)
    error = int(metrics.get("error", 0) or 0)
    missing = 0
    buyer_mismatch = 0

    db = getattr(window, "db", None)
    if db is not None and getattr(db, "is_open", False):
        from ..review_query import ReviewColumnFilter, ReviewQuery
        missing = db.count_review_invoices(ReviewQuery(column_filters=(
            ReviewColumnFilter("missing_extra", values=("缺证明",)),
        )))
        buyer_mismatch = db.count_review_invoices(ReviewQuery(column_filters=(
            ReviewColumnFilter("buyer_warning", values=("异常",)),
        )))

    return {
        "to_review": to_review,
        "missing_evidence": missing,
        "buyer_mismatch": buyer_mismatch,
        "parse_error": error,
        "export_ready": int(metrics.get("export_ready", 0) or 0),
    }


def _switch_to_review(
    window,
    status: str = TO_REVIEW,
    *,
    continuous: bool = False,
    extra_filters: dict | None = None,
) -> None:
    switcher = getattr(window, "_switch_main_page", None)
    if callable(switcher):
        switcher("review")

    def after_switch() -> None:
        if not isValid(window):
            return

        # Ensure continuous review mode is exited when jumping in non-continuous mode
        if not continuous:
            exit_review = getattr(window, "_exit_hci_continuous_review", None)
            if callable(exit_review):
                exit_review()

        # Dashboard counts describe all live invoices. A previous review search
        # or column filter must not hide the tasks the user just selected.
        resetter = getattr(window, "_reset_invoice_filters", None)
        if callable(resetter):
            resetter()

        if extra_filters:
            if hasattr(window, "column_filters"):
                window.column_filters.update(extra_filters)
            sync_cb = getattr(window, "_sync_column_filters_to_checkboxes", None)
            if callable(sync_cb):
                sync_cb()
            refresh_headers = getattr(window, "_refresh_column_filter_headers", None)
            if callable(refresh_headers):
                refresh_headers()
            update_chips = getattr(window, "_update_filter_summary_chips", None)
            if callable(update_chips):
                update_chips()

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
    elif key == "to_review":
        _switch_to_review(window, TO_REVIEW, continuous=False)
    elif key == "missing_evidence":
        _switch_to_review(
            window,
            "all",
            continuous=False,
            extra_filters={"missing_extra": {"values": {"缺证明"}}},
        )
    elif key == "buyer_mismatch":
        _switch_to_review(
            window,
            "all",
            continuous=False,
            extra_filters={"buyer_warning": {"values": {"异常"}}},
        )
    else:
        _switch_to_review(window, TO_REVIEW, continuous=False)


def _sync_dashboard_hci(window, metrics=None) -> None:
    if not isValid(window):
        return
    if window._current_page_key() != "overview":
        return
    counts = _dashboard_counts(window, metrics)
    cards = getattr(window, "hci_dashboard_task_cards", {}) or {}
    if cards:
        cards["to_review"].set_value(
            counts["to_review"], "所有尚未确认的发票 →"
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
            f"缺证明 {counts['missing_evidence']} 张 · "
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
        QTimer.singleShot(0, lambda snapshot=getattr(self, "_overview_metric_snapshot", None): _sync_dashboard_hci(self, snapshot))
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

    cards_row = ResponsiveTaskCardRow(task_host)
    specs = (
        ("to_review", "待审核", "warning"),
        ("missing_evidence", "缺证明材料", "warning"),
        ("buyer_mismatch", "购买方异常", "warning"),
        ("parse_error", "解析失败 / 异常", "danger"),
    )
    cards: dict[str, HciTaskCard] = {}
    for key, title, state in specs:
        card = HciTaskCard(key, title, state, cards_row)
        card.activated.connect(lambda task_key, w=window: _dashboard_task_clicked(w, task_key))
        cards_row.add_card(card)
        cards[key] = card
    window.hci_dashboard_task_cards = cards
    window.hci_dashboard_task_cards_row = cards_row
    task_layout.addWidget(cards_row)

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
        activity.set_title("当前概况")
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
        bar.show()
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

    upper = getattr(window, "left_upper_widget", None)
    filter_bar = getattr(window, "filter_bar_widget", None)
    if upper is not None:
        upper.setVisible(True)
    if filter_bar is not None:
        filter_bar.setVisible(True)

    bar = getattr(window, "hci_review_mode_bar", None)
    if bar is not None:
        bar.setProperty("active", False)
        getattr(window, "btn_hci_enter_review").show()
        getattr(window, "lbl_hci_review_progress").hide()
        getattr(window, "btn_hci_exit_review").hide()
        getattr(window, "lbl_hci_review_shortcuts").hide()
        _repolish(bar)
        bar.hide()

    preview = getattr(window, "preview_panel", None)
    if preview is not None:
        preview.setProperty("hciContinuousReview", False)
        _repolish(preview)
    detail = getattr(window, "_detail_panel", None)
    if detail is not None:
        detail.setProperty("hciContinuousReview", False)
        _repolish(detail)


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
    # The continuous-review bar only appears while the mode is active; its
    # entry point now lives in the batch menu.
    bar.hide()

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
                window._add_current_invoice_to_claim()
                if p.property("hciContinuousReview")
                and hasattr(d, "btn_add_to_claim")
                and d.btn_add_to_claim.isEnabled()
                else None
            )
        )
        window._hci_shortcut_e = shortcut_e
        window._hci_shortcut_g = shortcut_g


def _restore_import_sync_label(window) -> None:
    if getattr(window, "_shutdown_requested", False):
        return
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
    if getattr(window, "_shutdown_requested", False):
        return

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
    recorder = getattr(window, "_record_import_activity", None)
    if callable(recorder) and processed:
        try:
            failed = int(result.get("failed", 0) or 0)
            recorder("邮箱重新检查", scanned=processed, added=added, failed=failed,
                     status="failed" if failed else "complete")
        except TypeError:
            pass

    for name in ("_load_invoices", "_refresh_overview_page", "_refresh_imports_page"):
        callback = getattr(window, name, None)
        if callable(callback):
            try:
                callback()
            except Exception:
                pass

    activity = None
    pending_ids = ()
    scope_error = None
    refresh_scope = getattr(window, "_refresh_import_review_result_scope", None)
    if callable(refresh_scope):
        try:
            result = refresh_scope()
            if not isinstance(result, tuple) or len(result) != 2:
                raise TypeError(
                    "_refresh_import_review_result_scope must return "
                    "(activity, pending_ids)"
                )
            activity, pending_ids = result
            pending_ids = tuple(pending_ids or ())
        except Exception as exc:
            scope_error = exc

    review_button = getattr(window, "btn_hci_import_review_result", None)
    if review_button is not None:
        scope_error = scope_error or getattr(
            window, "_import_review_result_scope_error", None
        )
        if scope_error is not None:
            review_button.setText("审核范围暂不可用")
            review_button.setEnabled(False)
        elif activity is not None and pending_ids:
            review_button.setText(f"去审核 {len(pending_ids)} 张")
            review_button.setEnabled(True)
        else:
            review_button.setText("查看审核工作台")
            review_button.setEnabled(True)
        review_button.show()


def _history_recheck_failed(window, message: str) -> None:
    if getattr(window, "_shutdown_requested", False):
        return

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

        _begin_scan_presentation(window, "query")
    except Exception:
        window._hci_history_worker = None
        _release_history_operation(window, worker)
        worker.deleteLater()
        raise


def _release_history_operation(window, worker=None) -> None:
    if getattr(window, "_shutdown_requested", False):
        return
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


# ── HCI closure behavior (merged from hci_v1_closure) ──
def _sync_dashboard_closure(window) -> None:
    if window is None or not _qt_dispatch_allowed(window=window):
        return
    sync_hint = getattr(window, "lbl_overview_recent_imports", None)
    left_card = _section_ancestor(sync_hint)
    if left_card is not None:
        for button in left_card.findChildren(QPushButton):
            if button.text().strip() == "开始审核":
                button.hide()
                button.setEnabled(False)
                button.setProperty("hciDuplicateActionRetired", True)

    next_actions = getattr(window, "lbl_overview_next_actions", None)
    if next_actions is not None:
        next_actions.setText(
            "普通同步不会重复处理已有邮件；误删记录或需要重新识别历史附件时，使用“重新检查”。"
        )


def _install_dashboard_refresh_closure(window) -> None:
    if getattr(window, "_hci_dashboard_refresh_closure_installed", False):
        return
    original = getattr(window, "_refresh_overview_page", None)
    if not callable(original):
        return

    @wraps(original)
    def wrapped(self, *args, **kwargs):
        if not _qt_dispatch_allowed(window=self):
            return None
        result = original(*args, **kwargs)
        window_ref = weakref.ref(self)
        QTimer.singleShot(0, lambda: _sync_dashboard_closure(window_ref()))
        return result

    window._refresh_overview_page = MethodType(wrapped, window)
    window._hci_dashboard_refresh_closure_installed = True


def apply_dashboard_hci_closure(page: QWidget | None) -> None:
    """Remove legacy duplicate actions after the HCI dashboard is composed."""
    if page is None or not isValid(page) or page.property("hciV1DashboardClosureApplied"):
        return
    window = page.window()
    if page is not getattr(window, "overview_page", None):
        return
    if not page.property("hciV1DashboardApplied"):
        return

    page.setProperty("hciV1DashboardClosureApplied", True)
    _install_dashboard_refresh_closure(window)
    _sync_dashboard_closure(window)


def _focus_accepts_text() -> bool:
    widget = QApplication.focusWidget()
    return bool(widget is not None and is_keyboard_input_target(widget))


def _qt_dispatch_allowed(*, window=None, page=None) -> bool:
    """Keep deferred UI callbacks out of Qt shutdown and dead wrappers."""
    app = QApplication.instance()
    if app is None or not isValid(app) or QCoreApplication.closingDown():
        return False
    if window is not None and not isValid(window):
        return False
    if window is not None and getattr(window, "_shutdown_requested", False):
        return False
    if page is not None and not isValid(page):
        return False
    return True


def _activate_detail_action(page: QWidget, detail, attr: str) -> None:
    if page is None or not isValid(page):
        return
    window = page.window()
    if not _qt_dispatch_allowed(window=window, page=page):
        return
    if not page.property("hciContinuousReview") or _focus_accepts_text():
        return
    button = getattr(detail, attr, None)
    if button is not None and isValid(button) and button.isEnabled():
        button.click()


def _move_to_next_review_row(window) -> None:
    if window is None or not _qt_dispatch_allowed(window=window):
        return
    table = getattr(window, "table", None)
    if table is None or not isValid(table) or table.rowCount() <= 0:
        return

    # Continuous review must share the same paging boundary as the normal
    # Review workspace.  In particular, row 49 of a 50-row page is not the
    # end of a 61/259-row queue: load the next batch before selecting.
    paging = getattr(window, "review_paging", None)
    move_selection = getattr(paging, "move_selection", None)
    if callable(move_selection):
        move_selection(1)
        # “稍后处理” leaves review status unchanged, so the queue count does
        # not trigger the normal progress refresh. Update the cursor position
        # after selecting the next invoice.

        _sync_review_hci(window)
        return

    # Defensive fallback for a partially initialized page.  Never wrap to the
    # first row because that makes unseen records unreachable.
    row = max(0, table.currentRow())
    table.selectRow(min(table.rowCount() - 1, row + 1))

    _sync_review_hci(window)


def _install_review_progress_refresh(window, page: QWidget) -> None:
    """Refresh continuous-review progress after a successful DB mutation."""
    if getattr(window, "_hci_review_progress_refresh_installed", False):
        return
    original = getattr(window, "_set_selected_status", None)
    if not callable(original):
        return

    @wraps(original)
    def wrapped(self, *args, **kwargs):
        if not _qt_dispatch_allowed(window=self, page=page):
            return None
        result = original(*args, **kwargs)
        success = int((result or {}).get("success", 0) or 0) if isinstance(result, dict) else 0
        if (
            success > 0
            and _qt_dispatch_allowed(window=self, page=page)
            and page.property("hciContinuousReview")
        ):
            # _set_selected_status has already committed the mutation and
            # reloaded the filtered list when this callback is queued.
            window_ref = weakref.ref(self)
            page_ref = weakref.ref(page)
            QTimer.singleShot(
                0,
                lambda: _sync_review_progress_after_mutation(
                    window_ref(), page_ref()
                ),
            )
        return result

    window._set_selected_status = MethodType(wrapped, window)
    window._hci_review_progress_refresh_installed = True


def _sync_review_progress_after_mutation(window, page=None) -> None:
    if window is None or not _qt_dispatch_allowed(window=window, page=page):
        return

    _sync_review_hci(window)


def apply_review_hci_closure(page: QWidget | None) -> None:
    """Guard shortcuts and complete continuous-review navigation."""
    if page is None or not isValid(page) or page.property("hciV1ReviewClosureApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    detail = getattr(window, "_detail_panel", None)
    bar = getattr(window, "hci_review_mode_bar", None)
    if detail is None or bar is None:
        return

    page.setProperty("hciV1ReviewClosureApplied", True)
    _install_review_progress_refresh(window, page)

    # Disable the unguarded compatibility shortcuts created by the HCI layer.
    for attr in ("_hci_shortcut_e", "_hci_shortcut_g"):
        shortcut = getattr(window, attr, None)
        if shortcut is not None:
            shortcut.setEnabled(False)

    shortcut_e = QShortcut(QKeySequence("E"), page)
    shortcut_e.setContext(Qt.WidgetWithChildrenShortcut)
    shortcut_e.activated.connect(
        lambda p=page, d=detail: _activate_detail_action(p, d, "btn_add_evidence")
    )
    shortcut_g = QShortcut(QKeySequence("G"), page)
    shortcut_g.setContext(Qt.WidgetWithChildrenShortcut)
    shortcut_g.activated.connect(
        lambda p=page, d=detail: _activate_detail_action(p, d, "btn_add_to_claim")
    )
    window._hci_guarded_shortcut_e = shortcut_e
    window._hci_guarded_shortcut_g = shortcut_g

    btn_later = make_button("稍后处理", variant="secondary")
    btn_later.setToolTip("不改变审核状态，只切换到队列中的下一张")
    btn_later.clicked.connect(lambda: _move_to_next_review_row(window))
    btn_later.hide()
    layout = bar.layout()
    layout.insertWidget(max(0, layout.count() - 2), btn_later)
    window.btn_hci_review_later = btn_later

    window_ref = weakref.ref(window)
    page_ref = weakref.ref(page)
    btn_later_ref = weakref.ref(btn_later)

    def sync_later_visibility() -> None:
        target = window_ref()
        current_page = page_ref()
        button = btn_later_ref()
        if (
            target is None
            or current_page is None
            or button is None
            or not isValid(button)
            or not _qt_dispatch_allowed(window=target, page=current_page)
        ):
            return
        button.setVisible(bool(current_page.property("hciContinuousReview")))

    original_enter = getattr(window, "_enter_hci_continuous_review", None)
    original_exit = getattr(window, "_exit_hci_continuous_review", None)

    if callable(original_enter):
        @wraps(original_enter)
        def guarded_enter(self):
            if not _qt_dispatch_allowed(window=self, page=page):
                return None
            result = original_enter()
            sync_later_visibility()
            return result

        window._enter_hci_continuous_review = MethodType(guarded_enter, window)
        getattr(window, "btn_hci_enter_review").clicked.connect(
            lambda: QTimer.singleShot(0, sync_later_visibility)
        )

    if callable(original_exit):
        @wraps(original_exit)
        def guarded_exit(self):
            if not _qt_dispatch_allowed(window=self, page=page):
                return None
            result = original_exit()
            if isValid(btn_later):
                btn_later.hide()
            return result

        window._exit_hci_continuous_review = MethodType(guarded_exit, window)
        getattr(window, "btn_hci_exit_review").clicked.connect(btn_later.hide)


_SCAN_STAGE_LABELS = {
    "connect": "连接邮箱",
    "tls": "建立安全连接",
    "authenticate": "验证邮箱账号",
    "query": "查询新邮件",
    "query-start": "查询新邮件",
    "query-progress": "查询新邮件",
    "download": "下载附件",
    "parse": "识别票据信息",
    "save": "保存扫描结果",
}


def _format_scan_elapsed(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    if seconds >= 60:
        whole = int(seconds)
        return f"{whole // 60}分{whole % 60:02d}秒"
    return f"{seconds:.1f} 秒"


def _scan_elapsed(window) -> float:
    started = getattr(window, "_scan_started_at", None)
    if not started:
        return 0.0
    return max(0.0, time.monotonic() - started)


def _scan_failure_count(summary: dict) -> int:
    return sum(
        int(summary.get(key, 0) or 0)
        for key in ("download_failed", "parse_failed", "link_failed")
    )


def _set_scan_status_label(window, text: str) -> None:
    label = getattr(window, "lbl_import_scan_status", None)
    if label is None:
        return
    label.setWordWrap(True)
    label.setText(text)


def _render_scan_active(window, stage: str | None = None, elapsed: float | None = None) -> None:
    if not _qt_dispatch_allowed(window=window):
        return
    if getattr(window, "_hci_scan_terminal_stage", None):
        return
    window._hci_scan_presentation_state = "active"
    window._hci_scan_terminal_text = None
    stage = str(stage or getattr(window, "_hci_scan_stage_key", "connect"))
    window._hci_scan_stage_key = stage
    stage_label = _SCAN_STAGE_LABELS.get(stage, "处理扫描任务")
    if elapsed is None:
        elapsed = _scan_elapsed(window)
    _set_scan_status_label(
        window,
        f"● 正在同步\n当前阶段：{stage_label}\n已运行 {_format_scan_elapsed(elapsed)}",
    )


def _render_scan_terminal(
    window,
    terminal: str,
    *,
    elapsed: float,
    summary: dict | None = None,
    result: dict | None = None,
    reason: str = "",
) -> None:
    if not _qt_dispatch_allowed(window=window):
        return
    summary = summary or {}
    result = result or {}
    window._hci_scan_terminal_stage = terminal
    window._hci_history_terminal_card = None
    window._hci_scan_elapsed_frozen = float(elapsed)
    elapsed_text = _format_scan_elapsed(elapsed)

    if terminal == "complete":
        scanned = int(summary.get("scanned_headers") or summary.get("scanned") or 0)
        classified = int(summary.get("classified_invoice") or 0)
        failed = _scan_failure_count(summary)
        text = (
            "✓ 同步完成\n"
            f"检查邮件 {scanned} 封 · 识别发票候选 {classified} · 失败 {failed} 项\n"
            f"已运行 {elapsed_text}"
        )
        recent = getattr(window, "import_mail_recent_card", None)
        if recent is not None:
            recent.set_title("✓ 同步完成")
            recent.set_hint("本次同步结果按行展示检查、候选、新增、恢复、重复和失败数量。")
    elif terminal == "cancelled":
        counts = getattr(window, "_scan_stage_counts", {}) or {}
        processed = counts.get("processed")
        total = counts.get("total")
        handled = f"{processed} / {total} 封" if total is not None else f"{processed or 0} 封"
        text = f"同步已取消\n已处理：{handled}\n已运行 {elapsed_text}"
        recent = getattr(window, "import_mail_recent_card", None)
        if recent is not None:
            recent.set_title("同步已取消")
            recent.set_hint("本次同步已取消，已处理数量保留在结果明细中。")
    else:
        stage_label = _SCAN_STAGE_LABELS.get(
            str(getattr(window, "_hci_scan_stage_key", "")),
            "处理扫描任务",
        )
        safe_reason = str(reason or "请查看错误提示或失败明细。").strip()[:160]
        text = f"× 同步失败\n阶段：{stage_label}\n原因：{safe_reason}\n已运行 {elapsed_text}"
        recent = getattr(window, "import_mail_recent_card", None)
        if recent is not None:
            recent.set_title("× 同步失败")
            recent.set_hint("同步失败；请查看结果明细和错误提示。")

    window._hci_scan_presentation_state = terminal
    window._hci_scan_terminal_text = text
    _set_scan_status_label(window, text)


def _begin_scan_presentation(window, stage: str = "connect") -> None:
    """Enter the explicit active state for scan and history-recheck tasks."""
    if not _qt_dispatch_allowed(window=window):
        return
    window._hci_scan_terminal_stage = None
    window._hci_history_terminal_card = None
    window._hci_scan_elapsed_frozen = None
    window._hci_scan_terminal_text = None
    window._hci_scan_presentation_state = "active"
    window._hci_scan_stage_key = str(stage or "connect")
    window._scan_stage_counts = {}
    # Every explicit new task starts a fresh elapsed clock.  A previous
    # terminal run may have left the old timestamp on the window.
    window._scan_started_at = time.monotonic()
    _render_scan_active(window, window._hci_scan_stage_key)


def _render_history_recheck_terminal(window, result: dict | None = None) -> None:
    """An empty history selection is not evidence of a successful mail sync."""
    if not _qt_dispatch_allowed(window=window):
        return
    result = result or {}
    failed = int(result.get("failed", 0) or 0)
    _render_scan_terminal(
        window,
        "failed" if failed else "complete",
        elapsed=_scan_elapsed(window),
        summary={
            "scanned_headers": result.get("processed_emails", 0),
            "classified_invoice": result.get("added_or_restored", 0),
            "download_failed": result.get("failed", 0),
        },
        result=result,
    )
    processed = int(result.get("processed_emails", 0) or 0)
    added = int(result.get("added_or_restored", 0) or 0)
    if not processed:
        title = "暂无可重新检查的历史邮件"
        hint = "所选范围内没有已知邮件，本次未连接邮箱。请先补齐授权码并测试连接，再同步新邮件。"
    else:
        title = "历史重新检查存在失败" if failed else "历史重新检查完成"
        suffix = "（达到本次 200 封上限）" if result.get("limit_reached") else ""
        hint = f"处理 {processed} 封已知邮件，新增或恢复 {added} 条记录，失败 {failed} 封{suffix}。此操作不是新邮件同步。"
        if failed:
            hint += "请检查授权码、连接状态及失败日志。"
    text = f"{title}\n{hint}\n已运行 {_format_scan_elapsed(_scan_elapsed(window))}"
    window._hci_scan_terminal_text = text
    window._hci_history_terminal_card = (title, hint)
    _set_scan_status_label(window, text)
    recent = getattr(window, "import_mail_recent_card", None)
    if recent is not None:
        recent.set_title(title)
        recent.set_hint(hint)


def _render_history_recheck_failed(window, reason: str) -> None:
    """Render a history-recheck failure without losing its terminal state."""
    _render_scan_terminal(
        window,
        "failed",
        elapsed=_scan_elapsed(window),
        reason=reason,
    )


def _sync_import_scan_state(window) -> None:
    """Reapply authoritative active/terminal presentation after page refreshes."""
    if window is None or not _qt_dispatch_allowed(window=window):
        return
    state = str(getattr(window, "_hci_scan_presentation_state", "idle") or "idle")
    if state in {"complete", "failed", "cancelled"}:
        terminal_text = str(getattr(window, "_hci_scan_terminal_text", "") or "")
        if terminal_text:
            _set_scan_status_label(window, terminal_text)
        history_card = getattr(window, "_hci_history_terminal_card", None)
        recent = getattr(window, "import_mail_recent_card", None)
        if history_card and recent is not None:
            recent.set_title(history_card[0])
            recent.set_hint(history_card[1])
        return
    if state == "active":
        _render_scan_active(window)


def _sync_import_refresh_state(window) -> None:
    if window is None or not _qt_dispatch_allowed(window=window):
        return
    _sync_import_primary_bridge(window)
    _sync_import_scan_state(window)


def _install_scan_status_presentation(window) -> None:
    """Make the existing scan lifecycle legible while it is still running."""
    if getattr(window, "_hci_scan_status_presentation_installed", False):
        return
    imports_page = getattr(window, "imports_page", None)
    page_ref = weakref.ref(imports_page) if imports_page is not None else lambda: None

    original_start = getattr(window, "_scan_email_clicked", None)
    if callable(original_start):
        @wraps(original_start)
        def wrapped_start(self, *args, **kwargs):
            if not _qt_dispatch_allowed(window=self, page=page_ref()):
                return None
            result = original_start(*args, **kwargs)
            if getattr(self, "scan_worker", None) is not None:
                _begin_scan_presentation(self, "connect")
            return result

        window._scan_email_clicked = MethodType(wrapped_start, window)

    original_stage = getattr(window, "_scan_stage_updated", None)
    if callable(original_stage):
        @wraps(original_stage)
        def wrapped_stage(self, event, *args, **kwargs):
            if not _qt_dispatch_allowed(window=self, page=page_ref()):
                return None
            stage = str((event or {}).get("stage") or "") if isinstance(event, dict) else ""
            if stage not in {"complete", "failed", "cancelled"}:
                self._hci_scan_terminal_stage = None
                self._hci_scan_elapsed_frozen = None
                self._hci_scan_stage_key = stage or "connect"
            result = original_stage(event, *args, **kwargs)
            if stage not in {"complete", "failed", "cancelled"}:
                event_elapsed = (
                    int((event or {}).get("elapsed_ms") or 0) / 1000
                    if isinstance(event, dict)
                    else None
                )
                _render_scan_active(self, stage, max(_scan_elapsed(self), event_elapsed or 0.0))
            return result

        window._scan_stage_updated = MethodType(wrapped_stage, window)

    original_refresh = getattr(window, "_refresh_scan_elapsed", None)
    if callable(original_refresh):
        @wraps(original_refresh)
        def wrapped_refresh(self, *args, **kwargs):
            if not _qt_dispatch_allowed(window=self, page=page_ref()):
                return None
            result = original_refresh(*args, **kwargs)
            _sync_import_scan_state(self)
            return result

        window._refresh_scan_elapsed = MethodType(wrapped_refresh, window)

    # The application connects its elapsed timer during window construction,
    # before this closure replaces the bound method.  Add a weak overlay
    # callback so that the original timer cannot overwrite the HCI status text.
    elapsed_timer = getattr(window, "_scan_elapsed_timer", None)
    if elapsed_timer is not None:
        window_ref = weakref.ref(window)

        def refresh_status_overlay() -> None:
            target = window_ref()
            if target is not None and _qt_dispatch_allowed(
                window=target, page=page_ref()
            ):
                _render_scan_active(target)

        elapsed_timer.timeout.connect(refresh_status_overlay)
        window._hci_scan_elapsed_overlay = refresh_status_overlay

    original_finished = getattr(window, "_scan_email_finished", None)
    if callable(original_finished):
        @wraps(original_finished)
        def wrapped_finished(self, result, *args, **kwargs):
            if not _qt_dispatch_allowed(window=self, page=page_ref()):
                return None
            elapsed = _scan_elapsed(self)
            cancelled = bool(isinstance(result, dict) and result.get("cancelled"))
            outcome = original_finished(result, *args, **kwargs)
            if cancelled:
                _render_scan_terminal(
                    self,
                    "cancelled",
                    elapsed=elapsed,
                    result=result,
                )
            else:
                _render_scan_terminal(
                    self,
                    "complete",
                    elapsed=elapsed,
                    summary=getattr(self, "_last_scan_summary", {}) or {},
                    result=result,
                )
            return outcome

        window._scan_email_finished = MethodType(wrapped_finished, window)

    original_error = getattr(window, "_scan_email_error", None)
    if callable(original_error):
        @wraps(original_error)
        def wrapped_error(self, message, *args, **kwargs):
            if not _qt_dispatch_allowed(window=self, page=page_ref()):
                return None
            elapsed = _scan_elapsed(self)
            outcome = original_error(message, *args, **kwargs)
            _render_scan_terminal(
                self,
                "failed",
                elapsed=elapsed,
                reason=str(message or ""),
            )
            return outcome

        window._scan_email_error = MethodType(wrapped_error, window)

    window._hci_scan_status_presentation_installed = True


class _LegacyScanBridgeFilter(QObject):
    """Mirror enabled state from the hidden stable scan control to HCI CTA."""

    def __init__(self, window, legacy: QPushButton, visible: QPushButton):
        super().__init__(window)
        self._window_ref = weakref.ref(window)
        self._legacy_ref = weakref.ref(legacy)
        self._visible_ref = weakref.ref(visible)

    def eventFilter(self, watched, event):
        legacy = self._legacy_ref()
        visible = self._visible_ref()
        if legacy is None or visible is None:
            return False
        if watched is legacy and event.type() == QEvent.EnabledChange:
            visible.setEnabled(legacy.isEnabled())
        return False


def _sync_import_primary_bridge(window) -> None:
    if window is None or not _qt_dispatch_allowed(window=window):
        return
    legacy = getattr(window, "btn_import_scan_selected", None)
    visible = getattr(window, "btn_hci_sync_new_mail", None)
    if (
        legacy is None
        or visible is None
        or not isValid(legacy)
        or not isValid(visible)
    ):
        return

    missing_auth = legacy.text().strip() == "补授权码"
    if missing_auth:
        visible.setText("补授权码")
        visible.setToolTip("先补齐所选邮箱的授权码，再开始同步")
    else:
        # Preserve the established programmatic control contract while the user
        # interacts only with the HCI button.
        legacy.setText("开始扫描")
        visible.setText("同步新邮件")
        visible.setToolTip("只检查上次同步之后的新邮件")
    visible.setEnabled(legacy.isEnabled())
    legacy.hide()


def _install_import_primary_bridge(window) -> None:
    if getattr(window, "_hci_import_primary_bridge_installed", False):
        _sync_import_primary_bridge(window)
        return

    legacy = getattr(window, "btn_import_scan_selected", None)
    command = getattr(window, "import_mail_command_bar", None)
    recheck = getattr(window, "btn_hci_import_recheck", None)
    if legacy is None or command is None or recheck is None:
        return

    visible = make_button("同步新邮件", variant="primary")
    window_ref = weakref.ref(window)
    legacy_ref = weakref.ref(legacy)

    def forward_scan() -> None:
        target = window_ref()
        stable_control = legacy_ref()
        if (
            target is None
            or stable_control is None
            or not isValid(stable_control)
            or not _qt_dispatch_allowed(window=target)
        ):
            return
        stable_control.click()
        QTimer.singleShot(0, lambda: _sync_import_primary_bridge(window_ref()))

    visible.clicked.connect(forward_scan)
    window.btn_hci_sync_new_mail = visible

    cancel = getattr(window, "btn_import_scan_cancel", None)
    secondary = [recheck]
    if cancel is not None:
        secondary.append(cancel)
    command.set_actions(
        primary_action=visible,
        secondary_actions=secondary,
        more_menu=getattr(window, "import_mail_more", None),
    )

    bridge_filter = _LegacyScanBridgeFilter(window, legacy, visible)
    legacy.installEventFilter(bridge_filter)
    window._hci_import_primary_bridge_filter = bridge_filter
    window._hci_import_primary_bridge_installed = True
    _sync_import_primary_bridge(window)


def _install_import_refresh_bridge(window) -> None:
    if getattr(window, "_hci_import_refresh_bridge_installed", False):
        return
    original = getattr(window, "_refresh_imports_page", None)
    if not callable(original):
        return

    @wraps(original)
    def wrapped(self, *args, **kwargs):
        if not _qt_dispatch_allowed(window=self):
            return None
        result = original(*args, **kwargs)
        window_ref = weakref.ref(self)
        QTimer.singleShot(0, lambda: _sync_import_refresh_state(window_ref()))
        return result

    window._refresh_imports_page = MethodType(wrapped, window)
    window._hci_import_refresh_bridge_installed = True


def _sync_incremental_result(window, res: dict) -> None:
    if window is None or not _qt_dispatch_allowed(window=window):
        return
    if bool((res or {}).get("cancelled")):
        _sync_import_primary_bridge(window)
        return
    _sync_import_primary_bridge(window)

    recent = getattr(window, "import_mail_recent_card", None)
    if recent is not None:
        recent.set_title("✓ 同步完成")
        recent.set_hint("本次同步结果按行展示检查、候选、新增、恢复、重复和失败数量。")

    activity = None
    pending_ids = ()
    scope_error = None
    refresh_scope = getattr(window, "_refresh_import_review_result_scope", None)
    if callable(refresh_scope):
        try:
            result = refresh_scope()
            if not isinstance(result, tuple) or len(result) != 2:
                raise TypeError(
                    "_refresh_import_review_result_scope must return "
                    "(activity, pending_ids)"
                )
            activity, pending_ids = result
            pending_ids = tuple(pending_ids or ())
        except Exception as exc:
            scope_error = exc
    review = getattr(window, "btn_hci_import_review_result", None)
    if review is not None:
        scope_error = scope_error or getattr(
            window, "_import_review_result_scope_error", None
        )
        if scope_error is not None:
            review.setText("审核范围暂不可用")
            review.setEnabled(False)
        elif activity is not None and pending_ids:
            review.setText(f"去审核 {len(pending_ids)} 张")
            review.setEnabled(True)
        else:
            review.setText("查看审核工作台")
            review.setEnabled(True)
        review.show()


def _install_scan_finish_closure(window) -> None:
    if getattr(window, "_hci_scan_finish_closure_installed", False):
        return
    original = getattr(window, "_scan_email_finished", None)
    if not callable(original):
        return
    imports_page = getattr(window, "imports_page", None)
    page_ref = weakref.ref(imports_page) if imports_page is not None else lambda: None

    @wraps(original)
    def wrapped(self, res):
        if not _qt_dispatch_allowed(window=self, page=page_ref()):
            return None
        result = original(res)
        window_ref = weakref.ref(self)
        QTimer.singleShot(
            0,
            lambda: _sync_incremental_result(window_ref(), res or {}),
        )
        return result

    window._scan_email_finished = MethodType(wrapped, window)
    window._hci_scan_finish_closure_installed = True


def _running_history_worker(window):
    worker = getattr(window, "_hci_history_worker", None)
    if worker is not None and isValid(worker) and worker.isRunning():
        return worker
    for thread in window.findChildren(QThread):
        if thread.__class__.__name__ == "HistoryRecheckWorker" and thread.isRunning():
            return thread
    return None


class _HistoryCloseFilter(QObject):
    def __init__(self, window):
        super().__init__(window)
        self._window_ref = weakref.ref(window)

    def eventFilter(self, watched, event):
        window = self._window_ref()
        if window is None:
            return False
        if watched is window and event.type() == QEvent.Close:
            if _running_history_worker(window) is not None:
                event.ignore()
                status_bar = window.statusBar()
                if status_bar is not None:
                    status_bar.showMessage(
                        "正在重新检查历史邮件；为避免中断数据库写入，请等待任务完成后再关闭。",
                        6000,
                    )
                return True
        return False


def _install_history_delete_later_guard() -> None:
    """Delay deletion of a history QThread until its native thread has exited."""


    if getattr(HistoryRecheckWorker, "_hci_safe_delete_installed", False):
        return

    original_delete_later = HistoryRecheckWorker.deleteLater

    def safe_delete_later(self):
        if self.isRunning():
            if not self.property("hciDeleteAfterFinished"):
                self.setProperty("hciDeleteAfterFinished", True)
                worker_ref = weakref.ref(self)

                def delete_after_finished() -> None:
                    worker = worker_ref()
                    if (
                        worker is not None
                        and isValid(worker)
                        and not QCoreApplication.closingDown()
                    ):
                        original_delete_later(worker)

                self.finished.connect(delete_after_finished)
            return
        if isValid(self) and not QCoreApplication.closingDown():
            original_delete_later(self)

    HistoryRecheckWorker.deleteLater = safe_delete_later
    HistoryRecheckWorker._hci_safe_delete_installed = True


def _install_history_close_guard(window) -> None:
    if getattr(window, "_hci_history_close_guard_installed", False):
        return
    _install_history_delete_later_guard()
    close_filter = _HistoryCloseFilter(window)
    window.installEventFilter(close_filter)
    window._hci_history_close_filter = close_filter
    window._hci_history_close_guard_installed = True


def apply_import_hci_closure(page: QWidget | None) -> None:
    """Close incremental-sync and history-worker lifecycle gaps."""
    if page is None or not isValid(page) or page.property("hciV1ImportClosureApplied"):
        return
    window = page.window()
    if page is not getattr(window, "imports_page", None):
        return
    if not page.property("hciV1ImportApplied"):
        return

    page.setProperty("hciV1ImportClosureApplied", True)
    if not hasattr(window, "_hci_scan_presentation_state"):
        window._hci_scan_presentation_state = "idle"
    recent = getattr(window, "import_mail_recent_card", None)
    if recent is not None:
        recent.set_title("本次运行")
        recent.set_hint("完成一次同步后，结果会按行展示真实处理数量。")
    _install_import_primary_bridge(window)
    _install_import_refresh_bridge(window)
    _install_scan_status_presentation(window)
    _install_scan_finish_closure(window)
    _install_history_close_guard(window)
    _sync_import_scan_state(window)


def apply_task_flow_hci_closure(page: QWidget | None) -> None:
    if page is None or not isValid(page):
        return
    window = page.window()
    if page is getattr(window, "imports_page", None):
        apply_import_hci_closure(page)


def schedule_dashboard_hci_closure(page: QWidget | None) -> None:
    if (
        page is None
        or not isValid(page)
        or not _qt_dispatch_allowed(window=page.window(), page=page)
    ):
        return
    page_ref = weakref.ref(page)

    def run() -> None:
        target = page_ref()
        if (
            target is not None
            and isValid(target)
            and _qt_dispatch_allowed(window=target.window(), page=target)
        ):
            apply_dashboard_hci_closure(target)

    QTimer.singleShot(0, run)


def schedule_task_flow_hci_closure(page: QWidget | None) -> None:
    if (
        page is None
        or not isValid(page)
        or not _qt_dispatch_allowed(window=page.window(), page=page)
    ):
        return
    page_ref = weakref.ref(page)

    def run() -> None:
        target = page_ref()
        if (
            target is not None
            and isValid(target)
            and _qt_dispatch_allowed(window=target.window(), page=target)
        ):
            apply_task_flow_hci_closure(target)

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
    "apply_dashboard_hci_closure",
    "apply_import_hci_closure",
    "apply_review_hci_closure",
    "apply_task_flow_hci_closure",
    "schedule_dashboard_hci_closure",
    "schedule_task_flow_hci_closure",
    "_render_scan_active",
    "_render_scan_terminal",
]
