"""Regression tests for P1-11: header sorting with a separate filter zone."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.db import InvoiceDB


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


_QAPP = None


class ColumnSortingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        db_path = Path(directory) / "sorting.db"
        with InvoiceDB(db_path) as db:
            for number, amount, date in (
                ("SORT-3", "300.00", "2026-10-03"),
                ("SORT-1", "10.00", "2026-10-01"),
                ("SORT-2", "2.00", "2026-10-02"),
            ):
                db.insert_invoice(
                    {
                        "invoice_number": number,
                        "invoice_date": date,
                        "total_amount": amount,
                        "seller_name": "Synthetic Seller",
                        "buyer_name": "Synthetic Buyer",
                        "review_status": "to_review",
                    }
                )
        window = InvoiceReviewApp(db_path, splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    @staticmethod
    def _amounts(window):
        values = []
        for row in range(window.table.rowCount()):
            item = window.table.item(row, 3)
            text = item.text() if item is not None else ""
            digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
            try:
                values.append(float(digits))
            except ValueError:
                values.append(float("-inf"))
        return values

    def test_header_body_click_sorts_and_toggles_order(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertFalse(window.table.isSortingEnabled())
                window._on_header_section_clicked(3)
                self.assertEqual(self._amounts(window), sorted(self._amounts(window)))
                self.assertEqual(window.table.horizontalHeader().sortIndicatorSection(), 3)
                self.assertEqual(window.table.horizontalHeader().sortIndicatorOrder(), Qt.AscendingOrder)

                window._on_header_section_clicked(3)
                self.assertEqual(
                    self._amounts(window), sorted(self._amounts(window), reverse=True)
                )
                self.assertEqual(window.table.horizontalHeader().sortIndicatorOrder(), Qt.DescendingOrder)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_sort_survives_reload(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window._on_header_section_clicked(3)
                amounts = self._amounts(window)
                window._load_invoices()
                for _ in range(3):
                    self.app.processEvents()
                self.assertEqual(self._amounts(window), amounts)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_right_edge_funnel_zone_opens_filter_popup(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                header = window.table.horizontalHeader()
                section = 3
                left = header.sectionViewportPosition(section)
                window._column_filter_header_press_pos = QPoint(
                    left + header.sectionSize(section) - 4,
                    max(1, header.height() // 2),
                )
                window._on_header_section_clicked(section)
                popup = getattr(window, "_column_filter_popup", None)
                self.assertIsNotNone(popup)
                self.assertTrue(popup.isVisible())
                popup.close()
                window._column_filter_header_press_pos = None
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
