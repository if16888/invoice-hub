"""Final safety and lifecycle closure for Invoice Hub HCI v1.0.

This stage runs after the visual/HCI migrations. It owns interaction details
that must remain fail-safe regardless of later compatibility changes:
- dashboard exposes one review CTA instead of duplicate legacy actions;
- dashboard task-language remains stable after data refreshes;
- single-key review shortcuts never fire while editing text;
- continuous review exposes a truthful "稍后处理" navigation action;
- incremental mailbox sync ends with an actionable result;
- a running history re-check cannot be destroyed or interrupted by window close.
"""

from __future__ import annotations

import weakref
from functools import wraps
from types import MethodType

from PySide6.QtCore import QEvent, QObject, QThread, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from shiboken6 import isValid

from .ui_components import SectionCard, make_button
from .workbench_state import is_keyboard_input_target


def _section_ancestor(widget: QWidget | None) -> SectionCard | None:
    current = widget
    while current is not None:
        if isinstance(current, SectionCard):
            return current
        current = current.parentWidget()
    return None


def _sync_dashboard_closure(window) -> None:
    if not isValid(window):
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
        result = original(*args, **kwargs)
        QTimer.singleShot(0, lambda: _sync_dashboard_closure(self))
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


def _activate_detail_action(page: QWidget, detail, attr: str) -> None:
    if not page.property("hciContinuousReview") or _focus_accepts_text():
        return
    button = getattr(detail, attr, None)
    if button is not None and button.isEnabled():
        button.click()


def _move_to_next_review_row(window) -> None:
    table = getattr(window, "table", None)
    if table is None or table.rowCount() <= 0:
        return
    row = max(0, table.currentRow())
    next_row = row + 1
    if next_row >= table.rowCount():
        next_row = 0
    table.selectRow(next_row)


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

    original_enter = getattr(window, "_enter_hci_continuous_review", None)
    original_exit = getattr(window, "_exit_hci_continuous_review", None)

    if callable(original_enter):
        @wraps(original_enter)
        def guarded_enter(self):
            result = original_enter()
            btn_later.setVisible(bool(page.property("hciContinuousReview")))
            return result

        window._enter_hci_continuous_review = MethodType(guarded_enter, window)
        # The button was connected before the method wrapper above. Keep its
        # existing business callback and synchronize the closure UI afterwards.
        getattr(window, "btn_hci_enter_review").clicked.connect(
            lambda: QTimer.singleShot(
                0, lambda: btn_later.setVisible(bool(page.property("hciContinuousReview")))
            )
        )

    if callable(original_exit):
        @wraps(original_exit)
        def guarded_exit(self):
            result = original_exit()
            btn_later.hide()
            return result

        window._exit_hci_continuous_review = MethodType(guarded_exit, window)
        getattr(window, "btn_hci_exit_review").clicked.connect(btn_later.hide)


def _sync_incremental_result(window, res: dict) -> None:
    if bool((res or {}).get("cancelled")):
        return
    summary = getattr(window, "_last_scan_summary", None) or {}
    scanned = int(
        summary.get("scanned_headers")
        or summary.get("scanned")
        or summary.get("checked")
        or 0
    )
    new = int(
        summary.get("new_records")
        or summary.get("new")
        or summary.get("new_email_headers")
        or 0
    )
    restored = int(summary.get("restored") or 0)
    duplicates = int(summary.get("duplicates") or 0)

    primary = getattr(window, "btn_import_scan_selected", None)
    if primary is not None and primary.text() != "补授权码":
        primary.setText("同步新邮件")
        primary.setToolTip("只检查上次同步之后的新邮件")

    recent = getattr(window, "import_mail_recent_card", None)
    if recent is not None:
        recent.set_hint(
            f"同步完成：检查 {scanned} 封邮件；新增 {new}，恢复 {restored}，"
            f"已存在/重复 {duplicates}。"
        )

    review = getattr(window, "btn_hci_import_review_result", None)
    if review is not None:
        actionable = new + restored
        review.setText(f"去审核 {actionable} 张" if actionable else "查看审核工作台")
        review.show()


def _install_scan_finish_closure(window) -> None:
    if getattr(window, "_hci_scan_finish_closure_installed", False):
        return
    original = getattr(window, "_scan_email_finished", None)
    if not callable(original):
        return

    @wraps(original)
    def wrapped(self, res):
        result = original(res)
        QTimer.singleShot(0, lambda: _sync_incremental_result(self, res or {}))
        return result

    window._scan_email_finished = MethodType(wrapped, window)
    window._hci_scan_finish_closure_installed = True


def _running_history_worker(window):
    worker = getattr(window, "_hci_history_worker", None)
    if worker is not None and isValid(worker) and worker.isRunning():
        return worker
    # Result callbacks may clear the convenience attribute a fraction before the
    # QThread emits its built-in finished signal. Search parented workers too so
    # close remains fail-safe during that handoff.
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
    from .hci_v1 import HistoryRecheckWorker

    if getattr(HistoryRecheckWorker, "_hci_safe_delete_installed", False):
        return

    original_delete_later = HistoryRecheckWorker.deleteLater

    def safe_delete_later(self):
        if self.isRunning():
            if not self.property("hciDeleteAfterFinished"):
                self.setProperty("hciDeleteAfterFinished", True)
                self.finished.connect(lambda worker=self: original_delete_later(worker))
            return
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
    _install_scan_finish_closure(window)
    _install_history_close_guard(window)


def apply_task_flow_hci_closure(page: QWidget | None) -> None:
    if page is None or not isValid(page):
        return
    window = page.window()
    if page is getattr(window, "imports_page", None):
        apply_import_hci_closure(page)


def schedule_dashboard_hci_closure(page: QWidget | None) -> None:
    if page is None or not isValid(page):
        return
    page_ref = weakref.ref(page)

    def run() -> None:
        target = page_ref()
        if target is not None and isValid(target):
            apply_dashboard_hci_closure(target)

    QTimer.singleShot(0, run)


def schedule_task_flow_hci_closure(page: QWidget | None) -> None:
    if page is None or not isValid(page):
        return
    page_ref = weakref.ref(page)

    def run() -> None:
        target = page_ref()
        if target is not None and isValid(target):
            apply_task_flow_hci_closure(target)

    QTimer.singleShot(0, run)


__all__ = [
    "apply_dashboard_hci_closure",
    "apply_import_hci_closure",
    "apply_review_hci_closure",
    "apply_task_flow_hci_closure",
    "schedule_dashboard_hci_closure",
    "schedule_task_flow_hci_closure",
]
