"""Exercise learning consent and memory management through real review controls."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.invoice_detail_panel import EditFieldsDialog
from scripts.invoice_fetch.gui.seller_preferences_dialog import SellerPreferencesDialog


class SellerCategoryPreferenceGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config = {'reimbursement': {'strict_buyer_check': True, 'buyer_name': 'Synthetic Buyer'}}
        self.config_patch = patch('scripts.invoice_fetch.gui.app.load_config_safe', return_value=config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.view = InvoiceReviewApp(self.root / 'gui.db')
        self.view._deferred_init()
        self.view.resize(1200, 800)
        self.view.show()
        self.view._switch_main_page('review')
        self.counter = 0
        self.invoice = self.seed()
        self.select(self.invoice)

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def seed(self, **fields):
        self.counter += 1
        return self.view.db.insert_invoice({
            'invoice_number': f'MEMORY-GUI-{self.counter}', 'invoice_date': '2026-10-01',
            'seller_name': 'Synthetic Seller', 'buyer_name': 'Synthetic Buyer',
            'total_amount': '10.00', 'category': '其他', 'parse_success': 1,
            'review_status': 'to_review', 'confirmed_note': 'Original note', **fields,
        })

    def select(self, invoice_id):
        self.view._load_invoices(preserve_invoice_id=invoice_id)
        for row, invoice in enumerate(self.view.invoices_list):
            if invoice['id'] == invoice_id:
                self.view.table.selectRow(row)
                break
        self.app.processEvents()

    def edit(self, category, *, remember=True):
        def accepted(dialog):
            self.assertFalse(dialog.chk_remember_category.isEnabled())
            dialog.combo_category.setCurrentText(category)
            self.assertTrue(dialog.chk_remember_category.isEnabled())
            dialog.chk_remember_category.setChecked(remember)
            return QDialog.Accepted
        with patch.object(EditFieldsDialog, 'exec', accepted):
            self.view._detail_panel.btn_edit_fields.click()

    def test_category_edit_learns_and_reports_saved_memory(self):
        self.edit('交通')
        row = self.view.db.get_invoice(self.invoice)
        self.assertEqual(row['category'], '交通')
        self.assertEqual(row['category_source'], 'manual')
        self.assertEqual(row['confirmed_note'], 'Original note')
        self.assertEqual(self.view.db.get_seller_category('Synthetic Seller'), '交通')
        self.assertIn('已记住', self.view.statusBar().currentMessage())
        self.assertEqual(self.view.current_invoice['id'], self.invoice)
        self.assertEqual(self.view._data_operation_gate.owner, '')
        future = self.seed()
        self.select(future)
        self.assertEqual(self.view.current_invoice['category'], '交通')
        self.assertIn('来自商户分类记忆', self.view._detail_panel.lbl_core_category.toolTip())

    def test_one_off_category_edit_keeps_previous_merchant_memory(self):
        self.edit('交通')
        future = self.seed()
        self.select(future)
        self.edit('办公', remember=False)
        self.assertEqual(self.view.db.get_invoice(future)['category'], '办公')
        self.assertEqual(self.view.db.get_invoice(future)['category_source'], 'manual')
        self.assertEqual(self.view.db.get_seller_category('Synthetic Seller'), '交通')
        self.assertNotIn('已记住', self.view.statusBar().currentMessage())
        self.assertTrue(self.view._detail_panel.remember_seller_category)

    def test_cancelled_edit_changes_neither_invoice_nor_memory(self):
        before = self.view.db.get_invoice(self.invoice)
        def cancelled(dialog):
            dialog.combo_category.setCurrentText('交通')
            return QDialog.Rejected
        with patch.object(EditFieldsDialog, 'exec', cancelled):
            self.view._detail_panel.btn_edit_fields.click()
        self.assertEqual(self.view.db.get_invoice(self.invoice), before)
        self.assertEqual(self.view.db.list_seller_category_preferences(), [])

    def test_unrelated_field_edit_keeps_learning_option_inactive(self):
        def accepted(dialog):
            dialog.txt_amount.setText('12.50')
            self.assertFalse(dialog.chk_remember_category.isEnabled())
            return QDialog.Accepted
        with patch.object(EditFieldsDialog, 'exec', accepted):
            self.view._detail_panel.btn_edit_fields.click()
        row = self.view.db.get_invoice(self.invoice)
        self.assertEqual(row['total_amount'], '12.50')
        self.assertEqual(row['category_source'], 'rule')
        self.assertEqual(self.view.db.list_seller_category_preferences(), [])

    def test_pending_evidence_or_empty_seller_cannot_learn_in_editor(self):
        for fields in ({'invoice_type': '待关联证明材料'}, {'seller_name': ''}):
            with self.subTest(fields=fields):
                invoice = self.seed(**fields)
                self.select(invoice)
                def accepted(dialog):
                    dialog.combo_category.setCurrentText('交通')
                    self.assertFalse(dialog.chk_remember_category.isEnabled())
                    return QDialog.Accepted
                with patch.object(EditFieldsDialog, 'exec', accepted):
                    self.view._detail_panel.btn_edit_fields.click()
        self.assertEqual(self.view.db.list_seller_category_preferences(), [])

    def test_management_deletes_only_selected_memory_and_keeps_records(self):
        self.edit('交通')
        other = self.seed(seller_name='Other Synthetic Seller')
        self.select(other)
        self.edit('办公')
        before = self.view.db.get_all_invoices()
        def choose(dialog):
            self.assertFalse(dialog.forget_button.isEnabled())
            for row in range(dialog.table.rowCount()):
                if dialog.table.item(row, 0).text() == 'Synthetic Seller':
                    dialog.table.selectRow(row)
            self.assertTrue(dialog.forget_button.isEnabled())
            self.assertEqual(dialog.selected_sellers(), ('Synthetic Seller',))
            return QDialog.Accepted
        with patch.object(SellerPreferencesDialog, 'exec', choose):
            self.view.btn_seller_preferences.click()
        self.assertEqual(self.view.db.get_all_invoices(), before)
        self.assertEqual(self.view.db.get_seller_category('Synthetic Seller'), '')
        self.assertEqual(self.view.db.get_seller_category('Other Synthetic Seller'), '办公')
        self.assertEqual(self.view._data_operation_gate.owner, '')
        self.assertEqual(self.view.db.get_invoice(self.seed())['category'], '其他')

    def test_cancel_management_preserves_memory_and_releases_gate(self):
        self.edit('交通')
        before = self.view.db.list_seller_category_preferences()
        with patch.object(SellerPreferencesDialog, 'exec', return_value=QDialog.Rejected):
            self.view.btn_seller_preferences.click()
        self.assertEqual(self.view.db.list_seller_category_preferences(), before)
        self.assertEqual(self.view._data_operation_gate.owner, '')

    def test_empty_management_has_explanation_and_disabled_delete(self):
        def inspect(dialog):
            self.assertEqual(dialog.table.rowCount(), 0)
            self.assertFalse(dialog.empty_hint.isHidden())
            self.assertFalse(dialog.forget_button.isEnabled())
            self.assertEqual(dialog.selected_sellers(), ())
            return QDialog.Rejected
        with patch.object(SellerPreferencesDialog, 'exec', inspect):
            self.view.btn_seller_preferences.click()

    def test_memory_controls_fit_compact_review_and_scrollable_editor(self):
        self.view.resize(1024, 720)
        self.app.processEvents()
        button = self.view.btn_seller_preferences
        self.assertTrue(button.parentWidget().rect().contains(button.geometry()))
        def inspect(dialog):
            dialog.show()
            self.app.processEvents()
            self.assertTrue(dialog.form_scroll.widget().rect().contains(dialog.chk_remember_category.geometry()))
            self.assertTrue(dialog.rect().contains(dialog.form_scroll.geometry()))
            return QDialog.Rejected
        with patch.object(EditFieldsDialog, 'exec', inspect):
            self.view._detail_panel.btn_edit_fields.click()

    def test_active_data_operation_blocks_saving_and_memory_management(self):
        self.view._data_operation_gate.try_acquire('Synthetic worker')
        before = self.view.db.get_invoice(self.invoice)
        self.view.combo_category.setCurrentText('交通')
        try:
            with patch.object(QMessageBox, 'warning') as warning, \
                 patch.object(SellerPreferencesDialog, 'exec') as manager:
                self.view._save_invoice_fields()
                self.view.btn_seller_preferences.click()
            self.assertEqual(warning.call_count, 2)
            manager.assert_not_called()
        finally:
            self.view._data_operation_gate.release('Synthetic worker')
        self.assertEqual(self.view.db.get_invoice(self.invoice), before)
        self.assertEqual(self.view.db.list_seller_category_preferences(), [])

    def test_failed_save_does_not_learn_and_releases_gate(self):
        self.seed()
        self.select(self.invoice)
        def accepted(dialog):
            dialog.txt_number.setText('MEMORY-GUI-2')
            dialog.combo_category.setCurrentText('交通')
            dialog.chk_remember_category.setChecked(False)
            return QDialog.Accepted
        before = self.view.db.get_invoice(self.invoice)
        with patch.object(EditFieldsDialog, 'exec', accepted), patch.object(QMessageBox, 'warning') as warning:
            self.view._detail_panel.btn_edit_fields.click()
        warning.assert_called_once()
        self.assertEqual(self.view.db.get_invoice(self.invoice), before)
        self.assertEqual(self.view.combo_category.currentText(), before['category'])
        self.assertEqual(self.view.txt_number.text(), before['invoice_number'])
        self.assertEqual(self.view.db.list_seller_category_preferences(), [])
        self.assertEqual(self.view._data_operation_gate.owner, '')

    def test_refresh_failure_reports_that_category_and_memory_were_saved(self):
        with patch.object(self.view, '_load_invoices', side_effect=RuntimeError('Synthetic refresh failure')), \
             patch.object(QMessageBox, 'critical') as error:
            self.edit('交通')
        self.assertIn('已保存', error.call_args.args[2])
        self.assertEqual(self.view.db.get_invoice(self.invoice)['category'], '交通')
        self.assertEqual(self.view.db.get_seller_category('Synthetic Seller'), '交通')
        self.assertEqual(self.view._data_operation_gate.owner, '')


if __name__ == '__main__':
    unittest.main()
