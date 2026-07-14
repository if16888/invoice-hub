import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QSizePolicy

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.business_pages_baseline import _export_naming_state
from scripts.invoice_fetch.gui.ui_components import ChecklistRow


class BusinessPagesBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td, db_name="business-pages.db"):
        window = InvoiceReviewApp(Path(td) / db_name)
        window.resize(1600, 900)
        window.show()
        for _ in range(6):
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

    def test_shared_checklist_contract_uses_icons_and_nonblocking_warning(self):
        row = ChecklistRow("待处理", "—")
        row.setProperty("falseState", "warning")
        row.set_value("2 张", ok=False)
        try:
            self.assertEqual(row.property("state"), "warning")
            self.assertEqual(row.lbl_value.property("state"), "warning")
            self.assertEqual(row.lbl_icon.text(), "")
            self.assertFalse(row.lbl_icon.pixmap().isNull())
            self.assertEqual(row.lbl_icon.styleSheet(), "")
            self.assertEqual(row.lbl_value.styleSheet(), "")
        finally:
            row.deleteLater()

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

    def test_export_naming_state_warns_only_when_real_date_prefix_falls_back(self):
        self.assertEqual(
            _export_naming_state([
                {
                    "review_status": "approved",
                    "invoice_date": "",
                    "expense_date": "",
                    "mail_date": "",
                    "seller_name": "Synthetic Seller",
                },
                {
                    "review_status": "approved",
                    "invoice_date": "2026-07-02",
                    "seller_name": "",
                },
            ]),
            ("1 张将使用 unknown-date 前缀", "warning"),
        )

    def test_export_naming_state_matches_date_prefix_and_ignores_seller(self):
        self.assertEqual(
            _export_naming_state([
                {
                    "review_status": "approved",
                    "invoice_date": "2026-07-03",
                    "expense_date": "2026-07-01",
                    "seller_name": "",
                }
            ]),
            ("1 张使用日期前缀 + 原文件名", "success"),
        )

    def test_existing_claim_keeps_real_states_and_pending_is_nonblocking(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "prepopulated-export.db"
            # Use XML so the test exercises a real attachment without leaving a
            # QPdfDocument file handle open on Windows during temp cleanup.
            attachment = Path(td) / "synthetic.xml"
            attachment.write_text("<invoice>synthetic</invoice>", encoding="utf-8")

            with InvoiceDB(db_path) as db:
                claim_id = db.create_claim_group("2026-07 Synthetic")
                approved_id = db.insert_invoice({
                    "invoice_number": "APPROVED-1",
                    "invoice_date": "2026-07-03",
                    "expense_date": "2026-07-01",
                    "seller_name": "",
                    "total_amount": "10.00",
                    "attachment_path": str(attachment),
                    "review_status": "approved",
                })
                pending_id = db.insert_invoice({
                    "invoice_number": "PENDING-1",
                    "invoice_date": "2026-07-04",
                    "seller_name": "Pending Seller",
                    "total_amount": "20.00",
                    "attachment_path": str(attachment),
                    "review_status": "to_review",
                })
                db.add_invoice_to_claim(claim_id, approved_id)
                db.add_invoice_to_claim(claim_id, pending_id)

            window = self.make_window(td, db_name="prepopulated-export.db")
            try:
                window._export_dir = Path(td)
                window._refresh_export_page()
                for _ in range(4):
                    self.app.processEvents()

                self.assertEqual(window.export_check_approved.property("state"), "success")
                self.assertEqual(window.export_check_pending.property("state"), "warning")
                self.assertEqual(window.export_check_pending.lbl_value.text(), "1 张")
                self.assertEqual(window.export_check_naming.property("state"), "success")
                self.assertEqual(
                    window.export_check_naming.lbl_value.text(),
                    "1 张使用日期前缀 + 原文件名",
                )
                self.assertTrue(window.btn_run_export_page.isEnabled())
            finally:
                window.hide()
                window.deleteLater()
                QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
