import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QTableWidgetItem

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.review_feedback_fixes import sync_review_feedback_state
from scripts.invoice_fetch.gui.ui_components import ElidedTextLabel


class ReviewFeedbackFixesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td, width=1920, height=1080):
        window = InvoiceReviewApp(Path(td) / "review-feedback.db")
        window.resize(width, height)
        window.show()
        for _ in range(8):
            self.app.processEvents()
        window._switch_main_page("review")
        for _ in range(3):
            self.app.processEvents()
        return window

    def test_summary_keeps_decision_fields_and_hides_detail_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                detail = window._detail_panel
                self.assertTrue(window.review_page.property("reviewFeedbackFixesApplied"))
                self.assertTrue(window.review_page.property("reviewDetailClosureApplied"))
                self.assertIsInstance(detail.lbl_sum_seller, ElidedTextLabel)
                self.assertIsInstance(detail.lbl_sum_buyer, ElidedTextLabel)
                self.assertFalse(detail.lbl_sum_seller.isHidden())
                self.assertTrue(detail.lbl_sum_buyer.isHidden())
                self.assertTrue(detail.lbl_sum_date.isHidden())
                self.assertTrue(detail.lbl_sum_number.isHidden())
                self.assertTrue(detail.lbl_sum_number.property("summaryDuplicateHidden"))
            finally:
                window.close()

    def test_review_actions_share_one_readable_row(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                detail = window._detail_panel
                row = detail.findChild(QFrame, "ReviewActionRow")
                self.assertIsNotNone(row)
                self.assertEqual(row.layout().count(), 4)
                self.assertEqual(row.layout().itemAt(0).widget(), detail.btn_app)
                self.assertEqual(row.layout().itemAt(1).widget(), detail.btn_ign)
                self.assertEqual(row.layout().itemAt(2).widget(), detail.btn_err)
                self.assertGreaterEqual(detail.btn_app.height(), 34)
            finally:
                window.close()

    def test_summary_and_basic_info_values_follow_single_ownership(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                detail = window._detail_panel
                window.current_invoice = {
                    "expense_date": "2099-12-31",
                    "invoice_date": "2099-12-31",
                    "total_amount": "123.45",
                    "category": "示例分类",
                    "buyer_name": "示例科技有限公司",
                    "seller_name": "示例市示例区超长餐饮管理合伙企业（有限合伙）",
                }
                sync_review_feedback_state(window)
                self.assertFalse(detail.lbl_core_date.isHidden())
                self.assertFalse(detail.lbl_core_buyer.isHidden())
                self.assertTrue(detail.lbl_core_amount.isHidden())
                self.assertTrue(detail.lbl_core_seller.isHidden())
                self.assertEqual(detail.lbl_core_date.text(), "2099-12-31")
                self.assertEqual(detail.lbl_core_buyer.text(), window.current_invoice["buyer_name"])
                self.assertEqual(detail.lbl_sum_seller.toolTip(), window.current_invoice["seller_name"])
                self.assertEqual(detail.lbl_sum_buyer.toolTip(), window.current_invoice["buyer_name"])
                self.assertTrue(detail.lbl_sum_date.isHidden())
                self.assertEqual(detail.lbl_sum_date.text(), "2099-12-31")
            finally:
                window.close()

    def test_seller_table_cell_keeps_full_value_in_tooltip(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                seller = "示例市示例区超长餐饮管理合伙企业（有限合伙）"
                window.table.setRowCount(1)
                window.table.setItem(0, 4, QTableWidgetItem(seller))
                for _ in range(2):
                    self.app.processEvents()
                self.assertEqual(window.table.item(0, 4).toolTip(), seller)
            finally:
                window.close()

    def test_reimbursement_actions_use_separate_rows(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                detail = window._detail_panel
                self.assertTrue(detail.claim_setup_section.property("claimLayoutReflowed"))
                self.assertEqual(detail.claim_section_title.text(), "当前报销组")
                self.assertEqual(detail.claim_action_row.count(), 3)
                self.assertIs(detail.claim_action_row.itemAt(0).widget(), detail.btn_add_to_claim)
                detail.btn_add_to_claim.setText("加入 示例报销组")
                sync_review_feedback_state(window)
                self.assertEqual(detail.btn_add_to_claim.text(), "加入 示例报销组")
                self.assertEqual(detail.btn_add_to_claim.toolTip(), "加入 示例报销组")
            finally:
                window.close()

    def test_help_icon_and_text_share_one_entry_and_popup(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                button = window.btn_shortcut_help
                self.assertTrue(button.property("unifiedHelpEntry"))
                self.assertEqual(button.text(), "帮助")
                self.assertEqual(button.accessibleName(), "帮助")
                self.assertEqual(button.styleSheet(), "")
                popup = window.shortcut_disclosure
                window._show_shortcut_help_popup()
                self.app.processEvents()
                self.assertTrue(popup.isVisible())
                window._show_shortcut_help_popup()
                self.app.processEvents()
                self.assertFalse(popup.isVisible())
            finally:
                window.close()

    def test_detail_width_expands_on_desktop_but_stays_compact_at_1366(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td, 1920, 1080)
            try:
                expected_desktop_width = (
                    448 if window.workbench_nav.width() <= 96 else 400
                )
                self.assertEqual(window._detail_panel.width(), expected_desktop_width)
                window.resize(1366, 768)
                for _ in range(4):
                    self.app.processEvents()
                self.assertEqual(window._detail_panel.width(), 352)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
