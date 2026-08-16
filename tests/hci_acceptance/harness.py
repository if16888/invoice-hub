"""Harness infrastructure: result types, helpers, and report generation.

Provides the core machinery for running HCI acceptance scenarios with
dual backend/UI oracles, bounded Qt event processing, and structured
failure evidence.
"""

from __future__ import annotations

import gc
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QThread

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch import review_status


# ── Result data types ────────────────────────────────────────────────

REQUIRED_SCENARIO_IDS: tuple[str, ...] = (
    "CR-01",
    "CR-02",
    "CR-03",
    "CR-04",
    "CR-05",
    "CR-06",
    "CR-07",
    "CR-08",
    "RV-01",
    "RV-02",
    "MAIL-01",
    "MAIL-02",
    "MAIL-03",
    "MAIL-04",
    "MAIL-05",
    "DATE-01",
    "DATE-02",
    "SAFE-01",
    "EXPORT-01",
)


@dataclass
class ScenarioResult:
    """Outcome of a single HCI scenario."""

    id: str
    title: str
    passed: bool
    backend_expected: dict = field(default_factory=dict)
    backend_actual: dict = field(default_factory=dict)
    ui_expected: dict = field(default_factory=dict)
    ui_actual: dict = field(default_factory=dict)
    broken_invariant: str | None = None
    duration_ms: int = 0
    screenshot_path: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "passed": self.passed,
            "backend_expected": self.backend_expected,
            "backend_actual": self.backend_actual,
            "ui_expected": self.ui_expected,
            "ui_actual": self.ui_actual,
            "broken_invariant": self.broken_invariant,
            "duration_ms": self.duration_ms,
            "screenshot_path": self.screenshot_path,
            "error_message": self.error_message,
        }


@dataclass
class HarnessReport:
    """Aggregate report across all HCI scenarios."""

    scenarios: list[ScenarioResult] = field(default_factory=list)
    native_crash: bool = False
    timeout: bool = False
    residual_threads: int = 0
    residual_python: int = 0
    residual_invoicehub: int = 0
    residual_qtwebengine: int = 0

    @property
    def scenario_ids(self) -> list[str]:
        return [s.id for s in self.scenarios]

    @property
    def scenario_contract_ok(self) -> bool:
        actual_ids = self.scenario_ids
        return (
            len(actual_ids) == len(REQUIRED_SCENARIO_IDS)
            and len(set(actual_ids)) == len(REQUIRED_SCENARIO_IDS)
            and set(actual_ids) == set(REQUIRED_SCENARIO_IDS)
        )

    @property
    def residual_processes(self) -> int:
        return self.residual_python + self.residual_invoicehub + self.residual_qtwebengine

    @property
    def accepted(self) -> bool:
        return (
            self.scenario_contract_ok
            and self.failed == 0
            and not self.native_crash
            and not self.timeout
            and self.residual_threads == 0
            and self.residual_processes == 0
        )

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.passed)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if not s.passed)

    @property
    def total(self) -> int:
        return len(self.scenarios)

    def to_json(self) -> dict:
        return {
            "summary": {
                "accepted": self.accepted,
                "scenario_contract_ok": self.scenario_contract_ok,
                "passed": self.passed,
                "failed": self.failed,
                "total": self.total,
                "native_crash": self.native_crash,
                "timeout": self.timeout,
                "residual_threads": self.residual_threads,
                "residual_python": self.residual_python,
                "residual_invoicehub": self.residual_invoicehub,
                "residual_qtwebengine": self.residual_qtwebengine,
                "residual_processes": self.residual_processes,
            },
            "scenarios": [s.to_dict() for s in self.scenarios],
        }

    def to_markdown(self) -> str:
        contract_status = "PASS" if self.scenario_contract_ok else "FAIL"
        lines = [
            "# Invoice Hub HCI Acceptance Report",
            "",
            f"**Scenario contract:** {contract_status}",
            f"**Passed:** {self.passed} / {self.total}",
            f"**Failed:** {self.failed}",
            f"**Native crash:** {self.native_crash}",
            f"**Timeout:** {self.timeout}",
            f"**Residual threads:** {self.residual_threads}",
            f"**Residual Python:** {self.residual_python}",
            f"**Residual InvoiceHub:** {self.residual_invoicehub}",
            f"**Residual QtWebEngine:** {self.residual_qtwebengine}",
            "",
            "## Scenarios",
            "",
            "| ID | Title | Result |",
            "|---|---|---|",
        ]
        for s in self.scenarios:
            status = "PASS" if s.passed else "FAIL"
            lines.append(f"| {s.id} | {s.title} | {status} |")

        failed = [s for s in self.scenarios if not s.passed]
        if failed:
            lines.extend(["", "## Failures", ""])
            for s in failed:
                lines.extend([
                    f"### [{s.id}] {s.title}",
                    "",
                    f"**Broken invariant:** {s.broken_invariant or 'N/A'}",
                    "",
                    f"**Expected backend:** `{json.dumps(s.backend_expected, ensure_ascii=False)}`",
                    f"**Actual backend:** `{json.dumps(s.backend_actual, ensure_ascii=False)}`",
                    "",
                    f"**Expected UI:** `{json.dumps(s.ui_expected, ensure_ascii=False)}`",
                    f"**Actual UI:** `{json.dumps(s.ui_actual, ensure_ascii=False)}`",
                    "",
                ])
                if s.error_message:
                    lines.append(f"**Error:** {s.error_message}")
                    lines.append("")

        verdict = "PASS" if self.accepted else "FAIL"
        lines.extend([
            "",
            f"## Verdict: HCI ACCEPTANCE {verdict}",
        ])
        return "\n".join(lines)


