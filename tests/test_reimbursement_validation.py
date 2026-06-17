import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from scripts.invoice_fetch.claim_export import export_claim_package
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.reimbursement import buyer_warning


class ReimbursementValidationTests(unittest.TestCase):
    def test_buyer_warning_matches_missing_and_mismatch(self):
        cfg = {
            "reimbursement": {
                "buyer_name": "\u793a\u4f8b\u79d1\u6280\u6709\u9650\u516c\u53f8",
                "strict_buyer_check": True,
            }
        }

        self.assertEqual(buyer_warning({"buyer_name": "\u793a\u4f8b\u79d1\u6280\u6709\u9650\u516c\u53f8"}, cfg), "")
        self.assertEqual(buyer_warning({"buyer_name": ""}, cfg), "\u8d2d\u65b9\u62ac\u5934\u5f85\u6838\u5bf9")
        self.assertEqual(
            buyer_warning({"buyer_name": "其他公司"}, cfg),
            "购买方抬头不匹配：当前：其他公司；期望：示例科技有限公司",
        )

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
                    "buyer_name": "\u5176\u4ed6\u516c\u53f8",
                    "category": "\u9910\u996e",
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
                    reimbursement_config={
                        "buyer_name": "\u793a\u4f8b\u79d1\u6280\u6709\u9650\u516c\u53f8",
                        "strict_buyer_check": True,
                    },
                )

            manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
            warning = "购买方抬头不匹配：当前：其他公司；期望：示例科技有限公司"
            self.assertEqual(manifest["items"][0]["warning"], warning)

            wb = load_workbook(export_dir / "reimbursement.xlsx")
            ws = wb.active
            headers = [cell.value for cell in ws[1]]
            self.assertIn("\u6821\u9a8c\u63d0\u793a", headers)
            warning_col = headers.index("\u6821\u9a8c\u63d0\u793a") + 1
            self.assertEqual(ws.cell(row=2, column=warning_col).value, warning)


if __name__ == "__main__":
    unittest.main()
