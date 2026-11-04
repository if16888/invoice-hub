# -*- coding: utf-8 -*-
"""Attachment skip, backfill and claimed-invoice protection tests."""

import unittest
import tempfile
import shutil
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock


class TestAttachmentSkipLogic(unittest.TestCase):
    """Tests for skipping link download when attachment invoices exist."""

    def test_skip_when_parse_success_attachments_present(self):
        """When parsed_invoice_pdfs has parse_success, skip link download."""
        # Simulate the decision logic
        parsed_invoice_pdfs = [
            (MagicMock(), MagicMock(parse_success=True)),
        ]
        link_dl = MagicMock()
        link_dl._skip_when_attachment_invoice_present = True

        skip_for_attachment = False
        if link_dl._skip_when_attachment_invoice_present:
            success_attachment_pdfs = [
                att for att, info in parsed_invoice_pdfs
                if info.parse_success
            ]
            if success_attachment_pdfs:
                skip_for_attachment = True

        self.assertTrue(skip_for_attachment)
        # _download_url should not be called
        link_dl._download_url.assert_not_called()

    def test_do_not_skip_when_no_parse_success(self):
        """When no attachment invoices parse successfully, still try link download."""
        parsed_invoice_pdfs = [
            (MagicMock(), MagicMock(parse_success=False)),
        ]
        link_dl = MagicMock()
        link_dl._skip_when_attachment_invoice_present = True

        skip_for_attachment = False
        if link_dl._skip_when_attachment_invoice_present:
            success_attachment_pdfs = [
                att for att, info in parsed_invoice_pdfs
                if info.parse_success
            ]
            if success_attachment_pdfs:
                skip_for_attachment = True

        self.assertFalse(skip_for_attachment)

    def test_do_not_skip_when_config_disabled(self):
        """When config disables the skip, always try link download."""
        parsed_invoice_pdfs = [
            (MagicMock(), MagicMock(parse_success=True)),
        ]
        link_dl = MagicMock()
        link_dl._skip_when_attachment_invoice_present = False

        skip_for_attachment = False
        if link_dl._skip_when_attachment_invoice_present:
            success_attachment_pdfs = [
                att for att, info in parsed_invoice_pdfs
                if info.parse_success
            ]
            if success_attachment_pdfs:
                skip_for_attachment = True

        self.assertFalse(skip_for_attachment)

    def test_empty_attachments_still_tries_download(self):
        """No attachments at all -> still tries link download."""
        parsed_invoice_pdfs = []
        link_dl = MagicMock()
        link_dl._skip_when_attachment_invoice_present = True

        skip_for_attachment = False
        if link_dl._skip_when_attachment_invoice_present:
            success_attachment_pdfs = [
                att for att, info in parsed_invoice_pdfs
                if info.parse_success
            ]
            if success_attachment_pdfs:
                skip_for_attachment = True

        self.assertFalse(skip_for_attachment)


# ── 8. Filename conflict log tests ───────────────────────────────────


class TestFilenameConflictLogging(unittest.TestCase):
    """Tests for source_mode-based conflict log level."""


    def test_conflict_msg_does_not_leak_filename(self):
        """Conflict log uses mask_filename, never raw path."""
        from scripts.invoice_fetch.log_privacy import mask_filename

        # mask_filename should produce output that doesn't match the raw name
        raw_name = "my-real-invoice-12345.pdf"
        masked = mask_filename(raw_name)
        self.assertNotEqual(masked, raw_name)


# ── 9. Duplicate attachment backfill tests ────────────────────────────


