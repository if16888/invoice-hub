# -*- coding: utf-8 -*-
"""Unit tests covering the 4 P1 fixes in Invoice Hub v0.1.3-rc1."""

import os
import sys
import tempfile
import unittest
import json
import gc
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QAbstractItemView
    from PySide6.QtCore import Qt, QItemSelectionModel
    from PySide6.QtTest import QTest
    _HAS_PYSIDE = True
except ImportError:
    _HAS_PYSIDE = False

from scripts.invoice_fetch.attachment_handler import build_managed_attachment_name
from scripts.invoice_fetch.excel_export import export_excel
from scripts.invoice_fetch.db import InvoiceDB

_QAPP = None


def _get_or_create_app():
    global _QAPP
    if not _HAS_PYSIDE:
        return None
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class TestNamingRules(unittest.TestCase):
    """Tests for Fix 3: full-format naming with fallbacks for missing fields."""

    def test_naming_with_full_details(self):
        # YYYY-MM-DD_消费类型_金额_发票号_原件/证明材料.ext
        name = build_managed_attachment_name(
            original_name="my_invoice.pdf",
            invoice_date="2026-06-13",
            expense_date="2026-06-12",
            fallback_date="2026-06-11",
            category="餐饮",
            total_amount="123.45",
            invoice_number="98765432",
            role="原件"
        )
        self.assertEqual(name, "2026-06-12_餐饮_123.45_98765432_原件.pdf")

    def test_naming_with_missing_details_fallbacks(self):
        # Empty category -> 未分类, empty amount -> 金额待补全, empty number -> 待补全, empty role -> 原件
        name = build_managed_attachment_name(
            original_name="test.ofd",
            invoice_date="2026-06-13",
            expense_date=None,
            category=None,
            total_amount=None,
            invoice_number=None,
            role=None
        )
        self.assertEqual(name, "2026-06-13_test.ofd")

    def test_naming_partial_fields(self):
        # If at least one of category, amount, number is present, it uses full format
        name = build_managed_attachment_name(
            original_name="receipt.png",
            invoice_date="2026-06-13",
            category="交通",
            role="证明材料"
        )
        self.assertEqual(name, "2026-06-13_交通_金额待补全_待补全_证明材料.png")


class TestExcelSorting(unittest.TestCase):
    """Tests for Fix 4: Excel export stable sort (empty dates last)."""

    def test_excel_export_sorting_logic(self):
        rows = [
            {"id": 1, "expense_date": "", "invoice_date": "", "mail_date": "", "created_at": "", "invoice_number": "1"},
            {"id": 2, "expense_date": "2026-06-12", "invoice_number": "2"},
            {"id": 3, "expense_date": "", "invoice_date": "2026-06-10", "invoice_number": "3"},
            {"id": 4, "expense_date": "", "invoice_date": "", "mail_date": "2026-06-08", "invoice_number": "4"},
            {"id": 5, "expense_date": "", "invoice_date": "", "mail_date": "", "created_at": "2026-06-05", "invoice_number": "5"},
        ]
        # Copy to check non-mutation
        orig_rows = list(rows)

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "test.xlsx"
            export_excel(rows, dest)

            # Ensure original list not mutated
            self.assertEqual(rows, orig_rows)

            # Read back using openpyxl to verify order
            from openpyxl import load_workbook
            wb = load_workbook(dest)
            ws = wb.active

            # Row 1 is header. Rows 2-6 should be data
            # Target sorted order:
            # 1. 2026-06-05 (ID 5, created_at)
            # 2. 2026-06-08 (ID 4, mail_date)
            # 3. 2026-06-10 (ID 3, invoice_date)
            # 4. 2026-06-12 (ID 2, expense_date)
            # 5. Empty date (ID 1, sort sentinel 9999-12-31)
            row_vals = []
            for r in range(2, 7):
                inv_num = ws.cell(row=r, column=1).value  # col 1 is 发票号码
                row_vals.append(inv_num)

            # Assert order: "5", "4", "3", "2", "1"
            self.assertEqual(row_vals, ["5", "4", "3", "2", "1"])


