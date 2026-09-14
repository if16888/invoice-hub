import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.review_queue_semantics import (
    apply_import_review_scope_semantics,
    apply_review_queue_semantics,
)
from scripts.invoice_fetch.review_status import TO_REVIEW


class ReviewQueueSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self, td: str) -> InvoiceReviewApp:
        window = InvoiceReviewApp(Path(td) / "invoices.db")
        window.show()
        for _ in range(4):
            self.app.processEvents()
        apply_review_queue_semantics(window.review_page)
        apply_import_review_scope_semantics(window.imports_page)
        self.app.processEvents()
        return window

    def _insert_pending(self, window: InvoiceReviewApp, number: str) -> int:
        return window.db.insert_invoice(
            {
                "invoice_number": number,
                "total_amount": "10.00",
                "seller_name": "Queue Test",
                "invoice_date": "2026-09-14",
                "review_status": TO_REVIEW,
            }
        )

    def test_import_result_reviews_only_latest_live_batch(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                historical = [
                    self._insert_pending(window, f"HIST-{index}") for index in range(3)
                ]
                batch = [
                    self._insert_pending(window, f"BATCH-{index}") for index in range(2)
                ]
                window._record_import_activity(
                    "邮箱扫描",
                    added=2,
                    new_invoice_ids=batch,
                    review_invoice_ids=batch,
                )
                window._load_invoices()
                window._refresh_imports_page()
                for _ in range(3):
                    self.app.processEvents()

                button = window.btn_hci_import_review_result
                button.setText("去审核 2 张")
                button.show()
                button.click()
                for _ in range(6):
                    self.app.processEvents()

                self.assertEqual(tuple(window._review_scope_ids), tuple(batch))
                visible = {int(invoice["id"]) for invoice in window.invoices_list}
                self.assertEqual(visible, set(batch))
                self.assertTrue(window.review_page.property("hciContinuousReview"))
                self.assertIn("第 1 / 2 张", window.lbl_hci_review_progress.text())
                self.assertIn("本批还剩 2 张待审核", window.lbl_hci_review_progress.text())
                self.assertTrue(set(historical).isdisjoint(visible))
            finally:
                window.close()

    def test_later_moves_position_without_claiming_item_was_processed(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                batch = [
                    self._insert_pending(window, f"LATER-{index}") for index in range(3)
                ]
                window._record_import_activity(
                    "邮箱扫描",
                    added=3,
                    new_invoice_ids=batch,
                    review_invoice_ids=batch,
                )
                window._open_new_invoice_review()
                for _ in range(3):
                    self.app.processEvents()
                window._enter_hci_continuous_review()
                for _ in range(3):
                    self.app.processEvents()

                self.assertIn("第 1 / 3 张", window.lbl_hci_review_progress.text())
                self.assertIn("本批还剩 3 张待审核", window.lbl_hci_review_progress.text())

                window.btn_hci_review_later.click()
                for _ in range(3):
                    self.app.processEvents()

                self.assertIn("第 2 / 3 张", window.lbl_hci_review_progress.text())
                self.assertIn("本批还剩 3 张待审核", window.lbl_hci_review_progress.text())
                for invoice_id in batch:
                    invoice = next(
                        item for item in window.db.get_all_invoices() if int(item["id"]) == invoice_id
                    )
                    self.assertEqual(invoice["review_status"], TO_REVIEW)
            finally:
                window.close()

    def test_mail_only_missing_original_exposes_general_redownload(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.current_invoice = {
                    "id": 101,
                    "attachment_path": "",
                    "download_url": "",
                    "mail_uid": "5566",
                }
                runner = MagicMock()
                window._redownload_selected_invoices = runner

                detail = window._detail_panel
                detail.set_attachment_state(
                    has_file=False,
                    has_url=False,
                    can_download=True,
                )
                self.app.processEvents()

                self.assertIs(
                    detail.original_status_line._action_widget,
                    detail.btn_retry_download,
                )
                self.assertFalse(detail.btn_retry_download.isHidden())
                self.assertTrue(detail.btn_retry_download.isEnabled())
                self.assertFalse(detail.btn_add_attachment.isHidden())

                detail.btn_retry_download.click()
                self.app.processEvents()
                runner.assert_called_once_with()
            finally:
                window.close()

    def test_stale_attachment_path_with_mail_source_exposes_redownload(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                stale_path = Path(td) / "attachments" / "missing-original.pdf"
                window.current_invoice = {
                    "id": 103,
                    "attachment_path": str(stale_path),
                    "download_url": "",
                    "mail_uid": "7788",
                }
                runner = MagicMock()
                window._redownload_selected_invoices = runner

                detail = window._detail_panel
                detail.set_attachment_state(
                    has_file=False,
                    has_url=False,
                    can_download=True,
                )
                self.app.processEvents()

                self.assertIs(
                    detail.original_status_line._action_widget,
                    detail.btn_retry_download,
                )
                self.assertFalse(detail.btn_retry_download.isHidden())
                detail.btn_retry_download.click()
                self.app.processEvents()
                runner.assert_called_once_with()
            finally:
                window.close()

    def test_existing_original_does_not_offer_redundant_redownload(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                original = Path(td) / "existing-original.pdf"
                original.write_bytes(b"%PDF-1.7\ninvoice")
                window.current_invoice = {
                    "id": 104,
                    "attachment_path": str(original),
                    "download_url": "https://example.invalid/invoice.pdf",
                    "mail_uid": "8899",
                }

                detail = window._detail_panel
                detail.set_attachment_state(
                    has_file=True,
                    has_url=True,
                    can_download=True,
                )
                self.app.processEvents()

                self.assertIsNot(
                    detail.original_status_line._action_widget,
                    detail.btn_retry_download,
                )
            finally:
                window.close()

    def test_missing_original_without_source_keeps_manual_supplement(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.current_invoice = {
                    "id": 102,
                    "attachment_path": "",
                    "download_url": "",
                    "mail_uid": "",
                }
                detail = window._detail_panel
                detail.set_attachment_state(
                    has_file=False,
                    has_url=False,
                    can_download=False,
                )
                self.app.processEvents()

                self.assertIs(
                    detail.original_status_line._action_widget,
                    detail.btn_add_attachment,
                )
                self.assertFalse(detail.btn_add_attachment.isHidden())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