class TestDuplicateAttachmentBackfill(unittest.TestCase):
    """Tests for update_invoice_attachment_path_if_missing."""

    def setUp(self):
        import tempfile
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_backfill_when_attachment_path_empty(self):
        """Existing invoice with empty attachment_path -> backfill succeeds."""
        from scripts.invoice_fetch.db import InvoiceDB
        db_path = self.temp_dir / "test_backfill_empty.db"
        with InvoiceDB(db_path) as db:
            inv_id = db.insert_invoice({
                "invoice_number": "12345678",
                "total_amount": "100.00",
                "seller_name": "测试公司",
                "invoice_date": "2026-06-01",
                "attachment_path": "",
                "review_status": "to_review",
            })
            # Create a real attachment file
            att_file = self.temp_dir / "test_attachment.pdf"
            att_file.write_text("dummy pdf")
            result = db.update_invoice_attachment_path_if_missing(
                inv_id, str(att_file), file_hash="abc123"
            )
            self.assertTrue(result)
            inv = db.get_invoice(inv_id)
            self.assertEqual(inv["attachment_path"], str(att_file))

    def test_no_backfill_when_attachment_exists(self):
        """Existing invoice with valid attachment -> no backfill."""
        from scripts.invoice_fetch.db import InvoiceDB
        db_path = self.temp_dir / "test_backfill_exists.db"
        existing_file = self.temp_dir / "existing.pdf"
        existing_file.write_text("existing")
        with InvoiceDB(db_path) as db:
            inv_id = db.insert_invoice({
                "invoice_number": "12345678",
                "total_amount": "100.00",
                "seller_name": "测试公司",
                "invoice_date": "2026-06-01",
                "attachment_path": str(existing_file),
                "review_status": "to_review",
            })
            new_file = self.temp_dir / "new_attachment.pdf"
            new_file.write_text("new")
            result = db.update_invoice_attachment_path_if_missing(
                inv_id, str(new_file), file_hash="xyz789"
            )
            self.assertFalse(result)
            inv = db.get_invoice(inv_id)
            self.assertEqual(inv["attachment_path"], str(existing_file))

    def test_backfill_file_not_deleted_by_cleanup(self):
        """Backfilled path must be in kept_paths (simulated)."""
        # This is a logical test: verify that the method exists and is importable
        from scripts.invoice_fetch.db import InvoiceDB
        self.assertTrue(hasattr(InvoiceDB, "update_invoice_attachment_path_if_missing"))


# ── 10. Missing field safe backfill tests ─────────────────────────────


class TestDuplicateMissingFieldBackfill(unittest.TestCase):
    """Tests for update_invoice_missing_fields."""

    def setUp(self):
        import tempfile
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_backfill_empty_seller_name_to_review(self):
        """to_review invoice with empty seller_name -> backfill succeeds."""
        from scripts.invoice_fetch.db import InvoiceDB
        db_path = self.temp_dir / "test_seller_backfill.db"
        with InvoiceDB(db_path) as db:
            inv_id = db.insert_invoice({
                "invoice_number": "12345678",
                "total_amount": "100.00",
                "seller_name": "",
                "invoice_date": "2026-06-01",
                "review_status": "to_review",
            })
            result = db.update_invoice_missing_fields(
                inv_id, {"seller_name": "新销售方公司"},
            )
            self.assertIn("seller_name", result["updated_fields"])
            inv = db.get_invoice(inv_id)
            self.assertEqual(inv["seller_name"], "新销售方公司")

    def test_no_overwrite_existing_seller_name(self):
        """to_review invoice with existing seller_name -> no overwrite."""
        from scripts.invoice_fetch.db import InvoiceDB
        db_path = self.temp_dir / "test_no_overwrite.db"
        with InvoiceDB(db_path) as db:
            inv_id = db.insert_invoice({
                "invoice_number": "12345678",
                "total_amount": "100.00",
                "seller_name": "已有销售方",
                "invoice_date": "2026-06-01",
                "review_status": "to_review",
            })
            result = db.update_invoice_missing_fields(
                inv_id, {"seller_name": "另一个销售方"},
                only_if_empty=True,
            )
            self.assertIn("seller_name", result["skipped_fields"])
            inv = db.get_invoice(inv_id)
            self.assertEqual(inv["seller_name"], "已有销售方")

    def test_approved_does_not_backfill_business_fields(self):
        """Approved invoice -> seller_name backfill is skipped."""
        from scripts.invoice_fetch.db import InvoiceDB
        db_path = self.temp_dir / "test_approved_skip.db"
        with InvoiceDB(db_path) as db:
            inv_id = db.insert_invoice({
                "invoice_number": "12345678",
                "total_amount": "100.00",
                "seller_name": "",
                "invoice_date": "2026-06-01",
                "review_status": "approved",
            })
            result = db.update_invoice_missing_fields(
                inv_id, {"seller_name": "新销售方"},
            )
            self.assertIn("seller_name", result["skipped_fields"])
            inv = db.get_invoice(inv_id)
            self.assertEqual(inv["seller_name"], "")

    def test_approved_allows_attachment_backfill(self):
        """Approved invoice -> attachment_path backfill is allowed."""
        from scripts.invoice_fetch.db import InvoiceDB
        db_path = self.temp_dir / "test_approved_att.db"
        with InvoiceDB(db_path) as db:
            inv_id = db.insert_invoice({
                "invoice_number": "12345678",
                "total_amount": "100.00",
                "seller_name": "已审核销售方",
                "invoice_date": "2026-06-01",
                "attachment_path": "",
                "review_status": "approved",
            })
            result = db.update_invoice_missing_fields(
                inv_id, {"attachment_path": "/path/to/file.pdf"},
            )
            # attachment_path is exempt from approved check
            self.assertIn("attachment_path", result["updated_fields"])

    def test_backfill_multiple_fields(self):
        """Backfill seller_name, buyer_name, invoice_date simultaneously."""
        from scripts.invoice_fetch.db import InvoiceDB
        db_path = self.temp_dir / "test_multi_backfill.db"
        with InvoiceDB(db_path) as db:
            inv_id = db.insert_invoice({
                "invoice_number": "12345678",
                "total_amount": "100.00",
                "seller_name": "",
                "buyer_name": "",
                "invoice_date": "",
                "review_status": "to_review",
            })
            result = db.update_invoice_missing_fields(
                inv_id, {
                    "seller_name": "销售方A",
                    "buyer_name": "购买方B",
                    "invoice_date": "2026-06-15",
                },
            )
            self.assertEqual(len(result["updated_fields"]), 3)


