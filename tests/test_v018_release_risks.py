"""Targeted tests for v0.1.8 Release Risk fixes: RR-1 and RR-2.

RR-1: PDF + OFD both retained when homologous or co-occurring in email downloads.
RR-2: An invoice may belong to at most one claim group (DB obstruction, GUI feedback, and export fail-closed).
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.invoice_fetch import review_status
from scripts.invoice_fetch.claim_export import export_claim_package
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.link_downloader import DownloadedFile, _dedupe_downloaded_files


class TestV018ReleaseRisksRR1(unittest.TestCase):
    """RR-1: PDF + OFD must both be retained; deduplicate business records, not file formats."""

    def test_single_pdf_and_single_ofd_both_retained(self):
        f1 = DownloadedFile("url1", "p1", "invoice_100_0_resp.pdf", 100, True, "official_download")
        f2 = DownloadedFile("url2", "p2", "invoice_100_1_resp.ofd", 200, True, "official_download")
        results = _dedupe_downloaded_files([f1, f2])
        self.assertEqual(len(results), 2)
        filenames = [f.filename for f in results]
        self.assertIn("invoice_100_0_resp.pdf", filenames)
        self.assertIn("invoice_100_1_resp.ofd", filenames)

    def test_homologous_pdf_and_ofd_both_retained(self):
        f1 = DownloadedFile("url1", "p1", "电子发票_北京餐馆.pdf", 100, True, "official_download")
        f2 = DownloadedFile("url2", "p2", "北京餐馆.ofd", 200, True, "official_download")
        results = _dedupe_downloaded_files([f1, f2])
        self.assertEqual(len(results), 2)
        filenames = [f.filename for f in results]
        self.assertIn("电子发票_北京餐馆.pdf", filenames)
        self.assertIn("北京餐馆.ofd", filenames)

    def test_same_format_duplicates_still_deduped_pdf(self):
        f1 = DownloadedFile("url1", "p1", "invoice.pdf", 100, True, "official_download")
        f2 = DownloadedFile("url2", "p2", "invoice.pdf", 50, True, "print_fallback")
        results = _dedupe_downloaded_files([f1, f2])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source_type, "official_download")

    def test_same_format_duplicates_still_deduped_ofd(self):
        f1 = DownloadedFile("url1", "p1", "invoice.ofd", 100, True, "official_download")
        f2 = DownloadedFile("url2", "p2", "invoice.ofd", 50, True, "print_fallback")
        results = _dedupe_downloaded_files([f1, f2])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source_type, "official_download")

    def test_other_file_types_preserved(self):
        f_pdf = DownloadedFile("u1", "p1", "inv.pdf", 100, True, "official_download")
        f_ofd = DownloadedFile("u2", "p2", "inv.ofd", 100, True, "official_download")
        f_png = DownloadedFile("u3", "p3", "receipt.png", 50, True, "official_download")
        results = _dedupe_downloaded_files([f_pdf, f_ofd, f_png])
        self.assertEqual(len(results), 3)
        filenames = [f.filename for f in results]
        self.assertIn("inv.pdf", filenames)
        self.assertIn("inv.ofd", filenames)
        self.assertIn("receipt.png", filenames)


class TestV018ReleaseRisksRR2DB(unittest.TestCase):
    """RR-2 Layer 1: DB write entry obstruction for cross-claim duplicate invoices."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "test.db"
        self.db = InvoiceDB(self.db_path)

    def tearDown(self):
        if hasattr(self, "db") and self.db:
            self.db.close()
            self.db = None
        self._temp_dir.cleanup()

    def _create_sample_invoice(self, number: str = "INV001", is_evidence: bool = False) -> int:
        return self.db.insert_invoice({
            "invoice_number": number,
            "total_amount": "100.00",
            "seller_name": "Test Seller",
            "invoice_date": "2026-10-01",
            "invoice_type": "待关联证明材料" if is_evidence else "电子发票",
            "category": "交通",
            "review_status": review_status.APPROVED,
        })

    def test_invoice_add_to_claim_a_success(self):
        claim_a = self.db.create_claim_group("Claim A")
        inv_id = self._create_sample_invoice()

        success = self.db.add_invoice_to_claim(claim_a, inv_id)
        self.assertTrue(success)
        self.assertEqual(self.db.last_error, "")
        self.assertEqual(self.db.get_invoice_claim_id(inv_id), claim_a)

    def test_invoice_add_to_same_claim_duplicate_semantics(self):
        claim_a = self.db.create_claim_group("Claim A")
        inv_id = self._create_sample_invoice()

        self.assertTrue(self.db.add_invoice_to_claim(claim_a, inv_id))
        # Adding to the same claim again fails with integrity_error (duplicate in same claim)
        success = self.db.add_invoice_to_claim(claim_a, inv_id)
        self.assertFalse(success)
        self.assertEqual(self.db.last_error, "integrity_error")

    def test_invoice_add_to_different_claim_blocked_with_already_in_other_claim(self):
        claim_a = self.db.create_claim_group("Claim A")
        claim_b = self.db.create_claim_group("Claim B")
        inv_id = self._create_sample_invoice()

        self.assertTrue(self.db.add_invoice_to_claim(claim_a, inv_id))
        # Adding to claim B must be blocked with already_in_other_claim
        success = self.db.add_invoice_to_claim(claim_b, inv_id)
        self.assertFalse(success)
        self.assertEqual(self.db.last_error, "already_in_other_claim")
        # Verify invoice is still only in claim A
        self.assertEqual(self.db.count_claim_links(inv_id), 1)
        self.assertEqual(self.db.get_invoice_claim_id(inv_id), claim_a)

    def test_invoice_remove_from_claim_a_allows_add_to_claim_b(self):
        claim_a = self.db.create_claim_group("Claim A")
        claim_b = self.db.create_claim_group("Claim B")
        inv_id = self._create_sample_invoice()

        self.assertTrue(self.db.add_invoice_to_claim(claim_a, inv_id))
        self.assertFalse(self.db.add_invoice_to_claim(claim_b, inv_id))

        # Remove from claim A
        self.assertTrue(self.db.remove_invoice_from_claim(claim_a, inv_id))
        self.assertIsNone(self.db.get_invoice_claim_id(inv_id))

        # Now adding to claim B must succeed
        success = self.db.add_invoice_to_claim(claim_b, inv_id)
        self.assertTrue(success)
        self.assertEqual(self.db.last_error, "")
        self.assertEqual(self.db.get_invoice_claim_id(inv_id), claim_b)

    def test_evidence_only_invoice_cannot_be_added_to_claim(self):
        claim_a = self.db.create_claim_group("Claim A")
        evidence_id = self._create_sample_invoice("EVID001", is_evidence=True)

        success = self.db.add_invoice_to_claim(claim_a, evidence_id)
        self.assertFalse(success)
        self.assertEqual(self.db.last_error, "evidence_only")

    def test_nonexistent_invoice_returns_not_found(self):
        claim_a = self.db.create_claim_group("Claim A")
        success = self.db.add_invoice_to_claim(claim_a, 999999)
        self.assertFalse(success)
        self.assertEqual(self.db.last_error, "not_found")


