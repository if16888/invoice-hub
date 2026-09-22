import os
import tempfile
from io import BytesIO
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openpyxl
from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from scripts.invoice_fetch.claim_export import _normalized_finite_amount
from scripts.invoice_fetch.excel_export import export_excel
from scripts.invoice_fetch.gui.invoice_detail_panel import EditFieldsDialog


class AmountIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, amount: str) -> EditFieldsDialog:
        parent = QWidget()
        parent.combo_category = QComboBox(parent)
        parent.combo_category.addItems(["交通", "其他"])
        self.addCleanup(parent.deleteLater)
        dialog = EditFieldsDialog(
            parent,
            "001234567890",
            "2026-09-22",
            amount,
            "交通",
            "Buyer",
            "Seller",
        )
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_editor_rejects_non_finite_amounts(self):
        for raw in ("NaN", "Infinity", "-Infinity"):
            dialog = self._dialog(raw)
            with patch(
                "scripts.invoice_fetch.gui.invoice_detail_panel.QMessageBox.warning"
            ) as warning:
                self.assertIsNone(dialog.values())
                warning.assert_called_once()

    def test_editor_accepts_thousands_separator_and_normalizes_value(self):
        dialog = self._dialog("1,234.56")
        with patch(
            "scripts.invoice_fetch.gui.invoice_detail_panel.QMessageBox.warning"
        ) as warning:
            values = dialog.values()
        warning.assert_not_called()
        self.assertEqual(values["amount"], "1234.56")

    def test_claim_amount_boundary_rejects_non_finite_values(self):
        for raw in ("", "NaN", "Infinity", "-Infinity", "not-a-number"):
            with self.assertRaises(ValueError):
                _normalized_finite_amount(raw, invoice_identity="发票号 TEST")
        self.assertEqual(
            _normalized_finite_amount("-12.30", invoice_identity="发票号 TEST"),
            "-12.30",
        )
        self.assertEqual(
            _normalized_finite_amount("1,234.56", invoice_identity="发票号 TEST"),
            "1234.56",
        )

    def test_excel_amount_cells_are_numeric_but_invoice_number_stays_text(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.xlsx"
            export_excel(
                [
                    {
                        "invoice_number": "00123456789012345678",
                        "invoice_code": "000012345678",
                        "invoice_date": "2026-09-22",
                        "expense_date": "2026-09-22",
                        "amount": "100.25",
                        "total_amount": "128.50",
                        "seller_name": "Seller",
                        "buyer_name": "Buyer",
                        "category": "交通",
                    }
                ],
                path,
            )
            # Read into memory before parsing so openpyxl cannot retain
            # an OS-level handle to the TemporaryDirectory file on Windows.
            workbook_bytes = path.read_bytes()
            wb = openpyxl.load_workbook(BytesIO(workbook_bytes), data_only=False)
            try:
                ws = wb["发票汇总"]
                headers = {cell.value: cell.column for cell in ws[1]}
                number = ws.cell(2, headers["发票号码"])
                amount = ws.cell(2, headers["金额(税前)"])
                total = ws.cell(2, headers["价税合计"])

                self.assertEqual(number.data_type, "s")
                self.assertEqual(number.value, "00123456789012345678")
                self.assertEqual(amount.data_type, "n")
                self.assertEqual(total.data_type, "n")
                self.assertAlmostEqual(amount.value, 100.25, places=2)
                self.assertAlmostEqual(total.value, 128.50, places=2)
                self.assertEqual(amount.number_format, "#,##0.00")
                self.assertEqual(total.number_format, "#,##0.00")
            finally:
                wb.close()


if __name__ == "__main__":
    unittest.main()
