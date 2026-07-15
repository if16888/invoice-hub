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

    def _drain_events(self, cycles: int = 10) -> None:
        for _ in range(cycles):
            self.app.processEvents()

    def _make_window_with_invoices(self, td: str, count: int = 125) -> InvoiceReviewApp:
        window = InvoiceReviewApp(Path(td) / "review-paging.db")
        window.show()
        self._drain_events()
        apply_review_list_paging_fix(window.review_page)

        for index in range(count):
            inserted = window.db.insert_invoice(
                {
                    "invoice_number": f"PAGING-{index:04d}",
                    "invoice_date": "2026-07-01",
                    "expense_date": "2026-07-01",
                    "total_amount": f"{index + 1}.00",
                    "seller_name": f"Synthetic Seller {index:04d}",
                    "buyer_name": "Synthetic Buyer",
                    "review_status": TO_REVIEW,
                }
            )
            self.assertIsNotNone(inserted)

        window._review_page_limit = 50
        window._review_paging_signature = None
        window._load_invoices()
        self._drain_events()
        return window

    def test_mouse_and_keyboard_load_more_with_clear_counts(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window_with_invoices(td)
            try:
                self.assertEqual(len(window.invoices_list), 50)
                self.assertEqual(window.lbl_record_count.text(), "已加载 50 / 共 125 张")
                self.assertTrue(window.lbl_status_left.isHidden())
                self.assertEqual(
                    window.lbl_status_left.text(),
                    "当前显示 50 / 125 张｜首屏限量加载",
                )
                self.assertFalse(window.btn_load_all.isHidden())
                self.assertTrue(window.btn_load_all.property("legacyPagingCompatibilityProxy"))
                self.assertFalse(
                    window.btn_load_all.parentWidget().rect().intersects(
                        window.btn_load_all.geometry()
                    )
                )
                self.assertIn("向下滚动", window.lbl_record_count.toolTip())
                self.assertIn("↓", window.lbl_record_count.toolTip())

                window.table.selectRow(49)
                window._on_table_selection_changed()
                window._move_invoice_selection(1)
                self._drain_events()

                self.assertEqual(len(window.invoices_list), 100)
                self.assertEqual(window.table.currentRow(), 50)
                self.assertEqual(window.lbl_record_count.text(), "已加载 100 / 共 125 张")

                scrollbar = window.table.verticalScrollBar()
                window._maybe_load_more_invoices(scrollbar.maximum())
                self._drain_events()

                self.assertEqual(len(window.invoices_list), 125)
                self.assertEqual(window.lbl_record_count.text(), "已加载全部，共 125 张")
                self.assertEqual(window.lbl_status_left.text(), "共 125 张")
                self.assertTrue(window.btn_load_all.isHidden())
                self.assertIn("全部加载", window.lbl_record_count.toolTip())
            finally:
                window.close()
                window.deleteLater()
                self._drain_events()

    def test_filtered_scope_pages_then_shows_filtered_total(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window_with_invoices(td, count=60)
            try:
                window.current_filter_status = TO_REVIEW
                window._load_invoices()
                self._drain_events()

                self.assertEqual(len(window.invoices_list), 50)
                self.assertEqual(window.lbl_record_count.text(), "已加载 50 / 共 60 张")
                self.assertEqual(window._limited_first_load_total, 60)

                window._load_next_invoice_page()
                self._drain_events()

                self.assertEqual(len(window.invoices_list), 60)
                self.assertEqual(window.lbl_record_count.text(), "当前筛选 60 张")
            finally:
                window.close()
                window.deleteLater()
                self._drain_events()


if __name__ == "__main__":
    unittest.main()
