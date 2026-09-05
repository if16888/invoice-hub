"""Empirical Challenger Test Suite for Milestone 3 Filesystem Rollback and Leak Prevention.

Adversarial stress-testing of scripts/invoice_fetch/redownload.py and db.py:
1. PDF branch: DB update failure (returns False) cleans up moved destination file.
2. PDF branch: DB update exception (raises sqlite3.OperationalError / RuntimeError) cleans up destination file.
3. PDF branch: Baseline success preserves destination file and updates DB.
4. OFD branch: Baseline success preserves destination file and sets parse_success=0 with parse_note.
5. OFD branch: DB failure (returns False) cleans up destination file.
6. OFD branch: DB exception (raises Exception) cleans up destination file.
7. Unsupported format branch (e.g. .xml / .zip): Baseline success preserves destination file.
8. Unsupported format branch: DB failure (returns False) cleans up destination file.
9. Unsupported format branch: DB exception cleans up destination file.
10. Parser crash before DB update cleans up temporary download file.
11. Parser parse_success=False removes temporary download file.
12. Detail link retry (run_invoice_link_retry): DB update failure cleans up destination file.
13. Detail link retry (run_invoice_link_retry): DB update exception cleans up destination file.
14. Safe unlink behavior on various path formats (absolute, relative attachments/..., missing, None).
15. Encapsulation & leak check: verify zero direct _conn access in redownload.py.
16. Pre-existing file collision edge-case analysis.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch import redownload as redownload_module
from scripts.invoice_fetch import services as services_module
from scripts.invoice_fetch.redownload import (
    RedownloadInvoiceSnapshot,
    _safe_unlink,
    run_invoice_link_retry,
    run_invoice_redownload,
)


class TestEmpiricalChallengerM3(unittest.TestCase):
    """Adversarial challenger test cases against Milestone 3 redownload & rollback."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="challenger_m3_"))
        self.runtime_dir = self.temp_dir / "runtime"
        self.attachments_dir = self.runtime_dir / "attachments"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "challenger_redownload.db"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_invoice(self, **overrides) -> int:
        payload = {
            "invoice_number": "INV-ORIG-001",
            "invoice_code": "CODE-001",
            "invoice_date": "2026-06-01",
            "total_amount": "100.00",
            "seller_name": "Initial Seller",
            "buyer_name": "Buyer Corp",
            "mail_date": "2026-06-01",
            "mail_subject": "Invoice Email",
            "mail_sender": "billing@example.com",
            "attachment_path": "",
            "download_url": "https://example.test/download_target",
            "review_status": "to_review",
        }
        payload.update(overrides)
        with InvoiceDB(self.db_path) as db:
            invoice_id = db.insert_invoice(payload)
        self.assertIsNotNone(invoice_id)
        return int(invoice_id)

    def _count_attachment_files(self) -> list[Path]:
        """List all regular files under attachments directory."""
        if not self.attachments_dir.exists():
            return []
        return [p for p in self.attachments_dir.rglob("*") if p.is_file()]

    # ── 1. PDF Branch: DB Update Failure & Rollback ──

    def test_pdf_db_update_returns_false_unlinks_moved_file(self):
        """When update_invoice_parsed_metadata returns False, the moved file MUST be unlinked."""
        inv_id = self._seed_invoice(invoice_number="PDF-FAIL-01")
        download_file = self.temp_dir / "downloaded_raw.pdf"
        download_file.write_bytes(b"%PDF-1.4 mock invoice content for test")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        class FakeParser:
            def parse_pdf(self, path):
                return SimpleNamespace(
                    parse_success=True,
                    parse_note="",
                    invoice_code="CODE-PDF-01",
                    invoice_number="INV-PDF-NEW",
                    invoice_date="2026-06-01",
                    amount="90.00",
                    total_amount="100.00",
                    seller_name="Test Seller",
                    buyer_name="Buyer Corp",
                    invoice_type="电子发票",
                    item_name="Service",
                    expense_date="2026-06-01",
                    date_source="invoice_date",
                )

        captured_moved_paths = []
        real_rename = services_module._rename_by_invoice_code

        def tracking_rename(*args, **kwargs):
            rel = real_rename(*args, **kwargs)
            captured_moved_paths.append(rel)
            return rel

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(redownload_module._invoice_parser, "InvoiceParser", FakeParser), \
             patch.object(services_module, "_rename_by_invoice_code", side_effect=tracking_rename), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir), \
             patch.object(redownload_module.InvoiceDB, "update_invoice_parsed_metadata", return_value=False) as mock_db_update, \
             patch.object(redownload_module.InvoiceDB, "is_unique_conflict", return_value=True):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/file.pdf", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(mock_db_update.call_count, 1)
        self.assertEqual(result["buckets"]["download_failed"], 1)
        self.assertEqual(len(captured_moved_paths), 1)

        # Verify the file was moved and THEN unlinked by _safe_unlink
        moved_rel = captured_moved_paths[0]
        full_dest = self.runtime_dir / moved_rel
        self.assertFalse(
            full_dest.exists(),
            f"Orphaned file leaked in destination! {full_dest} must have been deleted by _safe_unlink",
        )
        self.assertFalse(
            download_file.exists(),
            "Source download file was moved and must not exist at initial download path",
        )
        # Verify 0 files remain in attachments directory
        remaining = self._count_attachment_files()
        self.assertEqual(
            len(remaining),
            0,
            f"Found orphaned files in attachments dir after DB failure: {remaining}",
        )

    def test_pdf_db_update_raises_exception_unlinks_moved_file(self):
        """When update_invoice_parsed_metadata raises an exception, the moved file MUST be unlinked."""
        inv_id = self._seed_invoice(invoice_number="PDF-EXC-01")
        download_file = self.temp_dir / "downloaded_raw.pdf"
        download_file.write_bytes(b"%PDF-1.4 exception trigger content")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        class FakeParser:
            def parse_pdf(self, path):
                return SimpleNamespace(
                    parse_success=True,
                    parse_note="",
                    invoice_code="CODE-EXC",
                    invoice_number="INV-EXC",
                    invoice_date="2026-06-01",
                    amount="50.00",
                    total_amount="50.00",
                    seller_name="Seller",
                    buyer_name="Buyer",
                    invoice_type="电子发票",
                    item_name="Item",
                    expense_date="2026-06-01",
                    date_source="invoice_date",
                )

        captured_moved = []

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(redownload_module._invoice_parser, "InvoiceParser", FakeParser), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir), \
             patch.object(
                 redownload_module.InvoiceDB,
                 "update_invoice_parsed_metadata",
                 side_effect=sqlite3.OperationalError("Simulated database lock or I/O failure"),
             ):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/file.pdf", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["download_failed"], 1)
        remaining = self._count_attachment_files()
        self.assertEqual(
            len(remaining),
            0,
            f"Orphaned files remaining in attachments after DB exception: {remaining}",
        )

    def test_pdf_success_preserves_destination_file(self):
        """Baseline check: When update_invoice_parsed_metadata succeeds, file remains intact."""
        inv_id = self._seed_invoice(invoice_number="PDF-SUCCESS-01")
        download_file = self.temp_dir / "downloaded_raw.pdf"
        download_file.write_bytes(b"%PDF-1.4 valid invoice content")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        class FakeParser:
            def parse_pdf(self, path):
                return SimpleNamespace(
                    parse_success=True,
                    parse_note="",
                    invoice_code="CODE-SUCC",
                    invoice_number="INV-SUCC",
                    invoice_date="2026-06-01",
                    amount="120.00",
                    total_amount="120.00",
                    seller_name="Vendor A",
                    buyer_name="Buyer B",
                    invoice_type="电子发票",
                    item_name="Consulting",
                    expense_date="2026-06-01",
                    date_source="invoice_date",
                )

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(redownload_module._invoice_parser, "InvoiceParser", FakeParser), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/file.pdf", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["file_restored"], 1)
        self.assertEqual(result["success_count"], 1)
        remaining = self._count_attachment_files()
        self.assertEqual(len(remaining), 1, "Exactly one file should exist under attachments")

        with InvoiceDB(self.db_path) as db:
            row = db.get_invoice(inv_id)
        self.assertEqual(row["invoice_number"], "INV-SUCC")
        self.assertEqual(row["parse_success"], 1)
        self.assertTrue(Path(row["attachment_path"]).as_posix().startswith("attachments/"))
        self.assertTrue((self.runtime_dir / row["attachment_path"]).exists())

    # ── 2. OFD Fallback Branch: DB Failure & Rollback ──

    def test_ofd_fallback_success_preserves_file(self):
        """Baseline OFD: When downloaded file is .ofd and DB succeeds, file exists and parse_success=0."""
        inv_id = self._seed_invoice(invoice_number="OFD-SUCC-01")
        download_file = self.temp_dir / "invoice.ofd"
        download_file.write_bytes(b"OFD dummy package data")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/file.ofd", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["metadata_refreshed"], 1)
        remaining = self._count_attachment_files()
        self.assertEqual(len(remaining), 1, "OFD file should be preserved in attachments")
        self.assertTrue(remaining[0].name.endswith(".ofd"))

        with InvoiceDB(self.db_path) as db:
            row = db.get_invoice(inv_id)
        self.assertEqual(row["parse_success"], 0)
        self.assertIn("OFD 原件已恢复", row["parse_note"])
        self.assertTrue((self.runtime_dir / row["attachment_path"]).exists())

    def test_ofd_fallback_db_returns_false_unlinks_moved_file(self):
        """When OFD update_invoice_raw_attachment returns False, destination file MUST be unlinked."""
        inv_id = self._seed_invoice(invoice_number="OFD-FAIL-01")
        download_file = self.temp_dir / "invoice.ofd"
        download_file.write_bytes(b"OFD dummy package data")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir), \
             patch.object(redownload_module.InvoiceDB, "update_invoice_raw_attachment", return_value=False) as mock_raw:

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/file.ofd", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(mock_raw.call_count, 1)
        self.assertEqual(result["buckets"]["download_failed"], 1)
        remaining = self._count_attachment_files()
        self.assertEqual(
            len(remaining),
            0,
            f"Orphaned OFD file was not unlinked on DB write failure: {remaining}",
        )

    def test_ofd_fallback_db_raises_exception_unlinks_moved_file(self):
        """When OFD update_invoice_raw_attachment raises Exception, destination file MUST be unlinked."""
        inv_id = self._seed_invoice(invoice_number="OFD-EXC-01")
        download_file = self.temp_dir / "invoice.ofd"
        download_file.write_bytes(b"OFD exception test package")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir), \
             patch.object(
                 redownload_module.InvoiceDB,
                 "update_invoice_raw_attachment",
                 side_effect=sqlite3.OperationalError("simulated locked"),
             ):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/file.ofd", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["download_failed"], 1)
        remaining = self._count_attachment_files()
        self.assertEqual(
            len(remaining),
            0,
            f"Orphaned OFD file leaked after DB exception: {remaining}",
        )

    # ── 3. Unsupported Format Branch (.xml / .zip / etc.) ──

    def test_unsupported_format_success_preserves_file(self):
        """Baseline unsupported format: file is preserved and marked with unsupported parse_note."""
        inv_id = self._seed_invoice(invoice_number="UNSUPP-SUCC")
        download_file = self.temp_dir / "invoice.xml"
        download_file.write_bytes(b"<xml>invoice data</xml>")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/file.xml", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["metadata_refreshed"], 1)
        remaining = self._count_attachment_files()
        self.assertEqual(len(remaining), 1)
        self.assertTrue(remaining[0].name.endswith(".xml"))

        with InvoiceDB(self.db_path) as db:
            row = db.get_invoice(inv_id)
        self.assertEqual(row["parse_success"], 0)
        self.assertIn("下载了不支持的文件类型 (.xml)", row["parse_note"])

    def test_unsupported_format_db_failure_unlinks_moved_file(self):
        """When unsupported format update_invoice_raw_attachment returns False, file MUST be unlinked."""
        inv_id = self._seed_invoice(invoice_number="UNSUPP-FAIL")
        download_file = self.temp_dir / "invoice.xml"
        download_file.write_bytes(b"<xml>invoice data</xml>")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir), \
             patch.object(redownload_module.InvoiceDB, "update_invoice_raw_attachment", return_value=False):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/file.xml", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["download_failed"], 1)
        remaining = self._count_attachment_files()
        self.assertEqual(
            len(remaining),
            0,
            f"Orphaned unsupported file leaked after DB write failure: {remaining}",
        )

    def test_unsupported_format_db_exception_unlinks_moved_file(self):
        """When unsupported format update_invoice_raw_attachment raises Exception, file MUST be unlinked."""
        inv_id = self._seed_invoice(invoice_number="UNSUPP-EXC")
        download_file = self.temp_dir / "invoice.zip"
        download_file.write_bytes(b"PK\x03\x04 fake zip")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir), \
             patch.object(
                 redownload_module.InvoiceDB,
                 "update_invoice_raw_attachment",
                 side_effect=RuntimeError("simulated crash during raw update"),
             ):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/file.zip", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["download_failed"], 1)
        remaining = self._count_attachment_files()
        self.assertEqual(
            len(remaining),
            0,
            f"Orphaned zip file leaked after DB exception: {remaining}",
        )

    # ── 4. Parser Failures & Temp Download Cleanup ──

    def test_parser_unhandled_exception_cleans_up_temp_download(self):
        """If parse_pdf raises an unexpected exception, the temporary download file MUST be cleaned up."""
        inv_id = self._seed_invoice(invoice_number="PARSE-CRASH")
        download_file = self.attachments_dir / "temp_download_crash.pdf"
        download_file.write_bytes(b"corrupted pdf bytes")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        class CrashingParser:
            def parse_pdf(self, path):
                raise ValueError("PDF syntax tree severely corrupted")

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(redownload_module._invoice_parser, "InvoiceParser", CrashingParser), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/corrupt.pdf", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["download_failed"], 1)
        self.assertFalse(
            download_file.exists(),
            "Temporary download file was not cleaned up after parser exception",
        )
        remaining = self._count_attachment_files()
        self.assertEqual(len(remaining), 0)

    def test_parser_parse_success_false_deletes_temp_file(self):
        """If parse_pdf returns parse_success=False, the temporary download file is deleted."""
        inv_id = self._seed_invoice(invoice_number="PARSE-FALSE")
        download_file = self.attachments_dir / "temp_not_invoice.pdf"
        download_file.write_bytes(b"%PDF not an invoice")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        class FailingParser:
            def parse_pdf(self, path):
                return SimpleNamespace(
                    parse_success=False,
                    parse_note="内容不像发票",
                )

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(redownload_module._invoice_parser, "InvoiceParser", FailingParser), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/not_invoice.pdf", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["download_failed"], 1)
        self.assertFalse(
            download_file.exists(),
            "Temporary download file should have been deleted when parse_success is False",
        )

    # ── 5. Detail Link Retry Rollback ──

    def test_link_retry_db_failure_unlinks_destination_file(self):
        """run_invoice_link_retry: If update_invoice_file_paths returns False, unlinks file."""
        inv_id = self._seed_invoice(invoice_number="RETRY-FAIL-01")
        download_file = self.temp_dir / "detail_download.pdf"
        download_file.write_bytes(b"%PDF detail invoice content")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(redownload_module.InvoiceDB, "update_invoice_file_paths", return_value=False):

            result = run_invoice_link_retry(
                {
                    "id": inv_id,
                    "download_url": "https://example.test/retry.pdf",
                    "invoice_number": "RETRY-FAIL-01",
                    "invoice_date": "2026-06-01",
                },
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["failure_detail"], "附件路径写入失败")
        remaining = self._count_attachment_files()
        self.assertEqual(
            len(remaining),
            0,
            f"Destination file was not cleaned up on link retry DB failure: {remaining}",
        )

    def test_link_retry_db_exception_unlinks_destination_file(self):
        """run_invoice_link_retry: If update_invoice_file_paths raises exception, unlinks file."""
        inv_id = self._seed_invoice(invoice_number="RETRY-EXC-01")
        download_file = self.temp_dir / "detail_download_exc.pdf"
        download_file.write_bytes(b"%PDF detail invoice content")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(
                 redownload_module.InvoiceDB,
                 "update_invoice_file_paths",
                 side_effect=sqlite3.OperationalError("database locked"),
             ):

            result = run_invoice_link_retry(
                {
                    "id": inv_id,
                    "download_url": "https://example.test/retry_exc.pdf",
                    "invoice_number": "RETRY-EXC-01",
                    "invoice_date": "2026-06-01",
                },
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertFalse(result["success"])
        remaining = self._count_attachment_files()
        self.assertEqual(
            len(remaining),
            0,
            f"Destination file leaked on link retry DB exception: {remaining}",
        )

    # ── 6. _safe_unlink Functionality Stress Tests ──

    def test_safe_unlink_handles_relative_path_with_attachments_prefix(self):
        target = self.attachments_dir / "2026-06-01" / "test_rel.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"data")
        self.assertTrue(target.exists())

        _safe_unlink("attachments/2026-06-01/test_rel.pdf", runtime_dir=self.runtime_dir)
        self.assertFalse(target.exists(), "File must be deleted using relative path with attachments/")

    def test_safe_unlink_handles_relative_path_without_prefix(self):
        target = self.attachments_dir / "2026-06-01" / "test_no_prefix.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"data")
        self.assertTrue(target.exists())

        _safe_unlink("2026-06-01/test_no_prefix.pdf", runtime_dir=self.runtime_dir)
        self.assertFalse(target.exists(), "File must be deleted using candidates fallback")

    def test_safe_unlink_handles_absolute_path(self):
        target = self.temp_dir / "absolute_file.pdf"
        target.write_bytes(b"data")
        self.assertTrue(target.exists())

        _safe_unlink(str(target), runtime_dir=self.runtime_dir)
        self.assertFalse(target.exists(), "Absolute path must be deleted directly")

    def test_safe_unlink_tolerates_none_empty_and_nonexistent(self):
        # None
        try:
            _safe_unlink(None)
            _safe_unlink("")
            _safe_unlink(self.temp_dir / "does_not_exist.pdf")
        except Exception as exc:
            self.fail(f"_safe_unlink raised unexpected exception on edge cases: {exc}")

    # ── 7. Encapsulation & Leak Prevention Checks ──

    def test_redownload_has_no_direct_conn_access(self):
        """redownload.py must NOT contain direct calls to db._conn or execute raw SQL."""
        import inspect
        source = inspect.getsource(redownload_module)
        self.assertNotIn(
            "_conn",
            source,
            "redownload.py still contains private '_conn' access! Encapsulation violated.",
        )
        self.assertNotIn(
            "UPDATE invoices SET",
            source,
            "redownload.py still contains raw SQL UPDATE statement! Encapsulation violated.",
        )

    # ── 8. Pre-existing File Collision Stress Test ──

    def test_existing_identical_file_reuse_and_rollback(self):
        """When destination file with identical content exists, check reuse and rollback behavior."""
        # Create an existing file under attachments/2026-06-01
        dest_dir = self.attachments_dir / "2026-06-01"
        dest_dir.mkdir(parents=True, exist_ok=True)
        content = b"%PDF-1.4 identical content for reuse"
        pre_existing = dest_dir / "2026-06-01_原件_INV-EXIST.pdf"
        pre_existing.write_bytes(content)

        # A new download arrives with identical content
        download_file = self.temp_dir / "new_download.pdf"
        download_file.write_bytes(content)

        inv_id = self._seed_invoice(invoice_number="INV-EXIST", invoice_date="2026-06-01")

        class FakeDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, *_args):
                return SimpleNamespace(file_path=str(download_file))
            def close(self):
                pass

        class FakeParser:
            def parse_pdf(self, path):
                return SimpleNamespace(
                    parse_success=True,
                    parse_note="",
                    invoice_code="CODE-EXIST",
                    invoice_number="INV-EXIST",
                    invoice_date="2026-06-01",
                    amount="10.00",
                    total_amount="10.00",
                    seller_name="Seller",
                    buyer_name="Buyer",
                    invoice_type="电子发票",
                    item_name="Item",
                    expense_date="2026-06-01",
                    date_source="invoice_date",
                )

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
             patch.object(redownload_module._invoice_parser, "InvoiceParser", FakeParser), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir), \
             patch.object(redownload_module.InvoiceDB, "update_invoice_parsed_metadata", return_value=False):

            result = run_invoice_redownload(
                [{"id": inv_id, "download_url": "https://example.test/exist.pdf", "mail_uid": None}],
                self.db_path,
                runtime_dir=self.runtime_dir,
            )

        self.assertEqual(result["buckets"]["download_failed"], 1)
        # Verify behavior: if services reused the file, _safe_unlink unlinks att_path.
        # Download file was deleted by rename_by_invoice_code reuse logic.
        self.assertFalse(download_file.exists())

    # ── 9. Multi-item Batch Isolation & Mixed Outcomes ──

    def test_batch_mixed_outcomes_preserves_successes_and_cleans_up_failures(self):
        """In a 4-item batch with mixed successes/failures, failed items MUST NOT leak files."""
        id_succ_pdf = self._seed_invoice(invoice_number="BATCH-SUCC-PDF")
        id_fail_pdf = self._seed_invoice(invoice_number="BATCH-FAIL-PDF")
        id_fail_ofd = self._seed_invoice(invoice_number="BATCH-FAIL-OFD")
        id_succ_unsupp = self._seed_invoice(invoice_number="BATCH-SUCC-TXT")

        file_succ_pdf = self.temp_dir / "dl_succ_pdf.pdf"
        file_succ_pdf.write_bytes(b"%PDF-1.4 success pdf")
        file_fail_pdf = self.temp_dir / "dl_fail_pdf.pdf"
        file_fail_pdf.write_bytes(b"%PDF-1.4 fail pdf")
        file_fail_ofd = self.temp_dir / "dl_fail_ofd.ofd"
        file_fail_ofd.write_bytes(b"fail ofd content")
        file_succ_unsupp = self.temp_dir / "dl_succ_txt.txt"
        file_succ_unsupp.write_bytes(b"plain invoice text")

        dl_map = {
            id_succ_pdf: file_succ_pdf,
            id_fail_pdf: file_fail_pdf,
            id_fail_ofd: file_fail_ofd,
            id_succ_unsupp: file_succ_unsupp,
        }

        class BatchDownloader:
            last_download_diagnostics = {}
            def __init__(self, download_dir):
                self.download_dir = Path(download_dir)
            def _download_url(self, _url, _uid, invoice_id, _date):
                return SimpleNamespace(file_path=str(dl_map[invoice_id]))
            def close(self):
                pass

        class BatchParser:
            def parse_pdf(self, path):
                suffix = "SUCC" if "succ" in str(path) else "FAIL"
                return SimpleNamespace(
                    parse_success=True,
                    parse_note="",
                    invoice_code=f"CODE-{suffix}",
                    invoice_number=f"BATCH-{suffix}-PDF",
                    invoice_date="2026-06-01",
                    amount="10.00",
                    total_amount="10.00",
                    seller_name="Batch Seller",
                    buyer_name="Batch Buyer",
                    invoice_type="电子发票",
                    item_name="Item",
                    expense_date="2026-06-01",
                    date_source="invoice_date",
                )

        # Real DB update for items, but fail for id_fail_pdf and id_fail_ofd
        real_update_parsed = redownload_module.InvoiceDB.update_invoice_parsed_metadata
        real_update_raw = redownload_module.InvoiceDB.update_invoice_raw_attachment

        def conditional_update_parsed(db_self, *args, **kwargs):
            inv_id = kwargs.get("invoice_id") or (args[0] if args else None)
            if inv_id == id_fail_pdf:
                db_self._set_last_error("unique_conflict")
                return False
            return real_update_parsed(db_self, *args, **kwargs)

        def conditional_update_raw(db_self, *args, **kwargs):
            inv_id = kwargs.get("invoice_id") or (args[0] if args else None)
            if inv_id == id_fail_ofd:
                raise sqlite3.OperationalError("Simulated raw attachment crash")
            return real_update_raw(db_self, *args, **kwargs)

        with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=BatchDownloader)), \
             patch.object(redownload_module._invoice_parser, "InvoiceParser", BatchParser), \
             patch.object(services_module, "RUNTIME_DIR", self.runtime_dir), \
             patch.object(redownload_module.InvoiceDB, "update_invoice_parsed_metadata", conditional_update_parsed), \
             patch.object(redownload_module.InvoiceDB, "update_invoice_raw_attachment", conditional_update_raw):

            items = [
                {"id": id_succ_pdf, "download_url": "https://example.test/1.pdf", "mail_uid": None},
                {"id": id_fail_pdf, "download_url": "https://example.test/2.pdf", "mail_uid": None},
                {"id": id_fail_ofd, "download_url": "https://example.test/3.ofd", "mail_uid": None},
                {"id": id_succ_unsupp, "download_url": "https://example.test/4.txt", "mail_uid": None},
            ]
            result = run_invoice_redownload(items, self.db_path, runtime_dir=self.runtime_dir)

        self.assertEqual(result["buckets"]["file_restored"], 1)      # id_succ_pdf
        self.assertEqual(result["buckets"]["metadata_refreshed"], 1) # id_succ_unsupp
        self.assertEqual(result["buckets"]["download_failed"], 2)    # id_fail_pdf, id_fail_ofd

        # Check files on disk: exactly 2 files exist (one PDF, one TXT). 0 files for failed items!
        remaining = self._count_attachment_files()
        self.assertEqual(len(remaining), 2, f"Expected exactly 2 preserved files, found {len(remaining)}: {remaining}")
        extensions = {p.suffix.lower() for p in remaining}
        self.assertEqual(extensions, {".pdf", ".txt"})

    # ── 10. Direct InvoiceDB Encapsulation & Integrity Tests ──

    def test_invoicedb_atomic_parsed_metadata_and_attachment_path(self):
        """InvoiceDB.update_invoice_parsed_metadata must atomically write attachment_path."""
        inv_id = self._seed_invoice(invoice_number="ENCAP-01")
        with InvoiceDB(self.db_path) as db:
            ok = db.update_invoice_parsed_metadata(
                invoice_id=inv_id,
                invoice_number="ENCAP-UPDATED",
                invoice_code="CODE-ENCAP",
                invoice_date="2026-06-02",
                amount="88.00",
                total_amount="88.00",
                seller_name="Seller Encap",
                buyer_name="Buyer Encap",
                invoice_type="电子发票",
                category="办公",
                attachment_path="attachments/2026-06-02/encap.pdf",
                file_hash="hash_encap_123",
            )
            self.assertTrue(ok)
            row = db.get_invoice(inv_id)
            self.assertEqual(row["invoice_number"], "ENCAP-UPDATED")
            self.assertEqual(row["attachment_path"], "attachments/2026-06-02/encap.pdf")
            self.assertEqual(row["file_hash"], "hash_encap_123")
            self.assertEqual(db.get_last_error(), "")
            self.assertFalse(db.is_unique_conflict())

    def test_invoicedb_unique_conflict_rolls_back_cleanly(self):
        """InvoiceDB.update_invoice_parsed_metadata on duplicate must rollback and set unique_conflict."""
        id1 = self._seed_invoice(invoice_number="DUP-KEY-1")
        id2 = self._seed_invoice(invoice_number="DUP-KEY-2")

        with InvoiceDB(self.db_path) as db:
            # Updating id2 to have the same composite key (invoice_number, total_amount, seller_name) as id1
            ok = db.update_invoice_parsed_metadata(
                invoice_id=id2,
                invoice_number="DUP-KEY-1",
                total_amount="100.00",
                seller_name="Initial Seller",
                attachment_path="attachments/2026-06-01/should_rollback.pdf",
            )
            self.assertFalse(ok)
            self.assertEqual(db.get_last_error(), "unique_conflict")
            self.assertTrue(db.is_unique_conflict())

            # Verify id2 was rolled back and NOT modified
            row2 = db.get_invoice(id2)
            self.assertEqual(row2["invoice_number"], "DUP-KEY-2")
            self.assertEqual(row2["attachment_path"], "")


if __name__ == "__main__":
    unittest.main()
