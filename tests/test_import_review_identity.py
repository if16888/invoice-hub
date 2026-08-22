import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp, ImportActivity
from scripts.invoice_fetch.mobile_upload import public_upload_result, UploadedFile
from scripts.invoice_fetch.review_status import APPROVED, TO_REVIEW


class ImportReviewIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._msg_patch = patch.object(QMessageBox, "information")
        self._msg_patch.start()

    def tearDown(self):
        self._msg_patch.stop()

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "invoices.db")
        window.show()
        self.app.processEvents()
        return window

    def test_test1_local_identity_preserves_new_ids_and_excludes_history(self):
        """TEST 1: Local import returns exact new IDs and excludes historical rows."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "invoices.db"
            with InvoiceDB(db_path) as db:
                h1 = db.insert_invoice({
                    "invoice_number": "HIST-001",
                    "total_amount": "100.00",
                    "seller_name": "历史商户1",
                    "invoice_date": "2026-01-01",
                    "review_status": TO_REVIEW,
                })
                h2 = db.insert_invoice({
                    "invoice_number": "HIST-002",
                    "total_amount": "200.00",
                    "seller_name": "历史商户2",
                    "invoice_date": "2026-01-02",
                    "review_status": TO_REVIEW,
                })

            window = self.make_window(td)
            try:
                new_id1 = window.db.insert_invoice({
                    "invoice_number": "NEW-001",
                    "total_amount": "50.00",
                    "seller_name": "新商户1",
                    "invoice_date": "2026-08-22",
                    "review_status": TO_REVIEW,
                })
                new_id2 = window.db.insert_invoice({
                    "invoice_number": "NEW-002",
                    "total_amount": "60.00",
                    "seller_name": "新商户2",
                    "invoice_date": "2026-08-22",
                    "review_status": TO_REVIEW,
                })

                window._import_local_finished({
                    "added": 2,
                    "duplicates": 1,
                    "conflicts": 0,
                    "pending_manual": 0,
                    "failed": 0,
                    "new_invoice_ids": [new_id1, new_id2],
                    "review_invoice_ids": [new_id1, new_id2],
                })

                self.assertEqual(len(window._import_activities), 1)
                act = window._import_activities[0]
                self.assertEqual(act.new_invoice_ids, (new_id1, new_id2))
                self.assertEqual(act.review_invoice_ids, (new_id1, new_id2))
                self.assertNotIn(h1, act.new_invoice_ids)
                self.assertNotIn(h2, act.new_invoice_ids)

                # Dashboard CTA
                window._refresh_overview_page()
                self.assertEqual(window.btn_overview_new_review.text(), "处理新增 2 张")
                self.assertFalse(window.btn_overview_new_review.isHidden())

                # Import Center CTA
                window._refresh_imports_page()
                self.assertEqual(window.btn_import_recent_review.text(), "处理新增 2 张")
                self.assertFalse(window.btn_import_recent_review.isHidden())
            finally:
                window.close()

    def test_test2_mobile_identity_internal_ids_and_http_sanitization(self):
        """TEST 2: Mobile upload internal result has IDs, HTTP JSON response is sanitized."""
        internal_result = {
            "accepted": 2,
            "duplicate": 1,
            "failed": 0,
            "imported": {
                "added": 2,
                "conflicts": 0,
                "pending_manual": 0,
                "new_invoice_ids": [101, 102],
                "review_invoice_ids": [101, 102],
            },
            "batch_id": "mobile_20260822_120000_abc",
        }
        sanitized = public_upload_result(internal_result)
        self.assertEqual(sanitized["accepted"], 2)
        self.assertEqual(sanitized["duplicate"], 1)
        self.assertEqual(sanitized["failed"], 0)
        self.assertEqual(sanitized["imported"], 2)
        self.assertEqual(sanitized["batch_id"], "mobile_20260822_120000_abc")
        self.assertNotIn("new_invoice_ids", sanitized)
        self.assertNotIn("review_invoice_ids", sanitized)

        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._mobile_upload_finished(internal_result)
                self.assertEqual(len(window._import_activities), 1)
                act = window._import_activities[0]
                self.assertEqual(act.new_invoice_ids, (101, 102))
                self.assertEqual(act.review_invoice_ids, (101, 102))
            finally:
                window.close()

    def test_test3_review_scope_isolation(self):
        """TEST 3: Review scope displays only scoped items and excludes historical items."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                h_ids = [
                    window.db.insert_invoice({
                        "invoice_number": f"H-{i}",
                        "total_amount": "10.00",
                        "seller_name": "历史",
                        "invoice_date": "2026-01-01",
                        "review_status": TO_REVIEW,
                    })
                    for i in range(3)
                ]
                new_ids = [
                    window.db.insert_invoice({
                        "invoice_number": f"N-{i}",
                        "total_amount": "20.00",
                        "seller_name": "本次",
                        "invoice_date": "2026-08-22",
                        "review_status": TO_REVIEW,
                    })
                    for i in range(2)
                ]

                window._record_import_activity("local", added=2, new_invoice_ids=new_ids, review_invoice_ids=new_ids)
                window._open_new_invoice_review()
                self.app.processEvents()

                visible_ids = {int(inv["id"]) for inv in window.invoices_list}
                self.assertEqual(visible_ids, set(new_ids))
                for hid in h_ids:
                    self.assertNotIn(hid, visible_ids)
                self.assertIn("本次新增", window.lbl_review_scope.text())
            finally:
                window.close()

    def test_test4_scope_progress_and_completion(self):
        """TEST 4: Approving items updates scope progress chip and finishes with completion state."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                ids = [
                    window.db.insert_invoice({
                        "invoice_number": f"P-{i}",
                        "total_amount": "10.00",
                        "seller_name": "Progress",
                        "invoice_date": "2026-08-22",
                        "review_status": TO_REVIEW,
                    })
                    for i in range(3)
                ]
                window._record_import_activity("local", added=3, new_invoice_ids=ids, review_invoice_ids=ids)
                window._open_new_invoice_review()
                self.app.processEvents()

                self.assertIn("3 张待确认", window.lbl_review_scope.text())
                self.assertFalse(window.review_scope_completion.isVisible())

                # Approve first invoice
                window.db.update_invoice_review_status(ids[0], APPROVED)
                window._load_invoices()
                self.app.processEvents()
                self.assertIn("2 张待确认", window.lbl_review_scope.text())
                self.assertFalse(window.review_scope_completion.isVisible())

                # Approve remaining invoices
                window.db.update_invoice_review_status(ids[1], APPROVED)
                window.db.update_invoice_review_status(ids[2], APPROVED)
                window._load_invoices()
                self.app.processEvents()

                self.assertIn("本次已处理完成", window.lbl_review_scope.text())
                self.assertTrue(window.review_scope_completion.isVisible())
            finally:
                window.close()

    def test_test5_exit_scope_restores_all_invoices(self):
        """TEST 5: Exiting scope restores historical invoices to table."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                h_id = window.db.insert_invoice({
                    "invoice_number": "HIST-EXIT",
                    "total_amount": "10.00",
                    "seller_name": "历史",
                    "invoice_date": "2026-01-01",
                    "review_status": TO_REVIEW,
                })
                n_id = window.db.insert_invoice({
                    "invoice_number": "NEW-EXIT",
                    "total_amount": "20.00",
                    "seller_name": "新增",
                    "invoice_date": "2026-08-22",
                    "review_status": TO_REVIEW,
                })

                window._record_import_activity("local", added=1, new_invoice_ids=[n_id], review_invoice_ids=[n_id])
                window._open_new_invoice_review()
                self.app.processEvents()
                self.assertEqual(len(window.invoices_list), 1)

                # Return to overview
                window._return_from_review_scope()
                self.app.processEvents()
                self.assertEqual(window._review_scope_ids, ())

                # Continue historical review
                window._continue_historical_review()
                self.app.processEvents()
                visible_ids = {int(inv["id"]) for inv in window.invoices_list}
                self.assertIn(h_id, visible_ids)
                self.assertIn(n_id, visible_ids)
            finally:
                window.close()

    def test_test6_activity_stale_state_reflects_live_pending(self):
        """TEST 6: CTA button reflects live remaining pending count when some items are already approved."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                ids = [
                    window.db.insert_invoice({
                        "invoice_number": f"STALE-{i}",
                        "total_amount": "10.00",
                        "seller_name": "Stale",
                        "invoice_date": "2026-08-22",
                        "review_status": TO_REVIEW,
                    })
                    for i in range(3)
                ]
                window._record_import_activity("local", added=3, new_invoice_ids=ids, review_invoice_ids=ids)

                # Approve 2 out of 3 invoices directly in DB
                window.db.update_invoice_review_status(ids[0], APPROVED)
                window.db.update_invoice_review_status(ids[1], APPROVED)

                window._refresh_overview_page()
                self.assertEqual(window.btn_overview_new_review.text(), "处理新增 1 张")

                window._refresh_imports_page()
                self.assertEqual(window.btn_import_recent_review.text(), "处理新增 1 张")
            finally:
                window.close()

    def test_test7_restored_semantics_included_in_review_not_added(self):
        """TEST 7: Soft-deleted invoice restored during import appears in review_invoice_ids but not new_invoice_ids."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                restored_id = window.db.insert_invoice({
                    "invoice_number": "RESTORED-001",
                    "total_amount": "100.00",
                    "seller_name": "已恢复商户",
                    "invoice_date": "2026-08-22",
                    "review_status": TO_REVIEW,
                })
                new_id = window.db.insert_invoice({
                    "invoice_number": "NEW-ONLY-001",
                    "total_amount": "50.00",
                    "seller_name": "纯新增商户",
                    "invoice_date": "2026-08-22",
                    "review_status": TO_REVIEW,
                })

                # Record activity with 1 added and 1 restored (total 2 for review)
                window._record_import_activity(
                    "local",
                    added=1,
                    restored=1,
                    new_invoice_ids=[new_id],
                    review_invoice_ids=[new_id, restored_id],
                )

                act = window._import_activities[0]
                self.assertEqual(act.added, 1)
                self.assertEqual(act.restored, 1)
                self.assertEqual(act.new_invoice_ids, (new_id,))
                self.assertEqual(act.review_invoice_ids, (new_id, restored_id))

                window._refresh_overview_page()
                self.assertEqual(window.btn_overview_new_review.text(), "处理本次 2 张")

                window._refresh_imports_page()
                self.assertEqual(window.btn_import_recent_review.text(), "处理本次 2 张")
            finally:
                window.close()

    def test_test8_email_batch_isolation(self):
        """TEST 8: Email scan activity preserves batch review identity."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                h_id = window.db.insert_invoice({
                    "invoice_number": "EMAIL-HIST",
                    "total_amount": "10.00",
                    "seller_name": "历史邮件",
                    "invoice_date": "2026-01-01",
                    "review_status": TO_REVIEW,
                })
                mail_ids = [
                    window.db.insert_invoice({
                        "invoice_number": f"EMAIL-NEW-{i}",
                        "total_amount": "25.00",
                        "seller_name": "邮件新增",
                        "invoice_date": "2026-08-22",
                        "review_status": TO_REVIEW,
                    })
                    for i in range(2)
                ]

                window._scan_email_finished({
                    "scanned": 5,
                    "new": 2,
                    "new_invoice_ids": mail_ids,
                    "review_invoice_ids": mail_ids,
                })

                act = window._import_activities[0]
                self.assertEqual(act.source, "mail")
                self.assertEqual(act.new_invoice_ids, tuple(mail_ids))
                self.assertEqual(act.review_invoice_ids, tuple(mail_ids))

                window._open_new_invoice_review()
                self.app.processEvents()
                visible_ids = {int(inv["id"]) for inv in window.invoices_list}
                self.assertEqual(visible_ids, set(mail_ids))
                self.assertNotIn(h_id, visible_ids)
            finally:
                window.close()

    def test_test11_qt_clicked_signal_safety(self):
        """TEST 11: Button clicks do not inadvertently pass boolean argument into parameter slots."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.btn_overview_new_review.click()
                self.app.processEvents()

                window.btn_import_recent_review.click()
                self.app.processEvents()

                window._return_from_review_scope()
                self.app.processEvents()
                self.assertEqual(window._review_scope_ids, ())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
