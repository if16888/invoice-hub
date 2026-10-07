import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QItemSelectionModel
from PySide6.QtWidgets import QApplication, QMessageBox

from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class BatchReviewGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original = self.root / 'synthetic.xml'
        self.original.write_text('<invoice/>', encoding='utf-8')
        config = {'reimbursement': {'strict_buyer_check': True, 'buyer_name': 'TargetCorp'}}
        self.config_patch = patch('scripts.invoice_fetch.gui.app.load_config_safe', return_value=config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.view = InvoiceReviewApp(self.root / 'review.db')
        self.view._deferred_init()
        self.view.resize(1200, 800)
        self.view.show()
        self.view._switch_main_page('review')
        self.counter = 0
        self.app.processEvents()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def seed(self, count=1, **fields):
        ids = []
        for _ in range(count):
            self.counter += 1
            ids.append(self.view.db.insert_invoice({
                'invoice_number': f'GUI-{self.counter}', 'invoice_date': '2026-07-01',
                'seller_name': 'Synthetic Seller', 'buyer_name': 'TargetCorp',
                'total_amount': '10.00', 'parse_success': 1, 'category': '交通',
                'attachment_path': str(self.original), 'review_status': 'to_review',
                'confirmed_note': f'Note {self.counter}', **fields,
            }))
        return ids

    def reload(self):
        self.view.review_paging.load_first_page()
        self.app.processEvents()

    def select(self, rows):
        model = self.view.table.selectionModel()
        model.clearSelection()
        for row in rows:
            model.select(model.model().index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.app.processEvents()

    def test_menu_selects_only_loaded_rows_and_bar_approval_preserves_notes(self):
        ids = self.seed(75)
        self.reload()
        self.assertEqual(len(self.view.invoices_list), 50)
        self.view.action_select_loaded.trigger()
        self.app.processEvents()
        selected = self.view._selected_batch_invoice_ids()
        self.assertEqual(len(selected), 50)
        self.assertTrue(self.view.batch_review_bar.isVisible())
        notes = {i: self.view.db.get_invoice(i)['confirmed_note'] for i in ids}
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes) as confirm:
            self.view.batch_review_bar.approve.click()
        self.assertEqual(confirm.call_args.args[-1], QMessageBox.No)
        self.assertIn('所选已加载记录', confirm.call_args.args[2])
        self.assertEqual({i for i in ids if self.view.db.get_invoice(i)['review_status'] == 'approved'}, set(selected))
        for i in ids:
            self.assertEqual(self.view.db.get_invoice(i)['confirmed_note'], notes[i])

    def test_filtered_batch_handles_unloaded_rows_and_freezes_filter_ids(self):
        matching = self.seed(75)
        bad = self.seed(buyer_name='WrongCorp')[0]
        other = self.seed(3, category='办公')
        self.view.column_filters = {'category': {'values': {'交通'}}}
        self.view._change_filter('to_review')
        self.reload()
        self.assertEqual(len(self.view.invoices_list), 50)
        new = []
        def confirm(*args):
            self.assertIn('包括未加载记录', args[2])
            self.assertIn('共 76 张', args[2])
            new.extend(self.seed())
            return QMessageBox.Yes
        with patch.object(QMessageBox, 'question', side_effect=confirm):
            result = self.view._batch_approve_filtered()
        self.assertEqual(result['success'], 75)
        self.assertEqual(result['skipped'], 1)
        self.assertTrue(all(self.view.db.get_invoice(i)['review_status'] == 'approved' for i in matching))
        self.assertTrue(all(self.view.db.get_invoice(i)['review_status'] == 'to_review' for i in [bad, *other, *new]))

    def test_cancel_keeps_status_and_releases_operation_gate(self):
        ids = self.seed(2)
        self.reload()
        self.select([0, 1])
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
            result = self.view._batch_approve_selected()
        self.assertEqual(result['success'], 0)
        self.assertEqual(self.view._data_operation_gate.owner, '')
        self.assertTrue(all(self.view.db.get_invoice(i)['review_status'] == 'to_review' for i in ids))

    def test_existing_multiselect_approve_uses_anomaly_protection(self):
        clean = self.seed()[0]
        bad = self.seed(missing_extra=1)[0]
        self.reload()
        self.select([0, 1])
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes) as confirm:
            result = self.view._set_selected_status('approved')
        self.assertEqual(result['success'], 1)
        self.assertEqual(result['skipped'], 1)
        self.assertIn('缺证明材料', confirm.call_args.args[2])
        self.assertEqual(self.view.db.get_invoice(clean)['review_status'], 'approved')
        self.assertEqual(self.view.db.get_invoice(bad)['review_status'], 'to_review')

    def test_recheck_uses_current_profile_after_confirmation(self):
        ids = self.seed(2)
        self.reload()
        self.select([0, 1])
        def confirm(*args):
            self.view.config['reimbursement']['buyer_name'] = 'DifferentCorp'
            return QMessageBox.Yes
        with patch.object(QMessageBox, 'question', side_effect=confirm):
            result = self.view._batch_approve_selected()
        self.assertEqual(result['success'], 0)
        self.assertEqual(result['skipped'], 2)
        self.assertTrue(all(self.view.db.get_invoice(i)['review_status'] == 'to_review' for i in ids))

    def test_busy_operation_cannot_start_batch_review(self):
        ids = self.seed(2)
        self.reload()
        self.select([0, 1])
        self.view._data_operation_gate.try_acquire('Synthetic worker')
        try:
            with patch.object(QMessageBox, 'warning') as warning, patch.object(QMessageBox, 'question') as confirm:
                self.view._batch_approve_selected()
            warning.assert_called_once()
            confirm.assert_not_called()
        finally:
            self.view._data_operation_gate.release('Synthetic worker')
        self.assertTrue(all(self.view.db.get_invoice(i)['review_status'] == 'to_review' for i in ids))

    def test_unsaved_single_invoice_fields_block_full_filter_batch(self):
        invoice = self.seed()[0]
        self.reload()
        self.view.table.selectRow(0)
        self.view.txt_buyer.setText('Unsaved edit')
        with patch.object(QMessageBox, 'question') as confirm:
            self.view._batch_approve_filtered()
        confirm.assert_not_called()
        self.assertIn('未保存字段', self.view.statusBar().currentMessage())
        self.assertEqual(self.view.db.get_invoice(invoice)['review_status'], 'to_review')

    def test_refresh_failure_reports_already_committed_status_truthfully(self):
        ids = self.seed(2)
        self.reload()
        self.select([0, 1])
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), \
             patch.object(self.view, '_load_invoices', side_effect=RuntimeError('synthetic refresh failure')), \
             patch.object(QMessageBox, 'critical') as error:
            result = self.view._batch_approve_selected()
        self.assertEqual(result['success'], 2)
        self.assertIn('已完成', error.call_args.args[2])
        self.assertNotIn('未写入', error.call_args.args[2])
        self.assertTrue(all(self.view.db.get_invoice(i)['review_status'] == 'approved' for i in ids))

    def test_ignore_and_clear_bar_actions_keep_notes(self):
        ids = self.seed(2)
        self.reload()
        self.select([0, 1])
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            self.view.batch_review_bar.ignore.click()
        for i in ids:
            self.assertEqual(self.view.db.get_invoice(i)['review_status'], 'ignored')
            self.assertEqual(self.view.db.get_invoice(i)['confirmed_note'], f'Note {i}')
        self.select([0, 1])
        self.view.batch_review_bar.clear.click()
        self.app.processEvents()
        self.assertEqual(self.view._selected_batch_invoice_ids(), ())
        self.assertFalse(self.view.batch_review_bar.isVisible())

    def test_batch_bar_buttons_fit_compact_review_pane(self):
        self.seed(2)
        self.reload()
        self.view.resize(1024, 720)
        self.select([0, 1])
        self.app.processEvents()
        bar = self.view.batch_review_bar
        for button in (bar.approve, bar.link, bar.ignore, bar.clear):
            self.assertTrue(bar.rect().contains(button.geometry()), f'{button.text()} exceeds {bar.width()}px pane')

    def test_batch_bar_can_join_selected_records_to_current_claim(self):
        ids = self.seed(2)
        claim = self.view.db.create_claim_group('Synthetic batch claim')
        self.view._load_claims(selected_claim_id=claim)
        self.reload()
        self.select([0, 1])
        with patch.object(QMessageBox, 'information'):
            self.view.batch_review_bar.link.click()
        self.assertEqual({row['id'] for row in self.view.db.get_claim_invoices(claim)}, set(ids))
        self.assertEqual(self.view._data_operation_gate.owner, '')


if __name__ == '__main__':
    unittest.main()
