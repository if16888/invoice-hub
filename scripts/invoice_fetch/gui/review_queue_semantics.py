"""Keep import-review scope, continuous-review progress, and retry semantics aligned.

This module consolidates three user-facing interaction contracts without adding
another compatibility/closure layer:

* an import result CTA reviews the live invoices from that import batch;
* continuous review separates cursor position from the number still pending;
* a missing original can be re-fetched from either a direct URL or its source
  mailbox through the existing general redownload pipeline.
"""

from __future__ import annotations

import weakref
from functools import wraps
from types import MethodType

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from ..config import RUNTIME_DIR
from ..review_status import TO_REVIEW
from .helpers import resolve_stored_path


def _query_remaining(window) -> int:
    state_factory = getattr(window, "_review_view_state", None)
    if callable(state_factory):
        try:
            return max(0, int(state_factory().query_total))
        except Exception:
            pass
    table = getattr(window, "table", None)
    if table is not None:
        try:
            return max(0, int(table.rowCount()))
        except Exception:
            pass
    return 0


def _review_progress_text(window) -> str:
    """Describe queue position and pending count as two distinct concepts."""
    remaining = _query_remaining(window)
    initial = int(getattr(window, "_hci_review_initial_total", 0) or 0)
    if initial <= 0 or remaining > initial:
        initial = remaining

    if initial <= 0:
        return "当前没有待审核发票"
    if remaining <= 0:
        return f"{initial} / {initial} · 本轮已完成"

    table = getattr(window, "table", None)
    row = 0
    if table is not None:
        try:
            row = max(0, int(table.currentRow()))
        except Exception:
            row = 0
    processed = max(0, initial - remaining)
    current = min(initial, processed + row + 1)
    scope_prefix = "本批" if tuple(getattr(window, "_review_scope_ids", ()) or ()) else "当前"
    return f"第 {current} / {initial} 张 · {scope_prefix}还剩 {remaining} 张待审核"


def _run_enter_preserving_explicit_scope(window, enter):
    """Enter HCI focus mode without letting it replace an explicit batch query."""
    scope_ids = tuple(getattr(window, "_review_scope_ids", ()) or ())
    changer = getattr(window, "_change_filter", None)
    if not scope_ids or not callable(changer):
        return enter()

    def preserve_scope(self, status):
        if status == TO_REVIEW and tuple(getattr(self, "_review_scope_ids", ()) or ()):
            return None
        return changer(status)

    window._change_filter = MethodType(preserve_scope, window)
    try:
        return enter()
    finally:
        window._change_filter = changer


def _install_review_progress_semantics(window) -> None:
    if getattr(window, "_review_queue_progress_semantics_installed", False):
        return

    # _sync_review_hci resolves the module function at call time. Replacing the
    # formatter keeps one rendering path instead of stacking another label
    # updater on top of HCI v1.
    from . import hci_v1

    hci_v1._review_progress_text = _review_progress_text

    original_enter = getattr(window, "_enter_hci_continuous_review", None)
    if callable(original_enter):
        @wraps(original_enter)
        def enter_with_queue_total(self):
            result = _run_enter_preserving_explicit_scope(self, original_enter)
            # At this point the authoritative Review query is already active, so
            # query_total truthfully reflects either the import scope or the full
            # pending queue.
            self._hci_review_initial_total = _query_remaining(self)
            hci_v1._sync_review_hci(self)
            return result

        window._enter_hci_continuous_review = MethodType(enter_with_queue_total, window)

    window._review_queue_progress_semantics_installed = True


def _original_file_is_available(invoice: dict | None) -> bool:
    invoice = invoice or {}
    raw_path = str(invoice.get("attachment_path") or "").strip()
    if not raw_path:
        return False
    try:
        path = resolve_stored_path(raw_path, RUNTIME_DIR)
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with path.open("rb") as handle:
            handle.read(10)
        return True
    except Exception:
        return False


def _has_redownload_source(invoice: dict | None) -> bool:
    invoice = invoice or {}
    if _original_file_is_available(invoice):
        return False
    if str(invoice.get("download_url") or "").strip():
        return True
    return bool(str(invoice.get("mail_uid") or "").strip())


def _show_retry_as_primary(window) -> None:
    detail = getattr(window, "_detail_panel", None)
    invoice = getattr(window, "current_invoice", None) or {}
    if detail is None or not _has_redownload_source(invoice):
        return

    retry = getattr(detail, "btn_retry_download", None)
    supplement = getattr(detail, "btn_add_attachment", None)
    status_line = getattr(detail, "original_status_line", None)
    if retry is None or status_line is None:
        return

    # MaterialStatusLine owns primary-action placement. Keep manual supplement
    # available as a secondary escape hatch rather than replacing it.
    set_action = getattr(status_line, "set_action", None)
    if callable(set_action):
        set_action(retry)
    retry.setText("重新下载")
    retry.setToolTip("从原始下载链接或来源邮件重新获取发票原件")
    retry.setEnabled(getattr(window, "_redownload_worker", None) is None)
    retry.show()

    if supplement is not None:
        supplement.setText("补充原件")
        layout = status_line.layout()
        if layout is not None and layout.indexOf(supplement) < 0:
            layout.addWidget(supplement)
        supplement.show()


