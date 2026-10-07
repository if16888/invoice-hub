"""Single-invoice assignment shortcut must not inherit the bulk selection."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp

_QAPP = QApplication.instance() or QApplication([])


def _window(tmp_path):
    path = tmp_path / 'shortcut.db'
    with InvoiceDB(path) as db:
        for i in range(2):
            db.insert_invoice({'invoice_number': f'SHORTCUT-{i}', 'total_amount': '10.00',
                               'seller_name': 'Seller', 'review_status': 'to_review'})
        claim = db.create_claim_group('Shortcut claim')
    view = InvoiceReviewApp(path, splash=None)
    view._deferred_init()
    view.show()
    view._switch_main_page('review')
    view._load_claims(selected_claim_id=claim)
    view._change_filter('all')
    view.activateWindow()
    _QAPP.processEvents()
    try:
        yield view, claim
    finally:
        view.close()
        _QAPP.processEvents()


def press(view):
    view.table.setFocus()
    _QAPP.processEvents()
    QTest.keyClick(view.table, Qt.Key_G, Qt.ControlModifier)
    _QAPP.processEvents()

class ClaimShortcutTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.tmp_path = Path(self._tempdir.name)
        generator = _window(self.tmp_path)
        self.window = next(generator)
        self.addCleanup(generator.close)

    def test_ctrl_g_adds_only_current_row_without_result_dialog(self):
        window = self.window
        view, claim = window
        selection = view.table.selectionModel()
        selection.select(view.table.model().index(0, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        selection.setCurrentIndex(view.table.model().index(1, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        ids = [inv['id'] for inv in view.invoices_list]
        assert len(selection.selectedRows()) == 2
        with patch('scripts.invoice_fetch.gui.app.QMessageBox.information') as info:
            press(view)
            assert view.db.get_invoice_claim_id(ids[1]) == claim
            assert view.db.get_invoice_claim_id(ids[0]) is None
            assert not info.called
            press(view)
            assert len(view.db.get_claim_invoices(claim)) == 1


    def test_ctrl_g_ignores_non_review_page_and_text_entry(self):
        window = self.window
        view, claim = window
        view.table.selectRow(0)
        view._switch_main_page('overview')
        view.workbench_shortcuts['Ctrl+G'].activated.emit()
        assert view.db.get_claim_invoices(claim) == []
        view._switch_main_page('review')
        view.txt_search.setFocus()
        _QAPP.processEvents()
        QTest.keyClick(view.txt_search, Qt.Key_G, Qt.ControlModifier)
        _QAPP.processEvents()
        assert view.db.get_claim_invoices(claim) == []


    def test_ctrl_g_ignores_modal_dialog(self):
        window = self.window
        view, claim = window
        view.table.selectRow(0)
        dialog = QDialog(view)
        dialog.setModal(True)
        dialog.show()
        _QAPP.processEvents()
        try:
            view.workbench_shortcuts['Ctrl+G'].activated.emit()
            assert view.db.get_claim_invoices(claim) == []
        finally:
            dialog.close()


    def test_ctrl_g_does_not_move_invoice_from_another_claim(self):
        window = self.window
        view, claim = window
        view.table.selectRow(0)
        invoice_id = view.invoices_list[0]['id']
        other = view.db.create_claim_group('Existing claim')
        assert view.db.add_invoice_to_claim(other, invoice_id)
        view._load_claims(selected_claim_id=claim)
        view.table.selectRow(0)
        with patch('scripts.invoice_fetch.gui.app.QMessageBox.warning') as warning:
            press(view)
            assert not warning.called
        assert '另一个报销组' in view.statusBar().currentMessage()
        assert view.db.get_invoice_claim_id(invoice_id) == other
        assert view.db.get_claim_invoices(claim) == []


    def test_ctrl_g_requires_selection_and_target_group(self):
        window = self.window
        view, claim = window
        view.table.clearSelection()
        with patch('scripts.invoice_fetch.gui.app.QMessageBox.warning') as warning:
            press(view)
            assert warning.called
            assert view.db.get_claim_invoices(claim) == []
            warning.reset_mock()
            view.table.selectRow(0)
            view.combo_claims.setCurrentIndex(-1)
            press(view)
            assert warning.called
            assert view.db.get_claim_invoices(claim) == []
