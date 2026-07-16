"""Capture Design Baseline v1.0 with synthetic data only.

Each invocation owns a new temporary runtime directory and SQLite database.  It
never opens the normal runtime directory, credentials store, or a user invoice.
Run one process per scale factor, before QApplication exists, for example::

    QT_SCALE_FACTOR=1.25 QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough \
      python scripts/dev/capture_design_v1.py --width 1440 --height 900 \
      --scale 1.25 --page review --state default --output out.png
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# This must happen before importing Invoice Hub, whose config module resolves
# RUNTIME_DIR at import time.  The per-run value is supplied by main().
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

from PySide6.QtCore import QPoint, QRect, Qt, QSettings
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QWidget,
)


PAGES = ("overview", "review", "imports", "export", "settings-mailbox", "settings-company", "settings-ai", "settings-data", "settings-about")
STATES = (
    "default", "buyer-mismatch", "buyer-match", "missing-original",
    "loaded-next-page", "nav-collapsed", "empty", "configured", "missing-authorization",
    "disabled", "error", "export-ready", "export-blocked",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--scale", required=True, type=float)
    parser.add_argument("--page", required=True, choices=PAGES)
    parser.add_argument("--state", required=True, choices=STATES)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--geometry-output", type=Path)
    return parser.parse_args()


def _write_synthetic_invoice(path: Path) -> None:
    """Create a clearly synthetic invoice preview; it contains no user data."""
    image = QImage(1240, 1754, QImage.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#1f3b5b"), 5))
    painter.drawRoundedRect(52, 48, 1136, 1658, 14, 14)
    painter.setPen(QColor("#123456"))
    painter.setFont(QFont("Segoe UI", 34, QFont.Bold))
    painter.drawText(QRect(100, 110, 1040, 70), Qt.AlignCenter, "SYNTHETIC INVOICE / 模拟发票")
    painter.setFont(QFont("Segoe UI", 18))
    painter.setPen(QColor("#475467"))
    for row, text in enumerate((
        "Invoice No: DEMO-000001", "Seller: Synthetic Supplier Ltd.",
        "Buyer: Default Test Company", "Date: 2026-07-15", "Amount: CNY 128.50",
        "This image is generated solely for UI verification.",
    )):
        painter.drawText(120, 290 + row * 86, text)
    painter.setBrush(QBrush(QColor("#eaf2ff")))
    painter.setPen(QPen(QColor("#8db4e8"), 2))
    painter.drawRect(120, 860, 1000, 430)
    painter.setFont(QFont("Segoe UI", 22, QFont.Bold))
    painter.setPen(QColor("#1f4f82"))
    painter.drawText(QRect(140, 900, 960, 100), Qt.AlignCenter, "SYNTHETIC — NOT A FINANCIAL DOCUMENT")
    painter.end()
    if not image.save(str(path), "PNG"):
        raise RuntimeError("could not create synthetic invoice preview")


def _seed_database(db_path: Path, runtime: Path) -> None:
    from scripts.invoice_fetch.db import InvoiceDB

    fixture_dir = runtime / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    preview = fixture_dir / "synthetic_invoice.png"
    _write_synthetic_invoice(preview)
    db = InvoiceDB(db_path)
    sellers = (
        "Synthetic Office Supplies Ltd.", "Demo Travel Services Co., Ltd.",
        "示例餐饮服务有限公司", "Very Long Synthetic Supplier Name Used To Verify Elision Behaviour Co., Ltd.",
    )
    start = date(2026, 7, 15)
    try:
        for index in range(259):
            approved = index >= 245
            has_original = index != 2
            buyer = "Default Test Company" if index != 1 else "Other Synthetic Buyer Company"
            extra = ["fixtures/synthetic_invoice.png"] if index % 5 == 0 else []
            invoice_id = db.insert_invoice({
                "invoice_number": f"DEMO-{index + 1:06d}",
                "invoice_code": f"CODE-{index + 1:05d}",
                "invoice_date": str(start - timedelta(days=index % 90)),
                "expense_date": str(start - timedelta(days=index % 90)),
                "amount": f"{(index % 89) + 10}.50",
                "total_amount": f"{(index % 89) + 10}.50",
                "seller_name": sellers[index % len(sellers)],
                "buyer_name": buyer,
                "invoice_type": "电子普通发票",
                "category": "差旅" if index % 2 else "办公",
                "review_status": "approved" if approved else "to_review",
                "parse_success": 1,
                "attachment_path": "fixtures/synthetic_invoice.png" if has_original else "fixtures/missing-original.png",
                "extra_paths": extra,
                "missing_extra": 1 if index % 7 == 0 else 0,
                "mail_subject": "Synthetic fixture only",
                "mail_sender": "fixture@example.invalid",
            })
            if invoice_id is None:
                raise RuntimeError(f"failed to insert synthetic invoice {index}")
    finally:
        db.close()


def _synthetic_config() -> dict:
    return {
        "email_accounts": [{
            "mailbox_key": "synthetic-mailbox", "name": "Synthetic Mailbox",
            "address": "synthetic@example.invalid", "provider": "custom", "enabled": True,
            "is_default": True, "imap": {"server": "imap.example.invalid", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
        }],
        "reimbursement": {"buyer_name": "Default Test Company", "strict_buyer_check": True},
        "email": {}, "imap": {}, "search": {}, "ai_profiles": [], "ai": {},
    }


def _wait(app: QApplication, milliseconds: int = 650) -> None:
    app.processEvents()
    QTest.qWait(milliseconds)
    app.processEvents()
    QTest.qWait(80)
    app.processEvents()


def _select_by_number(window, number: str) -> None:
    for row, invoice in enumerate(window.invoices_list):
        if invoice.get("invoice_number") == number:
            window.table.selectRow(row)
            window.table.setCurrentCell(row, 0)
            return
    raise RuntimeError(f"fixture invoice not loaded: {number}")


def _open_page(window, page: str) -> None:
    if page == "review":
        window._switch_main_page("review")
    elif page == "overview":
        window._switch_main_page("overview")
    elif page == "imports":
        window._switch_main_page("imports")
    elif page == "export":
        window._switch_main_page("export")
    else:
        window._switch_main_page("settings")
    if page == "settings-mailbox":
        window.settings_tabs.nav_list.setCurrentRow(0)
    elif page == "settings-company":
        window.settings_tabs.nav_list.setCurrentRow(1)
    elif page == "settings-ai":
        window.settings_tabs.nav_list.setCurrentRow(2)
    elif page == "settings-data":
        window.settings_tabs.nav_list.setCurrentRow(5)
    elif page == "settings-about":
        window.settings_tabs.nav_list.setCurrentRow(6)


def _exercise_lazy_loading(window, app: QApplication) -> dict:
    if len(window.invoices_list) != 50 or window.table.rowCount() != 50:
        raise RuntimeError("first invoice page must contain exactly 50 records")
    if "50" not in window.lbl_record_count.text() or "259" not in window.lbl_record_count.text():
        raise RuntimeError("initial lazy-load count is not visible")
    window.table.selectRow(49)
    window.table.setCurrentCell(49, 0)
    _wait(app, 200)
    before_id = window.current_invoice.get("id") if window.current_invoice else None
    window.table.setFocus(Qt.OtherFocusReason)
    QTest.keyClick(window.table, Qt.Key_Down)
    _wait(app, 700)
    if len(window.invoices_list) < 100 or window.table.rowCount() < 100:
        raise RuntimeError("keyboard navigation did not load the next invoice page")
    if window.table.currentRow() < 50:
        raise RuntimeError("selection jumped back instead of entering next page")
    if not window.current_invoice or window.current_invoice.get("id") == before_id:
        raise RuntimeError("detail panel did not synchronize after lazy loading")
    if not getattr(window, "current_preview_docs", None):
        raise RuntimeError("preview unexpectedly cleared after lazy loading")
    # A separate bottom scroll must continue to request records.
    scrollbar = window.table.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    _wait(app, 700)
    if len(window.invoices_list) < 150:
        raise RuntimeError("bottom scroll did not request another invoice page")
    return {"initial": 50, "after_keyboard": 100, "after_scroll": len(window.invoices_list)}


def _global_rect(widget: QWidget) -> QRect:
    top_left = widget.mapToGlobal(QPoint(0, 0))
    return QRect(top_left, widget.size())


def _is_scroll_descendant(widget: QWidget) -> bool:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea) or parent.metaObject().className() in {"QScrollArea", "QAbstractScrollArea", "QViewport"}:
            return True
        parent = parent.parentWidget()
    return False


def _classify_geometry_widget(widget: QWidget) -> tuple[str, str]:
    """Classify one visible widget without confusing Qt child views for defects."""
    if widget.isWindow() or widget.windowFlags() & (Qt.Popup | Qt.ToolTip | Qt.Tool):
        return "IGNORED", "top-level menu, popup, tooltip, or tool window"
    if widget.testAttribute(Qt.WA_DontShowOnScreen):
        return "FAIL", "visible business widget uses WA_DontShowOnScreen"
    parent = widget.parentWidget()
    if parent is None or not parent.isVisible():
        return "IGNORED", "invisible or detached parent"
    child_rect = widget.geometry()
    visible_rect = parent.rect()
    if _is_scroll_descendant(widget):
        # Content may exceed the viewport, but a child clipped by its own
        # immediate layout parent is still a real defect.
        if not visible_rect.intersects(child_rect) and parent.metaObject().className() not in {"QWidget", "QScrollArea", "QAbstractScrollArea"}:
            return "FAIL", "scroll content child is outside its immediate parent"
        return "INFO", "scroll content may exceed viewport"
    if visible_rect.contains(child_rect):
        if isinstance(widget, QAbstractButton) and widget.isEnabled() and not widget.text().strip() and widget.icon().isNull():
            return "FAIL", "blank enabled clickable button"
        if isinstance(widget, QAbstractButton) and widget.text().strip():
            if widget.objectName() == "WorkbenchShortcutEntry":
                return "INFO", "compact shortcut tool button uses intentional style width"
            required = widget.fontMetrics().horizontalAdvance(widget.text()) + 24
            if required > widget.contentsRect().width():
                return "FAIL", "button text exceeds available width"
        return "PASS", "within parent visible rect"
    if not child_rect.intersects(visible_rect):
        return "FAIL", "widget is completely outside parent visible rect"
    if isinstance(widget, (QAbstractButton, QLabel, QLineEdit)):
        return "FAIL", "key control is partially clipped by parent visible rect"
    return "INFO", "minor layout or DPI intersection"


def _geometry(window, args: argparse.Namespace) -> dict:
    def rect(widget: QWidget | None):
        if widget is None:
            return None
        r = widget.rect()
        return [r.x(), r.y(), r.width(), r.height()]

    key_widgets = {
        "search": getattr(window, "txt_search", None), "more": getattr(window, "btn_more", None),
        "approve_next": getattr(window, "btn_approve_next", getattr(window, "btn_app", None)),
        "mailbox_add": getattr(window, "btn_settings_mailbox_add", None),
        "mailbox_credential": getattr(window, "btn_settings_mailbox_add_credential", None),
        "mailbox_edit": getattr(window, "btn_settings_mailbox_edit_config", None),
        "mailbox_more": getattr(window, "settings_mailbox_more", None),
        "company_edit": getattr(window, "btn_settings_company_profile_edit", None),
        "company_copy": getattr(window, "btn_settings_company_profile_copy", None),
    }
    button_rects, text_metrics, failures = {}, {}, []
    for name, widget in key_widgets.items():
        if widget is None:
            continue
        button_rects[name] = rect(widget)
        if isinstance(widget, (QAbstractButton, QLineEdit, QLabel)):
            text_metrics[name] = {"text": widget.text() if hasattr(widget, "text") else "", "size_hint": [widget.sizeHint().width(), widget.sizeHint().height()], "rect": rect(widget)}
            if (
                widget.isVisible()
                and widget.sizeHint().width() > widget.width() + 2
                and isinstance(widget, QAbstractButton)
                and widget.text().strip() not in {"…", "...", "⋯"}
            ):
                failures.append(f"button text exceeds width: {name}")
            if widget.isVisible() and isinstance(widget, QLabel) and widget.sizeHint().height() > widget.height():
                failures.append(f"label height below size hint: {name}")

    overflow, transparent_clickables, ignored = [], [], []
    scanned_widgets = 0
    for widget in window.findChildren(QWidget):
        if not isinstance(widget, (QAbstractButton, QLineEdit, QLabel)):
            continue
        scanned_widgets += 1
        parent = widget.parentWidget()
        if not widget.isVisible() or parent is None or not parent.isVisible():
            continue
        classification, reason = _classify_geometry_widget(widget)
        if classification == "IGNORED":
            ignored.append({"class": type(widget).__name__, "objectName": widget.objectName(), "reason": reason})
            continue
        if classification == "FAIL":
            overflow.append({"class": type(widget).__name__, "objectName": widget.objectName(), "reason": reason})
        if isinstance(widget, QAbstractButton) and widget.isEnabled() and not widget.text().strip() and widget.icon().isNull():
            transparent_clickables.append(widget.objectName() or widget.metaObject().className())
    failures.extend(f"visible control outside parent: {item['class']}:{item['objectName']} ({item['reason']})" for item in overflow)
    failures.extend(f"blank clickable control: {item}" for item in transparent_clickables)

    toolbar = window.workbench_top_toolbar
    forbidden = []
    for button in toolbar.findChildren(QAbstractButton):
        if button.isVisible() and button.text() in {"导入", "同步", "导出", "扫描邮箱"}:
            forbidden.append(button.text())
    if forbidden:
        failures.append("review toolbar contains forbidden actions: " + ", ".join(forbidden))
    if getattr(window, "btn_edit_reimbursement_title", None) and window.btn_edit_reimbursement_title.isVisible():
        failures.append("review shows company profile button")
    if args.page == "review" and args.width == 1366 and args.height == 768 and window.table.rowCount():
        row_height = window.table.verticalHeader().defaultSectionSize()
        visible_rows = window.table.viewport().height() // max(1, row_height)
        if visible_rows < 7:
            failures.append(f"visible invoice rows below 7: {visible_rows}")
    else:
        visible_rows = window.table.viewport().height() // max(1, window.table.verticalHeader().defaultSectionSize())
    if args.page == "review" and window._detail_panel.width() < 340:
        failures.append(f"detail panel below 340px: {window._detail_panel.width()}")
    if args.page == "review" and window.preview_panel.height() < 240:
        failures.append(f"preview below 240px: {window.preview_panel.height()}")
    evaluated = [item for item in window.findChildren(QWidget) if isinstance(item, (QAbstractButton, QLineEdit, QLabel)) and item.isVisible()]
    scroll_content = [item for item in evaluated if _is_scroll_descendant(item)]
    clipped_key = [item for item in overflow if item["class"] in {"QPushButton", "QLineEdit"}]
    text_overflow = [item for item in overflow if "text" in item["reason"]]
    return {
        "case": {"page": args.page, "state": args.state, "width": args.width, "height": args.height, "scale": args.scale},
        "main_window_logical_size": [window.width(), window.height()],
        "device_pixel_ratio": window.devicePixelRatioF(),
        "navigation_width": window.workbench_nav.width(),
        "toolbar_height": toolbar.height(), "status_filter_height": window.filter_bar_widget.height(),
        "visible_invoice_rows": visible_rows, "main_splitter_sizes": window.main_splitter.sizes(),
        "vertical_pane_heights": [window.left_upper_widget.height(), window.preview_panel.height()],
        "detail_panel_width": window._detail_panel.width(), "settings_shell_width": window.settings_tabs.width(),
        "mailbox_list_width": window.settings_mailbox_list.width(),
        "mailbox_detail_width": window.mailbox_detail_surface.width(), "key_button_rects": button_rects,
        "key_text_metrics": text_metrics, "has_horizontal_scrollbar": window.table.horizontalScrollBar().isVisible(),
        "outside_parent_controls": overflow, "transparent_clickables": transparent_clickables,
        "total_widgets": len(window.findChildren(QWidget)), "scanned_widgets": scanned_widgets,
        "evaluated_widgets": len(evaluated), "scroll_content_widgets": len(scroll_content),
        "clipped_key_controls": clipped_key, "text_overflow_controls": text_overflow,
        "ignored_widgets": ignored,
        "ignored_widget_count": len(ignored),
        "fail_count": len(failures),
        "warn_count": 0,
        "forbidden_review_toolbar_actions": forbidden, "failures": failures,
        "result": "FAIL" if failures else "PASS",
    }


def _append_geometry(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {"runs": []}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    key = (record.get("case") or {}).copy()
    key["case_key"] = "{page}:{state}:{width}x{height}@{scale}".format(**key)
    record["case_key"] = key["case_key"]
    runs = [item for item in existing.setdefault("runs", []) if item.get("case_key") != record["case_key"]]
    runs.append(record)
    existing["runs"] = runs
    path.write_text(json.dumps(existing, ensure_ascii=True, indent=2), encoding="utf-8")


def main() -> int:
    args = _args()
    if args.width < 800 or args.height < 600:
        raise SystemExit("minimum screenshot size is 800x600")
    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        raise SystemExit("native Windows capture refuses QT_QPA_PLATFORM=offscreen")
    if str(args.scale) != os.environ.get("QT_SCALE_FACTOR", str(args.scale)):
        raise SystemExit("QT_SCALE_FACTOR must be set before this process starts and match --scale")

    with tempfile.TemporaryDirectory(prefix="invoice-hub-design-v1-", ignore_cleanup_errors=True) as temp:
        runtime = Path(temp) / "runtime"
        os.environ["INVOICE_HUB_RUNTIME_DIR"] = str(runtime)
        # Imports deliberately occur after the runtime override above.
        from scripts.invoice_fetch.gui import app as app_module
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(Path(temp) / "qsettings"))
        original_config = app_module.load_config_safe
        app_module.load_config_safe = _synthetic_config
        try:
            app = QApplication.instance() or QApplication([])
            _seed_database(runtime / "review.db", runtime)
            window = InvoiceReviewApp(runtime / "review.db")
            window.resize(args.width, args.height)
            window.show(); window.raise_(); window.activateWindow()
            _wait(app)
            _open_page(window, args.page)
            _wait(app)
            if args.page == "review":
                if args.state == "buyer-mismatch":
                    _select_by_number(window, "DEMO-000002")
                elif args.state == "buyer-match":
                    _select_by_number(window, "DEMO-000001")
                elif args.state == "missing-original":
                    _select_by_number(window, "DEMO-000003")
                elif args.state == "loaded-next-page":
                    _exercise_lazy_loading(window, app)
                elif args.state == "nav-collapsed":
                    window.resize(min(args.width, 1366), args.height)
                    window._apply_workbench_metrics()
                else:
                    _select_by_number(window, "DEMO-000001")
                _wait(app)
            elif args.state not in STATES:
                raise RuntimeError(f"unsupported state: {args.state}")

            image = window.grab()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if image.isNull() or not image.save(str(args.output)) or not args.output.exists() or args.output.stat().st_size == 0:
                raise RuntimeError(f"failed to save non-empty screenshot: {args.output}")
            report = _geometry(window, args)
            report["screenshot"] = str(args.output)
            if args.geometry_output:
                _append_geometry(args.geometry_output, report)
            print(json.dumps(report, ensure_ascii=True))
            window.db.close()
            window.close(); window.deleteLater(); _wait(app, 100)
        finally:
            app_module.load_config_safe = original_config
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
