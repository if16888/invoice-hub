"""Run the v0.1.7 Phase 1 synthetic GUI performance baseline.

This harness measures the current implementation only.  It uses temporary
SQLite databases and generated PDF bytes; it never reads real mailbox data,
credentials, invoice files, or user paths.  The default is 20 repetitions per
scenario, matching the Phase 1 acceptance contract.

Example (Windows PowerShell):

    $env:QT_QPA_PLATFORM = "offscreen"
    $env:INVOICE_HUB_PERFORMANCE = "1"
    python scripts/dev/performance_baseline_v1.py --repetitions 20 --output dist/performance/v017-baseline.json
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("INVOICE_HUB_PERFORMANCE", "1")
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
from PySide6.QtWidgets import QApplication, QMessageBox

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp


_OBSERVED_PROBES = []


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
    return ordered[index]


def _stats(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "min_ms": round(min(values), 3) if values else 0.0,
        "median_ms": round(statistics.median(values), 3) if values else 0.0,
        "p90_ms": round(_percentile(values, 0.90), 3),
        "p95_ms": round(_percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3) if values else 0.0,
    }


def _measure(app: QApplication, repetitions: int, callback: Callable[[], None]) -> dict[str, float | int]:
    values = []
    for _ in range(repetitions):
        app.processEvents()
        started = time.perf_counter()
        callback()
        app.processEvents(QEventLoop.AllEvents, 20)
        values.append((time.perf_counter() - started) * 1000.0)
    return _stats(values)


def _make_pdf(path: Path) -> None:
    """Write a tiny valid one-page PDF without a third-party generator."""

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Contents 4 0 R /Resources << >> >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode("ascii"))
        data.extend(body)
        data.extend(b"\nendobj\n")
    xref_offset = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(data)


def _seed_database(db_path: Path, count: int, attachment_dir: Path | None = None) -> list[int]:
    ids = []
    with InvoiceDB(db_path) as db:
        for index in range(count):
            attachment = ""
            if attachment_dir is not None:
                pdf_path = attachment_dir / f"synthetic-{index:04d}.pdf"
                if not pdf_path.exists():
                    _make_pdf(pdf_path)
                attachment = str(pdf_path)
            invoice_id = db.insert_invoice(
                {
                    "invoice_number": f"SYN-{index:06d}",
                    "invoice_date": "2026-08-01",
                    "expense_date": "2026-08-01",
                    "total_amount": f"{index + 1}.00",
                    "seller_name": "Synthetic Seller",
                    "buyer_name": "Synthetic Buyer",
                    "review_status": "to_review",
                    "attachment_path": attachment,
                }
            )
            if invoice_id is not None:
                ids.append(int(invoice_id))
    return ids


def _make_window(app: QApplication, db_path: Path) -> InvoiceReviewApp:
    config = {"reimbursement": {"strict_buyer_check": False}, "email_accounts": []}
    with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=config):
        window = InvoiceReviewApp(db_path)
    window.show()
    window._deferred_init()
    app.processEvents()
    # Keep the probe's in-memory records, but do not append every benchmark
    # line to QTextEdit: logging itself would become part of the measured UI
    # cost.  The real diagnostic mode keeps the normal redacted sink.
    window._performance_probe.set_sink(lambda _line: None)
    window._performance_probe.records.clear()
    window._performance_probe.stall_detector = window._performance_stall_detector
    _OBSERVED_PROBES.append(window._performance_probe)
    return window


def _close_window(app: QApplication, window: InvoiceReviewApp) -> None:
    # Benchmark teardown uses a deterministic controller fixture.  Firewall
    # inspection belongs to the separate mobile-network acceptance and would
    # otherwise add an external Windows subprocess to every GUI sample.
    window.mobile_upload_controller = _SyntheticMobileController(False)
    _release_preview(app, window)
    window.close()
    app.processEvents(QEventLoop.AllEvents, 50)
    _release_preview(app, window)
    if getattr(window, "db", None) is not None and window.db.is_open:
        window.db.close()


def _release_preview(app: QApplication, window: InvoiceReviewApp) -> None:
    controller = getattr(window, "pdf_preview_controller", None)
    if controller is not None:
        controller.clear()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents(QEventLoop.AllEvents, 20)


class _SyntheticMobileController:
    def __init__(self, active: bool) -> None:
        self.server = object() if active else None

    def shutdown(self) -> bool:
        self.server = None
        return True


def _run_page_switch(app: QApplication, root: Path, reps: int) -> dict:
    db_path = root / "p1.db"
    _seed_database(db_path, 50)
    window = _make_window(app, db_path)
    try:
        return {
            "id": "P1",
            "description": "idle page switching Overview↔Review and Review↔Imports",
            "stats": _measure(
                app,
                reps,
                lambda: (
                    window._switch_main_page("overview"),
                    window._switch_main_page("review"),
                    window._switch_main_page("imports"),
                    window._switch_main_page("review"),
                ),
            ),
        }
    finally:
        _close_window(app, window)


def _run_list_refresh(app: QApplication, root: Path, reps: int) -> list[dict]:
    results = []
    for count in (10, 50, 250, 1000):
        db_path = root / f"p2-{count}.db"
        _seed_database(db_path, count)
        window = _make_window(app, db_path)
        try:
            window._is_first_load = False
            results.append(
                {
                    "id": "P2",
                    "size": count,
                    "description": f"list refresh with {count} synthetic records",
                    "stats": _measure(app, reps, window._load_invoices),
                }
            )
        finally:
            _close_window(app, window)
    return results


def _run_local_import(app: QApplication, root: Path, reps: int) -> list[dict]:
    db_path = root / "p3.db"
    _seed_database(db_path, 10)
    window = _make_window(app, db_path)
    results = []
    try:
        for file_count in (1, 5, 20):
            def complete() -> None:
                window._import_activities = []
                window._import_local_finished(
                    {
                        "added": file_count,
                        "duplicates": 0,
                        "conflicts": 0,
                        "pending_manual": 0,
                        "failed": 0,
                        "new_invoice_ids": (),
                        "review_invoice_ids": (),
                    }
                )

            with patch.object(QMessageBox, "information"):
                results.append(
                    {
                        "id": "P3",
                        "size": file_count,
                        "description": f"local import completion with {file_count} synthetic files",
                        "stats": _measure(app, reps, complete),
                    }
                )
    finally:
        _close_window(app, window)
    return results


def _mobile_result(created: int, duplicates: int = 0) -> dict:
    return {
        "received": created + duplicates,
        "accepted": created,
        "created": created,
        "upload_duplicate": duplicates,
        "business_duplicate": 0,
        "upload_failed": 0,
        "import_failed": 0,
        "new_invoice_ids": (),
        "review_invoice_ids": (),
        "duplicate_outcomes": [{} for _ in range(duplicates)],
    }


def _run_mobile_completion(app: QApplication, root: Path, reps: int) -> list[dict]:
    db_path = root / "p4.db"
    _seed_database(db_path, 10)
    window = _make_window(app, db_path)
    results = []
    try:
        scenarios = (
            ("one-new", _mobile_result(1)),
            ("five-mixed", _mobile_result(2, 3)),
        )
        for label, result in scenarios:
            def complete(result=result) -> None:
                window._import_activities = []
                window._mobile_upload_finished(result)

            results.append(
                {
                    "id": "P4",
                    "size": label,
                    "description": "mobile upload completion",
                    "stats": _measure(app, reps, complete),
                }
            )

        def continuous() -> None:
            window._import_activities = []
            window._mobile_upload_finished(_mobile_result(1))
            window._mobile_upload_finished(_mobile_result(1, 1))

        results.append(
            {
                "id": "P4",
                "size": "continuous-A-B",
                "description": "two consecutive synthetic mobile batches",
                "stats": _measure(app, reps, continuous),
            }
        )
    finally:
        _close_window(app, window)
    return results


def _run_mail_completion(app: QApplication, root: Path, reps: int) -> list[dict]:
    db_path = root / "p5.db"
    _seed_database(db_path, 10)
    window = _make_window(app, db_path)
    results = []
    try:
        scenarios = (
            ("zero", {"scanned_headers": 0, "new_email_headers": 0, "classified_invoice": 0}),
            ("one", {"scanned_headers": 1, "new_email_headers": 1, "classified_invoice": 1}),
            ("multiple", {"scanned_headers": 10, "new_email_headers": 5, "classified_invoice": 5}),
        )
        for label, result in scenarios:
            def complete(result=result) -> None:
                window._import_activities = []
                window._scan_email_finished(result)

            with patch.object(QMessageBox, "information"):
                results.append(
                    {
                        "id": "P5",
                        "size": label,
                        "description": "deterministic email completion",
                        "stats": _measure(app, reps, complete),
                    }
                )
    finally:
        _close_window(app, window)
    return results


def _run_preview(app: QApplication, root: Path, reps: int) -> dict:
    attachment_dir = root / "preview-files"
    attachment_dir.mkdir()
    db_path = root / "p6.db"
    ids = _seed_database(db_path, 3, attachment_dir)
    large_path = attachment_dir / "synthetic-0002.pdf"
    large_path.write_bytes(large_path.read_bytes() + (b"% synthetic padding\n" * 50000))
    window = _make_window(app, db_path)
    try:
        window._is_first_load = False
        window._load_invoices()
        results = []
        scenarios = (
            ("single-page", (ids[0],)),
            ("multi-page-context", tuple(ids)),
            ("large-row", (ids[2],)),
        )
        for label, candidates in scenarios:
            cursor = [0]

            def select_next(candidates=candidates, cursor=cursor) -> None:
                window._select_invoice_by_id(candidates[cursor[0] % len(candidates)])
                cursor[0] += 1

            results.append(
                {
                    "id": "P6",
                    "size": label,
                    "description": "PDF row click to preview first event-loop paint",
                    "stats": _measure(app, reps, select_next),
                }
            )
        return results
    finally:
        _close_window(app, window)


def _run_shutdown(app: QApplication, root: Path, reps: int) -> list[dict]:
    results = []
    scenarios = (
        ("idle", 0, False, False, False),
        ("pdf-loaded", 3, True, False, False),
        ("mobile-active", 10, False, True, False),
        ("mobile-used-once", 10, False, True, True),
        ("representative-db", 250, False, False, False),
    )
    for label, count, load_pdf, mobile_active, mobile_used_once in scenarios:
        with tempfile.TemporaryDirectory(dir=root) as scenario_dir:
            scenario_root = Path(scenario_dir)
            attachment_dir = scenario_root / "files" if load_pdf else None
            if attachment_dir is not None:
                attachment_dir.mkdir()
            db_path = scenario_root / "shutdown.db"
            ids = _seed_database(db_path, count, attachment_dir)
            values = []
            for _ in range(reps):
                window = _make_window(app, db_path)
                if load_pdf and ids:
                    window._is_first_load = False
                    window._load_invoices()
                    window._select_invoice_by_id(ids[0])
                    app.processEvents()
                if mobile_active:
                    window.mobile_upload_controller = _SyntheticMobileController(True)
                else:
                    window.mobile_upload_controller = _SyntheticMobileController(False)
                if mobile_used_once:
                    window._mobile_upload_finished(_mobile_result(1))
                started = time.perf_counter()
                window.close()
                app.processEvents(QEventLoop.AllEvents, 50)
                values.append((time.perf_counter() - started) * 1000.0)
                _release_preview(app, window)
                if getattr(window, "db", None) is not None and window.db.is_open:
                    window.db.close()
            results.append(
                {
                    "id": "P7",
                    "size": label,
                    "description": "synthetic shutdown path",
                    "stats": _stats(values),
                }
            )
    return results


def run(repetitions: int) -> dict:
    app = QApplication.instance() or QApplication([])
    _OBSERVED_PROBES.clear()
    with tempfile.TemporaryDirectory(prefix="invoice-hub-perf-") as temp_dir:
        root = Path(temp_dir)
        scenarios = [_run_page_switch(app, root, repetitions)]
        scenarios.extend(_run_list_refresh(app, root, repetitions))
        scenarios.extend(_run_local_import(app, root, repetitions))
        scenarios.extend(_run_mobile_completion(app, root, repetitions))
        scenarios.extend(_run_mail_completion(app, root, repetitions))
        scenarios.extend(_run_preview(app, root, repetitions))
        scenarios.extend(_run_shutdown(app, root, repetitions))

        trace_totals = {}
        for probe in _OBSERVED_PROBES:
            for record in probe.records:
                event = str(record.get("event") or "unknown")
                trace_totals.setdefault(event, []).append(float(record.get("total_ms", 0.0)))
        trace_summary = {
            event: _stats(values)
            for event, values in sorted(trace_totals.items())
        }
        gaps = []
        stage_counts = Counter()
        for probe in _OBSERVED_PROBES:
            detector = getattr(probe, "stall_detector", None)
            if detector is None:
                continue
            gaps.extend(detector.gaps_ms)
            stage_counts.update(detector.stages)
        stalled = [gap for gap in gaps if gap > 50.0]
        stall_summary = {
            "count": len(stalled),
            "p95_ms": round(_percentile(stalled, 0.95), 3) if stalled else 0.0,
            "max_ms": round(max(stalled), 3) if stalled else 0.0,
            "stage_counts": dict(sorted(stage_counts.items())),
        }

        return {
            "schema": "invoice-hub-performance-baseline-v1",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "qt_platform": os.environ.get("QT_QPA_PLATFORM", ""),
                "performance_mode": os.environ.get("INVOICE_HUB_PERFORMANCE", ""),
                "synthetic_only": True,
                "repetitions": repetitions,
            },
            "scenarios": scenarios,
            "observability": {
                "trace_summary": trace_summary,
                "gui_stall_summary": stall_summary,
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repetitions < 20:
        parser.error("Phase 1 requires at least 20 repetitions per scenario")
    result = run(args.repetitions)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    # PowerShell's legacy console code page may be GBK; write the report as
    # UTF-8 bytes so arrows and other non-ASCII scenario labels cannot turn a
    # completed benchmark into a false non-zero exit.
    sys.stdout.buffer.write((encoded + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