# ── Qt event processing helpers ──────────────────────────────────────


def process_events(iterations: int = 5) -> None:
    """Process pending Qt events without blocking."""
    app = QApplication.instance()
    if app is None:
        return
    for _ in range(iterations):
        app.processEvents()


def process_events_until(
    predicate: Callable[[], bool],
    timeout_ms: int = 2000,
    poll_interval_ms: int = 10,
) -> bool:
    """Process Qt events until predicate returns True or timeout."""
    app = QApplication.instance()
    if app is None:
        return predicate()
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        end = time.monotonic() + (poll_interval_ms / 1000.0)
        while time.monotonic() < end:
            app.processEvents()
    return predicate()


# ── Backend oracle helpers ───────────────────────────────────────────


def db_status_counts(db: InvoiceDB) -> dict[str, int]:
    """Get fresh status counts directly from the database."""
    return {
        "all": db.count_invoices_for_status(status=None, include_deleted=False),
        review_status.TO_REVIEW: db.count_invoices_for_status(
            status=review_status.TO_REVIEW, include_deleted=False
        ),
        review_status.APPROVED: db.count_invoices_for_status(
            status=review_status.APPROVED, include_deleted=False
        ),
        review_status.IGNORED: db.count_invoices_for_status(
            status=review_status.IGNORED, include_deleted=False
        ),
        review_status.ERROR: db.count_invoices_for_status(
            status=review_status.ERROR, include_deleted=False
        ),
    }


# ── UI oracle helpers ────────────────────────────────────────────────


def ui_filter_badge_counts(window) -> dict[str, int]:
    """Read the visible filter badge counts from the SegmentControl."""
    counts = {}
    if not hasattr(window, "filter_buttons"):
        return counts
    for key, card in window.filter_buttons.items():
        try:
            counts[key] = int(card.value())
        except (ValueError, AttributeError):
            counts[key] = -1
    return counts


def ui_current_invoice_id(window) -> int | None:
    """Get the ID of the currently selected invoice from the window model."""
    inv = getattr(window, "current_invoice", None)
    if inv is None or not isinstance(inv, dict):
        return None
    return inv.get("id")


def ui_table_selected_id(window) -> int | None:
    """Get the invoice ID of the currently selected table row."""
    if not hasattr(window, "table") or not hasattr(window, "invoices_list"):
        return None
    row = window.table.currentRow()
    if row < 0 or row >= len(window.invoices_list):
        return None
    return window.invoices_list[row].get("id")


def ui_table_row_count(window) -> int:
    """Get the visible row count of the invoice table."""
    if not hasattr(window, "table"):
        return -1
    return window.table.rowCount()


def ui_scan_status_text(window) -> str:
    """Get the scan status label text."""
    lbl = getattr(window, "lbl_import_scan_status", None)
    if lbl is None:
        return ""
    return lbl.text()


def ui_export_button_enabled(window) -> bool | None:
    """Check if the export button is enabled."""
    btn = getattr(window, "btn_run_export_page", None)
    if btn is None:
        return None
    return btn.isEnabled()


# ── Screenshot helper ────────────────────────────────────────────────


def grab_screenshot(widget: QWidget, path: str) -> str | None:
    """Grab a screenshot of the widget and save to path."""
    try:
        pixmap = widget.grab()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(path, "PNG")
        return path
    except Exception:
        return None


# ── Lifecycle gate helpers ───────────────────────────────────────────


def find_running_qthreads(parent: QWidget | None = None) -> list[str]:
    """Find all QThread children that are still running."""
    running = []
    app = QApplication.instance()
    search_root = parent or app
    if search_root is None:
        return running
    for thread in search_root.findChildren(QThread):
        if thread.isRunning():
            name = thread.objectName() or repr(thread)
            running.append(name)
    return running


def cleanup_window(window, app=None) -> None:
    """Properly tear down a test window and ensure clean SQLite/Qt release."""
    if window is None:
        return
    if hasattr(window, "db") and window.db is not None:
        try:
            window.db.close()
        except Exception:
            pass
    try:
        window.close()
        window.deleteLater()
    except Exception:
        pass
    gc.collect()
    if app is None:
        app = QApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents()


# ── Report I/O ───────────────────────────────────────────────────────


def write_report(report: HarnessReport, output_dir: str | Path) -> tuple[Path, Path]:
    """Write JSON and Markdown reports. Returns (json_path, md_path)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "report.json"
    json_path.write_text(
        json.dumps(report.to_json(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    md_path = output_dir / "HCI_ACCEPTANCE.md"
    md_path.write_text(report.to_markdown(), encoding="utf-8")

    return json_path, md_path