def _retry_current_invoice(window) -> None:
    """Use the established batch pipeline for both URL and mailbox re-fetch."""
    if not _has_redownload_source(getattr(window, "current_invoice", None)):
        return
    table = getattr(window, "table", None)
    if table is not None:
        try:
            row = int(table.currentRow())
            if row >= 0:
                table.selectRow(row)
        except Exception:
            pass
    runner = getattr(window, "_redownload_selected_invoices", None)
    if callable(runner):
        runner()


def _install_redownload_semantics(window) -> None:
    if getattr(window, "_review_redownload_semantics_installed", False):
        return
    detail = getattr(window, "_detail_panel", None)
    if detail is None:
        return

    retry = getattr(detail, "btn_retry_download", None)
    if retry is not None:
        try:
            retry.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        window_ref = weakref.ref(window)
        retry.clicked.connect(
            lambda _checked=False, ref=window_ref: (
                _retry_current_invoice(ref()) if ref() is not None and isValid(ref()) else None
            )
        )

    original_attachment_state = getattr(detail, "set_attachment_state", None)
    if callable(original_attachment_state):
        @wraps(original_attachment_state)
        def set_attachment_state_with_source_retry(*args, **kwargs):
            result = original_attachment_state(*args, **kwargs)
            _show_retry_as_primary(window)
            return result

        detail.set_attachment_state = set_attachment_state_with_source_retry

    original_sync = getattr(window, "_sync_redownload_entry_state", None)
    if callable(original_sync):
        @wraps(original_sync)
        def sync_redownload_entry_state(self, *args, **kwargs):
            result = original_sync(*args, **kwargs)
            _show_retry_as_primary(self)
            return result

        window._sync_redownload_entry_state = MethodType(sync_redownload_entry_state, window)

    _show_retry_as_primary(window)
    window._review_redownload_semantics_installed = True


def apply_review_queue_semantics(page: QWidget | None) -> None:
    """Apply final Review semantics after the existing HCI stages."""
    if page is None or not isValid(page) or page.property("reviewQueueSemanticsApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    _install_review_progress_semantics(window)
    _install_redownload_semantics(window)
    page.setProperty("reviewQueueSemanticsApplied", True)


def _enter_current_review_queue(window) -> None:
    if window is None or not isValid(window):
        return
    enter = getattr(window, "_enter_hci_continuous_review", None)
    if callable(enter):
        enter()


def _open_import_result_review(window) -> None:
    """Prefer the latest live import scope; fall back to the full review queue."""
    if window is None or not isValid(window):
        return

    activity = None
    latest = getattr(window, "_latest_new_invoice_activity", None)
    if callable(latest):
        activity = latest()
    pending_ids: tuple[int, ...] = ()
    remaining = getattr(window, "_remaining_review_ids", None)
    if activity is not None and callable(remaining):
        try:
            pending_ids = tuple(remaining(activity) or ())
        except Exception:
            pending_ids = ()

    if pending_ids:
        opener = getattr(window, "_open_new_invoice_review", None)
        if callable(opener):
            opener()
            window_ref = weakref.ref(window)
            QTimer.singleShot(0, lambda: _enter_current_review_queue(window_ref()))
            return

    # No actionable rows from the latest import: the CTA is intentionally a
    # generic "查看审核工作台" entry instead of pretending a batch still exists.
    from .hci_v1 import _switch_to_review

    _switch_to_review(window, TO_REVIEW, continuous=True)


def apply_import_review_scope_semantics(page: QWidget | None) -> None:
    if page is None or not isValid(page) or page.property("importReviewScopeSemanticsApplied"):
        return
    window = page.window()
    if page is not getattr(window, "imports_page", None):
        return

    # The import HCI layer creates/replaces the visible result CTA and its
    # closure owns the final post-scan wiring. Never bind before that owner has
    # settled, otherwise a later HCI callback can restore the legacy full-queue
    # handler and turn "去审核 N 张" back into the whole historical queue.
    if not page.property("hciV1ImportClosureApplied"):
        page_ref = weakref.ref(page)
        QTimer.singleShot(0, lambda: apply_import_review_scope_semantics(page_ref()))
        return

    button = getattr(window, "btn_hci_import_review_result", None)
    if button is None:
        page_ref = weakref.ref(page)
        QTimer.singleShot(0, lambda: apply_import_review_scope_semantics(page_ref()))
        return

    try:
        button.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    window_ref = weakref.ref(window)
    button.clicked.connect(
        lambda _checked=False, ref=window_ref: _open_import_result_review(ref())
    )
    page.setProperty("importReviewScopeSemanticsApplied", True)


def schedule_task_flow_review_scope_semantics(page: QWidget | None) -> None:
    if page is None or not isValid(page):
        return
    page_ref = weakref.ref(page)
    QTimer.singleShot(0, lambda: apply_import_review_scope_semantics(page_ref()))


__all__ = [
    "apply_import_review_scope_semantics",
    "apply_review_queue_semantics",
    "schedule_task_flow_review_scope_semantics",
]
