import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSizePolicy

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.review_toolbar_filter_fixes import (
    ReimbursementTitleDialog,
    _refresh_buyer_warning,
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

    def test_review_toolbar_uses_clear_import_language(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertEqual(window.btn_import_local.text(), "添加发票")
                self.assertIn("本地文件", window.btn_import_local.toolTip())
                self.assertEqual(window.action_import_local.text(), "本地文件")
                self.assertEqual(window.action_import_mobile.text(), "手机上传")
                self.assertEqual(window.action_import_mail.text(), "邮箱扫描")
                self.assertTrue(window.btn_scan_email.isHidden())
                self.assertEqual(window.action_scan_email.text(), "扫描邮箱")
                self.assertEqual(window.btn_import_local.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
                self.assertLessEqual(window.btn_import_local.maximumWidth(), 108)
            finally:
                window.close()

    def test_status_filters_are_compact_and_column_filters_are_discoverable(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertEqual(window.filter_bar_widget.height(), 40)
                for card in window.filter_buttons.values():
                    self.assertEqual(card.height(), 30)
                    self.assertLessEqual(card.maximumWidth(), 92)
                self.assertTrue(window.btn_advanced_filter.isHidden())
                self.assertEqual(window.lbl_record_sort.text(), "列标题可筛选")
                self.assertTrue(window.btn_reset_filters.isHidden())
                for column in range(window.table.columnCount()):
                    item = window.table.horizontalHeaderItem(column)
                    self.assertTrue(item.text().endswith("▾"), item.text())
                    self.assertIn("点击筛选", item.toolTip())
            finally:
                window.close()

    def test_active_column_filter_marks_header_and_reveals_clear_action(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.column_filters["seller_name"] = {"values": {"Synthetic Seller"}}
                window._refresh_column_filter_headers()
                self.app.processEvents()
                seller_header = window.table.horizontalHeaderItem(4)
                self.assertTrue(seller_header.text().endswith("●"), seller_header.text())
                self.assertFalse(window.btn_reset_filters.isHidden())
            finally:
                window.close()

    def test_seller_column_is_capped_and_user_resizable(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertEqual(window.table.columnWidth(4), 260)
                self.assertEqual(window.table.columnWidth(5), 190)
                self.assertEqual(window._min_column_widths[4], 180)
                self.assertEqual(window._min_column_widths[5], 160)
                window.table.setColumnWidth(4, 220)
                self.assertEqual(window.table.columnWidth(4), 220)
            finally:
                window.close()

    def test_buyer_mismatch_has_direct_title_configuration_entry(self):
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
                _refresh_buyer_warning(window)
                detail = window._detail_panel
                self.assertTrue(detail.property("buyerTitleEntryInstalled"))
                self.assertTrue(detail.buyer_warning_action_row.isVisible())
                self.assertEqual(detail.btn_edit_reimbursement_title.text(), "修改抬头")
                self.assertIn("不匹配", detail.lbl_buyer_warning.text())
                self.assertEqual(window.action_reimbursement_title.text(), "报销抬头设置")
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
