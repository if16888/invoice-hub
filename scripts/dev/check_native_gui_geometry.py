"""Classify whether the current native desktop can run GUI geometry contracts.

This is a preflight only.  It never changes product geometry constraints and it
does not turn an unsuitable hosted desktop into a passing native release gate.
Exit codes:
  0 - native geometry has a positive splitter adjustment range
  2 - environment is unsuitable for the native GUI contract
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _rect_payload(rect) -> dict[str, int]:
    return {
        "x": int(rect.x()),
        "y": int(rect.y()),
        "width": int(rect.width()),
        "height": int(rect.height()),
    }


def seed_geometry_fixture(db_path: Path) -> None:
    """Seed the populated workbench state the native tests exercise.

    The empty-database first-run onboarding intentionally collapses the
    record header, original preview and detail pane.  Probing that state
    would report a different vertical-splitter range than the native
    geometry tests, which always run against a populated workbench.
    """
    from scripts.invoice_fetch.db import InvoiceDB

    with InvoiceDB(db_path) as db:
        db.insert_invoice(
            {
                "invoice_number": "NATIVE-001",
                "invoice_date": "2026-10-18",
                "total_amount": "10.00",
                "seller_name": "Synthetic Seller",
                "buyer_name": "Synthetic Buyer",
                "review_status": "to_review",
            }
        )


def vertical_splitter_metrics(
    *, sizes, record_minimum, record_maximum, preview_minimum
) -> dict[str, int | bool]:
    """Return the feasible record-pane bounds and remaining drag room.

    A QSplitter can be resized while its current position sits inside
    [lower, upper]; the initial position may legitimately sit above a
    fixed maximum, so feasibility is measured from the current sizes
    exactly like the native test does.
    """
    measurements = [int(value) for value in sizes]
    total = sum(measurements)
    current = measurements[0] if measurements else 0
    lower = int(record_minimum)
    upper = min(int(record_maximum), total - int(preview_minimum))
    down_room = max(0, current - lower)
    up_room = max(0, upper - current)
    return {
        "current": current,
        "total": total,
        "lower": lower,
        "upper": upper,
        "down_room": down_room,
        "up_room": up_room,
        "adjustable": max(down_room, up_room) > 0,
    }


def _classify(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
    print(f"NATIVE_GUI_GEOMETRY_CLASSIFICATION={payload['classification']}", flush=True)
    print(f"NATIVE_GUI_GEOMETRY_EXIT_CODE={payload['exit_code']}", flush=True)
    return int(payload["exit_code"])


def main() -> int:
    requested_platform = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
    if requested_platform in {"offscreen", "minimal", "minimalegl"}:
        return _classify(
            {
                "classification": "ENVIRONMENT UNSUITABLE FOR NATIVE GUI CONTRACT",
                "reason": f"non-native Qt platform requested: {requested_platform}",
                "qt_platform": requested_platform,
                "exit_code": 2,
            }
        )

    try:
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QSplitter
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        from scripts.invoice_fetch.gui.workbench_settings import (
            workbench_settings as make_workbench_settings,
        )
    except Exception as exc:
        return _classify(
            {
                "classification": "ENVIRONMENT UNSUITABLE FOR NATIVE GUI CONTRACT",
                "reason": f"native Qt application could not be imported: {type(exc).__name__}",
                "error": str(exc),
                "exit_code": 2,
            }
        )

    app = QApplication.instance() or QApplication(sys.argv)
    window = None
    with tempfile.TemporaryDirectory(prefix="invoice-hub-native-geometry-") as td:
        db_path = Path(td) / "invoices.db"
        seed_geometry_fixture(db_path)

        settings_patch = patch(
            "scripts.invoice_fetch.gui.app.workbench_settings",
            side_effect=lambda runtime_dir=None: make_workbench_settings(
                runtime_dir or Path(td)
            ),
        )
        settings_patch.start()
        try:
            window = InvoiceReviewApp(db_path, splash=None)
            screen = app.primaryScreen()
            available = screen.availableGeometry() if screen is not None else window.geometry()
            geometry = screen.geometry() if screen is not None else window.geometry()
            window.show()
            window.showNormal()
            window.raise_()
            window.activateWindow()
            target_width = max(1, min(1200, available.width() - 40))
            target_height = max(1, min(900, available.height() - 10))
            window.resize(target_width, target_height)

            deadline = time.monotonic() + 2.0
            splitter = None
            while time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(20)
                app.processEvents()
                candidate = getattr(window, "left_splitter", None)
                middle = getattr(window, "middle_workspace", None)
                if middle is not None and middle.layout() is not None:
                    middle.layout().activate()
                if candidate is not None:
                    parent = candidate.parentWidget()
                    if parent is not None and parent.layout() is not None:
                        parent.layout().activate()
                    candidate.updateGeometry()
                if (
                    isinstance(candidate, QSplitter)
                    and candidate.count() == 2
                    and candidate.handle(1) is not None
                    and len(candidate.sizes()) == 2
                    and all(int(size) > 0 for size in candidate.sizes())
                ):
                    splitter = candidate
                    break

            payload = {
                "qt_platform": requested_platform or "native-default",
                "screen_geometry": _rect_payload(geometry),
                "available_geometry": _rect_payload(available),
                "logical_dpi": {
                    "x": float(screen.logicalDotsPerInchX()) if screen is not None else None,
                    "y": float(screen.logicalDotsPerInchY()) if screen is not None else None,
                },
                "device_pixel_ratio": float(screen.devicePixelRatio()) if screen is not None else None,
                "window_client_size": [int(window.width()), int(window.height())],
            }

            if splitter is None:
                payload.update(
                    {
                        "classification": "ENVIRONMENT UNSUITABLE FOR NATIVE GUI CONTRACT",
                        "reason": "real vertical splitter did not become available",
                        "exit_code": 2,
                    }
                )
                return _classify(payload)

            sizes = [int(value) for value in splitter.sizes()]
            record = splitter.widget(0)
            preview = splitter.widget(1)
            record_min = int(record.minimumHeight())
            preview_min = int(preview.minimumHeight())
            record_max = int(record.maximumHeight())
            metrics = vertical_splitter_metrics(
                sizes=sizes,
                record_minimum=record_min,
                record_maximum=record_max,
                preview_minimum=preview_min,
            )
            total = int(metrics["total"])
            lower = int(metrics["lower"])
            upper = int(metrics["upper"])
            payload.update(
                {
                    "splitter_client_size": [int(splitter.width()), int(splitter.height())],
                    "splitter_sizes": sizes,
                    "splitter_total": total,
                    "record_minimum": record_min,
                    "record_maximum": record_max,
                    "preview_minimum": preview_min,
                    "feasible_lower": lower,
                    "feasible_upper": upper,
                    "current_record": int(metrics["current"]),
                    "down_room": int(metrics["down_room"]),
                    "up_room": int(metrics["up_room"]),
                }
            )
            if not bool(metrics["adjustable"]):
                payload.update(
                    {
                        "classification": "ENVIRONMENT UNSUITABLE FOR NATIVE GUI CONTRACT",
                        "reason": "splitter has no positive user-adjustment range",
                        "exit_code": 2,
                    }
                )
            else:
                payload.update(
                    {
                        "classification": "NATIVE GUI GEOMETRY SUITABLE",
                        "reason": "splitter has a positive user-adjustment range",
                        "exit_code": 0,
                    }
                )
            return _classify(payload)
        finally:
            if window is not None:
                try:
                    if window.db is not None:
                        window.db.close()
                    window.close()
                    window.deleteLater()
                    for _ in range(5):
                        app.processEvents()
                except Exception:
                    pass
            settings_patch.stop()


if __name__ == "__main__":
    raise SystemExit(main())
