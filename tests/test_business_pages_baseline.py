import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtWidgets import QApplication, QSizePolicy

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.business_pages_baseline import _export_naming_state
from scripts.invoice_fetch.gui.ui_components import ChecklistRow


class BusinessPagesBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td, db_name="business-pages.db", size=(1600, 900)):
        window = InvoiceReviewApp(Path(td) / db_name)
        window.resize(*size)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window


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
                self.assertEqual(window.export_check_dir.property("state"), "muted")
                self.assertEqual(
                    window.export_check_dir.lbl_value.text(),
                    "已设置（导出时验证）",
                )
                self.assertEqual(window.export_check_dir.lbl_value.toolTip(), str(Path(td)))
                self.assertTrue(window.btn_run_export_page.isEnabled())
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
