import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

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

    def test_dashboard_continue_clears_stale_search_and_quick_filters(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window_with_status_mix(td)
            try:
                QTest.qWait(100)  # Finish the scheduled desktop initialization.
                window.txt_search.setText("APPROVED-00")
                window.chk_unlinked.setChecked(True)
                window.column_filters["seller_name"] = {"mode": "values", "values": ["Other Seller"]}
                window._load_invoices()
                window._switch_main_page("overview")
                self.app.processEvents()
                window.btn_hci_continue_tasks.click()
                for _ in range(40):
                    QTest.qWait(25)
                    if window.review_page.property("hciContinuousReview"):
                        break

                self.assertEqual(window.txt_search.text(), "")
                self.assertFalse(window.chk_unlinked.isChecked())
                self.assertEqual(window.column_filters, {})
                self.assertEqual(window.current_filter_status, TO_REVIEW)
                self.assertEqual(window.table.rowCount(), 11)
                self.assertTrue(window.review_page.property("hciContinuousReview"))
                self.assertNotIn("没有待审核", window.lbl_hci_review_progress.text())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
