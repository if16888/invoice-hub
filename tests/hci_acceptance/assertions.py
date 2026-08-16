"""Cross-oracle assertion functions for HCI acceptance scenarios.

Each assertion compares backend (DB) state with visible UI (Qt widget)
state and raises AssertionError with detailed evidence on mismatch.
"""

from __future__ import annotations

from scripts.invoice_fetch import review_status

from .harness import (
    db_status_counts,
    ui_filter_badge_counts,
    ui_current_invoice_id,
    ui_table_selected_id,
)


def assert_status_counts_consistent(db, window, context: str = "") -> None:
    """Assert that DB status counts exactly match UI filter badge counts.

    This is the fundamental cross-oracle invariant: the visible badge
    numbers must reflect the true database state at all times.
    """
    backend = db_status_counts(db)
    ui = ui_filter_badge_counts(window)

    mismatches = []
    for key in [review_status.TO_REVIEW, review_status.APPROVED,
                review_status.IGNORED, review_status.ERROR, "all"]:
        db_val = backend.get(key, -1)
        ui_val = ui.get(key, -1)
        if db_val != ui_val:
            mismatches.append(f"{key}: DB={db_val} UI={ui_val}")

    if mismatches:
        prefix = f"[{context}] " if context else ""
        raise AssertionError(
            f"{prefix}Status count mismatch between DB and UI badges:\n"
            + "\n".join(f"  {m}" for m in mismatches)
            + f"\n  Full DB: {backend}\n  Full UI: {ui}"
        )


def assert_selection_consistent(window, context: str = "") -> None:
    """Assert that the table selection and current_invoice agree.

    The table's selected row ID must match window.current_invoice["id"].
    """
    table_id = ui_table_selected_id(window)
    model_id = ui_current_invoice_id(window)

    if table_id is None and model_id is None:
        return  # Both empty is consistent

    if table_id != model_id:
        prefix = f"[{context}] " if context else ""
        raise AssertionError(
            f"{prefix}Selection inconsistency:\n"
            f"  table selected ID: {table_id}\n"
            f"  current_invoice ID: {model_id}"
        )


def assert_db_status_count(db, status: str, expected: int, context: str = "") -> None:
    """Assert a specific DB status count equals expected value."""
    actual = db.count_invoices_for_status(status=status, include_deleted=False)
    if actual != expected:
        prefix = f"[{context}] " if context else ""
        raise AssertionError(
            f"{prefix}DB count for {status}: expected={expected}, actual={actual}"
        )


def assert_ui_badge_count(window, status_key: str, expected: int, context: str = "") -> None:
    """Assert a specific UI badge count equals expected value."""
    counts = ui_filter_badge_counts(window)
    actual = counts.get(status_key, -1)
    if actual != expected:
        prefix = f"[{context}] " if context else ""
        raise AssertionError(
            f"{prefix}UI badge for {status_key}: expected={expected}, actual={actual}"
        )


def assert_scan_terminal(window, context: str = "") -> None:
    """Assert that the scan UI is in a terminal state (not active)."""
    text = ""
    lbl = getattr(window, "lbl_import_scan_status", None)
    if lbl is not None:
        text = lbl.text()

    # Terminal states should not contain active indicators
    active_indicators = ["准备连接", "正在"]
    for indicator in active_indicators:
        if indicator in text:
            prefix = f"[{context}] " if context else ""
            raise AssertionError(
                f"{prefix}Scan status appears active but should be terminal:\n"
                f"  text: {text}"
            )


def assert_scan_active(window, context: str = "") -> None:
    """Assert that the scan UI shows an active (non-terminal) state."""
    text = ""
    lbl = getattr(window, "lbl_import_scan_status", None)
    if lbl is not None:
        text = lbl.text()

    # Active states should contain stage info and elapsed time
    terminal_stages = ["完成", "失败", "已取消", "未开始"]
    for stage in terminal_stages:
        if stage in text:
            prefix = f"[{context}] " if context else ""
            raise AssertionError(
                f"{prefix}Scan status appears terminal but should be active:\n"
                f"  text: {text}"
            )


def assert_no_residual_threads(window, context: str = "") -> list[str]:
    """Assert no QThreads are still running. Returns empty list on success."""
    from .harness import find_running_qthreads
    running = find_running_qthreads(window)
    if running:
        prefix = f"[{context}] " if context else ""
        raise AssertionError(
            f"{prefix}Residual running QThreads: {running}"
        )
    return running
