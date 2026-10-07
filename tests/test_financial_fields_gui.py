import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QDialog

from tests.test_claim_reason_gui import _window
from scripts.invoice_fetch.gui.financial_fields_dialog import FinancialFieldsDialog


class FinancialFieldsGuiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        generator = _window(Path(temporary.name))
        self.window, self.claim, self.invoice = next(generator)
        self.addCleanup(generator.close)
        self.window._switch_main_page('review')
        self.window._change_filter('all')
        self.window.table.selectRow(0)

    def test_save_financial_fields_preserves_current_invoice(self):
        def edit(dialog):
            for key, text in [('amount', '10'), ('tax_amount', '0'), ('tax_rate', '免税'),
                              ('buyer_tax_id', 'OTHER-ID')]:
                dialog.unknown[key].setChecked(False)
                dialog.fields[key].setText(text)
            dialog.invoice_code.setText('123')
            return QDialog.Accepted
        with patch.object(FinancialFieldsDialog, 'exec', edit):
            self.window.btn_edit_financial_fields.click()
        row = self.window.db.get_invoice(self.invoice)
        self.assertEqual(row['tax_rate'], '免税')
        self.assertEqual(row['tax_amount'], '0')
        self.assertEqual(row['invoice_code'], '123')
        self.assertEqual(self.window.current_invoice['id'], self.invoice)

    def test_cancel_and_unknown_stay_unknown(self):
        with patch.object(FinancialFieldsDialog, 'exec', return_value=QDialog.Rejected):
            self.window.btn_edit_financial_fields.click()
        row = self.window.db.get_invoice(self.invoice)
        self.assertIsNone(row['tax_amount'])
        self.assertIsNone(row['buyer_tax_id'])
        dialog = FinancialFieldsDialog(row, self.window)
        self.assertIsNone(dialog.values()['buyer_tax_id'])
        dialog.unknown['buyer_tax_id'].setChecked(False)
        self.assertEqual(dialog.values()['buyer_tax_id'], '')

    def test_editor_persists_declared_tax_id_type(self):
        def edit(dialog):
            dialog.tax_id_type.setCurrentIndex(dialog.tax_id_type.findData('uscc'))
            dialog.unknown['buyer_tax_id'].setChecked(False)
            dialog.fields['buyer_tax_id'].setText('91350211M000100Y46')
            return QDialog.Accepted
        with patch.object(FinancialFieldsDialog, 'exec', edit):
            self.window.btn_edit_financial_fields.click()
        row = self.window.db.get_invoice(self.invoice)
        self.assertEqual(row['buyer_tax_id_type'], 'uscc')
        self.assertEqual(row['buyer_tax_id'], '91350211M000100Y46')
