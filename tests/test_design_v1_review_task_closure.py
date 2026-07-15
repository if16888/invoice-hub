import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.design_v1_review_task_closure import (
    _refresh_compact_buyer_warning,
)


class DesignV1ReviewTaskClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self, td: str) -> InvoiceReviewApp:
        window = InvoiceReviewApp(Path(td) / "design-v1-review-task.db")
        window.resize(1600, 900)
        window.show()
        for _ in range(10):
            self.app.processEvents()
        window._switch_main_page("review")
        for _ in range(4):
            self.app.processEvents()
        return window

    def test_review_toolbar_only_exposes_review_owned_actions(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                self.assertTrue(window.review_page.property("designV1ReviewTaskClosureApplied"))
                for attr in (
                    "btn_import_local",
                    "btn_scan_email",
                    "btn_toolbar_export",
                ):
                    button = getattr(window, attr)
                    self.assertTrue(button.isHidden(), attr)
                    self.assertTrue(button.property("reviewCrossWorkflowActionRemoved"), attr)
                    self.assertTrue(button.testAttribute(Qt.WA_DontShowOnScreen), attr)

                self.assertEqual(window.btn_more.text(), "更多")
                self.assertEqual(window.btn_more.toolTip(), "更多审核操作")
                self.assertIn("购买方", window.txt_search.placeholderText())
                self.assertIn("发票审核", window.workbench_top_toolbar.toolTip())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_buyer_mismatch_is_compact_and_has_no_settings_shortcut(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.config = {
                    "reimbursement": {
                        "buyer_name": "Expected Company",
                        "strict_buyer_check": True,
                    }
                }
                window.current_invoice = {"buyer_name": "Actual Company"}
                _refresh_compact_buyer_warning(window)

                detail = window._detail_panel
                self.assertEqual(
                    detail.lbl_buyer_warning.text(),
                    "购买方与默认开票主体不一致",
                )
                self.assertIn("Actual Company", detail.lbl_buyer_warning.toolTip())
                self.assertIn("Expected Company", detail.lbl_buyer_warning.toolTip())
                self.assertFalse(detail.lbl_buyer_warning.isHidden())
                self.assertFalse(detail.buyer_warning_action_row.isHidden())
                self.assertTrue(detail.btn_edit_reimbursement_title.isHidden())
                self.assertTrue(
                    detail.btn_edit_reimbursement_title.property(
                        "reviewCompanyActionRemoved"
                    )
                )

                window.current_invoice = {"buyer_name": "Expected Company"}
                _refresh_compact_buyer_warning(window)
                self.assertTrue(detail.lbl_buyer_warning.isHidden())
                self.assertTrue(detail.buyer_warning_action_row.isHidden())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
