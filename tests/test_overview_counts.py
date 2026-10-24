# -*- coding: utf-8 -*-
"""The workbench summary aggregates must match the per-row data-status rules.

`_collect_overview_metrics` used to hydrate every invoice row and derive the
buckets in Python.  The SQL aggregate is much cheaper on a large ledger, so it
must keep the exact same semantics — this module compares it with the existing
per-row helper on a deliberately mixed fixture.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp

NEEDS_FIX_STATUSES = {"待补全", "缺原件", "缺证明", "未识别"}


class OverviewCountsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _close(self, window):
        try:
            window.close()
        except Exception:
            pass
        try:
            db = getattr(window, "db", None)
            if db is not None and getattr(db, "is_open", False):
                db.close()
        except Exception:
            pass
        self.app.processEvents()

    def _seed(self, db_path: Path) -> Path:
        runtime = db_path.parent
        attachments = runtime / "attachments"
        attachments.mkdir(parents=True, exist_ok=True)
        present = attachments / "present.pdf"
        present.write_bytes(b"%PDF-1.4 synthetic")
        month = datetime.now().strftime("%Y-%m")
        base = {
            "invoice_number": "SYN-1",
            "total_amount": "10.00",
            "seller_name": "Seller",
            "invoice_date": "2026-01-02",
            "attachment_path": str(present),
            "review_status": "to_review",
        }
        counter = {"value": 0}

        def make(**overrides) -> dict:
            counter["value"] += 1
            data = dict(base)
            data["invoice_number"] = f"SYN-{counter['value']}"
            data.update(overrides)
            return data

        rows = [
            make(),                                                         # normal
            make(invoice_number=""),                                        # 待补全
            make(total_amount=""),                                          # 待补全
            make(invoice_date=""),                                          # 待补全
            make(seller_name=""),                                           # 待补全
            make(attachment_path=""),                                       # 缺原件
            make(missing_extra=1),                                          # 缺证明
            make(invoice_number="", total_amount="", seller_name=""),        # 未识别
            make(expense_date="2026-03-04", invoice_date=""),                # normal (日期回退)
            make(invoice_date=f"{month}-05", total_amount="100.50"),         # 本月
            make(invoice_date=f"{month}-06", total_amount="abc"),            # 本月但金额无效
            make(review_status="error"),                                     # 异常状态
            make(review_status="approved"),                                  # 已通过
        ]
        with InvoiceDB(db_path) as db:
            for row in rows:
                db.insert_invoice(row)
            deleted_id = db.insert_invoice(make())
            db.soft_delete_invoice(deleted_id)
        return db_path

    def _reference(self, window: InvoiceReviewApp) -> dict:
        rows = window.db.get_all_invoices(include_deleted=False)
        needs_fix = sum(
            1 for row in rows if window._get_invoice_data_status(row) in NEEDS_FIX_STATUSES
        )
        month_prefix = datetime.now().strftime("%Y-%m")
        month_total = Decimal("0")
        for row in rows:
            date_text = str(row.get("expense_date") or row.get("invoice_date") or "").strip()
            if not date_text.startswith(month_prefix):
                continue
            try:
                value = Decimal(str(row.get("total_amount") or "0").replace(",", "").strip() or "0")
            except (InvalidOperation, ValueError):
                continue
            if value.is_finite():
                month_total += value
        return {
            "total": len(rows),
            "needs_fix": needs_fix,
            "month_total": month_total,
            "to_review": sum(1 for row in rows if (row.get("review_status") or "to_review") == "to_review"),
            "error": sum(1 for row in rows if row.get("review_status") == "error"),
        }

    def test_aggregates_match_the_per_row_data_status_rules(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db_path = self._seed(Path(td) / "runtime" / "invoices.db")
            window = InvoiceReviewApp(db_path, splash=None)
            window._deferred_init()
            self.app.processEvents()
            try:
                reference = self._reference(window)
                metrics = window._collect_overview_metrics()
                self.assertIsNotNone(metrics)
                for key in ("total", "needs_fix", "to_review", "error"):
                    self.assertEqual(metrics[key], reference[key], key)
                self.assertEqual(metrics["month_total"], reference["month_total"])
                # The mixed fixture must actually exercise the buckets.
                self.assertGreater(reference["needs_fix"], 0)
                self.assertEqual(metrics["month_total"], Decimal("100.50"))
            finally:
                self._close(window)

    def test_deleted_rows_are_not_counted(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db_path = self._seed(Path(td) / "runtime" / "invoices.db")
            with InvoiceDB(db_path) as db:
                counts = db.review_overview_counts(datetime.now().strftime("%Y-%m"))
                self.assertEqual(counts["total"], 13, "软删除的记录不应进入统计")
                all_rows = db.get_all_invoices(include_deleted=True)
                self.assertEqual(len(all_rows), 14)

    def test_empty_database_reports_zeroes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            runtime = Path(td) / "runtime"
            runtime.mkdir(parents=True)
            window = InvoiceReviewApp(runtime / "invoices.db", splash=None)
            window._deferred_init()
            self.app.processEvents()
            try:
                metrics = window._collect_overview_metrics()
                self.assertIsNotNone(metrics)
                self.assertEqual(metrics["total"], 0)
                self.assertEqual(metrics["needs_fix"], 0)
                self.assertEqual(metrics["export_ready"], 0)
                self.assertEqual(metrics["month_total"], Decimal("0"))
            finally:
                self._close(window)


if __name__ == "__main__":
    unittest.main()
