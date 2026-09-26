import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView, QSizePolicy, QWidget

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_METRICS
from scripts.invoice_fetch.gui.design_v1_review_task_closure import (
    _refresh_compact_buyer_warning,
)
from scripts.invoice_fetch.gui.review_toolbar_filter_fixes import (
    ReimbursementTitleDialog,
    _repair_material_rows,
    _save_reimbursement_title,
)


class ReviewToolbarFilterFixesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "review-toolbar-filter.db")
        window.resize(1600, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        window._switch_main_page("review")
        for _ in range(3):
            self.app.processEvents()
        return window


    def test_clicking_header_center_opens_filter_for_any_visible_column(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                header = window.table.horizontalHeader()
                for section, key in ((2, "expense_date"), (4, "seller_name"), (5, "invoice_number")):
                    popup = getattr(window, "_column_filter_popup", None)
                    if popup is not None:
                        popup.close()
                        window._column_filter_popup = None
                    center_x = (
                        header.sectionViewportPosition(section)
                        + header.sectionSize(section) // 2
                    )
                    QTest.mouseClick(
                        header.viewport(),
                        Qt.LeftButton,
                        Qt.NoModifier,
                        QPoint(center_x, header.height() // 2),
                    )
                    for _ in range(4):
                        self.app.processEvents()
                    popup = window._column_filter_popup
                    self.assertIsNotNone(popup)
                    self.assertEqual(popup.key, key)
                    popup.close()
                    window._column_filter_popup = None
            finally:
                window.close()


    def test_seller_column_is_capped_and_invoice_column_fills_remainder(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                header = window.table.horizontalHeader()
                self.assertGreaterEqual(window.table.columnWidth(4), 180)
                self.assertLessEqual(window.table.columnWidth(4), 320)
                self.assertGreaterEqual(window.table.columnWidth(5), 178)
                self.assertEqual(
                    header.sectionResizeMode(5),
                    QHeaderView.Interactive,
                )
                self.assertEqual(window._min_column_widths[4], 180)
                self.assertGreaterEqual(window._min_column_widths[5], 178)
                window.table.setColumnWidth(4, 220)
                self.assertEqual(window.table.columnWidth(4), 220)
                window.resize(1500, 850)
                self.app.processEvents()
                self.assertEqual(window.table.columnWidth(4), 220)
                self.assertGreaterEqual(header.length(), window.table.viewport().width() - 4)
            finally:
                window.close()


    def test_buyer_mismatch_is_compact_without_direct_settings_entry(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.config = {
                    "reimbursement": {
                        "buyer_name": "Expected Company",
                        "buyer_tax_id": "9132",
                        "strict_buyer_check": True,
                    }
                }
                window.current_invoice = {"buyer_name": "Actual Company"}
                _refresh_compact_buyer_warning(window)
                detail = window._detail_panel
                self.assertFalse(detail.buyer_warning_action_row.isHidden())
                self.assertEqual(
                    detail.lbl_buyer_warning.text(),
                    "⚠️ 购买方与默认开票主体不一致：当前发票：Actual Company；默认主体：Expected Company",
                )
                self.assertIn("Actual Company", detail.lbl_buyer_warning.toolTip())
                self.assertIn("Expected Company", detail.lbl_buyer_warning.toolTip())
                self.assertTrue(detail.lbl_buyer_warning.wordWrap())
                self.assertEqual(detail.lbl_buyer_warning.maximumHeight(), 76)
                self.assertTrue(detail.btn_edit_reimbursement_title.isHidden())
            finally:
                window.close()

    def test_reimbursement_title_save_updates_local_config_contract(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.config = {"reimbursement": {}}
                with patch("scripts.invoice_fetch.gui.review_toolbar_filter_fixes.save_config") as save:
                    _save_reimbursement_title(window, "Example Company", "913200", True)
                saved = window.config["reimbursement"]
                self.assertEqual(saved["buyer_name"], "Example Company")
                self.assertEqual(saved["buyer_tax_id"], "913200")
                self.assertTrue(saved["strict_buyer_check"])
                save.assert_called_once()
            finally:
                window.close()

    def test_reimbursement_title_dialog_loads_existing_values(self):
        dialog = ReimbursementTitleDialog(
            {"buyer_name": "Example Company", "buyer_tax_id": "913200", "strict_buyer_check": True}
        )
        try:
            self.assertEqual(dialog.txt_buyer_name.text(), "Example Company")
            self.assertEqual(dialog.txt_tax_id.text(), "913200")
            self.assertTrue(dialog.chk_strict.isChecked())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
