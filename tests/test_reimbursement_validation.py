import gc
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from scripts.invoice_fetch.claim_export import export_claim_package
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.reimbursement import (
    amount_total,
    buyer_warning,
    compact_buyer_warning,
    format_currency_amount,
)


class ReimbursementValidationTests(unittest.TestCase):
    def test_invoice_amount_display_keeps_currency_zero_and_unknown_values(self):
        for amount, currency, expected in (
            ("78.5", "USD", "USD 78.50"),
            ("1,234.50", "eur", "EUR 1234.50"),
            (0, "USD", "USD 0.00"),
            (None, "USD", "USD —"),
            ("", "CNY", "¥—"),
            ("10", "人民币", "¥10.00"),
            ("10", None, "¥10.00"),
        ):
            with self.subTest(amount=amount, currency=currency):
                self.assertEqual(format_currency_amount(amount, currency), expected)

    def test_amount_total_rejects_non_finite_values(self):
        from decimal import Decimal

        count, total, has_missing = amount_total([
            {"total_amount": "100.00"},
            {"total_amount": "NaN"},
            {"total_amount": "Infinity"},
            {"total_amount": "sNaN"},
            {"total_amount": "50.00"},
        ])

        self.assertEqual(count, 5)
        self.assertEqual(total, Decimal("150.00"))
        self.assertTrue(has_missing)

    def test_buyer_warning_matches_missing_and_mismatch(self):
        cfg = {
            "reimbursement": {
                "buyer_name": "示例科技有限公司",
                "strict_buyer_check": True,
            }
        }

        self.assertEqual(buyer_warning({"buyer_name": "示例科技有限公司"}, cfg), "")
        self.assertEqual(buyer_warning({"buyer_name": ""}, cfg), "购方抬头待核对")

        detailed = buyer_warning({"buyer_name": "其他公司"}, cfg)
        self.assertEqual(
            detailed,
            "购买方与默认开票主体不一致（购买方抬头不匹配）："
            "当前发票：其他公司；默认主体：示例科技有限公司",
        )
        self.assertEqual(
            compact_buyer_warning(detailed),
            "购买方与默认开票主体不一致："
            "当前发票：其他公司；默认主体：示例科技有限公司",
        )

    def test_buyer_warning_without_expected_preset_only_warns_when_missing(self):
        cfg = {"reimbursement": {"strict_buyer_check": True}}

        self.assertEqual(buyer_warning({"buyer_name": "任意公司"}, cfg), "")
        self.assertEqual(buyer_warning({"buyer_name": ""}, cfg), "购方抬头待核对")

    def test_claim_export_records_buyer_warning_in_manifest_and_excel(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "runtime"
            attachment = runtime / "attachments" / "invoice.pdf"
            attachment.parent.mkdir(parents=True)
            attachment.write_bytes(b"pdf")
            db_path = runtime / "invoices.db"

            with InvoiceDB(db_path) as db:
                invoice_id = db.insert_invoice({
                    "invoice_number": "BUYER001",
                    "invoice_date": "2026-05-30",
                    "total_amount": "18.00",
                    "seller_name": "Seller",
                    "buyer_name": "其他公司",
                    "category": "餐饮",
                    "attachment_path": "attachments/invoice.pdf",
                    "review_status": "approved",
                })
                claim_id = db.create_claim_group("buyer warning claim")
                db.add_invoice_to_claim(claim_id, invoice_id)

                export_dir = export_claim_package(
                    db,
                    claim_id,
                    project_root=root,
                    runtime_dir=runtime,
                    export_root=root / "exports",
                    reimbursement_config={
                        "buyer_name": "示例科技有限公司",
                        "strict_buyer_check": True,
                    },
                )

            manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
            warning = (
                "购买方与默认开票主体不一致（购买方抬头不匹配）："
                "当前发票：其他公司；默认主体：示例科技有限公司"
            )
            self.assertEqual(manifest["items"][0]["warning"], warning)

            wb = load_workbook(export_dir / "reimbursement.xlsx")
            ws = wb["发票汇总"]
            headers = [cell.value for cell in ws[1]]
            self.assertIn("校验提示", headers)
            warning_col = headers.index("校验提示") + 1
            self.assertEqual(ws.cell(row=2, column=warning_col).value, warning)
            wb.close()
            del ws, wb
            gc.collect()


class CurrencyTotalsTests(unittest.TestCase):
    def test_known_currencies_are_not_added_together(self):
        from scripts.invoice_fetch.reimbursement import currency_total
        self.assertEqual(currency_total([{"total_amount": "10", "currency": "USD"},
            {"total_amount": "20", "currency": "RMB"}]), "¥20.00 / USD 10.00")

    def test_empty_and_invalid_totals_keep_safe_zero_display(self):
        from scripts.invoice_fetch.reimbursement import currency_total
        self.assertEqual(currency_total([{"total_amount": "NaN"}]), "¥0.00")
        self.assertEqual(currency_total([]), "¥0.00")


class EvidenceCurrencyTotalsTests(unittest.TestCase):
    def test_formatted_total_excludes_evidence_from_count_and_money(self):
        from scripts.invoice_fetch.reimbursement import format_amount_total
        rows = [{"total_amount": "20", "currency": "CNY"}, {"total_amount": "10", "currency": "USD"},
                {"total_amount": "800", "record_role": "evidence", "currency": "CNY"}]
        self.assertEqual(format_amount_total(rows), "2 张｜合计 ¥20.00 / USD 10.00")


if __name__ == "__main__":
    unittest.main()
