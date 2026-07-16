import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.review_list_paging_fix import apply_review_list_paging_fix
from scripts.invoice_fetch.review_status import TO_REVIEW

_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class ReviewListPagingFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _events(self):
        for _ in range(12):
            self.app.processEvents()

    def _window(self, td, count=125):
        window = InvoiceReviewApp(Path(td) / "paging.db")
        window.show()
        self._events()
        apply_review_list_paging_fix(window.review_page)
        for index in range(count):
            self.assertIsNotNone(window.db.insert_invoice({
                "invoice_number": f"PAGING-{index:04d}",
                "invoice_date": "2026-07-01", "expense_date": "2026-07-01",
                "total_amount": f"{index + 1}.00", "seller_name": f"Synthetic {index}",
                "buyer_name": "Synthetic Buyer", "review_status": TO_REVIEW,
            }))
        window._review_page_limit = 50
        window.review_paging.load_first_page()
        self._events()
        return window

    def test_formal_method_is_not_monkey_patched(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertIs(window._append_next_invoice_batch.__func__, InvoiceReviewApp._append_next_invoice_batch)
            finally:
                window.close()

    def test_load_next_preserves_middle_selection(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window.table.selectRow(25)
                window._on_table_selection_changed()
                selected = window.current_invoice["id"]
                window.review_paging.load_next_page()
                self._events()
                self.assertGreaterEqual(len(window.invoices_list), 100)
                self.assertEqual(window.current_invoice["id"], selected)
            finally:
                window.close()

    def test_boundary_selection_enters_next_batch(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window.table.selectRow(49)
                window._on_table_selection_changed()
                window._move_invoice_selection(1)
                self._events()
                self.assertGreaterEqual(window.table.currentRow(), 50)
                self.assertGreaterEqual(len(window.invoices_list), 100)
            finally:
                window.close()

    def test_filtered_scope_resets_and_pages(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td, 60)
            try:
                window.current_filter_status = TO_REVIEW
                window.review_paging.reset_scope(("status", TO_REVIEW))
                window.review_paging.load_first_page()
                self._events()
                self.assertEqual(len(window.invoices_list), 50)
                window.review_paging.load_next_page()
                self._events()
                self.assertEqual(len(window.invoices_list), 60)
            finally:
                window.close()

    def test_double_trigger_is_guarded(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window.review_paging.loading = True
                window.review_paging.load_next_page()
                self.assertEqual(len(window.invoices_list), 50)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
