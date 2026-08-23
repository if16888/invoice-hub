import hashlib
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
from scripts.invoice_fetch.invoice_parser import InvoiceInfo
from scripts.invoice_fetch.mobile_upload import MobileUploadServer, public_upload_result, UploadedFile
from scripts.invoice_fetch.review_status import APPROVED, TO_REVIEW
from scripts.invoice_fetch.services import import_local_directory


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
                "duplicates": 1,
                "new_invoice_ids": [101, 102],
                "review_invoice_ids": [101, 102],
                "duplicate_outcomes": [{
                    "source_name": "copy.pdf",
                    "existing_invoice_id": 101,
                    "duplicate_kind": "invoice_identity",
                    "reason_flags": {"file_hash_match": False},
                }],
            },
            "batch_id": "mobile_20260822_120000_abc",
        }
        sanitized = public_upload_result(internal_result)
        self.assertEqual(sanitized["accepted"], 2)
        self.assertEqual(sanitized["duplicate"], 2)
        self.assertEqual(sanitized["received"], 3)
        self.assertEqual(sanitized["failed"], 0)
        self.assertEqual(sanitized["imported"], 2)
        self.assertEqual(sanitized["batch_id"], "mobile_20260822_120000_abc")
        self.assertNotIn("new_invoice_ids", sanitized)
        self.assertNotIn("review_invoice_ids", sanitized)
        self.assertNotIn("duplicate_outcomes", sanitized)

        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._mobile_upload_finished(internal_result)
                self.assertEqual(len(window._import_activities), 1)
                act = window._import_activities[0]
                self.assertEqual(act.new_invoice_ids, (101, 102))
                self.assertEqual(act.review_invoice_ids, (101, 102))
                self.assertEqual(act.duplicates, 2)
                self.assertEqual(len(act.duplicate_outcomes), 1)
                window._refresh_imports_page()
                self.assertFalse(window.btn_import_recent_duplicates.isHidden())
                self.assertEqual(window.btn_import_recent_duplicates.text(), "查看重复项（1）")
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

    def test_e2e_a_local_soft_delete_restore(self):
        """E2E A: Local soft delete restore - id in restored & review, excluded from new_ids."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "invoices.db"
            import_dir = Path(td) / "import_inbox"
            import_dir.mkdir(parents=True)
            file_path = import_dir / "invoice_restore_a.pdf"
            file_path.write_bytes(b"%PDF-1.4 synthetic restore invoice a")
            file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()

            with InvoiceDB(db_path) as db:
                inv_id = db.insert_invoice({
                    "invoice_number": "RESTORE-A-001",
                    "total_amount": "123.45",
                    "seller_name": "商户A",
                    "invoice_date": "2026-08-22",
                    "file_hash": file_hash,
                    "review_status": TO_REVIEW,
                })
                self.assertTrue(db.soft_delete_invoice(inv_id))

            mock_parsed = InvoiceInfo(
                invoice_number="RESTORE-A-001",
                total_amount="123.45",
                seller_name="商户A",
                invoice_date="2026-08-22",
                parse_success=True,
            )
            with patch("scripts.invoice_fetch.__main__.InvoiceParser.parse_pdf", return_value=mock_parsed):
                stats = import_local_directory(import_dir, db_path)

            self.assertNotIn(inv_id, stats["new_invoice_ids"])
            self.assertIn(inv_id, stats["restored_invoice_ids"])
            self.assertIn(inv_id, stats["review_invoice_ids"])
            with InvoiceDB(db_path) as db:
                row = db.get_invoice(inv_id)
                self.assertEqual(row["is_deleted"], 0)

    def test_e2e_b_existing_invoice_evidence_update(self):
        """E2E B: Existing to_review invoice receiving evidence is not added to new, restored or review IDs."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "invoices.db"
            import_dir = Path(td) / "import_inbox"
            import_dir.mkdir(parents=True)
            evid_path = import_dir / "trip_itinerary.pdf"
            evid_path.write_bytes(b"%PDF-1.4 synthetic trip itinerary evidence")

            with InvoiceDB(db_path) as db:
                inv_id = db.insert_invoice({
                    "invoice_number": "DIDI-ORDER-123",
                    "total_amount": "56.00",
                    "seller_name": "滴滴出行",
                    "invoice_date": "2026-08-22",
                    "invoice_type": "电子发票",
                    "review_status": TO_REVIEW,
                })

            mock_parsed = InvoiceInfo(
                invoice_number="DIDI-ORDER-123",
                total_amount="56.00",
                seller_name="滴滴出行",
                invoice_date="2026-08-22",
                invoice_type="行程单",
                parse_success=True,
            )
            with patch("scripts.invoice_fetch.__main__.InvoiceParser.parse_pdf", return_value=mock_parsed):
                stats = import_local_directory(import_dir, db_path)

            self.assertNotIn(inv_id, stats["new_invoice_ids"])
            self.assertNotIn(inv_id, stats["restored_invoice_ids"])
            self.assertNotIn(inv_id, stats["review_invoice_ids"])

    def test_e2e_c_mobile_duplicate_restore(self):
        """E2E C: Mobile duplicate restore returns restored ID in internal result, but strictly redacts HTTP result."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td) / "runtime"
            db_path = runtime_dir / "invoices.db"
            content = b"%PDF-1.4 synthetic mobile duplicate payload"
            digest = hashlib.sha256(content).hexdigest()

            with InvoiceDB(db_path) as db:
                inv_id = db.insert_invoice({
                    "invoice_number": "MOBILE-RESTORE-C",
                    "total_amount": "88.88",
                    "seller_name": "手机商户",
                    "file_hash": digest,
                    "review_status": TO_REVIEW,
                })
                self.assertTrue(db.soft_delete_invoice(inv_id))

            server = MobileUploadServer(
                runtime_dir=runtime_dir,
                db_path=db_path,
                host="127.0.0.1",
                port=0,
                import_on_upload=True,
            )
            server.start()
            self.addCleanup(server.stop)

            # First upload to establish known hash in session
            server.save_uploads([UploadedFile("first.pdf", content, "application/pdf")])
            # Soft delete the invoice in DB
            with InvoiceDB(db_path) as db:
                self.assertTrue(db.soft_delete_invoice(inv_id))
            # Second upload of same duplicate hash triggers duplicate restore
            internal_result = server.save_uploads([UploadedFile("second.pdf", content, "application/pdf")])

            self.assertIn(inv_id, internal_result["restored_invoice_ids"])
            self.assertIn(inv_id, internal_result["review_invoice_ids"])

            http_result = public_upload_result(internal_result)
            self.assertNotIn("new_invoice_ids", http_result)
            self.assertNotIn("restored_invoice_ids", http_result)
            self.assertNotIn("review_invoice_ids", http_result)
            self.assertNotIn("invoice_id", http_result)
        self.assertEqual(
            set(http_result.keys()),
            {
                "accepted", "duplicate", "failed", "imported", "received",
                "created", "restored", "upload_duplicate", "business_duplicate",
                "upload_failed", "import_failed", "batch_id",
            },
        )

    def test_e2e_d_approved_restored_record(self):
        """E2E D: Restoring an approved invoice includes id in restored_invoice_ids but NOT in review_invoice_ids."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "invoices.db"
            import_dir = Path(td) / "import_inbox"
            import_dir.mkdir(parents=True)
            file_path = import_dir / "invoice_approved_d.pdf"
            file_path.write_bytes(b"%PDF-1.4 synthetic approved restore invoice d")
            file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()

            with InvoiceDB(db_path) as db:
                inv_id = db.insert_invoice({
                    "invoice_number": "APPROVED-D-001",
                    "total_amount": "99.00",
                    "seller_name": "已通过商户",
                    "invoice_date": "2026-08-22",
                    "file_hash": file_hash,
                    "review_status": APPROVED,
                })
                self.assertTrue(db.soft_delete_invoice(inv_id))

            mock_parsed = InvoiceInfo(
                invoice_number="APPROVED-D-001",
                total_amount="99.00",
                seller_name="已通过商户",
                invoice_date="2026-08-22",
                parse_success=True,
            )
            with patch("scripts.invoice_fetch.__main__.InvoiceParser.parse_pdf", return_value=mock_parsed):
                stats = import_local_directory(import_dir, db_path)

            self.assertNotIn(inv_id, stats["new_invoice_ids"])
            self.assertIn(inv_id, stats["restored_invoice_ids"])
            self.assertNotIn(inv_id, stats["review_invoice_ids"])
            with InvoiceDB(db_path) as db:
                row = db.get_invoice(inv_id)
                self.assertEqual(row["is_deleted"], 0)
                self.assertEqual(row["review_status"], APPROVED)

    def test_scope_copy_pure_new_vs_contains_restored(self):
        """Test scope banner copy: '本次新增 · N 张待确认' vs '本次导入 · N 张待确认'."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                n1 = window.db.insert_invoice({
                    "invoice_number": "N-1",
                    "total_amount": "10.00",
                    "seller_name": "S1",
                    "review_status": TO_REVIEW,
                })
                n2 = window.db.insert_invoice({
                    "invoice_number": "N-2",
                    "total_amount": "20.00",
                    "seller_name": "S2",
                    "review_status": TO_REVIEW,
                })
                r1 = window.db.insert_invoice({
                    "invoice_number": "R-1",
                    "total_amount": "30.00",
                    "seller_name": "S3",
                    "review_status": TO_REVIEW,
                })

                # Pure new
                window._record_import_activity("local", added=2, new_invoice_ids=[n1, n2], review_invoice_ids=[n1, n2])
                window._open_new_invoice_review()
                self.app.processEvents()
                self.assertEqual(window.lbl_review_scope.text(), "本次新增 · 2 张待确认")

                # Clear scope
                window._return_from_review_scope()
                self.app.processEvents()

                # Contains restored
                window._record_import_activity("local", added=1, restored=1, new_invoice_ids=[n1], review_invoice_ids=[n1, r1])
                window._open_new_invoice_review()
                self.app.processEvents()
                self.assertEqual(window.lbl_review_scope.text(), "本次导入 · 2 张待确认")
            finally:
                window.close()

    def test_e2e_e_mobile_direct_restored_result_reaches_gui_scoped_review(self):
        """E2E E: Mobile direct restored result reaches GUI scoped review and isolates items."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td) / "runtime"
            db_path = runtime_dir / "invoices.db"
            content_to_review = b"%PDF-1.4 mobile to_review duplicate payload"
            digest_to_review = hashlib.sha256(content_to_review).hexdigest()
            content_approved = b"%PDF-1.4 mobile approved duplicate payload"
            digest_approved = hashlib.sha256(content_approved).hexdigest()

            with InvoiceDB(db_path) as db:
                h_id = db.insert_invoice({
                    "invoice_number": "HIST-NOT-SCOPED",
                    "total_amount": "50.00",
                    "seller_name": "历史发票",
                    "review_status": TO_REVIEW,
                })
                r_id = db.insert_invoice({
                    "invoice_number": "MOBILE-RESTORED-TO-REVIEW",
                    "total_amount": "99.99",
                    "seller_name": "手机恢复商户",
                    "file_hash": digest_to_review,
                    "review_status": TO_REVIEW,
                })
                appr_id = db.insert_invoice({
                    "invoice_number": "MOBILE-RESTORED-APPROVED",
                    "total_amount": "88.88",
                    "seller_name": "手机审批商户",
                    "file_hash": digest_approved,
                    "review_status": APPROVED,
                })

            server = MobileUploadServer(
                runtime_dir=runtime_dir,
                db_path=db_path,
                host="127.0.0.1",
                port=0,
                import_on_upload=True,
            )
            server.start()
            self.addCleanup(server.stop)

            # Establish hashes in session
            server.save_uploads([
                UploadedFile("r.pdf", content_to_review, "application/pdf"),
                UploadedFile("a.pdf", content_approved, "application/pdf"),
            ])

            # Soft delete both in DB
            with InvoiceDB(db_path) as db:
                self.assertTrue(db.soft_delete_invoice(r_id))
                self.assertTrue(db.soft_delete_invoice(appr_id))

            # Duplicate upload 1: approved duplicate restore
            res_appr = server.save_uploads([UploadedFile("a2.pdf", content_approved, "application/pdf")])
            self.assertIn(appr_id, res_appr["restored_invoice_ids"])
            self.assertNotIn(appr_id, res_appr["review_invoice_ids"])

            # Test window with approved restore -> no review CTA
            window = self.make_window(runtime_dir)
            try:
                window._mobile_upload_finished(res_appr)
                window._refresh_overview_page()
                self.assertTrue(window.btn_overview_new_review.isHidden())
                window._refresh_imports_page()
                self.assertTrue(window.btn_import_recent_review.isHidden())

                # Duplicate upload 2: to_review duplicate restore
                res_to_rev = server.save_uploads([UploadedFile("r2.pdf", content_to_review, "application/pdf")])
                self.assertIn(r_id, res_to_rev["restored_invoice_ids"])
                self.assertIn(r_id, res_to_rev["review_invoice_ids"])

                window._mobile_upload_finished(res_to_rev)
                # Each completed POST owns a distinct immutable run-history row,
                # even when both uploads share one QR-code session.
                self.assertEqual(len(window._import_activities), 2)
                act = window._import_activities[0]
                self.assertEqual(act.restored, 1)
                self.assertEqual(act.review_invoice_ids, (r_id,))
                self.assertEqual(act.new_invoice_ids, ())

                window._refresh_overview_page()
                self.assertEqual(window.btn_overview_new_review.text(), "审核本批 1 张")
                self.assertFalse(window.btn_overview_new_review.isHidden())

                window._refresh_imports_page()
                self.assertEqual(window.btn_import_recent_review.text(), "审核本批 1 张")
                self.assertFalse(window.btn_import_recent_review.isHidden())

                # Click review CTA and check scope isolation
                window._open_new_invoice_review()
                self.app.processEvents()

                visible_ids = {int(inv["id"]) for inv in window.invoices_list}
                self.assertEqual(visible_ids, {r_id})
                self.assertNotIn(h_id, visible_ids)
                self.assertNotIn(appr_id, visible_ids)
                self.assertEqual(window.lbl_review_scope.text(), "本次导入 · 1 张待确认")
            finally:
                window.close()

    def test_e2e_f_error_conflict_created_identity_is_not_review_identity(self):
        """E2E F: Conflict/error rows are created but excluded from review_invoice_ids in local and mobile imports."""
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td) / "runtime"
            db_path = runtime_dir / "invoices.db"
            import_dir = Path(td) / "import_inbox"
            import_dir.mkdir(parents=True)

            # Insert an existing invoice
            with InvoiceDB(db_path) as db:
                existing_id = db.insert_invoice({
                    "invoice_number": "CONFLICT-001",
                    "total_amount": "100.00",
                    "seller_name": "原商户A",
                    "invoice_date": "2026-08-01",
                    "review_status": TO_REVIEW,
                })

            # Create a conflicting file with same invoice number but different seller/amount
            file_path = import_dir / "conflict_invoice.pdf"
            file_path.write_bytes(b"%PDF-1.4 conflict payload")
            mock_parsed = InvoiceInfo(
                invoice_number="CONFLICT-001",
                total_amount="200.00",
                seller_name="冲突商户B",
                invoice_date="2026-08-22",
                parse_success=True,
            )

            # 1. Local import test
            with patch("scripts.invoice_fetch.invoice_parser.InvoiceParser.parse_pdf", return_value=mock_parsed):
                stats = import_local_directory(import_dir, db_path)

            self.assertEqual(stats["conflicts"], 1)
            self.assertEqual(len(stats["new_invoice_ids"]), 1)
            conflict_id = stats["new_invoice_ids"][0]
            self.assertNotEqual(conflict_id, existing_id)
            # Crucial assertion: conflict row is created, but NOT in review_invoice_ids!
            self.assertNotIn(conflict_id, stats["review_invoice_ids"])

            with InvoiceDB(db_path) as db:
                row = db.get_invoice(conflict_id)
                self.assertEqual(row["review_status"], "error")

            # 2. Mobile import test
            server = MobileUploadServer(
                runtime_dir=runtime_dir,
                db_path=db_path,
                host="127.0.0.1",
                port=0,
                import_on_upload=True,
            )
            server.start()
            self.addCleanup(server.stop)

            mock_mob = InvoiceInfo(
                invoice_number="CONFLICT-001",
                total_amount="300.00",
                seller_name="冲突商户C",
                invoice_date="2026-08-22",
                parse_success=True,
            )
            with patch("scripts.invoice_fetch.invoice_parser.InvoiceParser.parse_pdf", return_value=mock_mob):
                internal_result = server.save_uploads([UploadedFile("mobile_conflict.pdf", b"%PDF-1.4 mob conflict", "application/pdf")])

            self.assertEqual(len(internal_result["new_invoice_ids"]), 1)
            mob_conflict_id = internal_result["new_invoice_ids"][0]
            self.assertNotIn(mob_conflict_id, internal_result["review_invoice_ids"])


if __name__ == "__main__":
    unittest.main()
