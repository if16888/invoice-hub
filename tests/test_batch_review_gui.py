import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QDate, QEvent, QItemSelectionModel, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

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

    def test_recent_three_months_from_date_header_preserves_paging_and_batch_scope(self):
        today = date.today()
        # Qt's existing calendar-month convention is an independent reference
        # for the Review preset (not the implementation being tested).
        start = QDate(today.year, today.month, today.day).addMonths(-3).toPython()
        within = sorted({start, today, *(today - timedelta(days=n) for n in range(2, 88, 4))})
        expected, pending = set(), set()
        for day in within:
            for status in ('to_review', 'approved', 'to_review'):
                invoice_id = self.seed(expense_date=day.isoformat(), invoice_date=day.isoformat(), review_status=status)[0]
                expected.add(invoice_id)
                if status == 'to_review':
                    pending.add(invoice_id)
        for day in [start - timedelta(days=n) for n in range(1, 183, 7)] + [today + timedelta(days=1), today + timedelta(days=21)]:
            self.seed(2, expense_date=day.isoformat(), invoice_date=day.isoformat())
        for expense, invoice in (('', start.isoformat()), (None, today.isoformat()),
                                 (within[1].isoformat(), (today + timedelta(days=1)).isoformat())):
            invoice_id = self.seed(expense_date=expense, invoice_date=invoice)[0]
            expected.add(invoice_id)
            pending.add(invoice_id)
        self.seed(expense_date=(start - timedelta(days=1)).isoformat(), invoice_date=today.isoformat())
        self.seed(expense_date='', invoice_date='')
        self.seed(expense_date='not-a-date', invoice_date=today.isoformat())
        self.seed(expense_date=today.isoformat(), invoice_date=today.isoformat(), is_deleted=1)
        self.assertEqual((len(expected), len(pending), self.counter), (75, 51, 135))

        def invoice_state():
            # Use the test window's owned connection, not an extra open file
            # handle that could outlive TemporaryDirectory on Windows.
            return list(self.view.db._conn.iterdump())

        before = invoice_state()
        self.view.resize(1440, 900)
        self.view.activateWindow()
        QTest.qWait(20)
        self.reload()
        QTest.mouseClick(self.view.workbench_nav_buttons['review'], Qt.LeftButton)
        self.app.processEvents()
        header = self.view.table.horizontalHeader()
        section = 2
        point = QPoint(header.sectionViewportPosition(section) + header.sectionSize(section) - 8, header.height() // 2)
        self.assertTrue(header.viewport().rect().contains(point))
        self.assertEqual(header.logicalIndexAt(point), section)
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.app.processEvents()
        popup = self.view._column_filter_popup
        try:
            self.assertTrue(popup.isVisible())
            self.assertEqual(popup.key, 'expense_date')
            combo = popup.quick_combo
            target = combo.findData('last_3_months')
            self.assertGreaterEqual(target, 0, 'recent three calendar months is available in the actual date popup')
            self.assertEqual(combo.itemText(target), '最近 3 个月')
            self.assertEqual([combo.itemData(i) for i in range(target)], ['', 'today', 'week', 'month', 'last_30_days'])
            QTest.mouseClick(combo, Qt.LeftButton)
            self.app.processEvents()
            QTest.qWait(20)
            choice = combo.view()
            self.assertTrue(choice.isVisible())
            # A keyboard choice in the actual opened combo is portable to
            # offscreen Qt's nested popup surface (mouse grabs vary by host).
            QTest.keyClick(choice, Qt.Key_End)
            self.assertEqual(choice.currentIndex().data(Qt.UserRole), 'last_3_months')
            QTest.keyClick(choice, Qt.Key_Return)
            self.app.processEvents()
            QTest.qWait(20)
            self.assertEqual(combo.currentData(), 'last_3_months')
            apply = next(button for button in popup.findChildren(QPushButton) if button.text() == '应用')
            QTest.mouseClick(apply, Qt.LeftButton)
            self.app.processEvents()
            self.assertFalse(popup.isVisible())
            self.assertFalse(choice.isVisible())
        finally:
            if popup is not None and popup.isVisible():
                popup.quick_combo.hidePopup()
                popup.close()
                self.app.processEvents()
        self.assertIsNone(self.app.activePopupWidget())
        self.assertEqual(self.view.column_filters['expense_date'], {'quick': 'last_3_months'})
        self.assertTrue(any('费用日期: 最近 3 个月' in button.text()
                            for button in self.view.filter_chips_widget.findChildren(QPushButton)))

        def visible_ids():
            from scripts.invoice_fetch.gui.app import SORT_ID_ROLE
            ids = [row['id'] for row in self.view.invoices_list]
            self.assertEqual(self.view.table.rowCount(), len(ids))
            self.assertEqual([self.view.table.item(row, 5).data(SORT_ID_ROLE) for row in range(len(ids))], ids)
            return ids

        def assert_two_pages(wanted, second_size):
            self.assertEqual(self.view._record_total_matching, len(wanted))
            first = visible_ids()
            self.assertEqual(len(first), 50)
            self.assertTrue(self.view.btn_review_next_page.isEnabled())
            QTest.mouseClick(self.view.btn_review_next_page, Qt.LeftButton)
            self.app.processEvents()
            second = visible_ids()
            self.assertEqual(len(second), second_size)
            self.assertFalse(set(first) & set(second))
            self.assertEqual(set(first + second), wanted)

        assert_two_pages(expected, 25)
        self.assertIn('75', self.view.action_approve_filtered.text())
        # Real QAction computes the whole query scope, not just the visible
        # 25 rows. Only the modal's response is controlled to cancel safely.
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as confirm:
            self.view.action_approve_filtered.trigger()
        confirm.assert_called_once()
        self.assertIn('共 75 张：可通过 51 张，跳过 24 张', confirm.call_args.args[2])
        self.assertEqual(confirm.call_args.args[-1], QMessageBox.No)
        self.assertEqual(invoice_state(), before)
        QTest.mouseClick(self.view.filter_buttons['to_review'], Qt.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.view.current_filter_status, 'to_review')
        self.assertEqual(self.view.column_filters['expense_date'], {'quick': 'last_3_months'})
        assert_two_pages(pending, 1)
        self.assertEqual(invoice_state(), before)

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
