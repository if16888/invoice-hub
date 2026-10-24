"""Validation tests for parser date/number hardening.

Every string in this module is synthetic (fabricated invoice text and file
names).  No runtime/ or attachments/ data is used.

Covered P1 fixes:
- impossible calendar dates are rejected instead of being stored verbatim;
- a date-like run in the file name never becomes the invoice number;
- a bare 20-digit run (old-style 校验码) never becomes the invoice number;
- well-formed invoices keep parsing exactly as before.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch.invoice_parser import (
    InvoiceParser,
    normalize_date,
    parse_railway_invoice_date,
    parse_railway_travel_date,
    parse_subject,
)


class _FakePdfPage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakePdfDocument:
    def __init__(self, text):
        self.pages = [_FakePdfPage(text)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakePdfPlumber:
    def __init__(self, text):
        self._text = text

    def open(self, path):
        return _FakePdfDocument(self._text)


def _parse_text(text: str, filename: str = "invoice.pdf"):
    """Run InvoiceParser.parse_pdf over synthetic text with a fake PDF backend."""
    parser = InvoiceParser()
    fake_plumber = _FakePdfPlumber(text)
    with tempfile.TemporaryDirectory() as td:
        pdf_path = Path(td) / filename
        pdf_path.write_bytes(b"%PDF-1.4 synthetic")
        with patch.object(parser, "_plumber", return_value=fake_plumber):
            return parser.parse_pdf(str(pdf_path))


def _basic_invoice_lines(*extra_lines: str, issue_date: str = "2026年05月01日") -> str:
    return "\n".join([
        "电子发票（普通发票）",
        *extra_lines,
        f"开票日期：{issue_date}",
        "销售方名称：示例餐饮管理有限公司",
        "购买方名称：示例科技有限公司",
        "合计 ¥100.00",
        "价税合计（小写）¥106.00",
    ])


class NormalizeDateValidationTests(unittest.TestCase):
    def test_impossible_calendar_dates_are_rejected(self):
        for value in (
            "2026年13月45日",
            "2026-13-45",
            "2026年02月30日",
            "2025-02-29",   # 2025 is not a leap year
            "0000-01-01",
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_date(value), "")

    def test_valid_dates_in_all_supported_formats_still_parse(self):
        cases = {
            "2026年05月01日": "2026-05-01",
            "2026年5月1日": "2026-05-01",
            "2026 年 05 月 01 日": "2026-05-01",
            "2026-05-01": "2026-05-01",
            "2026/5/1": "2026-05-01",
            "2026-05-01T10:00:00": "2026-05-01",
            "2024年02月29日": "2024-02-29",   # 2024 is a leap year
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_date(raw), expected)

    def test_unrecognized_format_is_kept_unchanged(self):
        # Backward-compatible passthrough: only *recognized but impossible*
        # dates are rejected; unknown formats are left for the caller.
        self.assertEqual(normalize_date("2026.05.01"), "2026.05.01")

    def test_railway_date_helpers_reject_impossible_dates(self):
        self.assertIsNone(parse_railway_travel_date("2026年13月45日 08:47开"))
        self.assertIsNone(parse_railway_invoice_date("开票日期：2026年13月45日"))
        # Well-formed railway dates keep working.
        self.assertEqual(parse_railway_travel_date("2026年05月07日 08:47开"), "2026-05-07")
        self.assertEqual(parse_railway_invoice_date("开票日期：2026年05月18日"), "2026-05-18")

    def test_subject_line_impossible_date_is_not_used(self):
        parsed = parse_subject("您的订单 2026-13-45 已开票")
        self.assertNotIn("invoice_date", parsed)

        valid = parse_subject("电子发票 2026年05月01日开具")
        self.assertEqual(valid["invoice_date"], "2026-05-01")


class ParsePdfDateValidationTests(unittest.TestCase):
    def test_impossible_issue_date_is_left_empty_with_review_note(self):
        text = _basic_invoice_lines(
            "发票号码：26322000000000000001",
            issue_date="2026年13月45日",
        )
        info = _parse_text(text)

        self.assertEqual(info.invoice_date, "")
        self.assertNotIn("13月", info.invoice_date)
        self.assertIn("开票日期无效", info.parse_note)
        self.assertEqual(info.expense_date, "")
        self.assertEqual(info.date_source, "unknown")
        # Contract unchanged: a labelled invoice number still counts as parsed.
        self.assertTrue(info.parse_success)
        self.assertEqual(info.invoice_number, "26322000000000000001")

    def test_next_valid_date_candidate_wins(self):
        text = "\n".join([
            "电子发票（普通发票）",
            "发票号码：26322000000000000001",
            "开票日期：2026年13月45日",
            "开票日期：2026年05月01日",
            "销售方名称：示例餐饮管理有限公司",
            "购买方名称：示例科技有限公司",
            "价税合计（小写）¥106.00",
        ])
        info = _parse_text(text)

        self.assertEqual(info.invoice_date, "2026-05-01")
        self.assertNotIn("开票日期无效", info.parse_note)

    def test_slash_format_issue_date_still_parsed(self):
        text = _basic_invoice_lines(
            "发票号码：26322000000000000001",
            issue_date="2026/05/01",
        )
        info = _parse_text(text)

        self.assertEqual(info.invoice_date, "2026-05-01")
        self.assertEqual(info.expense_date, "2026-05-01")
        self.assertEqual(info.date_source, "invoice_date")

    def test_invalid_date_and_missing_number_keep_both_notes(self):
        text = _basic_invoice_lines(issue_date="2026年13月45日")
        info = _parse_text(text)

        self.assertEqual(info.invoice_number, "")
        self.assertIn("开票日期无效", info.parse_note)
        self.assertIn("未提取到发票号码", info.parse_note)


class InvoiceNumberFallbackTests(unittest.TestCase):
    def test_filename_date_is_not_invoice_number(self):
        text = _basic_invoice_lines()
        info = _parse_text(text, filename="发票20260501.pdf")

        self.assertEqual(info.invoice_number, "")
        self.assertNotEqual(info.invoice_number, "20260501")
        # The issue date itself must still be parsed from the text.
        self.assertEqual(info.invoice_date, "2026-05-01")
        # parse_success contract is intentionally unchanged: no number -> False.
        self.assertFalse(info.parse_success)

    def test_filename_date_is_skipped_when_real_number_present(self):
        text = _basic_invoice_lines()
        info = _parse_text(text, filename="发票20260501_11803786.pdf")

        self.assertEqual(info.invoice_number, "11803786")
        self.assertNotEqual(info.invoice_code, "20260501")

    def test_classic_code_and_number_filename_still_extracted(self):
        text = _basic_invoice_lines()
        info = _parse_text(text, filename="031002500111_11803786.pdf")

        self.assertEqual(info.invoice_code, "031002500111")
        self.assertEqual(info.invoice_number, "11803786")

    def test_bare_20_digit_verification_code_is_not_invoice_number(self):
        text = "\n".join([
            "电子发票（普通发票）",
            "开票日期：2026年05月15日",
            "销售方名称：示例服务有限公司",
            "购买方名称：示例科技有限公司",
            "校验码 12345678901234567890",
            "价税合计（小写）¥88.00",
        ])
        info = _parse_text(text)

        self.assertEqual(info.invoice_number, "")
        self.assertNotEqual(info.invoice_number, "12345678901234567890")
        self.assertEqual(info.invoice_date, "2026-05-15")

    def test_real_8_digit_number_wins_over_20_digit_verification_code(self):
        text = "\n".join([
            "电子发票（普通发票）",
            "开票日期：2026年05月15日",
            "销售方名称：示例服务有限公司",
            "购买方名称：示例科技有限公司",
            "单据编号 11803786",
            "校验码 12345678901234567890",
            "价税合计（小写）¥88.00",
        ])
        info = _parse_text(text)

        self.assertEqual(info.invoice_number, "11803786")


class WellFormedInvoiceRegressionTests(unittest.TestCase):
    def test_normal_electronic_invoice_still_parses(self):
        text = "\n".join([
            "电子发票（普通发票）",
            "发票号码：26322000000000000001",
            "开票日期：2026年05月23日",
            "销售方名称：示例餐饮管理有限公司",
            "购买方名称：示例科技有限公司",
            "项目名称 规格型号 数量 单价 金额 税率 税额",
            "*餐饮服务*餐费 1 100.00 100.00 6% 6.00",
            "合计 ¥100.00",
            "价税合计（小写）¥106.00",
        ])
        info = _parse_text(text)

        self.assertTrue(info.parse_success)
        self.assertEqual(info.invoice_number, "26322000000000000001")
        self.assertEqual(info.invoice_date, "2026-05-23")
        self.assertEqual(info.expense_date, "2026-05-23")
        self.assertEqual(info.date_source, "invoice_date")
        self.assertEqual(info.amount, "100.00")
        self.assertEqual(info.total_amount, "106.00")
        self.assertEqual(info.seller_name, "示例餐饮管理有限公司")
        self.assertEqual(info.buyer_name, "示例科技有限公司")
        self.assertEqual(info.invoice_type, "电子发票")


if __name__ == "__main__":
    unittest.main()