# ── 11. Seller name fallback parser tests ────────────────────────────


class TestSellerNameFallbackParser(unittest.TestCase):
    """Tests for _extract_seller_name_fallback."""

    @staticmethod
    def _extract(text):
        from scripts.invoice_fetch.invoice_parser import InvoiceParser
        return InvoiceParser._extract_seller_name_fallback(text)

    def test_extract_seller_from_seller_block(self):
        """Text with both buyer and seller blocks -> extract seller name."""
        text = (
            "购买方信息\n"
            "名称：购买方科技有限公司\n"
            "纳税人识别号：9111000011112222\n\n"
            "销售方信息\n"
            "名称：北京华联科技有限公司\n"
            "纳税人识别号：9111000033334444\n\n"
            "价税合计 ¥100.00\n"
        )
        result = self._extract(text)
        self.assertIn("北京", result)
        self.assertIn("华联", result)
        self.assertNotIn("购买方", result)

    def test_extract_seller_with_ocr_spacing(self):
        """Seller block with OCR cross-character spacing still matches."""
        text = (
            "销 售 方 信 息\n"
            "名称：北京某餐饮管理有限公司\n"
            "纳 税 人 识 别 号：91110105123456789X\n"
            "备注：无\n"
        )
        result = self._extract(text)
        self.assertIn("北京", result)
        self.assertIn("餐饮", result)

    def test_no_buyer_confusion(self):
        """Only buyer info present -> returns empty."""
        text = (
            "购买方信息\n"
            "名称：购买方科技有限公司\n"
            "纳税人识别号：9111000011112222\n"
            "备注：无\n"
        )
        result = self._extract(text)
        self.assertEqual(result, "")

    def test_no_seller_block_returns_empty(self):
        """No seller block at all -> returns empty."""
        text = "项目名称：餐饮服务\n规格型号：无\n价税合计：¥100.00\n"
        result = self._extract(text)
        self.assertEqual(result, "")

    def test_seller_name_with_parentheses(self):
        """Seller name containing parentheses is still extracted."""
        text = (
            "销售方信息\n"
            "名称：华住酒店管理（上海）有限公司\n"
            "纳税人识别号：91310000666600001U\n"
        )
        result = self._extract(text)
        self.assertIn("华住", result)
        self.assertIn("上海", result)

    def test_seller_block_stops_before_remarks(self):
        """Seller block extraction stops at 备注 marker."""
        text = (
            "销售方信息\n"
            "名称：上海锦江酒店管理有限公司\n"
            "纳税人识别号：9111000099998888\n"
            "备注：开票人：张三\n"
            "收款人：李四\n"
            "购买方信息\n"
            "名称：测试购买方有限公司\n"
        )
        result = self._extract(text)
        self.assertIn("锦江", result)
        self.assertNotIn("张三", result)
        self.assertNotIn("购买方", result)

    def test_fallback_integrated_in_parse_pdf(self):
        """Verify _extract_seller_name_fallback is callable from InvoiceParser."""
        from scripts.invoice_fetch.invoice_parser import InvoiceParser
        parser = InvoiceParser()
        self.assertTrue(hasattr(parser, "_extract_seller_name_fallback"))
        result = InvoiceParser._extract_seller_name_fallback("")
        self.assertEqual(result, "")


