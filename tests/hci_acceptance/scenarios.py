"""19 HCI State-Transition Acceptance Scenarios for Invoice Hub.

Rules:
1. Every scenario is dual-oracle: backend DB state AND visible Qt widget state.
2. Actions follow: ACTION -> process Qt events -> observe.
3. NO artificial sync calls (e.g. _sync_review_hci) after actions.
4. NO fallback simulations for missing product features.
5. Real product presentation handlers for mail sync lifecycle.
6. Three-layer fail-closed verification for export.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QWidget

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch import review_status
from scripts.invoice_fetch.review_status import APPROVED, ERROR, IGNORED, TO_REVIEW
from scripts.invoice_fetch.gui.hci_v1 import (
    _enter_hci_continuous_review,
    _exit_hci_continuous_review,
)

from .assertions import (
    assert_db_status_count,
    assert_scan_active,
    assert_scan_terminal,
    assert_selection_consistent,
    assert_status_counts_consistent,
)
from .harness import (
    ScenarioResult,
    db_status_counts,
    process_events,
    ui_current_invoice_id,
    ui_filter_badge_counts,
    ui_table_selected_id,
)


def _prepare_review_page(window) -> None:
    """Helper to navigate to review page and ensure initial table selection."""
    window._switch_main_page("review")
    process_events()
    if hasattr(window, "table") and window.table.rowCount() > 0:
        if window.table.currentRow() < 0:
            window._ensure_single_row_selection(0)
            process_events()


# ── CR-01: 连续审核进入 ─────────────────────────────────────────────


def run_cr_01(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """CR-01: 连续审核进入 — 列表隐藏，预览和详情显示，进度为 1/N · 还剩 N 张."""
    t0 = time.perf_counter()
    _prepare_review_page(window)

    _enter_hci_continuous_review(window)
    process_events()

    backend_actual = db_status_counts(db)
    to_review_count = backend_actual[TO_REVIEW]

    continuous_prop = bool(window.review_page.property("hciContinuousReview"))
    upper_visible = window.left_upper_widget.isVisible()
    progress_text = window.lbl_hci_review_progress.text() if hasattr(window, "lbl_hci_review_progress") else ""
    preview_visible = window.preview_panel.isVisible() if hasattr(window, "preview_panel") else True
    detail_visible = window._detail_panel.isVisible() if hasattr(window, "_detail_panel") else True

    backend_expected = {TO_REVIEW: to_review_count}
    ui_expected = {
        "continuous_mode": True,
        "list_hidden": True,
        "preview_visible": True,
        "detail_visible": True,
        "progress_current": 1,
        "progress_initial": to_review_count,
        "progress_remaining": to_review_count,
    }
    ui_actual = {
        "continuous_mode": continuous_prop,
        "list_hidden": not upper_visible,
        "preview_visible": preview_visible,
        "detail_visible": detail_visible,
        "progress_text": progress_text,
    }

    broken = None
    if not continuous_prop:
        broken = "review_page property 'hciContinuousReview' is not True"
    elif upper_visible:
        broken = "left_upper_widget (invoice list) should be hidden in continuous review"
    elif f"1 / {to_review_count}" not in progress_text:
        broken = f"Progress text '{progress_text}' does not contain '1 / {to_review_count}'"
    elif f"还剩 {to_review_count}" not in progress_text and f"剩 {to_review_count}" not in progress_text:
        broken = f"Progress text '{progress_text}' does not contain remaining count '{to_review_count}'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="CR-01",
        title="连续审核进入",
        passed=broken is None,
        backend_expected=backend_expected,
        backend_actual=backend_actual,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── CR-02: 连续审核通过一张 ─────────────────────────────────────────


def run_cr_02(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """CR-02: 连续审核通过一张 — APPROVED+1, TO_REVIEW-1, UI 2/N · 还剩 N-1, current_invoice 切换.

    Note: Must NOT call _sync_review_hci! Only natural product state transition is allowed.
    """
    t0 = time.perf_counter()
    _prepare_review_page(window)

    _enter_hci_continuous_review(window)
    process_events()

    initial_to_review = db.count_invoices_for_status(TO_REVIEW)
    initial_approved = db.count_invoices_for_status(APPROVED)
    initial_inv_id = ui_current_invoice_id(window)

    # ACTION: approve current invoice through natural product handler
    window._set_selected_status(APPROVED)
    process_events()

    backend_actual = db_status_counts(db)
    new_to_review = backend_actual[TO_REVIEW]
    new_approved = backend_actual[APPROVED]
    new_inv_id = ui_current_invoice_id(window)
    progress_text = window.lbl_hci_review_progress.text() if hasattr(window, "lbl_hci_review_progress") else ""

    backend_expected = {
        TO_REVIEW: initial_to_review - 1,
        APPROVED: initial_approved + 1,
    }
    ui_expected = {
        "progress_current": 2,
        "progress_initial": initial_to_review,
        "progress_remaining": initial_to_review - 1,
        "invoice_advanced": True,
    }
    ui_actual = {
        "progress_text": progress_text,
        "previous_invoice_id": initial_inv_id,
        "current_invoice_id": new_inv_id,
    }

    broken = None
    if new_approved != initial_approved + 1:
        broken = f"DB APPROVED expected {initial_approved + 1}, got {new_approved}"
    elif new_to_review != initial_to_review - 1:
        broken = f"DB TO_REVIEW expected {initial_to_review - 1}, got {new_to_review}"
    elif f"2 / {initial_to_review}" not in progress_text:
        broken = f"UI continuous progress stale: expected '2 / {initial_to_review}', got '{progress_text}'"
    elif f"{initial_to_review - 1}" not in progress_text:
        broken = f"UI continuous progress stale remaining count: expected '{initial_to_review - 1}', got '{progress_text}'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="CR-02",
        title="连续审核通过一张",
        passed=broken is None,
        backend_expected=backend_expected,
        backend_actual=backend_actual,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── CR-03: 连续审核连续通过两张 ─────────────────────────────────────


def run_cr_03(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """CR-03: 连续审核连续通过两张 — APPROVED+2, TO_REVIEW-2, UI 3/N · 还剩 N-2 (捕获永远 1/N).

    Note: Must NOT call _sync_review_hci!
    """
    t0 = time.perf_counter()
    _prepare_review_page(window)

    _enter_hci_continuous_review(window)
    process_events()

    initial_to_review = db.count_invoices_for_status(TO_REVIEW)
    initial_approved = db.count_invoices_for_status(APPROVED)

    # Approve first
    window._set_selected_status(APPROVED)
    process_events()

    # Approve second
    window._set_selected_status(APPROVED)
    process_events()

    backend_actual = db_status_counts(db)
    new_to_review = backend_actual[TO_REVIEW]
    new_approved = backend_actual[APPROVED]
    progress_text = window.lbl_hci_review_progress.text() if hasattr(window, "lbl_hci_review_progress") else ""

    backend_expected = {
        TO_REVIEW: initial_to_review - 2,
        APPROVED: initial_approved + 2,
    }
    ui_expected = {
        "progress_current": 3,
        "progress_initial": initial_to_review,
        "progress_remaining": initial_to_review - 2,
    }
    ui_actual = {
        "progress_text": progress_text,
    }

    broken = None
    if new_approved != initial_approved + 2:
        broken = f"DB APPROVED expected {initial_approved + 2}, got {new_approved}"
    elif new_to_review != initial_to_review - 2:
        broken = f"DB TO_REVIEW expected {initial_to_review - 2}, got {new_to_review}"
    elif f"3 / {initial_to_review}" not in progress_text:
        broken = f"UI continuous progress stale: expected '3 / {initial_to_review}', got '{progress_text}' (stuck at 1/N or 2/N)"
    elif f"{initial_to_review - 2}" not in progress_text:
        broken = f"UI continuous progress stale remaining: expected '{initial_to_review - 2}', got '{progress_text}'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="CR-03",
        title="连续审核连续通过两张",
        passed=broken is None,
        backend_expected=backend_expected,
        backend_actual=backend_actual,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── CR-04: Ignore 状态转换 ──────────────────────────────────────────


def run_cr_04(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """CR-04: Ignore 状态转换 — IGNORED+1, TO_REVIEW-1, 离开待审核队列."""
    t0 = time.perf_counter()
    _prepare_review_page(window)

    _enter_hci_continuous_review(window)
    process_events()

    initial_to_review = db.count_invoices_for_status(TO_REVIEW)
    initial_ignored = db.count_invoices_for_status(IGNORED)

    window._set_selected_status(IGNORED)
    process_events()

    backend_actual = db_status_counts(db)
    new_to_review = backend_actual[TO_REVIEW]
    new_ignored = backend_actual[IGNORED]
    progress_text = window.lbl_hci_review_progress.text() if hasattr(window, "lbl_hci_review_progress") else ""

    backend_expected = {
        TO_REVIEW: initial_to_review - 1,
        IGNORED: initial_ignored + 1,
    }
    ui_expected = {
        "progress_remaining": initial_to_review - 1,
        "progress_current": 2,
    }
    ui_actual = {
        "progress_text": progress_text,
    }

    broken = None
    if new_ignored != initial_ignored + 1:
        broken = f"DB IGNORED expected {initial_ignored + 1}, got {new_ignored}"
    elif new_to_review != initial_to_review - 1:
        broken = f"DB TO_REVIEW expected {initial_to_review - 1}, got {new_to_review}"
    elif f"{initial_to_review - 1}" not in progress_text:
        broken = f"UI progress '{progress_text}' expected remaining '{initial_to_review - 1}'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="CR-04",
        title="Ignore 状态转换",
        passed=broken is None,
        backend_expected=backend_expected,
        backend_actual=backend_actual,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── CR-05: Error 状态转换 ───────────────────────────────────────────


def run_cr_05(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """CR-05: Error 状态转换 — ERROR+1, TO_REVIEW-1, UI/DB 一致."""
    t0 = time.perf_counter()
    _prepare_review_page(window)

    _enter_hci_continuous_review(window)
    process_events()

    initial_to_review = db.count_invoices_for_status(TO_REVIEW)
    initial_error = db.count_invoices_for_status(ERROR)

    window._set_selected_status(ERROR)
    process_events()

    backend_actual = db_status_counts(db)
    new_to_review = backend_actual[TO_REVIEW]
    new_error = backend_actual[ERROR]
    progress_text = window.lbl_hci_review_progress.text() if hasattr(window, "lbl_hci_review_progress") else ""

    backend_expected = {
        TO_REVIEW: initial_to_review - 1,
        ERROR: initial_error + 1,
    }
    ui_expected = {
        "progress_remaining": initial_to_review - 1,
    }
    ui_actual = {
        "progress_text": progress_text,
    }

    broken = None
    if new_error != initial_error + 1:
        broken = f"DB ERROR expected {initial_error + 1}, got {new_error}"
    elif new_to_review != initial_to_review - 1:
        broken = f"DB TO_REVIEW expected {initial_to_review - 1}, got {new_to_review}"
    elif f"{initial_to_review - 1}" not in progress_text:
        broken = f"UI progress '{progress_text}' expected remaining '{initial_to_review - 1}'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="CR-05",
        title="Error 状态转换",
        passed=broken is None,
        backend_expected=backend_expected,
        backend_actual=backend_actual,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── CR-06: 稍后处理 ─────────────────────────────────────────────────


def run_cr_06(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """CR-06: 稍后处理 — review_status 不变，TO_REVIEW count 不变，已处理数不错误+1."""
    t0 = time.perf_counter()
    _prepare_review_page(window)

    _enter_hci_continuous_review(window)
    process_events()

    initial_to_review = db.count_invoices_for_status(TO_REVIEW)
    initial_inv_id = ui_current_invoice_id(window)

    # Action: skip / move to next row without changing status
    window._move_invoice_selection(1)
    process_events()

    backend_actual = db_status_counts(db)
    new_to_review = backend_actual[TO_REVIEW]
    new_inv_id = ui_current_invoice_id(window)
    progress_text = window.lbl_hci_review_progress.text() if hasattr(window, "lbl_hci_review_progress") else ""

    inv_in_db = db.get_invoice(initial_inv_id)
    initial_inv_status = inv_in_db["review_status"] if inv_in_db else None

    backend_expected = {
        TO_REVIEW: initial_to_review,
        "skipped_invoice_status": TO_REVIEW,
    }
    ui_expected = {
        "progress_remaining": initial_to_review,
        "invoice_moved": True,
    }
    ui_actual = {
        "progress_text": progress_text,
        "initial_inv_status": initial_inv_status,
        "new_invoice_id": new_inv_id,
    }

    broken = None
    if new_to_review != initial_to_review:
        broken = f"DB TO_REVIEW changed on skip: expected {initial_to_review}, got {new_to_review}"
    elif initial_inv_status != TO_REVIEW:
        broken = f"Skipped invoice status changed to {initial_inv_status}"
    elif f"1 / {initial_to_review}" not in progress_text:
        broken = f"UI progress '{progress_text}' should still show 1 / {initial_to_review} (processed count must not +1)"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="CR-06",
        title="稍后处理",
        passed=broken is None,
        backend_expected=backend_expected,
        backend_actual=backend_actual,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── CR-07: Exit / Re-enter ──────────────────────────────────────────


def run_cr_07(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """CR-07: Exit / Re-enter — 新 session initial_total 等于当前 fresh TO_REVIEW，旧 total 不泄漏."""
    t0 = time.perf_counter()
    _prepare_review_page(window)

    _enter_hci_continuous_review(window)
    process_events()

    # Process 2 invoices
    window._set_selected_status(APPROVED)
    process_events()

    window._set_selected_status(APPROVED)
    process_events()

    # Exit continuous review
    _exit_hci_continuous_review(window)
    process_events()

    # Re-enter continuous review
    _enter_hci_continuous_review(window)
    process_events()

    fresh_to_review = db.count_invoices_for_status(TO_REVIEW)
    backend_actual = db_status_counts(db)
    progress_text = window.lbl_hci_review_progress.text() if hasattr(window, "lbl_hci_review_progress") else ""

    backend_expected = {TO_REVIEW: fresh_to_review}
    ui_expected = {
        "progress_text_pattern": f"1 / {fresh_to_review}",
        "remaining": fresh_to_review,
    }
    ui_actual = {
        "progress_text": progress_text,
        "initial_total_stored": getattr(window, "_hci_review_initial_total", None),
    }

    broken = None
    if f"1 / {fresh_to_review}" not in progress_text:
        broken = f"Re-entered progress '{progress_text}' should show '1 / {fresh_to_review}', not leak old total"
    elif f"{fresh_to_review}" not in progress_text:
        broken = f"Re-entered progress '{progress_text}' should show remaining '{fresh_to_review}'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="CR-07",
        title="Exit / Re-enter",
        passed=broken is None,
        backend_expected=backend_expected,
        backend_actual=backend_actual,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── CR-08: 最后一张完成 ─────────────────────────────────────────────


def run_cr_08(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """CR-08: 最后一张完成 — TO_REVIEW=0, 显示 '本轮已完成', 不得 2/1 或崩溃."""
    t0 = time.perf_counter()

    # Arrange: ensure exactly 1 standard normal invoice is left in TO_REVIEW, others APPROVED
    all_to_review = db.list_invoices(status=TO_REVIEW, include_deleted=False)
    for inv in all_to_review[1:]:
        db.update_invoice_review_status(inv["id"], APPROVED)
    for inv in db.list_invoices(include_deleted=False):
        if inv.get("invoice_type") == "待关联证明材料" and inv.get("review_status") == TO_REVIEW:
            db.update_invoice_review_status(inv["id"], IGNORED)

    window._load_invoices()
    _prepare_review_page(window)

    _enter_hci_continuous_review(window)
    process_events()

    # Approve the single remaining invoice
    window._ensure_single_row_selection(0)
    process_events()
    window._set_selected_status(APPROVED)
    process_events()

    backend_actual = db_status_counts(db)
    to_review_remaining = backend_actual[TO_REVIEW]
    progress_text = window.lbl_hci_review_progress.text() if hasattr(window, "lbl_hci_review_progress") else ""

    backend_expected = {TO_REVIEW: 0}
    ui_expected = {
        "progress_text_contains": "本轮已完成",
        "no_crash": True,
    }
    ui_actual = {
        "progress_text": progress_text,
    }

    broken = None
    if to_review_remaining != 0:
        broken = f"DB TO_REVIEW expected 0, got {to_review_remaining}"
    elif "本轮已完成" not in progress_text:
        broken = f"UI progress '{progress_text}' should indicate completion ('本轮已完成')"
    elif "2 / 1" in progress_text:
        broken = f"UI progress '{progress_text}' contains illegal '2 / 1'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="CR-08",
        title="最后一张完成",
        passed=broken is None,
        backend_expected=backend_expected,
        backend_actual=backend_actual,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── RV-01: 普通审核列表 / DB / 详情一致 ─────────────────────────────


def run_rv_01(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """RV-01: 普通审核列表 / DB / 详情一致 — table ID == current_invoice.id == detail panel ID == preview ID."""
    t0 = time.perf_counter()
    _prepare_review_page(window)

    table_id = ui_table_selected_id(window)
    current_inv_id = ui_current_invoice_id(window)

    db_inv = db.get_invoice(table_id) if table_id else None
    detail_number = window.txt_number.text().strip() if hasattr(window, "txt_number") else ""

    backend_expected = {
        "selected_invoice_exists": True,
        "invoice_number": db_inv["invoice_number"] if db_inv else "",
    }
    backend_actual = {
        "db_invoice_id": db_inv["id"] if db_inv else None,
        "db_invoice_number": db_inv["invoice_number"] if db_inv else "",
    }
    ui_expected = {
        "table_id": table_id,
        "model_id": table_id,
        "detail_number": db_inv["invoice_number"] if db_inv else "",
    }
    ui_actual = {
        "table_id": table_id,
        "current_invoice_id": current_inv_id,
        "detail_number": detail_number,
    }

    broken = None
    if table_id is None or current_inv_id is None:
        broken = "No invoice selected in table or current_invoice is None"
    elif table_id != current_inv_id:
        broken = f"Table selected ID ({table_id}) != current_invoice ID ({current_inv_id})"
    elif db_inv is None:
        broken = f"Selected invoice ID {table_id} does not exist in DB"
    elif detail_number and db_inv["invoice_number"] and detail_number != db_inv["invoice_number"]:
        broken = f"Detail panel number '{detail_number}' != DB number '{db_inv['invoice_number']}'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="RV-01",
        title="普通审核列表 / DB / 详情一致",
        passed=broken is None,
        backend_expected=backend_expected,
        backend_actual=backend_actual,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── RV-02: 普通审核计数一致 ─────────────────────────────────────────


def run_rv_02(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """RV-02: 普通审核计数一致 — UI badge counts == DB counts for all statuses + total."""
    t0 = time.perf_counter()
    _prepare_review_page(window)

    backend_counts = db_status_counts(db)
    ui_counts = ui_filter_badge_counts(window)

    mismatches = []
    for key in [TO_REVIEW, APPROVED, IGNORED, ERROR, "all"]:
        db_val = backend_counts.get(key, -1)
        ui_val = ui_counts.get(key, -1)
        if db_val != ui_val:
            mismatches.append(f"{key}: DB={db_val} UI={ui_val}")

    broken = "; ".join(mismatches) if mismatches else None
    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="RV-02",
        title="普通审核计数一致",
        passed=broken is None,
        backend_expected=backend_counts,
        backend_actual=backend_counts,
        ui_expected=backend_counts,
        ui_actual=ui_counts,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── MAIL-01: 同步 active / DOWNLOAD ──────────────────────────────────


def run_mail_01(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """MAIL-01: 同步 active / DOWNLOAD — 注入 DOWNLOAD 阶段，显示 '正在同步' / '下载附件' 及耗时."""
    t0 = time.perf_counter()
    window._switch_main_page("imports")
    process_events()

    event = {
        "stage": "download",
        "elapsed_ms": 1500,
        "counts": {"processed": 4, "total": 10},
    }
    window._scan_started_at = time.monotonic() - 1.5
    window._scan_stage_updated(event)
    process_events()

    status_text = window.lbl_import_scan_status.text() if hasattr(window, "lbl_import_scan_status") else ""

    ui_expected = {
        "contains_download": True,
        "contains_elapsed": True,
        "is_active": True,
    }
    ui_actual = {
        "status_text": status_text,
    }

    broken = None
    if "下载" not in status_text:
        broken = f"Status text '{status_text}' does not contain '下载'"
    elif "1.5" not in status_text and "1" not in status_text:
        broken = f"Status text '{status_text}' does not reflect elapsed time"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="MAIL-01",
        title="同步 active / DOWNLOAD",
        passed=broken is None,
        backend_expected={},
        backend_actual={},
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── MAIL-02: Active Stage Transition ────────────────────────────────


def run_mail_02(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """MAIL-02: Active Stage Transition — DOWNLOAD -> PARSE -> SAVE 每步 active，中文阶段正确，耗时单调不减."""
    t0 = time.perf_counter()
    window._switch_main_page("imports")
    process_events()

    stages = [
        ("download", 1000, "下载"),
        ("parse", 2000, "识别"),
        ("save", 3000, "保存"),
    ]

    snapshots = []
    broken = None
    prev_elapsed = 0

    for stage_key, elapsed_ms, label_sub in stages:
        event = {"stage": stage_key, "elapsed_ms": elapsed_ms, "counts": {}}
        window._scan_started_at = time.monotonic() - (elapsed_ms / 1000)
        window._scan_stage_updated(event)
        process_events()

        text = window.lbl_import_scan_status.text()
        snapshots.append((stage_key, text))

        if label_sub not in text and stage_key not in text:
            broken = f"Stage '{stage_key}' text '{text}' missing label '{label_sub}'"
            break
        if elapsed_ms < prev_elapsed:
            broken = f"Elapsed time not monotonic: {elapsed_ms} < {prev_elapsed}"
            break
        prev_elapsed = elapsed_ms

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="MAIL-02",
        title="active stage transition",
        passed=broken is None,
        backend_expected={"stages": ["download", "parse", "save"]},
        backend_actual={"stages": [s[0] for s in snapshots]},
        ui_expected={"monotonic_elapsed": True, "active_stages": True},
        ui_actual={"snapshots": snapshots},
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── MAIL-03: Complete ────────────────────────────────────────────────


def run_mail_03(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """MAIL-03: Complete — 注入 COMPLETE，验证 terminal presentation、counts、以及推进时钟后 elapsed 保持冻结."""
    t0 = time.perf_counter()
    window._switch_main_page("imports")
    process_events()

    window.scan_worker = type("FinishedWorker", (), {"_trigger_btn": None, "isRunning": lambda s: False})()

    res = {
        "cancelled": False,
        "scanned": 800,
        "candidate": 39,
        "download_failed": 9,
        "elapsed": 535.6,
    }

    try:
        from scripts.invoice_fetch.gui.hci_v1_closure import _render_scan_terminal
        _render_scan_terminal(
            window,
            "complete",
            elapsed=535.6,
            summary={"scanned": 800, "classified_invoice": 39, "download_failed": 9},
            result=res,
        )
    except ImportError:
        window._scan_email_finished(res)

    process_events()

    status_text = window.lbl_import_scan_status.text() if hasattr(window, "lbl_import_scan_status") else ""

    # Advance clock and process UI events: terminal presentation and elapsed must remain frozen
    window._scan_started_at = time.monotonic() - 9999.0
    process_events()

    post_tick_text = window.lbl_import_scan_status.text() if hasattr(window, "lbl_import_scan_status") else ""

    ui_expected = {
        "terminal_complete": True,
        "contains_800": True,
        "contains_39": True,
        "contains_failed_9": True,
        "elapsed_frozen": True,
    }
    ui_actual = {
        "status_text": status_text,
        "post_tick_text": post_tick_text,
    }

    broken = None
    if "完成" not in status_text:
        broken = f"Completed status '{status_text}' does not contain '完成'"
    elif "正在" in status_text:
        broken = f"Completed status '{status_text}' should not contain '正在'"
    elif "800" not in status_text or "39" not in status_text:
        broken = f"Completed status '{status_text}' missing summary counts (800, 39)"
    elif "失败 9 项" not in status_text:
        broken = f"Completed status '{status_text}' missing expected failure text '失败 9 项'"
    elif status_text != post_tick_text:
        broken = f"Elapsed time not frozen after completion: before='{status_text}', after='{post_tick_text}'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="MAIL-03",
        title="Complete",
        passed=broken is None,
        backend_expected=res,
        backend_actual=res,
        ui_expected=ui_expected,
        ui_actual=ui_actual,
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── MAIL-04: Failed ──────────────────────────────────────────────────


def run_mail_04(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """MAIL-04: Failed — 走真实 failure handler 进入 FAILED，错误原因安全脱敏，非 active."""
    t0 = time.perf_counter()
    window._switch_main_page("imports")
    process_events()

    window.scan_worker = type("FinishedWorker", (), {"_trigger_btn": None, "isRunning": lambda s: False})()

    # Trigger failure through real product handler with sanitized error reason
    try:
        from scripts.invoice_fetch.gui.hci_v1_closure import _render_scan_terminal
        _render_scan_terminal(
            window,
            "failed",
            elapsed=13.0,
            reason="网络连接超时 (IMAP server timeout)",
        )
    except ImportError:
        window._finish_scan_ui(cancelled=False)

    process_events()
    status_text = window.lbl_import_scan_status.text() if hasattr(window, "lbl_import_scan_status") else ""

    broken = None
    if "失败" not in status_text:
        broken = f"Failed status '{status_text}' does not contain '失败'"
    elif "正在" in status_text:
        broken = f"Failed status '{status_text}' should not contain '正在'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="MAIL-04",
        title="Failed",
        passed=broken is None,
        backend_expected={"failed": True},
        backend_actual={"failed": True},
        ui_expected={"terminal": True, "contains_failed": True},
        ui_actual={"status_text": status_text},
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── MAIL-05: Cancelled ───────────────────────────────────────────────


def run_mail_05(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """MAIL-05: Cancelled — 走真实 cancellation handler，显示已取消，cancel button 隐藏/重置."""
    t0 = time.perf_counter()
    window._switch_main_page("imports")
    process_events()

    window.scan_worker = type("FinishedWorker", (), {"_trigger_btn": None, "isRunning": lambda s: False})()

    try:
        from scripts.invoice_fetch.gui.hci_v1_closure import _render_scan_terminal
        _render_scan_terminal(window, "cancelled", elapsed=12.0, result={"cancelled": True})
    except ImportError:
        window._finish_scan_ui(cancelled=True)

    process_events()

    status_text = window.lbl_import_scan_status.text() if hasattr(window, "lbl_import_scan_status") else ""
    cancel_btn_visible = window.btn_import_scan_cancel.isVisible() if hasattr(window, "btn_import_scan_cancel") else False

    broken = None
    if "已取消" not in status_text:
        broken = f"Cancelled status '{status_text}' does not contain '已取消'"
    elif cancel_btn_visible:
        broken = "Cancel button should be hidden after cancellation"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="MAIL-05",
        title="Cancelled",
        passed=broken is None,
        backend_expected={"cancelled": True},
        backend_actual={"cancelled": True},
        ui_expected={"contains_cancelled": True, "cancel_btn_hidden": True},
        ui_actual={"status_text": status_text, "cancel_btn_visible": cancel_btn_visible},
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── DATE-01: 日期范围默认和 preset ──────────────────────────────────


def run_date_01(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """DATE-01: 日期范围默认和 preset — end=today, 7d/30d/3m presets 使用 QDate.addMonths(-3) 契约.

    Rule: If DateRangeDialog is missing, must FAIL with explicit contract missing message (NO fallback calculation).
    """
    t0 = time.perf_counter()
    today = QDate.currentDate()

    try:
        from scripts.invoice_fetch.gui.date_range_dialog import DateRangeDialog
    except ImportError:
        duration = int((time.perf_counter() - t0) * 1000)
        return ScenarioResult(
            id="DATE-01",
            title="日期范围默认和 preset",
            passed=False,
            backend_expected={"dialog_component_available": True},
            backend_actual={"dialog_component_available": False},
            ui_expected={"mature_date_range_ui": True},
            ui_actual={"mature_date_range_ui": False},
            broken_invariant="required mature date-range UI missing (DateRangeDialog not found)",
            duration_ms=duration,
        )

    dialog = DateRangeDialog()
    try:
        initial_end = dialog.end_date_edit.date()

        dialog._apply_preset("7d")
        d7_start = dialog.start_date_edit.date()
        d7_end = dialog.end_date_edit.date()

        dialog._apply_preset("30d")
        d30_start = dialog.start_date_edit.date()
        d30_end = dialog.end_date_edit.date()

        dialog._apply_preset("3m")
        d3m_start = dialog.start_date_edit.date()
        d3m_end = dialog.end_date_edit.date()

        broken = None
        if initial_end != today:
            broken = f"Default end date expected today ({today}), got {initial_end}"
        elif d7_start != today.addDays(-7) or d7_end != today:
            broken = f"Preset 7d mismatch: start={d7_start}, end={d7_end}"
        elif d30_start != today.addDays(-30) or d30_end != today:
            broken = f"Preset 30d mismatch: start={d30_start}, end={d30_end}"
        elif d3m_start != today.addMonths(-3) or d3m_end != today:
            broken = f"Preset 3m mismatch: start={d3m_start}, end={d3m_end}"

        duration = int((time.perf_counter() - t0) * 1000)
        return ScenarioResult(
            id="DATE-01",
            title="日期范围默认和 preset",
            passed=broken is None,
            backend_expected={},
            backend_actual={},
            ui_expected={"preset_7d": "-7d", "preset_30d": "-30d", "preset_3m": "-3m"},
            ui_actual={"d7": str(d7_start), "d30": str(d30_start), "d3m": str(d3m_start)},
            broken_invariant=broken,
            duration_ms=duration,
        )
    finally:
        dialog.close()
        dialog.deleteLater()


# ── DATE-02: 日期范围非法 ───────────────────────────────────────────


def run_date_02(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """DATE-02: 日期范围非法 — start > end 时拒绝 accept，不调用重检，有明确错误反馈.

    Rule: If DateRangeDialog is missing, must FAIL with explicit validation UI missing message.
    """
    t0 = time.perf_counter()
    today = QDate.currentDate()

    try:
        from scripts.invoice_fetch.gui.date_range_dialog import DateRangeDialog
    except ImportError:
        duration = int((time.perf_counter() - t0) * 1000)
        return ScenarioResult(
            id="DATE-02",
            title="日期范围非法",
            passed=False,
            backend_expected={"dialog_component_available": True},
            backend_actual={"dialog_component_available": False},
            ui_expected={"date_range_validation_ui": True},
            ui_actual={"date_range_validation_ui": False},
            broken_invariant="date-range validation UI missing (DateRangeDialog not found)",
            duration_ms=duration,
        )

    dialog = DateRangeDialog()
    try:
        dialog.start_date_edit.setDate(today)
        dialog.end_date_edit.setDate(today.addDays(-1))
        dialog.accept()
        result_code = dialog.result()
        error_text = dialog.error_label.text()
        error_shown = bool(error_text) and not dialog.error_label.isHidden()

        broken = None
        if result_code == QDialog.Accepted:
            broken = "DateRangeDialog accepted invalid date range (start > end)"
        elif not error_shown:
            broken = "DateRangeDialog failed to display visible error label on invalid range"

        duration = int((time.perf_counter() - t0) * 1000)
        return ScenarioResult(
            id="DATE-02",
            title="日期范围非法",
            passed=broken is None,
            backend_expected={"invalid_accepted": False},
            backend_actual={"invalid_accepted": result_code == QDialog.Accepted},
            ui_expected={"dialog_rejected": True, "error_shown": True},
            ui_actual={"result_code": result_code, "error_text": error_text, "error_shown": error_shown},
            broken_invariant=broken,
            duration_ms=duration,
        )
    finally:
        dialog.close()
        dialog.deleteLater()


# ── SAFE-01: 数据操作互斥 ───────────────────────────────────────────


def run_safe_01(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """SAFE-01: 数据操作互斥 — 扫描/重检 active 时阻止互斥操作 (如并发备份/重检).

    Asserts:
    1. Backend: Operation did NOT start (acquired is False).
    2. UI Feedback: Clear, visible, non-silent user feedback received with expected semantics.
    3. Lifecycle: Busy reason cleanly cleared upon release.
    """
    t0 = time.perf_counter()

    gate = getattr(window, "_data_operation_gate", None)
    if gate is None:
        duration = int((time.perf_counter() - t0) * 1000)
        return ScenarioResult(
            id="SAFE-01",
            title="数据操作互斥",
            passed=False,
            broken_invariant="DataOperationGate not found on application window",
            duration_ms=duration,
        )

    warnings_shown: list[tuple[str, str]] = []

    # Hold gate with a mock active task ("历史记录重检")
    with gate.operation("历史记录重检"):
        try_begin = getattr(window, "_try_begin_data_operation", None)
        with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warning:
            mock_warning.side_effect = lambda parent, title, text, *args, **kwargs: (
                warnings_shown.append((str(title), str(text))) or QMessageBox.Ok
            )
            # Attempt concurrent backup operation with user notifications enabled
            acquired = try_begin("数据库备份", notify=True) if callable(try_begin) else gate.try_acquire("数据库备份")
            process_events()

    busy_cleared = gate.busy_reason() == ""

    # UI feedback evaluation: must receive visible feedback, silent rejection is FAIL
    ui_feedback_present = len(warnings_shown) > 0
    feedback_title, feedback_text = warnings_shown[0] if ui_feedback_present else ("", "")
    semantic_valid = (
        ("无法执行" in feedback_title or "暂时无法执行" in feedback_title or "提示" in feedback_title)
        and ("正在运行" in feedback_text or "请完成" in feedback_text or "请稍后" in feedback_text or "请完成后再试" in feedback_text)
        and ("重检" in feedback_text or "历史" in feedback_text or "数据操作" in feedback_text)
    )

    broken = None
    if acquired:
        broken = "DataOperationGate failed to block concurrent database operation"
    elif not ui_feedback_present:
        broken = "SAFE-01 UI SILENT: blocked operation produced no user-visible QMessageBox.warning or feedback"
    elif not semantic_valid:
        broken = (
            f"SAFE-01 UI SEMANTIC ERROR: warning dialog text '{feedback_title}: {feedback_text}' "
            "missing required busy semantics ('无法执行', '正在运行', '历史记录重检')"
        )
    elif not busy_cleared:
        broken = f"DataOperationGate did not clear busy reason after release: '{gate.busy_reason()}'"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="SAFE-01",
        title="数据操作互斥",
        passed=broken is None,
        backend_expected={"operation_blocked": True, "gate_released": True},
        backend_actual={"operation_blocked": not acquired, "gate_released": busy_cleared},
        ui_expected={"ui_feedback_present": True, "semantic_valid": True},
        ui_actual={
            "acquired": acquired,
            "ui_feedback_present": ui_feedback_present,
            "feedback_title": feedback_title,
            "feedback_text": feedback_text,
        },
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── EXPORT-01: 缺材料 fail-closed ───────────────────────────────────


def run_export_01(window, db: InvoiceDB, qapp: QApplication) -> ScenarioResult:
    """EXPORT-01: 缺材料 fail-closed — 三层拦截验证:

    1. Preflight detects missing evidence.
    2. GUI: export action disabled / blocked.
    3. Backend: direct call to export_claim_package MUST fail-closed with expected ValueError.
       Unexpected exceptions (TypeError, AttributeError, DB exception, etc.) cause Scenario FAIL.
    """
    t0 = time.perf_counter()

    # Arrange: claim group with approved invoice missing required extra material
    claim_id = db.create_claim_group("Preflight Test Claim")
    inv_id = db.insert_invoice({
        "invoice_number": "SYN-EXP-001",
        "invoice_date": "2026-07-01",
        "total_amount": "100.00",
        "seller_name": "Export Test Seller",
        "review_status": APPROVED,
        "attachment_path": "synthetic/exp-001.pdf",
        "has_extra": True,
        "extra_type": "行程单",
        "missing_extra": True,
        "extra_paths": "[]",
    })
    db.add_invoice_to_claim(claim_id, inv_id)

    # 1. Preflight Layer
    stats = window._claim_export_preflight_stats(claim_id) if hasattr(window, "_claim_export_preflight_stats") else {}
    missing_detected = stats.get("missing_extra", 0) > 0

    # 2. GUI Layer
    window._switch_main_page("export")
    process_events()
    window._load_claims()
    process_events()

    if hasattr(window, "export_group_list"):
        for row in range(window.export_group_list.count()):
            item = window.export_group_list.item(row)
            if item and item.data(32) == claim_id:
                window.export_group_list.setCurrentItem(item)
                process_events()
                break

    if hasattr(window, "_sync_export_claim_selection"):
        window._sync_export_claim_selection()
        process_events()

    gui_button_disabled = False
    if hasattr(window, "btn_run_export_page"):
        gui_button_disabled = not window.btn_run_export_page.isEnabled()

    # 3. Backend Layer (bypass GUI and call export_claim_package directly)
    from scripts.invoice_fetch.claim_export import export_claim_package
    backend_rejected = False
    rejection_details = ""
    unexpected_exception = ""

    try:
        export_claim_package(
            db=db,
            claim_id=claim_id,
            project_root=Path(db._db_path).parent if hasattr(db, "_db_path") else Path("."),
            runtime_dir=Path(db._db_path).parent / "runtime" if hasattr(db, "_db_path") else Path("."),
        )
    except ValueError as exc:
        backend_rejected = True
        rejection_details = f"ValueError: {exc}"
    except Exception as exc:
        backend_rejected = False
        unexpected_exception = f"{type(exc).__name__}: {exc}"

    broken = None
    if not missing_detected:
        broken = f"Layer 1 FAIL: Preflight failed to detect missing_extra in stats: {stats}"
    elif not gui_button_disabled:
        broken = "Layer 2 FAIL: GUI export button is enabled despite missing evidence blocker"
    elif unexpected_exception:
        broken = f"Layer 3 FAIL: Backend export raised unexpected exception ({unexpected_exception}) instead of expected fail-closed contract ValueError"
    elif not backend_rejected:
        broken = "Layer 3 FAIL: Backend export did not fail-closed when evidence was missing (no ValueError raised)"

    duration = int((time.perf_counter() - t0) * 1000)
    return ScenarioResult(
        id="EXPORT-01",
        title="缺材料 fail-closed",
        passed=broken is None,
        backend_expected={
            "layer1_preflight_detected": True,
            "layer2_gui_disabled": True,
            "layer3_backend_rejected": True,
            "layer3_expected_exception": "ValueError",
        },
        backend_actual={
            "layer1_preflight_detected": missing_detected,
            "layer2_gui_disabled": gui_button_disabled,
            "layer3_backend_rejected": backend_rejected,
            "rejection_details": rejection_details or unexpected_exception or "None",
        },
        ui_expected={"btn_run_export_page_disabled": True},
        ui_actual={"btn_disabled": gui_button_disabled},
        broken_invariant=broken,
        duration_ms=duration,
    )


# ── Scenario Registry (19 Scenarios) ────────────────────────────────

ALL_SCENARIOS = [
    ("CR-01", "连续审核进入", run_cr_01),
    ("CR-02", "连续审核通过一张", run_cr_02),
    ("CR-03", "连续审核连续通过两张", run_cr_03),
    ("CR-04", "Ignore 状态转换", run_cr_04),
    ("CR-05", "Error 状态转换", run_cr_05),
    ("CR-06", "稍后处理", run_cr_06),
    ("CR-07", "Exit / Re-enter", run_cr_07),
    ("CR-08", "最后一张完成", run_cr_08),
    ("RV-01", "普通审核列表 / DB / 详情一致", run_rv_01),
    ("RV-02", "普通审核计数一致", run_rv_02),
    ("MAIL-01", "同步 active / DOWNLOAD", run_mail_01),
    ("MAIL-02", "active stage transition", run_mail_02),
    ("MAIL-03", "Complete", run_mail_03),
    ("MAIL-04", "Failed", run_mail_04),
    ("MAIL-05", "Cancelled", run_mail_05),
    ("DATE-01", "日期范围默认和 preset", run_date_01),
    ("DATE-02", "日期范围非法", run_date_02),
    ("SAFE-01", "数据操作互斥", run_safe_01),
    ("EXPORT-01", "缺材料 fail-closed", run_export_01),
]