class TestGUIFixes(unittest.TestCase):
    """Tests for Fix 1 (toolbar busy transitions) and Fix 2 (multi-row delete selection & de-dup)."""

    def setUp(self):
        if not _HAS_PYSIDE:
            self.skipTest("PySide6 not available")
        self.app = _get_or_create_app()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = InvoiceDB(self.db_path)

        # Seed mock invoices
        self.db._conn.execute("""
            INSERT INTO invoices (invoice_number, invoice_date, total_amount, seller_name, is_deleted, review_status)
            VALUES ('111', '2026-06-11', '10.00', 'SellerA', 0, 'to_review'),
                   ('222', '2026-06-12', '20.00', 'SellerB', 0, 'to_review'),
                   ('333', '2026-06-13', '30.00', 'SellerC', 0, 'to_review')
        """)
        self.db._conn.commit()

        # Patch QMessageBox dialogs to prevent blocking popup dialogs
        self.msgbox_patcher = patch.object(QMessageBox, "question", return_value=QMessageBox.Yes)
        self.msgbox_patcher.start()

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value={}):
            self.review_app = InvoiceReviewApp(db_path=self.db_path)
            self.review_app._deferred_init()  # Initialize DB, categories, and load table rows
        self.review_app.show()
        self.app.processEvents()

    def tearDown(self):
        self.msgbox_patcher.stop()
        if hasattr(self, "review_app") and self.review_app is not None:
            if hasattr(self.review_app, "db") and self.review_app.db is not None:
                self.review_app.db.close()
            self.review_app.close()
            self.review_app.deleteLater()
        self.db.close()
        gc.collect()
        if self.app:
            self.app.processEvents()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_toolbar_buttons_busy_state(self):
        app = self.review_app
        # Initial states
        self.assertTrue(app.btn_import_local.isEnabled())
        self.assertTrue(app.btn_mobile_upload.isEnabled())
        self.assertTrue(app.btn_scan_email.isEnabled())
        self.assertTrue(app.btn_toolbar_export.isEnabled())

        # Set import local busy
        app._set_action_busy(app.btn_import_local, "导入中...")
        self.assertEqual(app.btn_import_local.text(), "导入中...")
        self.assertEqual(app.btn_import_local.property("busy"), "true")

        # Others must be disabled
        self.assertFalse(app.btn_import_local.isEnabled())
        self.assertFalse(app.btn_mobile_upload.isEnabled())
        self.assertFalse(app.btn_scan_email.isEnabled())
        self.assertFalse(app.btn_toolbar_export.isEnabled())

        # Clear busy
        app._clear_action_busy(app.btn_import_local, "导入发票")
        self.assertEqual(app.btn_import_local.text(), "导入发票")
        self.assertEqual(app.btn_import_local.property("busy"), "false")

        # Restored to enabled
        self.assertTrue(app.btn_import_local.isEnabled())
        self.assertTrue(app.btn_mobile_upload.isEnabled())
        self.assertTrue(app.btn_scan_email.isEnabled())
        self.assertTrue(app.btn_toolbar_export.isEnabled())

    def test_delete_multiple_rows_deduplication_and_selection_hint(self):
        app = self.review_app
        self.assertEqual(app.table.rowCount(), 3)

        # Explicitly select rows 0 and 1 using QItemSelectionModel flags
        app.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        model = app.table.selectionModel()
        model.clearSelection()

        # Select row 0
        idx0 = app.table.model().index(0, 0)
        model.select(idx0, QItemSelectionModel.Select | QItemSelectionModel.Rows)

        # Select row 1
        idx1 = app.table.model().index(1, 0)
        model.select(idx1, QItemSelectionModel.Select | QItemSelectionModel.Rows)

        # Confirm selected rows count
        self.assertEqual(len(model.selectedRows()), 2)

        # Trigger delete selected
        app._delete_selected_invoices()

        # Database should reflect deletion (only 1 undeleted remains)
        remaining = [r for r in app.db.get_all_invoices() if r.get("is_deleted") != 1]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["invoice_number"], "111")

        # UI table should reload and select the remaining row
        # min_selected_row was 0. Remaining row index in new list is 0.
        # So selection should be auto-restored to row 0.
        self.assertEqual(app.table.currentRow(), 0)
        self.assertEqual(app.table.item(0, 3).text(), "111")  # Column 3 shows invoice number
