"""Final safety and lifecycle closure for Invoice Hub HCI v1.0.

This stage runs after the visual/HCI migrations. It owns interaction details
that must remain fail-safe regardless of later compatibility changes:
- dashboard exposes one review CTA instead of duplicate legacy actions;
- dashboard task-language remains stable after data refreshes;
- single-key review shortcuts never fire while editing text;
- continuous review exposes a truthful "稍后处理" navigation action;
- visible mailbox sync uses HCI language while the legacy scan control remains
  a stable hidden execution interface;
- incremental mailbox sync ends with an actionable result;
- a running history re-check cannot be destroyed or interrupted by window close.
"""

from __future__ import annotations

import time
import weakref
from functools import wraps
from types import MethodType

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Qt, QTimer
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
    row = max(0, table.currentRow())
    next_row = row + 1
    if next_row >= table.rowCount():
        next_row = 0
    table.selectRow(next_row)


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
    from .hci_v1 import _sync_review_hci

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
    elif terminal == "cancelled":
        counts = getattr(window, "_scan_stage_counts", {}) or {}
        processed = counts.get("processed")
        total = counts.get("total")
        handled = f"{processed} / {total} 封" if total is not None else f"{processed or 0} 封"
        text = f"同步已取消\n已处理：{handled}\n已运行 {elapsed_text}"
        recent = getattr(window, "import_mail_recent_card", None)
        if recent is not None:
            recent.set_title("同步已取消")
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

    _set_scan_status_label(window, text)


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
            self._hci_scan_terminal_stage = None
            self._hci_scan_elapsed_frozen = None
            self._hci_scan_stage_key = "connect"
            return original_start(*args, **kwargs)

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
            _render_scan_active(self)
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
        QTimer.singleShot(0, lambda: _sync_import_primary_bridge(window_ref()))
        return result

    window._refresh_imports_page = MethodType(wrapped, window)
    window._hci_import_refresh_bridge_installed = True


def _sync_incremental_result(window, res: dict) -> None:
    if window is None or not _qt_dispatch_allowed(window=window):
        return
    if bool((res or {}).get("cancelled")):
        _sync_import_primary_bridge(window)
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

    _sync_import_primary_bridge(window)

    recent = getattr(window, "import_mail_recent_card", None)
    if recent is not None:
        recent.set_title("✓ 同步完成")
        failed = _scan_failure_count(summary)
        recent.set_hint(
            f"检查邮件 {scanned} 封；识别发票候选 {int(summary.get('classified_invoice', 0) or 0)}；"
            f"新增 {new}，恢复 {restored}，已存在/重复 {duplicates}，失败 {failed} 项。"
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
    from .hci_v1 import HistoryRecheckWorker

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
    recent = getattr(window, "import_mail_recent_card", None)
    if recent is not None:
        recent.set_title("本次运行")
        recent.set_hint("同步结果会说明检查范围、找到多少票据，以及下一步可以做什么。")
    _install_import_primary_bridge(window)
    _install_import_refresh_bridge(window)
    _install_scan_status_presentation(window)
    _install_scan_finish_closure(window)
    _install_history_close_guard(window)


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
    "apply_dashboard_hci_closure",
    "apply_import_hci_closure",
    "apply_review_hci_closure",
    "apply_task_flow_hci_closure",
    "schedule_dashboard_hci_closure",
    "schedule_task_flow_hci_closure",
]
