import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSizePolicy

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.business_pages_baseline import _export_naming_state


class BusinessPagesBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "business-pages.db")
        window.resize(1600, 900)
        window.show()
        for _ in range(5):
            self.app.processEvents()
        return window

    def test_dashboard_uses_desktop_width_and_content_width_primary(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertTrue(window.overview_page.property("dashboardBaselineApplied"))
                self.assertEqual(window.overview_content_host.minimumWidth(), 960)
                self.assertEqual(window.overview_content_host.maximumWidth(), 1360)
                button = window.btn_overview_continue_review
                self.assertEqual(button.text(), "继续审核")
                self.assertEqual(button.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
                self.assertLessEqual(button.maximumWidth(), 180)
            finally:
                window.close()

    def test_import_task_flow_uses_responsibility_widths(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertTrue(window.imports_page.property("importBaselineApplied"))
                self.assertEqual(window.import_source_card.width(), 248)
                self.assertEqual(window.import_mail_recent_card.width(), 340)
                self.assertEqual(window.import_task_stack.maximumWidth(), 900)
                self.assertEqual(window.import_rules_detail.objectName(), "ImportRulesSubtleSection")
                self.assertEqual(window.btn_import_local_task.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
            finally:
                window.close()

    def test_export_task_flow_is_compact_and_has_truthful_naming_check(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertTrue(window.export_page.property("exportBaselineApplied"))
                self.assertEqual(window.export_group_card.width(), 280)
                self.assertEqual(window.export_integrity_card.width(), 360)
                self.assertTrue(hasattr(window, "export_check_naming"))
                self.assertEqual(window.export_check_naming.objectName(), "ExportNamingChecklistRow")
                self.assertEqual(window.export_check_naming.lbl_icon.text(), "")
                self.assertEqual(window.export_check_naming.property("state"), "muted")
                self.assertEqual(window.export_check_naming.lbl_value.text(), "等待选择报销组")
                self.assertEqual(window.btn_run_export_page.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
                self.assertLessEqual(window.btn_run_export_page.maximumWidth(), 180)
            finally:
                window.close()

    def test_export_naming_state_requires_approved_invoices(self):
        self.assertEqual(
            _export_naming_state([
                {
                    "review_status": "to_review",
                    "invoice_date": "2026-07-01",
                    "seller_name": "Synthetic Seller",
                }
            ]),
            ("等待可导出发票", "muted"),
        )

    def test_export_naming_state_warns_when_fallback_names_are_required(self):
        self.assertEqual(
            _export_naming_state([
                {
                    "review_status": "approved",
                    "invoice_date": "",
                    "seller_name": "Synthetic Seller",
                },
                {
                    "review_status": "approved",
                    "invoice_date": "2026-07-02",
                    "seller_name": "",
                },
            ]),
            ("2 张将使用默认名称", "warning"),
        )

    def test_export_naming_state_passes_only_with_date_and_seller(self):
        self.assertEqual(
            _export_naming_state([
                {
                    "review_status": "approved",
                    "expense_date": "2026-07-01",
                    "seller_name": "Synthetic Seller",
                }
            ]),
            ("1 张可按日期与商户命名", "success"),
        )


if __name__ == "__main__":
    unittest.main()
