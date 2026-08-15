# -*- coding: utf-8 -*-
"""Regression coverage for mouse selection on reimbursement-group rows."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class ClaimMouseSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _flush(self):
        self.app.processEvents()
        self.app.processEvents()

    def test_mouse_click_switches_claim_and_associated_invoice_surface(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "claim-mouse-selection.db"
            with InvoiceDB(db_path) as db:
                first_invoice = db.insert_invoice(
                    {
                        "invoice_number": "CLAIM-A-001",
                        "total_amount": "10.00",
                        "seller_name": "Seller A",
                        "invoice_date": "2026-08-01",
                        "review_status": "approved",
                    }
                )
                second_invoice = db.insert_invoice(
                    {
                        "invoice_number": "CLAIM-B-001",
                        "total_amount": "20.00",
                        "seller_name": "Seller B",
                        "invoice_date": "2026-08-02",
                        "review_status": "approved",
                    }
                )
                first_claim = db.create_claim_group("Claim A")
                second_claim = db.create_claim_group("Claim B")
                self.assertTrue(db.add_invoice_to_claim(first_claim, first_invoice))
                self.assertTrue(db.add_invoice_to_claim(second_claim, second_invoice))

            window = InvoiceReviewApp(db_path, splash=None)
            try:
                window._deferred_init()
                self._flush()
                window.export_group_list.show()
                window.export_group_list.resize(360, 180)

                def row_for_claim(claim_id):
                    for row in range(window.export_group_list.count()):
                        if window.export_group_list.item(row).data(Qt.UserRole) == claim_id:
                            return row
                    return -1

                first_row_index = row_for_claim(first_claim)
                second_row_index = row_for_claim(second_claim)
                self.assertGreaterEqual(first_row_index, 0)
                self.assertGreaterEqual(second_row_index, 0)
                window.export_group_list.setCurrentRow(first_row_index)
                self._flush()

                self.assertEqual(window.export_group_list.count(), 2)
                self.assertEqual(window.export_group_list.currentItem().data(Qt.UserRole), first_claim)
                self.assertEqual(window.combo_claims.currentData(), first_claim)
                self.assertIn("Seller A", window.export_invoice_list.item(0).text())

                second_item = window.export_group_list.item(second_row_index)
                second_row = window.export_group_list.itemWidget(second_item)
                second_title = second_row.findChildren(QLabel)[0]
                QTest.mouseClick(second_title, Qt.LeftButton, pos=second_title.rect().center())
                self._flush()

                self.assertEqual(window.export_group_list.currentItem().data(Qt.UserRole), second_claim)
                self.assertEqual(window.combo_claims.currentData(), second_claim)
                self.assertIn("Seller B", window.export_invoice_list.item(0).text())
                self.assertEqual(second_row.property("selected"), "true")
                self.assertNotEqual(
                    window.export_group_list.itemWidget(window.export_group_list.item(first_row_index)).property("selected"),
                    "true",
                )

                QTest.mouseDClick(second_title, Qt.LeftButton, pos=second_title.rect().center())
                self._flush()
                self.assertEqual(window.export_group_list.currentItem().data(Qt.UserRole), second_claim)

                first_item = window.export_group_list.item(first_row_index)
                first_row = window.export_group_list.itemWidget(first_item)
                first_title = first_row.findChildren(QLabel)[0]
                QTest.mouseClick(first_title, Qt.LeftButton, pos=first_title.rect().center())
                self._flush()

                self.assertEqual(window.export_group_list.currentItem().data(Qt.UserRole), first_claim)
                self.assertEqual(window.combo_claims.currentData(), first_claim)
                self.assertIn("Seller A", window.export_invoice_list.item(0).text())

                window._refresh_export_page()
                self._flush()
                self.assertEqual(window.export_group_list.currentItem().data(Qt.UserRole), first_claim)
            finally:
                if getattr(window, "db", None) is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                self._flush()


if __name__ == "__main__":
    unittest.main()
