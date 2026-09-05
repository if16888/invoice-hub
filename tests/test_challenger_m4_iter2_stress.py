"""Empirical Challenger Stress Test Suite for Milestone M4 Iteration 2.

Exhaustively verifies:
1. Parameter propagation: calling `_process_email(..., source_mode="reprocess")`
   passes `source_mode="reprocess"` down to all 6 `_rename_by_invoice_code` and
   all 6 `_attach_email_extras_to_invoice` calls across all execution paths.
2. Extra attachments helper: `_attach_email_extras_to_invoice` passes `source_mode`
   down to `_rename_by_invoice_code`.
3. Collision log severity oracle: `source_mode="reprocess"` emits INFO, while
   `source_mode="normal"` emits WARNING on name collision.
4. Concurrent thread safety: `services._rename_source_mode` remains strictly
   unmodified ('normal') under high-concurrency multi-threaded workloads.
5. AST integrity: zero assignments to `_rename_source_mode` across repo.
"""

import ast
import concurrent.futures
import logging
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.invoice_fetch import services
from scripts.invoice_fetch.db import InvoiceDB


class TestM4Iter2EmpiricalStress(unittest.TestCase):
    """Empirical challenger tests for Milestone M4 Iteration 2."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="challenger_m4_i2_"))
        self.db_path = self.temp_dir / "test.db"
        self.db = InvoiceDB(self.db_path)
        self.db.__enter__()

    def tearDown(self):
        try:
            self.db.__exit__(None, None, None)
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_base_mocks(self):
        mock_msg = MagicMock()
        mock_msg.uid = 1001
        mock_msg.subject = "发票报销: 服务费"
        mock_msg.sender = "billing@example.com"
        mock_msg.date = "2026-06-15"
        mock_msg.raw_msg = b"Dummy email body"

        mock_att_handler = MagicMock()
        mock_att_handler._base = self.temp_dir / "attachments"
        mock_att_handler._base.mkdir(parents=True, exist_ok=True)

        mock_parser = MagicMock()
        mock_link_dl = MagicMock()

        return mock_msg, mock_att_handler, mock_parser, mock_link_dl

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 1: Exhaustive Dynamic Path Verification for _process_email
    # ──────────────────────────────────────────────────────────────────────────

    def test_01_path_attachment_new_invoice_threads_source_mode(self):
        """Path: Direct attachment invoice (new) -> rename & attach called with source_mode='reprocess'."""
        msg, att_handler, parser, link_dl = self._create_base_mocks()

        att_pdf = MagicMock()
        att_pdf.is_invoice = True
        att_pdf.is_extra = False
        att_pdf.file_path = str(self.temp_dir / "inv1.pdf")
        att_pdf.original_name = "inv1.pdf"
        Path(att_pdf.file_path).write_bytes(b"%PDF-1.4 invoice")

        att_extra = MagicMock()
        att_extra.is_invoice = False
        att_extra.is_extra = True
        att_extra.file_path = str(self.temp_dir / "trip1.pdf")
        att_extra.original_name = "trip1.pdf"
        Path(att_extra.file_path).write_bytes(b"%PDF-1.4 trip")

        att_handler.extract.return_value = [att_pdf, att_extra]
        link_dl.extract_and_download.return_value = []

        parsed_info = MagicMock()
        parsed_info.invoice_number = "INV-NEW-01"
        parsed_info.invoice_code = "CODE-NEW-01"
        parsed_info.invoice_date = "2026-06-15"
        parsed_info.expense_date = "2026-06-15"
        parsed_info.date_source = "invoice_date"
        parsed_info.amount = "100.00"
        parsed_info.total_amount = "100.00"
        parsed_info.seller_name = "Cloud Services Inc"
        parsed_info.buyer_name = "Client Corp"
        parsed_info.invoice_type = "增值税电子普通发票"
        parsed_info.parse_success = True
        parsed_info.parse_note = ""
        parsed_info.raw_text = "IT服务费"
        parsed_info.item_name = "服务费"
        parser.parse_pdf.return_value = parsed_info

        with patch("scripts.invoice_fetch.services._rename_by_invoice_code", return_value="2026-06/renamed.pdf") as mock_rename, \
             patch("scripts.invoice_fetch.services._attach_email_extras_to_invoice", return_value=["2026-06/extra.pdf"]) as mock_attach, \
             patch("scripts.invoice_fetch.services._match_email_extras_to_invoices", return_value=({id(parsed_info): [att_extra]}, [])):

            services._process_email(
                msg=msg,
                att_handler=att_handler,
                parser=parser,
                link_dl=link_dl,
                db=self.db,
                categories={},
                source_mode="reprocess",
            )

            self.assertTrue(mock_rename.called, "Expected _rename_by_invoice_code to be called")
            self.assertEqual(mock_rename.call_args.kwargs.get("source_mode"), "reprocess")

            self.assertTrue(mock_attach.called, "Expected _attach_email_extras_to_invoice to be called")
            self.assertEqual(mock_attach.call_args.kwargs.get("source_mode"), "reprocess")

    def test_02_path_attachment_repair_threads_source_mode(self):
        """Path: Attachment repair (existing invoice with missing file) -> rename & attach with source_mode='reprocess'."""
        msg, att_handler, parser, link_dl = self._create_base_mocks()

        # Seed existing invoice in DB whose attachment_path does not exist on disk
        existing_id = self.db.insert_invoice({
            "invoice_number": "INV-REPAIR-01",
            "invoice_code": "CODE-REPAIR-01",
            "invoice_date": "2026-06-15",
            "total_amount": "200.00",
            "seller_name": "Cloud Repair Inc",
            "attachment_path": "non_existent_file.pdf",
            "extra_paths": [],
            "parse_success": True,
        })

        att_pdf = MagicMock()
        att_pdf.is_invoice = True
        att_pdf.is_extra = False
        att_pdf.file_path = str(self.temp_dir / "repair.pdf")
        att_pdf.original_name = "repair.pdf"
        Path(att_pdf.file_path).write_bytes(b"%PDF-1.4 invoice repair")

        att_extra = MagicMock()
        att_extra.is_invoice = False
        att_extra.is_extra = True
        att_extra.file_path = str(self.temp_dir / "repair_extra.pdf")
        att_extra.original_name = "repair_extra.pdf"
        Path(att_extra.file_path).write_bytes(b"%PDF-1.4 repair extra")

        att_handler.extract.return_value = [att_pdf, att_extra]
        link_dl.extract_and_download.return_value = []

        parsed_info = MagicMock()
        parsed_info.invoice_number = "INV-REPAIR-01"
        parsed_info.invoice_code = "CODE-REPAIR-01"
        parsed_info.invoice_date = "2026-06-15"
        parsed_info.expense_date = "2026-06-15"
        parsed_info.date_source = "invoice_date"
        parsed_info.amount = "200.00"
        parsed_info.total_amount = "200.00"
        parsed_info.seller_name = "Cloud Repair Inc"
        parsed_info.buyer_name = "Client Corp"
        parsed_info.invoice_type = "增值税电子普通发票"
        parsed_info.parse_success = True
        parsed_info.parse_note = ""
        parsed_info.raw_text = "维修服务"
        parsed_info.item_name = "维修服务"
        parser.parse_pdf.return_value = parsed_info

        with patch("scripts.invoice_fetch.services._rename_by_invoice_code", return_value="2026-06/repaired.pdf") as mock_rename, \
             patch("scripts.invoice_fetch.services._attach_email_extras_to_invoice", return_value=["2026-06/extra.pdf"]) as mock_attach, \
             patch("scripts.invoice_fetch.services._match_email_extras_to_invoices", return_value=({id(parsed_info): [att_extra]}, [])):

            services._process_email(
                msg=msg,
                att_handler=att_handler,
                parser=parser,
                link_dl=link_dl,
                db=self.db,
                categories={},
                source_mode="reprocess",
            )

            self.assertTrue(mock_rename.called, "Expected _rename_by_invoice_code to be called for repair")
            self.assertEqual(mock_rename.call_args.kwargs.get("source_mode"), "reprocess")

            self.assertTrue(mock_attach.called, "Expected _attach_email_extras_to_invoice to be called for repair")
            self.assertEqual(mock_attach.call_args.kwargs.get("source_mode"), "reprocess")

    def test_03_path_attachment_duplicate_backfill_threads_source_mode(self):
        """Path: Attachment duplicate backfill -> rename & attach called with source_mode='reprocess'."""
        msg, att_handler, parser, link_dl = self._create_base_mocks()

        existing_id = self.db.insert_invoice({
            "invoice_number": "INV-DUP-01",
            "invoice_code": "CODE-DUP-01",
            "invoice_date": "2026-06-15",
            "total_amount": "300.00",
            "seller_name": "Dup Seller Inc",
            "attachment_path": "",
            "extra_paths": [],
            "parse_success": True,
        })

        att_pdf = MagicMock()
        att_pdf.is_invoice = True
        att_pdf.is_extra = False
        att_pdf.file_path = str(self.temp_dir / "dup.pdf")
        att_pdf.original_name = "dup.pdf"
        Path(att_pdf.file_path).write_bytes(b"%PDF-1.4 invoice dup")

        att_extra = MagicMock()
        att_extra.is_invoice = False
        att_extra.is_extra = True
        att_extra.file_path = str(self.temp_dir / "dup_extra.pdf")
        att_extra.original_name = "dup_extra.pdf"
        Path(att_extra.file_path).write_bytes(b"%PDF-1.4 dup extra")

        att_handler.extract.return_value = [att_pdf, att_extra]
        link_dl.extract_and_download.return_value = []

        parsed_info = MagicMock()
        parsed_info.invoice_number = "INV-DUP-01"
        parsed_info.invoice_code = "CODE-DUP-01"
        parsed_info.invoice_date = "2026-06-15"
        parsed_info.expense_date = "2026-06-15"
        parsed_info.date_source = "invoice_date"
        parsed_info.amount = "300.00"
        parsed_info.total_amount = "300.00"
        parsed_info.seller_name = "Dup Seller Inc"
        parsed_info.buyer_name = "Client Corp"
        parsed_info.invoice_type = "增值税电子普通发票"
        parsed_info.parse_success = True
        parsed_info.parse_note = ""
        parsed_info.raw_text = "服务费"
        parsed_info.item_name = "服务费"
        parser.parse_pdf.return_value = parsed_info

        first_call = True
        def mock_find(db, inv_num, total, seller, include_deleted=True):
            nonlocal first_call
            if first_call:
                first_call = False
                return None
            return {"id": existing_id, "attachment_path": "", "extra_paths": []}

        with patch("scripts.invoice_fetch.services._find_existing_invoice_for_parse", side_effect=mock_find), \
             patch("scripts.invoice_fetch.services._rename_by_invoice_code", return_value="2026-06/dup_backfill.pdf") as mock_rename, \
             patch("scripts.invoice_fetch.services._attach_email_extras_to_invoice", return_value=["2026-06/extra.pdf"]) as mock_attach, \
             patch("scripts.invoice_fetch.services._match_email_extras_to_invoices", return_value=({id(parsed_info): [att_extra]}, [])):

            services._process_email(
                msg=msg,
                att_handler=att_handler,
                parser=parser,
                link_dl=link_dl,
                db=self.db,
                categories={},
                source_mode="reprocess",
            )

            self.assertTrue(mock_rename.called, "Expected _rename_by_invoice_code to be called for duplicate backfill")
            self.assertEqual(mock_rename.call_args.kwargs.get("source_mode"), "reprocess")

            self.assertTrue(mock_attach.called, "Expected _attach_email_extras_to_invoice to be called for duplicate backfill")
            self.assertEqual(mock_attach.call_args.kwargs.get("source_mode"), "reprocess")

    def test_04_path_link_download_new_invoice_threads_source_mode(self):
        """Path: Browser link download new invoice -> rename & attach with source_mode='reprocess'."""
        msg, att_handler, parser, link_dl = self._create_base_mocks()

        att_handler.extract.return_value = []

        dl_pdf = MagicMock()
        dl_pdf.is_invoice = True
        dl_pdf.file_path = str(self.temp_dir / "dl_new.pdf")
        dl_pdf.filename = "dl_new.pdf"
        dl_pdf.url = "https://example.com/inv.pdf"
        Path(dl_pdf.file_path).write_bytes(b"%PDF-1.4 link dl")

        extra_file = MagicMock()
        extra_file.file_path = str(self.temp_dir / "dl_extra.pdf")
        extra_file.original_name = "dl_extra.pdf"
        Path(extra_file.file_path).write_bytes(b"%PDF-1.4 extra")

        link_dl.download_from_email.return_value = [dl_pdf]

        parsed_info = MagicMock()
        parsed_info.invoice_number = "INV-LINK-NEW-01"
        parsed_info.invoice_code = "CODE-LINK-NEW-01"
        parsed_info.invoice_date = "2026-06-15"
        parsed_info.expense_date = "2026-06-15"
        parsed_info.date_source = "invoice_date"
        parsed_info.amount = "400.00"
        parsed_info.total_amount = "400.00"
        parsed_info.seller_name = "Link Download Vendor"
        parsed_info.buyer_name = "Client Corp"
        parsed_info.invoice_type = "增值税电子普通发票"
        parsed_info.parse_success = True
        parsed_info.parse_note = ""
        parsed_info.raw_text = "云资源"
        parsed_info.item_name = "云资源"
        parser.parse_pdf.return_value = parsed_info

        with patch("scripts.invoice_fetch.services._rename_by_invoice_code", return_value="2026-06/dl_renamed.pdf") as mock_rename, \
             patch("scripts.invoice_fetch.services._attach_email_extras_to_invoice", return_value=["2026-06/extra.pdf"]) as mock_attach, \
             patch("scripts.invoice_fetch.services._match_email_extras_to_invoices", return_value=({id(parsed_info): [extra_file]}, [])):

            services._process_email(
                msg=msg,
                att_handler=att_handler,
                parser=parser,
                link_dl=link_dl,
                db=self.db,
                categories={},
                source_mode="reprocess",
            )

            self.assertTrue(mock_rename.called, "Expected _rename_by_invoice_code for link download new invoice")
            self.assertEqual(mock_rename.call_args.kwargs.get("source_mode"), "reprocess")

            self.assertTrue(mock_attach.called, "Expected _attach_email_extras_to_invoice for link download new invoice")
            self.assertEqual(mock_attach.call_args.kwargs.get("source_mode"), "reprocess")

    def test_05_path_link_download_repair_threads_source_mode(self):
        """Path: Browser link download repair -> rename & attach with source_mode='reprocess'."""
        msg, att_handler, parser, link_dl = self._create_base_mocks()

        existing_id = self.db.insert_invoice({
            "invoice_number": "INV-LINK-REP-01",
            "invoice_code": "CODE-LINK-REP-01",
            "invoice_date": "2026-06-15",
            "total_amount": "500.00",
            "seller_name": "Link Repair Vendor",
            "attachment_path": "missing_link_file.pdf",
            "extra_paths": [],
            "parse_success": True,
        })

        att_handler.extract.return_value = []

        dl_pdf = MagicMock()
        dl_pdf.is_invoice = True
        dl_pdf.file_path = str(self.temp_dir / "dl_rep.pdf")
        dl_pdf.filename = "dl_rep.pdf"
        dl_pdf.url = "https://example.com/rep.pdf"
        Path(dl_pdf.file_path).write_bytes(b"%PDF-1.4 link rep")

        extra_file = MagicMock()
        extra_file.file_path = str(self.temp_dir / "dl_rep_extra.pdf")
        extra_file.original_name = "dl_rep_extra.pdf"
        Path(extra_file.file_path).write_bytes(b"%PDF-1.4 extra")

        link_dl.download_from_email.return_value = [dl_pdf]

        parsed_info = MagicMock()
        parsed_info.invoice_number = "INV-LINK-REP-01"
        parsed_info.invoice_code = "CODE-LINK-REP-01"
        parsed_info.invoice_date = "2026-06-15"
        parsed_info.expense_date = "2026-06-15"
        parsed_info.date_source = "invoice_date"
        parsed_info.amount = "500.00"
        parsed_info.total_amount = "500.00"
        parsed_info.seller_name = "Link Repair Vendor"
        parsed_info.buyer_name = "Client Corp"
        parsed_info.invoice_type = "增值税电子普通发票"
        parsed_info.parse_success = True
        parsed_info.parse_note = ""
        parsed_info.raw_text = "云资源"
        parsed_info.item_name = "云资源"
        parser.parse_pdf.return_value = parsed_info

        with patch("scripts.invoice_fetch.services._rename_by_invoice_code", return_value="2026-06/dl_repaired.pdf") as mock_rename, \
             patch("scripts.invoice_fetch.services._attach_email_extras_to_invoice", return_value=["2026-06/extra.pdf"]) as mock_attach, \
             patch("scripts.invoice_fetch.services._match_email_extras_to_invoices", return_value=({id(parsed_info): [extra_file]}, [])):

            services._process_email(
                msg=msg,
                att_handler=att_handler,
                parser=parser,
                link_dl=link_dl,
                db=self.db,
                categories={},
                source_mode="reprocess",
            )

            self.assertTrue(mock_rename.called, "Expected _rename_by_invoice_code for link download repair")
            self.assertEqual(mock_rename.call_args.kwargs.get("source_mode"), "reprocess")

            self.assertTrue(mock_attach.called, "Expected _attach_email_extras_to_invoice for link download repair")
            self.assertEqual(mock_attach.call_args.kwargs.get("source_mode"), "reprocess")

    def test_06_path_link_download_duplicate_backfill_threads_source_mode(self):
        """Path: Browser link download duplicate backfill -> rename & attach with source_mode='reprocess'."""
        msg, att_handler, parser, link_dl = self._create_base_mocks()

        existing_id = self.db.insert_invoice({
            "invoice_number": "INV-LINK-DUP-01",
            "invoice_code": "CODE-LINK-DUP-01",
            "invoice_date": "2026-06-15",
            "total_amount": "600.00",
            "seller_name": "Link Dup Vendor",
            "attachment_path": "",
            "extra_paths": [],
            "parse_success": True,
        })

        att_handler.extract.return_value = []

        dl_pdf = MagicMock()
        dl_pdf.is_invoice = True
        dl_pdf.file_path = str(self.temp_dir / "dl_dup.pdf")
        dl_pdf.filename = "dl_dup.pdf"
        dl_pdf.url = "https://example.com/dup.pdf"
        Path(dl_pdf.file_path).write_bytes(b"%PDF-1.4 link dup")

        extra_file = MagicMock()
        extra_file.file_path = str(self.temp_dir / "dl_dup_extra.pdf")
        extra_file.original_name = "dl_dup_extra.pdf"
        Path(extra_file.file_path).write_bytes(b"%PDF-1.4 extra")

        link_dl.download_from_email.return_value = [dl_pdf]

        parsed_info = MagicMock()
        parsed_info.invoice_number = "INV-LINK-DUP-01"
        parsed_info.invoice_code = "CODE-LINK-DUP-01"
        parsed_info.invoice_date = "2026-06-15"
        parsed_info.expense_date = "2026-06-15"
        parsed_info.date_source = "invoice_date"
        parsed_info.amount = "600.00"
        parsed_info.total_amount = "600.00"
        parsed_info.seller_name = "Link Dup Vendor"
        parsed_info.buyer_name = "Client Corp"
        parsed_info.invoice_type = "增值税电子普通发票"
        parsed_info.parse_success = True
        parsed_info.parse_note = ""
        parsed_info.raw_text = "云资源"
        parsed_info.item_name = "云资源"
        parser.parse_pdf.return_value = parsed_info

        first_call = True
        def mock_find(db, inv_num, total, seller, include_deleted=True):
            nonlocal first_call
            if first_call:
                first_call = False
                return None
            return {"id": existing_id, "attachment_path": "", "extra_paths": []}

        with patch("scripts.invoice_fetch.services._find_existing_invoice_for_parse", side_effect=mock_find), \
             patch("scripts.invoice_fetch.services._rename_by_invoice_code", return_value="2026-06/dl_dup_backfill.pdf") as mock_rename, \
             patch("scripts.invoice_fetch.services._attach_email_extras_to_invoice", return_value=["2026-06/extra.pdf"]) as mock_attach, \
             patch("scripts.invoice_fetch.services._match_email_extras_to_invoices", return_value=({id(parsed_info): [extra_file]}, [])):

            services._process_email(
                msg=msg,
                att_handler=att_handler,
                parser=parser,
                link_dl=link_dl,
                db=self.db,
                categories={},
                source_mode="reprocess",
            )

            self.assertTrue(mock_rename.called, "Expected _rename_by_invoice_code for link download duplicate backfill")
            self.assertEqual(mock_rename.call_args.kwargs.get("source_mode"), "reprocess")

            self.assertTrue(mock_attach.called, "Expected _attach_email_extras_to_invoice for link download duplicate backfill")
            self.assertEqual(mock_attach.call_args.kwargs.get("source_mode"), "reprocess")

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 2: Extra Attachments Helper Parameter Threading
    # ──────────────────────────────────────────────────────────────────────────

    def test_07_attach_email_extras_forwards_source_mode_to_rename(self):
        """_attach_email_extras_to_invoice accepts source_mode and passes it to _rename_by_invoice_code."""
        inv_id = self.db.insert_invoice({
            "invoice_number": "INV-EXTRAS-01",
            "invoice_code": "CODE-EXTRAS-01",
            "invoice_date": "2026-06-15",
            "total_amount": "100.00",
            "seller_name": "Extras Seller",
            "attachment_path": "inv.pdf",
            "extra_paths": [],
            "parse_success": True,
        })

        extra = MagicMock()
        extra.file_path = str(self.temp_dir / "extra1.pdf")
        extra.original_name = "extra1.pdf"
        Path(extra.file_path).write_bytes(b"%PDF-1.4 extra file")

        with patch("scripts.invoice_fetch.services._rename_by_invoice_code", return_value="2026-06/extra_renamed.pdf") as mock_rename:
            services._attach_email_extras_to_invoice(
                db=self.db,
                invoice_id=inv_id,
                extra_files=[extra],
                code="CODE-EXTRAS-01",
                inv_date="2026-06-15",
                att_base=self.temp_dir / "attachments",
                category="办公",
                total_amount="100.00",
                invoice_number="INV-EXTRAS-01",
                kept_paths=set(),
                source_mode="reprocess",
            )

            self.assertTrue(mock_rename.called)
            self.assertEqual(mock_rename.call_args.kwargs.get("source_mode"), "reprocess")

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 3: Collision Log Severity Behavioral Oracle
    # ──────────────────────────────────────────────────────────────────────────

    def test_08_rename_collision_log_severity_oracle(self):
        """Collision logs INFO under source_mode='reprocess', but WARNING under source_mode='normal'."""
        att_dir = self.temp_dir / "att_test"
        att_dir.mkdir(parents=True, exist_ok=True)

        # 1. First create initial file
        src_init = self.temp_dir / "src_init.pdf"
        src_init.write_bytes(b"content_init_AAA")
        services._rename_by_invoice_code(
            file_path=str(src_init),
            invoice_code="INV123",
            invoice_date="2026-06-15",
            att_dir=att_dir,
            original_name="test_doc.pdf",
        )

        # 2. Conflicting file with different content under source_mode='reprocess' -> INFO log, NOT WARNING
        src_reprocess = self.temp_dir / "src_reprocess.pdf"
        src_reprocess.write_bytes(b"content_reprocess_BBB")

        with self.assertLogs("invoice_fetch", level=logging.INFO) as log_ctx:
            renamed = services._rename_by_invoice_code(
                file_path=str(src_reprocess),
                invoice_code="INV123",
                invoice_date="2026-06-15",
                att_dir=att_dir,
                source_mode="reprocess",
                original_name="test_doc.pdf",
            )
            info_logs = [record for record in log_ctx.records if record.levelno == logging.INFO and "检测到同名文件" in record.getMessage()]
            warning_logs = [record for record in log_ctx.records if record.levelno >= logging.WARNING and "检测到同名文件" in record.getMessage()]
            self.assertTrue(len(info_logs) >= 1, "Expected INFO log on name collision during reprocess")
            self.assertEqual(len(warning_logs), 0, "Unexpected WARNING log on name collision during reprocess")

        # 3. Conflicting file under source_mode='normal' -> WARNING log
        src_normal = self.temp_dir / "src_normal.pdf"
        src_normal.write_bytes(b"content_normal_CCC")

        with self.assertLogs("invoice_fetch", level=logging.INFO) as log_ctx:
            renamed_2 = services._rename_by_invoice_code(
                file_path=str(src_normal),
                invoice_code="INV123",
                invoice_date="2026-06-15",
                att_dir=att_dir,
                source_mode="normal",
                original_name="test_doc.pdf",
            )
            warning_logs = [record for record in log_ctx.records if record.levelno == logging.WARNING and "检测到同名文件" in record.getMessage()]
            self.assertTrue(len(warning_logs) >= 1, "Expected WARNING log on name collision during normal mode")

        # 4. Conflicting file with source_mode=None -> falls back to module global (normal) -> WARNING log
        src_default = self.temp_dir / "src_default.pdf"
        src_default.write_bytes(b"content_default_DDD")

        with self.assertLogs("invoice_fetch", level=logging.INFO) as log_ctx:
            renamed_3 = services._rename_by_invoice_code(
                file_path=str(src_default),
                invoice_code="INV123",
                invoice_date="2026-06-15",
                att_dir=att_dir,
                source_mode=None,
                original_name="test_doc.pdf",
            )
            warning_logs = [record for record in log_ctx.records if record.levelno == logging.WARNING and "检测到同名文件" in record.getMessage()]
            self.assertTrue(len(warning_logs) >= 1, "Expected WARNING log on fallback to default global mode")

        # 5. Global mode remains untouched
        self.assertEqual(services._rename_source_mode, "normal")

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 4: High-Concurrency Thread Safety Stress Test
    # ──────────────────────────────────────────────────────────────────────────

    def test_09_high_concurrency_thread_safety_immutability(self):
        """Stress-test concurrent executions with mixed source_mode values.

        Asserts that services._rename_source_mode is never mutated across 24 concurrent worker threads.
        """
        initial_mode = services._rename_source_mode
        self.assertEqual(initial_mode, "normal")

        errors = []
        mode_violations = []

        def worker_task(worker_id: int):
            try:
                worker_dir = self.temp_dir / f"worker_{worker_id}"
                worker_dir.mkdir(parents=True, exist_ok=True)
                att_dir = worker_dir / "att"
                att_dir.mkdir(parents=True, exist_ok=True)

                orig_name = f"doc_{worker_id}.pdf"
                init_src = worker_dir / f"init_{worker_id}.pdf"
                init_src.write_bytes(b"existing_data_000")

                services._rename_by_invoice_code(
                    file_path=str(init_src),
                    invoice_code=f"CODE_{worker_id}",
                    invoice_date="2026-06-15",
                    att_dir=att_dir,
                    original_name=orig_name,
                )

                src = worker_dir / f"new_{worker_id}.pdf"
                src.write_bytes(b"new_data_111")

                mode = "reprocess" if worker_id % 2 == 0 else "normal"

                # Check services._rename_source_mode immediately before
                if services._rename_source_mode != "normal":
                    mode_violations.append((worker_id, "before", services._rename_source_mode))

                res = services._rename_by_invoice_code(
                    file_path=str(src),
                    invoice_code=f"CODE_{worker_id}",
                    invoice_date="2026-06-15",
                    att_dir=att_dir,
                    source_mode=mode,
                    original_name=orig_name,
                )

                # Check services._rename_source_mode immediately after
                if services._rename_source_mode != "normal":
                    mode_violations.append((worker_id, "after", services._rename_source_mode))

            except Exception as ex:
                errors.append((worker_id, ex))

        # Launch 24 threads simultaneously
        threads = []
        for i in range(24):
            t = threading.Thread(target=worker_task, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread worker errors: {errors}")
        self.assertEqual(mode_violations, [], f"Global _rename_source_mode was mutated: {mode_violations}")
        self.assertEqual(services._rename_source_mode, "normal")

    # ──────────────────────────────────────────────────────────────────────────
    # Dimension 5: Static AST Immutability Enforcement
    # ──────────────────────────────────────────────────────────────────────────

    def test_10_ast_zero_assignments_to_rename_source_mode(self):
        """Verify across scripts/ and tests/ that _rename_source_mode is NEVER assigned outside services.py:195."""
        repo_root = Path(__file__).resolve().parent.parent
        assignments = []

        for folder in ["scripts", "tests"]:
            base = repo_root / folder
            for py_path in base.rglob("*.py"):
                tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                        targets = []
                        if isinstance(node, ast.Assign):
                            targets = node.targets
                        elif isinstance(node, ast.AnnAssign):
                            targets = [node.target]
                        elif isinstance(node, ast.AugAssign):
                            targets = [node.target]

                        for t in targets:
                            if isinstance(t, ast.Attribute) and t.attr == "_rename_source_mode":
                                assignments.append((str(py_path.relative_to(repo_root)), node.lineno, "attr"))
                            elif isinstance(t, ast.Name) and t.id == "_rename_source_mode":
                                # Allow only the single definition in services.py line 195
                                if not (py_path.name == "services.py" and node.lineno == 195):
                                    assignments.append((str(py_path.relative_to(repo_root)), node.lineno, "name"))

        self.assertEqual(
            assignments,
            [],
            f"Found forbidden assignments mutating _rename_source_mode: {assignments}",
        )


if __name__ == "__main__":
    unittest.main()
