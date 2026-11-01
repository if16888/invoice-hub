"""Regression tests for the final batch (P1-17 inline edit, P1-5 settings tabs, P2-4 detail)."""

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


class FinalBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_inline_edit_commits_one_field(self):
        from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel

        panel = InvoiceDetailPanel()
        try:
            panel._set_core_field_values(seller="旧销售方", amount="100.00")
            panel._begin_inline_edit("seller")
            self.assertFalse(panel.inline_edit_bar.isHidden())
            self.assertEqual(panel.inline_edit_input.text(), "旧销售方")
            panel.inline_edit_input.setText("新销售方")
            panel._commit_inline_edit()
            self.assertEqual(panel.txt_seller.text(), "新销售方")
            self.assertEqual(panel.lbl_core_seller.text(), "新销售方")
            self.assertTrue(panel.inline_edit_bar.isHidden())
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()

    def test_buyer_warning_detail_action_follows_the_controller(self):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        from scripts.invoice_fetch.gui.buyer_warning_controller import refresh_buyer_warning

        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "final-warning.db", splash=None)
            window.show()
            for _ in range(6):
                self.app.processEvents()
            try:
                window.config = {"reimbursement": {"buyer_name": "Expected Company", "strict_buyer_check": True}}
                window.current_invoice = {"buyer_name": "Actual Company"}
                refresh_buyer_warning(window)
                detail = window._detail_panel
                self.assertFalse(detail.lbl_buyer_warning.isHidden())
                self.assertFalse(detail.btn_buyer_warning_detail.isHidden())
                detail.lbl_buyer_warning.setToolTip("完整购买方警告")
                detail._show_full_buyer_warning()
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()



if __name__ == "__main__":
    unittest.main()
