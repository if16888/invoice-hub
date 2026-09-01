import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.review_paging import (
    ReviewPagingController,
    install_review_paging,
)
from scripts.invoice_fetch.review_status import TO_REVIEW

_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class ReviewPagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _events(self):
        for _ in range(12):
            self.app.processEvents()

    def _stub_page(self):
        window = QWidget()
        page = QWidget(window)
        window.invoices_list = []
        window._record_total_matching = 0
        window.lbl_record_count = QLabel(window)
        window.lbl_status_left = QLabel(window)
        window.lbl_status_left.show()
        window._load_invoices = Mock()
        window.search_reload_timer = QTimer(window)
        install_review_paging(page)
        self.addCleanup(window.deleteLater)
        return window

    def _window(self, td, count=125):
        window = InvoiceReviewApp(Path(td) / "paging.db")
        window.show()
        self._events()
        install_review_paging(window.review_page)
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

    def test_installer_owns_controller_copy_timer_and_legacy_status_contract(self):
        window = self._stub_page()
        self.assertIsInstance(window.review_paging, ReviewPagingController)
        self.assertEqual(window._review_page_limit, 50)
        self.assertIsNone(window._review_paging_signature)
        self.assertTrue(window.lbl_status_left.isHidden())
        self.assertTrue(window.lbl_status_left.property("pagingCountDetached"))

        window.invoices_list = [{"id": 1}]
        window._record_total_matching = 2
        window._refresh_review_paging_copy()
        self.assertEqual(window.lbl_record_count.text(), "已加载 1 / 共 2 张")

        window.invoices_list.append({"id": 2})
        window._refresh_review_paging_copy()
        self.assertEqual(window.lbl_record_count.text(), "已加载全部，共 2 张")

        window.search_reload_timer.timeout.emit()
        window._load_invoices.assert_called_once_with()

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
                queries = []
                original_list = window.db.list_review_invoices

                def record_query(query):
                    queries.append(query)
                    return original_list(query)

                window.db.list_review_invoices = record_query
                window.table.selectRow(25)
                window._on_table_selection_changed()
                selected = window.current_invoice["id"]
                first_page_ids = [invoice["id"] for invoice in window.invoices_list]
                window.review_paging.load_next_page()
                self._events()
                self.assertGreaterEqual(len(window.invoices_list), 100)
                self.assertEqual(
                    [invoice["id"] for invoice in window.invoices_list[:50]],
                    first_page_ids,
                )
                self.assertEqual(window.current_invoice["id"], selected)
                self.assertEqual([(query.limit, query.offset) for query in queries], [(50, 50)])
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

    def test_search_scope_reset_returns_to_first_page(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td, 60)
            try:
                window.txt_search.setText("PAGING-0059")
                window.search_reload_timer.stop()
                window.review_paging.reset_scope(("search", "PAGING-0059"))
                window.review_paging.load_first_page()
                self._events()
                self.assertEqual(len(window.invoices_list), 1)
                self.assertEqual(window.invoices_list[0]["invoice_number"], "PAGING-0059")

                window.txt_search.setText("")
                window.search_reload_timer.stop()
                window.review_paging.reset_scope(("search", ""))
                window.review_paging.load_first_page()
                self._events()
                self.assertEqual(len(window.invoices_list), 50)
            finally:
                window.close()

    def test_keyboard_selection_crosses_page_boundary_in_both_directions(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td, 60)
            try:
                window.table.selectRow(49)
                window._on_table_selection_changed()
                window._move_invoice_selection(1)
                self._events()
                self.assertEqual(window.table.currentRow(), 50)
                self.assertEqual(window.current_invoice["id"], window.invoices_list[50]["id"])

                window._move_invoice_selection(-1)
                self._events()
                self.assertEqual(window.table.currentRow(), 49)
                self.assertEqual(window.current_invoice["id"], window.invoices_list[49]["id"])
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
