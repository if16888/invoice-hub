"""Regression tests for P1-8 (loading/inline error) and P2-7 menu alias."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


_QAPP = None


class P1StateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / "p1states.db", splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_load_failure_shows_inline_error_page_with_retry(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            original = window.db.list_review_invoices
            original_count = window.db.count_review_invoices
            try:
                def fail(_query):
                    raise RuntimeError("synthetic db failure")

                window.db.list_review_invoices = fail
                window.db.count_review_invoices = fail
                window._load_invoices()
                self.assertIs(window.left_stack.currentWidget(), window.review_error_card)
                self.assertIn("synthetic db failure", window.review_error_card.lbl_text.text())
                self.assertEqual(window.review_btn_retry.text(), "重试")
                self.assertFalse(window.review_btn_retry.isHidden())
            finally:
                window.db.list_review_invoices = original
                window.db.count_review_invoices = original_count
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_loading_page_exists_and_material_actions_have_a_menu_alias(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertIsNotNone(window.review_loading_page)
                self.assertEqual(window.review_loading_page.lbl_text.text(), "正在加载发票…")
                detail = window._detail_panel
                actions = [a.text() for a in detail.inline_more_menu.actions()]
                self.assertIn("管理 / 补充材料", actions)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
