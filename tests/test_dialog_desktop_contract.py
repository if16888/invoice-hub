"""Real dialog behavior: safe defaults, action order, scrolling and keyboard."""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox, QWidget

from scripts.invoice_fetch.gui.app import SingleTaskMailboxDialog, SingleTaskAiProfileDialog
from scripts.invoice_fetch.gui.claim_reason_dialog import ClaimReasonDialog
from scripts.invoice_fetch.gui.company_tax_profile import CompanyTaxProfileDialog
from scripts.invoice_fetch.gui.dialog_shell import install_dialog_presentation
from scripts.invoice_fetch.gui.financial_fields_dialog import FinancialFieldsDialog
from scripts.invoice_fetch.gui.seller_preferences_dialog import SellerPreferencesDialog
from scripts.invoice_fetch.gui.styles import APP_STYLESHEET


class DialogDesktopContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        install_dialog_presentation(cls.app)

    def setUp(self):
        self.host = QWidget()
        self.host.setStyleSheet(APP_STYLESHEET)
        self.addCleanup(self.host.close)

    def settle(self, dialog):
        dialog.show()
        for _ in range(8):
            self.app.processEvents()

    def test_return_saves_form_and_cancel_precedes_save(self):
        dialog = ClaimReasonDialog({'name': 'Synthetic claim'}, self.host)
        self.addCleanup(dialog.close)
        self.settle(dialog)
        buttons = dialog.findChild(QDialogButtonBox)
        cancel, save = buttons.button(QDialogButtonBox.Cancel), buttons.button(QDialogButtonBox.Save)
        self.assertLess(cancel.x(), save.x())
        self.assertTrue(save.isDefault())
        dialog.fields['department'].setText('Synthetic department')
        dialog.fields['department'].setFocus()
        QTest.keyClick(dialog.fields['department'], Qt.Key_Return)
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.values()['department'], 'Synthetic department')

    def test_destructive_confirmation_keeps_cancel_default(self):
        box = QMessageBox(self.host)
        box.setText('Synthetic deletion confirmation')
        remove = box.addButton('删除', QMessageBox.DestructiveRole)
        cancel = box.addButton('取消', QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        self.addCleanup(box.close)
        self.settle(box)
        self.assertIs(box.defaultButton(), cancel)
        self.assertEqual(remove.property('variant'), 'danger')
        QTest.keyClick(box, Qt.Key_Return)
        self.assertIs(box.clickedButton(), cancel)

    def test_memory_deletion_is_not_a_default_accept_action(self):
        dialog = SellerPreferencesDialog([{'seller_name': 'Synthetic', 'preferred_category': '办公',
                                           'updated_at': '2026-11-06'}], self.host)
        self.addCleanup(dialog.close)
        dialog.table.selectRow(0)
        self.settle(dialog)
        self.assertEqual(dialog.forget_button.property('variant'), 'danger')
        self.assertFalse(dialog.forget_button.isDefault())
        QTest.keyClick(dialog, Qt.Key_Return)
        self.assertEqual(dialog.result(), QDialog.Rejected)

    def test_forms_fit_naturally_and_footer_survives_a_short_window(self):
        factories = (
            lambda: SingleTaskMailboxDialog(self.host, preset_id='custom'),
            lambda: SingleTaskAiProfileDialog(self.host),
            lambda: CompanyTaxProfileDialog({}, self.host),
            lambda: FinancialFieldsDialog({'amount': '100', 'tax_amount': '6'}, self.host),
        )
        for factory in factories:
            dialog = factory()
            try:
                self.settle(dialog)
                scroll = dialog.form_scroll
                # The natural desktop size should not needlessly hide fields.
                self.assertEqual(scroll.verticalScrollBar().maximum(), 0, type(dialog).__name__)
                footer = dialog.findChild(QWidget, 'DialogFooter')
                self.assertTrue(dialog.rect().contains(footer.geometry()))
                dialog.resize(dialog.width(), min(360, dialog.height()))
                for _ in range(4):
                    self.app.processEvents()
                self.assertTrue(dialog.rect().contains(footer.geometry()))
                self.assertLessEqual(scroll.y() + scroll.height(), footer.y())
                self.assertLessEqual(dialog.height(), dialog.maximumHeight())
                if isinstance(dialog, FinancialFieldsDialog):
                    unknown = dialog.unknown['buyer_tax_id']
                    self.assertIsNone(dialog.values()['buyer_tax_id'])
                    unknown.setFocus()
                    QTest.keyClick(unknown, Qt.Key_Space)
                    self.assertTrue(dialog.fields['buyer_tax_id'].isEnabled())
                    self.assertEqual(dialog.values()['buyer_tax_id'], '')
            finally:
                dialog.close()

    def test_escape_does_not_change_original_company_profile(self):
        original = {'buyer_name': 'Synthetic company'}
        dialog = CompanyTaxProfileDialog(original, self.host)
        self.addCleanup(dialog.close)
        self.settle(dialog)
        dialog.txt_buyer_name.setText('Unsaved change')
        QTest.keyClick(dialog.txt_buyer_name, Qt.Key_Escape)
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertEqual(original, {'buyer_name': 'Synthetic company'})