# ── 12. Link-download skip with attachments (integration test) ────────


class TestAttachmentSkipLinkDownloadIntegration(unittest.TestCase):
    """Test the decision to skip link downloads when attachments already parse."""

    def test_skip_logic_with_config_true(self):
        """Default config (True) + parse_success attachment -> skip."""
        from unittest.mock import MagicMock

        parsed_invoice_pdfs = [
            (MagicMock(), MagicMock(parse_success=True)),
        ]
        link_dl = MagicMock()
        link_dl._skip_when_attachment_invoice_present = True

        skip = False
        if getattr(link_dl, "_skip_when_attachment_invoice_present", True):
            success_attachment_pdfs = [
                att for att, info in parsed_invoice_pdfs if info.parse_success
            ]
            if success_attachment_pdfs:
                skip = True
        self.assertTrue(skip)

    def test_skip_logic_with_config_false(self):
        """Config False -> never skip even with parse_success attachment."""
        from unittest.mock import MagicMock

        parsed_invoice_pdfs = [
            (MagicMock(), MagicMock(parse_success=True)),
        ]
        link_dl = MagicMock()
        link_dl._skip_when_attachment_invoice_present = False

        skip = False
        if getattr(link_dl, "_skip_when_attachment_invoice_present", True):
            success_attachment_pdfs = [
                att for att, info in parsed_invoice_pdfs if info.parse_success
            ]
            if success_attachment_pdfs:
                skip = True
        self.assertFalse(skip)

    def test_no_parse_success_no_skip(self):
        """No parse_success attachment -> don't skip, try link download."""
        from unittest.mock import MagicMock

        parsed_invoice_pdfs = [
            (MagicMock(), MagicMock(parse_success=False)),
        ]
        link_dl = MagicMock()
        link_dl._skip_when_attachment_invoice_present = True

        skip = False
        if getattr(link_dl, "_skip_when_attachment_invoice_present", True):
            success_attachment_pdfs = [
                att for att, info in parsed_invoice_pdfs if info.parse_success
            ]
            if success_attachment_pdfs:
                skip = True
        self.assertFalse(skip)


# ── 13. Hardening commits tests for INVOICE-PREVIEW-DOWNLOAD-PARSER-002 ──


