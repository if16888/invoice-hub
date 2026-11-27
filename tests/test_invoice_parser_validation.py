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


def _invoice_with_amounts(*amount_lines: str, title: str = "电子发票（普通发票）") -> str:
    return "\n".join([
        title,
        "发票号码：26322000000000000001",
        "开票日期：2026年05月23日",
        "销售方名称：示例服务有限公司",
        "购买方名称：示例科技有限公司",
        *amount_lines,
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


class ParsePdfAmountValidationTests(unittest.TestCase):
    def assert_amounts(self, lines, expected, *, title="电子发票（普通发票）"):
        info = _parse_text(_invoice_with_amounts(*lines, title=title))
        self.assertTrue(info.parse_success)
        self.assertEqual((info.amount, info.tax_amount, info.total_amount), expected)

    def test_signed_amounts_are_bound_to_each_label(self):
        cases = [
            (("合计 ¥-100.00", "税额：¥-6.00", "价税合计（小写）¥-106.00"),
             ("-100.00", "-6.00", "-106.00")),
            (("合计 -￥100.00", "税额：-￥6.00", "价税合计（小写）-￥106.00"),
             ("-100.00", "-6.00", "-106.00")),
            (("合 计 ￥ − 1,000.00", "合计税额：￥−60.00", "价税合计（⼩写）￥−1,060.00"),
             ("-1000.00", "-60.00", "-1060.00")),
            (("金 额：− ¥100.00", "税额合计 −¥6.00", "价 税 合 计 −¥106.00"),
             ("-100.00", "-6.00", "-106.00")),
            (("不含税金额：－ ￥1,234.00", "税 额 ￥ － 12.34", "价税合计金额：－￥1,246.34"),
             ("-1234.00", "-12.34", "-1246.34")),
            (("合计 -100.00", "税额：-6.00", "价 税 合 计（小写）-106.00"),
             ("-100.00", "-6.00", "-106.00")),
            (("金额：￥1,000.00", "税额合计：60.00", "价税合计（小写）￥1,060.00"),
             ("1000.00", "60.00", "1060.00")),
        ]
        for lines, expected in cases:
            with self.subTest(lines=lines):
                self.assert_amounts(lines, expected)

    def test_explicit_total_wins_over_later_unlabelled_and_remark_amounts(self):
        for tail in ("￥199.00", "备注：原订单⾦额 ￥199.00", "总计 ￥199.00"):
            with self.subTest(tail=tail):
                self.assert_amounts(
                    ("合计 ￥-100.00", "税额：￥-6.00", "价税合计（⼩写）￥-106.00", tail),
                    ("-100.00", "-6.00", "-106.00"),
                )
        # PDF reading order may put the remarks block ahead of the total.
        self.assert_amounts(
            ("备注：原订单⾦额 ￥199.00", "合计 ￥100.00", "税额：￥6.00",
             "价税合计（⼩写）￥106.00"),
            ("100.00", "6.00", "106.00"),
        )
        self.assert_amounts(
            ("合计 ￥-100.00", "税额：￥-6.00", "价税合计 ￥-106.00 备注：原订单金额 ￥199.00"),
            ("-100.00", "-6.00", "-106.00"),
        )

    def test_total_before_independent_subtotal_does_not_fill_pretax(self):
        self.assert_amounts(
            ("价税合计 ￥106.00", "合 计 ￥100.00", "税额：￥6.00"),
            ("100.00", "6.00", "106.00"),
        )
        self.assert_amounts(
            ("价 税 合 计 － ￥106.00", "金 额：-100.00"),
            ("-100.00", None, "-106.00"),
        )

    def test_total_only_never_becomes_pretax_and_missing_fields_are_not_calculated(self):
        for line, total in (("价 税 合 计 ￥106.00", "106.00"),
                            ("价 税 合 计 −￥106.00", "-106.00"),
                            ("价税合计（⼩写）¥-106.00", "-106.00")):
            with self.subTest(line=line):
                self.assert_amounts((line,), ("", None, total))
        self.assert_amounts(("税额：￥6.00", "价税合计 ￥106.00"), ("", "6.00", "106.00"))
        self.assert_amounts(("合计 ￥100.00", "税额：￥6.00"), ("100.00", "6.00", ""))

    def test_unlabelled_second_subtotal_column_does_not_supply_missing_tax(self):
        self.assert_amounts(
            ("合 计 ￥-100.00 ￥-6.00", "价税合计（⼤写）负壹佰零陆元整（⼩写）￥-106.00"),
            ("-100.00", None, "-106.00"),
        )

    def test_sign_is_not_inferred_from_red_invoice_or_other_fields(self):
        self.assert_amounts(
            ("合计 ￥100.00", "税额：￥6.00", "价税合计 ￥106.00"),
            ("100.00", "6.00", "106.00"), title="红字电子发票（普通发票）",
        )
        self.assert_amounts(
            ("合计 ￥-100.00", "税额：￥6.00", "价税合计 ￥106.00"),
            ("-100.00", "6.00", "106.00"),
        )

    def test_ambiguous_or_malformed_explicit_total_is_left_empty(self):
        for lines in (
            ("价税合计 ￥-106.00 ￥199.00",),
            ("价税合计 ￥-106.00", "价税合计 ￥-105.00"),
            ("价税合计 ￥--106.00", "备注：原订单金额 ￥199.00"),
            ("价税合计 ￥−1,00.00",),
            ("价税合计 ￥−106.000",),
        ):
            with self.subTest(lines=lines):
                self.assert_amounts(lines, ("", None, ""))

    def test_total_fallbacks_keep_sign_without_stealing_other_fields(self):
        for label in ("（小写）", "小 写：", "壹佰圆整 ", "总计：", "合计金额 ", "发票金额：", "人民币 ", ""):
            for token, total in (("￥106.00", "106.00"), ("− ￥106.00", "-106.00")):
                with self.subTest(label=label, token=token):
                    self.assert_amounts((label + token,), ("", None, total))
        for lines, expected in (
            (("合计 ￥-100.00",), ("-100.00", None, "")),
            (("合计", "￥100.00"), ("100.00", None, "")),
            (("税额：￥-6.00",), ("", "-6.00", "")),
            (("合计 ￥100.00", "税额 ￥6.00", "收款人：示例", "人民币 ￥106.00"), ("100.00", "6.00", "106.00")),
            (("税前金额 待核", "收款人：示例", "人民币 ￥106.00"), ("", None, "106.00")),
            (("备注：原订单金额 ￥199.00",), ("", None, "")),
            (("备注：原订单", "￥199.00"), ("", None, "")),
            (("原订单⾦额 ￥199.00",), ("", None, "")),
            (("人民币 --￥106.00",), ("", None, "")),
            (("￥−1,00.00",), ("", None, "")),
        ):
            with self.subTest(lines=lines):
                self.assert_amounts(lines, expected)

    def test_remark_regions_do_not_supply_invoice_amounts(self):
        for lines, expected in (
            (("合计 ￥-100.00", "税额：￥-6.00", "价税合计（小写）￥-106.00备注：￥199.00"),
             ("-100.00", "-6.00", "-106.00")),
            (("价税合计 ￥106.00元备注：原单 ￥199.00",), ("", None, "106.00")),
            (("合计 ￥100.00", "税额：￥6.00", "价税合计 ￥106.00", "备注：以下为原订单摘录，仅供参考",
              "“价税合计 ￥399.00”", "开票⼈：示例甲"), ("100.00", "6.00", "106.00")),
            (("合计 ￥-100.00", "税额：￥-6.00", "备注：下⾏仅列原单⽀付信息，不计⼊本票",
              "“发票⾦额：￥399.00”", "开票人：示例甲"), ("-100.00", "-6.00", "")),
            (("合计 ￥100.00", "税额：￥6.00", "价税合计 ￥106.00", "备注：原订单信息",
              "原件摘录", "价税合计 ￥199.00"), ("100.00", "6.00", "106.00")),
            (("合计 ￥100.00", "税额：￥6.00", "价税合计（小写）待人工确认", "备注：原单摘录",
              "价税合计 ￥199.00"), ("100.00", "6.00", "")),
            (("价税合计（小写）￥106.00", "备注：原订单收费明细", "⾦额：￥199.00"), ("", None, "106.00")),
            (("价税合计 ￥106.00", "备注：退款明细", "金额：￥199.00"), ("", None, "106.00")),
            (("价税合计 ￥106.00", "备注：普通说明", "金额：￥199.00", "税额：￥12.00"), ("", None, "106.00")),
            (("备注：退款", "原订单信息", "价税合计 ￥399.00"), ("", None, "")),
            (("备注：退款", "以下为原单摘录", "价税合计 ￥399.00", "本票价税合计 ￥106.00"), ("", None, "106.00")),
            (("合计 ￥100.00", "税额：￥6.00", "价税合计 ￥106.00", "备注：补充说明",
              "上次发票：价税合计 ￥199.00"), ("100.00", "6.00", "106.00")),
            (("备注：补充说明", "上次发票：价税合计 ￥199.00"), ("", None, "")),
            (("备注：补充说明", "上次发票：", "价税合计 ￥199.00"), ("", None, "")),
            (("备注：补充说明", "“前次凭证”", "价税合计 ￥199.00", "本票价税合计 ￥106.00"),
             ("", None, "106.00")),
            (("备注：", "金额：￥199.00"), ("", None, "")),
            (("备注：原票信息", "金额：￥199.00", "税额：￥6.00", "价税合计 ￥106.00"), ("", None, "")),
            (("备注：原订单收费明细", "金额：￥199.00", "本票价税合计 ￥106.00"), ("", None, "106.00")),
            (("备注：原单摘录", "“以下内容", "本票价税合计 ￥199.00", "”", "本票价税合计 ￥106.00"),
             ("", None, "106.00")),
            (("合计 ￥100.00", "税额：￥6.00", "备注：出差用途", "价税合计 ￥106.00"),
             ("100.00", "6.00", "106.00")),
            (("价税合计（小写）", "备注：原单摘录", "￥199.00"), ("", None, "")),
            (("（小写）", "备注：原订单金额 ￥199.00", "￥199.00"), ("", None, "")),
        ):
            with self.subTest(lines=lines):
                self.assert_amounts(lines, expected)

    def test_conflicting_invoice_net_and_tax_values_are_left_unknown(self):
        for lines, expected in (
            (("税前金额：￥100.00 或 ￥200.00", "税额：￥6.00 或 ￥12.00", "价税合计 ￥106.00"),
             ("", None, "106.00")),
            (("税前金额：￥100.00", "合计 ￥200.00", "税额合计 ￥6.00", "税额 ￥12.00", "价税合计 ￥106.00"),
             ("", None, "106.00")),
            (("不含税金额：待核对", "金额：￥40.00", "合计税额：待核对", "税额：￥6.00", "价税合计 ￥106.00"),
             ("", None, "106.00")),
            (("税前金额：￥100.00", "￥200.00"), ("", None, "")),
            (("税额：￥6.00", "或 ￥12.00"), ("", None, "")),
            (("税额：￥6.00", "或 ￥12.00", "收款人：示例", "人民币 ￥106.00"), ("", None, "106.00")),
            (("合计 ￥100.00 或 ￥200.00", "价税合计 ￥106.00"), ("", None, "106.00")),
            (("合计 ￥100.00 ￥6.00", "价税合计 ￥106.00"), ("100.00", None, "106.00")),
        ):
            with self.subTest(lines=lines):
                self.assert_amounts(lines, expected)

    def test_item_subtotal_and_repeated_item_tax_are_not_invoice_summaries(self):
        for lines, expected in (
            (("第一项", "小计 ￥40.00", "第二项：见清单", "不含税金额：待核对", "税额：￥6.00", "价税合计 ￥106.00"),
             ("", "6.00", "106.00")),
            (("小计 ￥40.00", "小计 ￥60.00", "合计 ￥100.00", "税额：￥6.00", "价税合计 ￥106.00"),
             ("100.00", "6.00", "106.00")),
            (("项目一 小计：￥40.00", "价税合计 ￥106.00"), ("", None, "106.00")),
            (("项目甲 金额：￥50.00 税额：￥3.00", "项目乙 金额：￥50.00 税额：￥3.00",
              "合计 ￥100.00 ￥6.00", "价税合计 ￥106.00"), ("100.00", None, "106.00")),
        ):
            with self.subTest(lines=lines):
                self.assert_amounts(lines, expected)

    def test_total_and_net_summary_labels_keep_distinct_semantics(self):
        self.assert_amounts(("合计金额 ￥100.00", "合计税额：￥6.00", "价税合计 ￥106.00"),
                            ("100.00", "6.00", "106.00"))
        self.assert_amounts(("金额合计 ￥100.00", "税额合计 ￥6.00", "总计 ￥106.00"),
                            ("100.00", "6.00", "106.00"))
        self.assert_amounts(("合计金额 ￥106.00",), ("", None, "106.00"))

    def test_split_negative_sign_is_preserved_only_when_bound(self):
        for sign in ("-", "−", "－"):
            with self.subTest(sign=sign):
                self.assert_amounts((f"价税合计（小写）{sign}", "￥106.00"), ("", None, "-106.00"))
                self.assert_amounts((f"⼈⺠币 {sign}", "￥106.00"), ("", None, "-106.00"))
                self.assert_amounts((sign, "￥106.00"), ("", None, ""))
                self.assert_amounts((f"人民币 {sign}", "￥-106.00"), ("", None, ""))
                self.assert_amounts((f"税前金额：{sign}", "￥100.00", "税额：￥", f"{sign}6.00", "价税合计 -106.00"),
                                    ("-100.00", "-6.00", "-106.00"))

    def test_total_decorations_keep_the_explicit_lowercase_value(self):
        for line in (
            "价税合计（⼤写）⊗壹佰零陆元整（⼩写）￥106.00",
            "价税合计（⼩写，单位：元）￥106.00",
            "价税合计（小写）：⼈⺠币￥106.00",
            "价税合计（小写）：人民币106.00元",
            "价税合计（元）￥106.00",
        ):
            with self.subTest(line=line):
                self.assert_amounts(("合计 ￥100.00", "税额：￥6.00", line), ("100.00", "6.00", "106.00"))

    def test_parallel_summary_columns_do_not_lose_explicit_total_to_deposit(self):
        for sign in ("", "-"):
            for trailing in ((), ("预付押金 ￥199.00",)):
                with self.subTest(sign=sign, trailing=trailing):
                    self.assert_amounts((f"合计 ￥{sign}100.00", f"税额：￥{sign}6.00",
                                         f"税率：6% 价税合计 ￥{sign}106.00", *trailing),
                                        (f"{sign}100.00", f"{sign}6.00", f"{sign}106.00"))
        for gross in ("￥--106.00", "￥106.00 或 ￥199.00", "（小写）待核对"):
            with self.subTest(gross=gross):
                self.assert_amounts(("合计 ￥100.00", "税额：￥6.00", f"税率：6% 价税合计 {gross}",
                                     "预付押金 ￥299.00"), ("100.00", "6.00", ""))
        self.assert_amounts(("税率：6% 税前金额 ￥100.00", "开票日期：2026年05月23日 合计税额 ￥6.00",
                             "价税合计 ￥106.00"), ("100.00", "6.00", "106.00"))
        self.assert_amounts(("合计 ￥100.00", "税额：￥6.00", "收款人：示例 价税合计 ￥106.00",
                             "预付押金 ￥199.00"), ("100.00", "6.00", "106.00"))
        self.assert_amounts(("合计 ￥100.00", "税额：￥6.00", "汇总区域 价税合计 待核对",
                             "预付押金 ￥199.00"), ("100.00", "6.00", ""))
        self.assert_amounts(("上次发票：价税合计 ￥199.00", "预付押金 ￥299.00"), ("", None, ""))
        self.assert_amounts(("合计 ￥100.00", "税额：￥6.00", "备注：出差用途", "税率：6% 价税合计 ￥106.00"),
                            ("100.00", "6.00", "106.00"))
        self.assert_amounts(("合计 ￥100.00", "税额：￥6.00", "税率：6% 原订单 价税合计 ￥199.00",
                             "税率：6% “价税合计 ￥199.00”", "价税合计 ￥106.00"), ("100.00", "6.00", "106.00"))

    def test_fiscal_toll_keeps_legacy_total_while_vat_toll_is_signed(self):
        for remark in ("备注：示例车辆通行", "备注：本票不作为增值税发票使用", "备注：原订单票种为增值税普通发票"):
            with self.subTest(remark=remark):
                info = _parse_text("\n".join([
                    "车辆通行费财政电子票据", "票据号码：95810015", "开票日期：2026年11月20日",
                    "财政电子票据公共服务平台", "交费项目：高速公路车辆通行费", remark, "合计 ￥35.00",
                ]))
                self.assertTrue(info.parse_success)
                self.assertEqual((info.amount, info.tax_amount, info.total_amount), ("35.00", None, "35.00"))
        fiscal = _parse_text("财务专用章\n车牌号：某车\n入站：甲\n出口站：乙\n票据号码：95810015\n合计 ￥35.00")
        self.assertTrue(fiscal.parse_success)
        self.assertEqual((fiscal.amount, fiscal.tax_amount, fiscal.total_amount), ("35.00", None, "35.00"))
        self.assert_amounts(("收费项目：高速公路通行费", "合计 ￥-100.00", "税额：￥-6.00", "价税合计 ￥-106.00",
                             "备注：原单为财政电子票据"),
                            ("-100.00", "-6.00", "-106.00"))


if __name__ == "__main__":
    unittest.main()
