import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.review_status import APPROVED, IGNORED, TO_REVIEW


class ReviewFilterConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window_with_status_mix(self, td):
        window = InvoiceReviewApp(Path(td) / "review-filter.db")
        window.show()
        self.app.processEvents()
        for index in range(11):
            window.db.insert_invoice({
                "invoice_number": f"TO-REVIEW-{index:02d}",
                "invoice_date": "2026-09-01",
                "expense_date": "2026-09-01",
                "total_amount": "1.00",
                "seller_name": "Synthetic Seller",
                "attachment_path": "synthetic.pdf",
                "review_status": TO_REVIEW,
            })
        for index in range(27):
            window.db.insert_invoice({
                "invoice_number": f"APPROVED-{index:02d}",
                "invoice_date": "2026-09-01",
                "expense_date": "2026-09-01",
                "total_amount": "1.00",
                "seller_name": "Synthetic Seller",
                "attachment_path": "synthetic.pdf",
                "review_status": APPROVED,
            })
        window.db.insert_invoice({
            "invoice_number": "IGNORED-00",
            "invoice_date": "2026-09-01",
            "expense_date": "2026-09-01",
            "total_amount": "1.00",
            "seller_name": "Synthetic Seller",
            "attachment_path": "synthetic.pdf",
            "review_status": IGNORED,
        })
        return window

    def test_programmatic_status_filter_matches_selected_segment_and_rows(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window_with_status_mix(td)
            try:
                # This mirrors completion/review handoff, which changes the
                # query state without a click on the status segment.
                window.current_filter_status = TO_REVIEW
                window._load_invoices()

                self.assertEqual(window.status_segment_control.selected(), TO_REVIEW)
                self.assertFalse(window.filter_buttons["all"].property("selected"))
                self.assertTrue(window.filter_buttons[TO_REVIEW].property("selected"))
                self.assertEqual(window.filter_buttons["all"].value(), "39")
                self.assertEqual(window.filter_buttons[TO_REVIEW].value(), "11")
                self.assertEqual(window.table.rowCount(), 11)
                self.assertIn("11", window.lbl_record_count.text())
            finally:
                window.close()

    def test_clicking_all_shows_all_records_after_status_filter(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window_with_status_mix(td)
            try:
                window.current_filter_status = TO_REVIEW
                window._load_invoices()
                window._change_filter("all")

                self.assertIsNone(window.current_filter_status)
                self.assertEqual(window.status_segment_control.selected(), "all")
                self.assertTrue(window.filter_buttons["all"].property("selected"))
                self.assertEqual(window.table.rowCount(), 39)
                self.assertIn("39", window.lbl_record_count.text())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