class TestV018ReleaseRisksRR2Export(unittest.TestCase):
    """RR-2 Layer 3: Export fails closed when cross-claim duplicate invoices exist."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.project_root = self.root / "project"
        self.runtime_dir = self.project_root / "runtime"
        self.export_root = self.project_root / "exports"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.export_root.mkdir(parents=True, exist_ok=True)

        self.source_file = self.root / "inv_source.pdf"
        self.source_file.write_bytes(b"%PDF-1.4 sample invoice content")

        self.db_path = self.runtime_dir / "invoices.db"
        self.db = InvoiceDB(self.db_path)

    def tearDown(self):
        if hasattr(self, "db") and self.db:
            self.db.close()
            self.db = None
        self._temp_dir.cleanup()

    def test_historical_cross_claim_duplicate_blocks_export_and_leaves_no_artifacts(self):
        claim_a = self.db.create_claim_group("Claim A")
        claim_b = self.db.create_claim_group("Claim B")

        inv_id = self.db.insert_invoice({
            "invoice_number": "INV_CROSS_001",
            "total_amount": "250.00",
            "seller_name": "Multi Claim Corp",
            "invoice_date": "2026-10-01",
            "category": "餐饮",
            "review_status": review_status.APPROVED,
            "attachment_path": str(self.source_file),
        })

        # Inject historical cross-claim duplicate directly in SQLite
        # simulating legacy data where an invoice was added to multiple claims
        self.db._conn.execute(
            "INSERT INTO claim_group_items (claim_id, invoice_id, note) VALUES (?, ?, ?)",
            (claim_a, inv_id, "legacy A"),
        )
        self.db._conn.execute(
            "INSERT INTO claim_group_items (claim_id, invoice_id, note) VALUES (?, ?, ?)",
            (claim_b, inv_id, "legacy B"),
        )
        self.db._conn.commit()

        self.assertEqual(self.db.count_claim_links(inv_id), 2)

        # 1. Attempt to export Claim A -> must raise ValueError
        with self.assertRaises(ValueError) as ctx_a:
            export_claim_package(
                db=self.db,
                claim_id=claim_a,
                project_root=self.project_root,
                runtime_dir=self.runtime_dir,
                export_root=self.export_root,
            )
        self.assertIn("导出已阻断", str(ctx_a.exception))
        self.assertIn("1 张发票同时关联了其他报销组", str(ctx_a.exception))

        # 2. Attempt to export Claim B -> must also raise ValueError
        with self.assertRaises(ValueError) as ctx_b:
            export_claim_package(
                db=self.db,
                claim_id=claim_b,
                project_root=self.project_root,
                runtime_dir=self.runtime_dir,
                export_root=self.export_root,
            )
        self.assertIn("导出已阻断", str(ctx_b.exception))
        self.assertIn("1 张发票同时关联了其他报销组", str(ctx_b.exception))

        # 3. Verify fail-closed invariants:
        # - No export directory created in export_root
        self.assertEqual(list(self.export_root.iterdir()), [])
        # - No export_runs recorded in DB for either claim
        self.assertEqual(self.db.list_export_runs(claim_a), [])
        self.assertEqual(self.db.list_export_runs(claim_b), [])

        # 4. Resolve the conflict by removing the invoice from Claim B
        self.db.remove_invoice_from_claim(claim_b, inv_id)
        self.assertEqual(self.db.count_claim_links(inv_id), 1)

        # 5. Now export Claim A succeeds normally
        export_dir_a = export_claim_package(
            db=self.db,
            claim_id=claim_a,
            project_root=self.project_root,
            runtime_dir=self.runtime_dir,
            export_root=self.export_root,
        )
        self.assertTrue(export_dir_a.is_dir())
        self.assertTrue((export_dir_a / "reimbursement.xlsx").is_file())
        self.assertTrue((export_dir_a / "manifest.json").is_file())
        self.assertEqual(len(self.db.list_export_runs(claim_a)), 1)


class TestV018ReleaseRisksRR2GUI(unittest.TestCase):
    """RR-2 Layer 2: GUI feedback when invoice already in other claim."""

    def test_gui_reports_clear_message_when_invoice_already_in_other_claim(self):
        try:
            from PySide6.QtCore import QItemSelectionModel
            from PySide6.QtWidgets import QApplication, QMessageBox
            import sys
            app = QApplication.instance() or QApplication(sys.argv)

            with tempfile.TemporaryDirectory() as td:
                db_path = Path(td) / "test_gui_cross_claim.db"
                with InvoiceDB(db_path) as db:
                    claim_a = db.create_claim_group("Claim Group A")
                    claim_b = db.create_claim_group("Claim Group B")
                    inv_id = db.insert_invoice({
                        "invoice_number": "INV-CROSS-GUI-001",
                        "invoice_type": "电子发票",
                        "review_status": review_status.TO_REVIEW,
                    })
                    # Already in Claim A
                    self.assertTrue(db.add_invoice_to_claim(claim_a, inv_id))

                from scripts.invoice_fetch.gui.app import InvoiceReviewApp
                window = InvoiceReviewApp(db_path, splash=None)
                try:
                    window._deferred_init()
                    app.processEvents()

                    # Select Claim B in combo
                    claim_b_idx = window.combo_claims.findData(claim_b)
                    self.assertGreaterEqual(claim_b_idx, 0)
                    window.combo_claims.setCurrentIndex(claim_b_idx)

                    # Select the invoice in the table
                    window.table.selectRow(0)
                    app.processEvents()

                    # Attempt to link the invoice to Claim B
                    with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok) as mock_info:
                        result = window._link_invoices_to_claim()
                        app.processEvents()

                    self.assertEqual(result.get("linked", 0), 0)
                    self.assertEqual(result.get("other_claim", 0), 1)

                    # Verify user-facing message explicitly instructs user
                    message = mock_info.call_args.args[2]
                    self.assertIn("这张发票已经属于另一个报销组，请先从原报销组移除后再加入当前组", message)

                finally:
                    if hasattr(window, "pdf_document") and window.pdf_document is not None:
                        window.pdf_document.close()
                    if hasattr(window, "db") and window.db is not None:
                        window.db.close()
                    window.close()
                    window.deleteLater()
                    app.processEvents()
        except Exception as e:
            if isinstance(e, (ImportError, RuntimeError)):
                self.skipTest(f"Skipping GUI test in headless/unsupported environment: {e}")
            raise


if __name__ == "__main__":
    unittest.main()
