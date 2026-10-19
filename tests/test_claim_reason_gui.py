"""Exercise real reason dialog fields through the application save handlers."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.claim_reason_dialog import ClaimReasonDialog, InvoiceReasonDialog

_QAPP = QApplication.instance() or QApplication([])


def _window(tmp_path):
    path = tmp_path / 'reason-gui.db'
    with InvoiceDB(path) as db:
        claim = db.create_claim_group('Project', reason_detail='原事由')
        invoice = db.insert_invoice({'invoice_number': 'REASON-GUI', 'total_amount': '10.00',
                                     'seller_name': 'Seller', 'review_status': 'to_review'})
        assert db.add_invoice_to_claim(claim, invoice)
    view = InvoiceReviewApp(path, splash=None)
    view._deferred_init()
    view.show()
    view._load_claims(selected_claim_id=claim)
    _QAPP.processEvents()
    try:
        yield view, claim, invoice
    finally:
        view.close()
        _QAPP.processEvents()

class ClaimReasonGuiTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.tmp_path = Path(self._tempdir.name)
        generator = _window(self.tmp_path)
        self.window = next(generator)
        self.addCleanup(generator.close)

    def test_group_editor_saves_defaults_and_invoice_override_survives(self):
        window = self.window
        view, claim, invoice = window
        view._switch_main_page('export')
        assert view.export_group_list.currentItem().data(Qt.UserRole) == claim

        def edit(dialog):
            dialog.fields['reason_category'].setText('会议')
            dialog.fields['reason_detail'].setText('年度培训')
            dialog.fields['applicant_name'].setText('李某')
            dialog.fields['department'].setText('研发')
            return QDialog.Accepted

        with patch.object(ClaimReasonDialog, 'exec', edit):
            view.btn_edit_claim_reason.click()
        assert view.db.get_invoice_reason(invoice) == '会议 · 年度培训'
        assert view.db.get_claim_group(claim)['applicant_name'] == '李某'
        assert view.db.update_invoice_reason(invoice, '独立事由')
        with patch.object(ClaimReasonDialog, 'exec', edit):
            view.btn_edit_claim_reason.click()
        assert view.db.get_invoice_reason(invoice) == '独立事由'


    def test_invoice_editor_sets_override_then_restores_inheritance(self):
        window = self.window
        view, claim, invoice = window
        view._switch_main_page('review')
        view._change_filter('all')
        self.assertTrue(view._select_invoice_by_id(invoice))
        _QAPP.processEvents()

        def override(dialog):
            assert dialog.inherit.isChecked()
            dialog.inherit.setChecked(False)
            assert dialog.reason.isEnabled()
            dialog.reason.setText(' 单张补充说明 ')
            return QDialog.Accepted

        with patch.object(InvoiceReasonDialog, 'exec', override):
            view.btn_edit_invoice_reason.click()
        assert view.db.get_invoice_reason(invoice) == '单张补充说明'
        assert view.current_invoice['id'] == invoice

        def restore(dialog):
            assert not dialog.inherit.isChecked()
            dialog.inherit.setChecked(True)
            assert not dialog.reason.isEnabled()
            return QDialog.Accepted

        with patch.object(InvoiceReasonDialog, 'exec', restore):
            view.btn_edit_invoice_reason.click()
        assert view.db.get_invoice(invoice)['custom_reason'] is None
        assert view.db.get_invoice_reason(invoice) == '原事由'

    def test_export_page_confirms_reimbursement_and_refreshes_locked_state(self):
        view, claim, invoice = self.window
        export_run = view.db.add_export_run(
            claim, 'exports/test-run', 'generic_excel', 1, invoice_ids=[invoice]
        )
        view._refresh_export_page()
        assert view.export_group_list.currentItem().data(Qt.UserRole) == claim
        assert view.btn_mark_claim_reimbursed.isEnabled()
        with patch('scripts.invoice_fetch.gui.app.QMessageBox.question', return_value=QMessageBox.Yes):
            view._mark_selected_claim_reimbursed()
        assert view.db.get_claim_group(claim)['status'] == 'reimbursed'
        assert view.db.get_invoice(invoice)['reimbursed_group_id'] == claim
        assert not view.btn_mark_claim_reimbursed.isEnabled()

    def test_inline_reason_editor_saves_override_with_enter(self):
        view, _claim, invoice = self.window
        view._switch_main_page('review')
        view._change_filter('all')
        self.assertTrue(view._select_invoice_by_id(invoice))
        _QAPP.processEvents()

        editor = view.txt_invoice_reason_inline
        self.assertTrue(editor.isEnabled())
        self.assertEqual(editor.text(), '原事由')
        editor.setFocus()
        editor.setText('单票交通')
        QTest.keyClick(editor, Qt.Key_Return)
        _QAPP.processEvents()

        self.assertEqual(view.db.get_invoice(invoice)['custom_reason'], '单票交通')
        self.assertEqual(view.db.get_invoice_reason(invoice), '单票交通')
        self.assertEqual(view.current_invoice['id'], invoice)


    def test_cancel_and_busy_operation_do_not_write(self):
        window = self.window
        view, claim, invoice = window
        view._switch_main_page('export')
        with patch.object(ClaimReasonDialog, 'exec', return_value=QDialog.Rejected):
            view.btn_edit_claim_reason.click()
        assert view.db.get_invoice_reason(invoice) == '原事由'
        with patch.object(view, '_data_operation_busy_reason', return_value='完整备份操作'), \
             patch.object(ClaimReasonDialog, 'exec') as editor:
            view.btn_edit_claim_reason.click()
            assert not editor.called
        assert view.db.get_invoice_reason(invoice) == '原事由'
