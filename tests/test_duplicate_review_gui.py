import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.duplicate_review_dialog import DuplicateReviewDialog

_QAPP = QApplication.instance() or QApplication([])


class DuplicateReviewGuiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'queue.db'
        with InvoiceDB(path) as db:
            ids = [db.insert_invoice({'seller_name': 'Taxi', 'invoice_date': '2026-10-07',
                                      'total_amount': '10', 'review_status': 'to_review'}) for _ in range(2)]
        self.invoice_ids = ids
        self.window = InvoiceReviewApp(path, splash=None)
        self.window._deferred_init()
        self.window.show()
        self.window._switch_main_page('review')
        _QAPP.processEvents()
        self.addCleanup(self.window.close)

    def test_dialog_reviews_opens_both_originals_and_resets(self):
        opened = []
        dialog = DuplicateReviewDialog(self.window.db, self.window, opened.append, lambda: True)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.table.rowCount(), 1)
        dialog._open('invoice_id')
        dialog._open('reference_id')
        self.assertEqual(set(opened), set(self.invoice_ids))
        dialog._resolve('duplicate')
        self.assertEqual(dialog.table.rowCount(), 0)
        for invoice in self.invoice_ids:
            self.assertEqual(self.window.db.get_invoice(invoice)['review_status'], 'to_review')
        dialog.filter.setCurrentIndex(dialog.filter.findData('duplicate'))
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertTrue(dialog.reset_button.isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in dialog.resolve_buttons))
        dialog._reset()
        dialog.filter.setCurrentIndex(dialog.filter.findData('pending'))
        self.assertEqual(dialog.table.rowCount(), 1)
        dialog._resolve('distinct')
        self.assertEqual(len(self.window.db.list_duplicate_candidates('distinct')), 1)

    def test_busy_operation_prevents_opening_or_resolving(self):
        with patch.object(self.window, '_data_operation_busy_reason', return_value='完整备份操作'), \
             patch.object(DuplicateReviewDialog, 'exec') as editor:
            self.window.btn_soft_duplicate_review.click()
            self.assertFalse(editor.called)
        dialog = DuplicateReviewDialog(self.window.db, self.window, lambda _id: None, lambda: False)
        self.addCleanup(dialog.close)
        dialog._resolve('duplicate')
        self.assertEqual(len(self.window.db.list_duplicate_candidates()), 1)
