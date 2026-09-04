import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class InvoiceDetailOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "invoice-detail-ownership.db")
        window.resize(1600, 900)
        window.show()
        for _ in range(10):
            self.app.processEvents()
        window._switch_main_page("review")
        for _ in range(4):
            self.app.processEvents()
        return window

    def test_summary_and_basic_information_have_single_owners(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                detail = window._detail_panel
                self.assertTrue(window.review_page.property("reviewDetailClosureApplied"))
                self.assertFalse(detail.lbl_sum_amount.isHidden())
                self.assertFalse(detail.lbl_sum_category.isHidden())
                self.assertFalse(detail.lbl_sum_seller.isHidden())
                self.assertTrue(detail.lbl_sum_date.isHidden())
                self.assertTrue(detail.lbl_sum_buyer.isHidden())
                self.assertTrue(detail.lbl_sum_number.isHidden())

                self.assertFalse(detail.lbl_core_number.isHidden())
                self.assertFalse(detail.lbl_core_date.isHidden())
                self.assertFalse(detail.lbl_core_buyer.isHidden())
                self.assertTrue(detail.lbl_core_amount.isHidden())
                self.assertTrue(detail.lbl_core_category.isHidden())
                self.assertTrue(detail.lbl_core_seller.isHidden())

                visible_summary_text = {
                    label.text().strip()
                    for label in detail.summary_card.findChildren(QLabel)
                    if not label.isHidden()
                }
                self.assertNotIn("费用日期", visible_summary_text)
                self.assertNotIn("购买方", visible_summary_text)
                self.assertNotIn("发票号码: —", visible_summary_text)
            finally:
                window.close()

    def test_material_rows_are_final_visible_surfaces(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                detail = window._detail_panel
                self.assertTrue(detail.property("materialCompatibilitySurfacesRemoved"))
                self.assertIsNone(detail.original_card)
                self.assertIsNone(detail.evidence_card)
                self.assertTrue(detail.original_status_line.property("finalMaterialRow"))
                self.assertTrue(detail.evidence_status_line.property("finalMaterialRow"))
                self.assertFalse(detail.original_status_line.isHidden())
                self.assertFalse(detail.evidence_status_line.isHidden())

                combo = detail.combo_supporting_docs
                self.assertTrue(combo.property("compatibilityModelOnly"))
                self.assertTrue(combo.isHidden())
                self.assertTrue(combo.testAttribute(Qt.WA_DontShowOnScreen))
                self.assertIs(combo.parentWidget(), detail)
            finally:
                window.close()

    def test_material_callbacks_still_update_status_line_actions(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                detail = window._detail_panel
                detail.set_attachment_state(has_file=False, has_url=False)
                self.assertEqual(detail.original_status_line.lbl_status.text(), "缺失")
                self.assertIs(detail.original_status_line._action_widget, detail.btn_add_attachment)

                detail.update_evidence_row([])
                self.assertEqual(detail.evidence_status_line.lbl_status.text(), "缺失")
                self.assertIs(detail.evidence_status_line._action_widget, detail.btn_add_evidence)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