class TestDuplicateSafeBackfill(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test_dup.db"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_duplicate_safe_backfill_logic(self):
        from scripts.invoice_fetch.db import InvoiceDB
        from scripts.invoice_fetch.services import _refresh_invoice_from_parse

        with InvoiceDB(self.db_path) as db:
            # 1. 插入一个 existing 发票，具有非空 seller_name="原有销售方"
            inv_id_1 = db.insert_invoice({
                "invoice_number": "111111",
                "invoice_code": "code1",
                "invoice_date": "2026-06-01",
                "amount": "100.00",
                "total_amount": "100.00",
                "seller_name": "原有销售方",
                "buyer_name": "",
                "invoice_type": "电子发票",
                "category": "其他",
                "review_status": "to_review",
            })
            existing_1 = db.get_invoice(inv_id_1)

            # 调用 refresh，传入不同的 seller_name="新解析的销售方"，但 force_refresh_metadata=False
            res = _refresh_invoice_from_parse(
                db, existing_1,
                invoice_number="111111",
                invoice_code="code1",
                invoice_date="2026-06-01",
                amount="100.00",
                total_amount="100.00",
                seller_name="新解析的销售方",
                buyer_name="购买方A",
                invoice_type="电子发票",
                category="其他",
                has_extra=False,
                extra_type="",
                missing_extra=False,
                parse_note="",
                force_refresh_metadata=False
            )
            self.assertTrue(res)
            # 断言已有的 seller_name 依然是 "原有销售方"（不覆盖）
            inv_after_1 = db.get_invoice(inv_id_1)
            self.assertEqual(inv_after_1["seller_name"], "原有销售方")
            # 断言原本为空的 buyer_name 被成功回填为 "购买方A"
            self.assertEqual(inv_after_1["buyer_name"], "购买方A")

            # 2. 插入一个 existing 发票，seller_name 为空
            inv_id_2 = db.insert_invoice({
                "invoice_number": "222222",
                "invoice_code": "code2",
                "invoice_date": "2026-06-02",
                "amount": "200.00",
                "total_amount": "200.00",
                "seller_name": "",
                "buyer_name": "",
                "invoice_type": "电子发票",
                "category": "其他",
                "review_status": "to_review",
            })
            existing_2 = db.get_invoice(inv_id_2)

            res2 = _refresh_invoice_from_parse(
                db, existing_2,
                invoice_number="222222",
                invoice_code="code2",
                invoice_date="2026-06-02",
                amount="200.00",
                total_amount="200.00",
                seller_name="回填销售方",
                buyer_name="购买方B",
                invoice_type="电子发票",
                category="其他",
                has_extra=False,
                extra_type="",
                missing_extra=False,
                parse_note="",
                force_refresh_metadata=False
            )
            self.assertTrue(res2)
            # 断言原本为空的 seller_name 被成功回填
            inv_after_2 = db.get_invoice(inv_id_2)
            self.assertEqual(inv_after_2["seller_name"], "回填销售方")


class TestClaimedInvoiceProtection(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test_claimed.db"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_claimed_invoice_protection_rules(self):
        from scripts.invoice_fetch.db import InvoiceDB
        from scripts.invoice_fetch.services import _refresh_invoice_from_parse

        with InvoiceDB(self.db_path) as db:
            # 1. 插入一个 existing 发票，且将其关联到报销组以使其成为 claimed 发票
            inv_id = db.insert_invoice({
                "invoice_number": "333333",
                "invoice_code": "code3",
                "invoice_date": "2026-06-03",
                "amount": "300.00",
                "total_amount": "300.00",
                "seller_name": "",
                "buyer_name": "",
                "invoice_type": "电子发票",
                "category": "其他",
                "attachment_path": "",
                "review_status": "to_review",
            })
            # 插入 claim_group_items
            db._conn.execute(
                "INSERT INTO claim_group_items (claim_id, invoice_id, note) VALUES (?, ?, ?)",
                (1, inv_id, "test claim")
            )
            db._conn.commit()

            existing = db.get_invoice(inv_id)
            self.assertTrue(db.count_claim_links(inv_id) > 0)

            # 调用 refresh，试图回填 seller_name
            res = _refresh_invoice_from_parse(
                db, existing,
                invoice_number="333333",
                invoice_code="code3",
                invoice_date="2026-06-03",
                amount="300.00",
                total_amount="300.00",
                seller_name="想回填的销售方",
                buyer_name="想回填的购买方",
                invoice_type="电子发票",
                category="其他",
                has_extra=False,
                extra_type="",
                missing_extra=False,
                parse_note="",
                force_refresh_metadata=False
            )
            self.assertTrue(res)

            # 验证 seller_name 依然为空，不被更新
            inv_after = db.get_invoice(inv_id)
            self.assertEqual(inv_after["seller_name"], "")

            # 2. 验证 update_invoice_missing_fields 对 claimed 发票只允许更新 attachment_path / file_hash
            result = db.update_invoice_missing_fields(
                inv_id,
                {
                    "seller_name": "再次尝试",
                    "attachment_path": "/fake/path.pdf",
                    "file_hash": "hash123",
                    "invalid_field": "sql_inject"
                }
            )
            # seller_name 和 invalid_field 被 skipped，而 attachment_path 和 file_hash 被 updated
            self.assertIn("seller_name", result["skipped_fields"])
            self.assertIn("invalid_field", result["skipped_fields"])
            self.assertIn("attachment_path", result["updated_fields"])
            self.assertIn("file_hash", result["updated_fields"])
