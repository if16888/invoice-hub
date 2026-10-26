"""Exercise reimbursement navigation and material snapshot reuse."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
import scripts.invoice_fetch.claim_export as materials

_APP = QApplication.instance() or QApplication([])

class ReimbursementAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 'audit.db'
        with InvoiceDB(path) as db:
            self.claim = db.create_claim_group('Audit')
            for i in range(110):
                db.insert_invoice({'invoice_number': f'AUDIT-{i}', 'total_amount': '10', 'review_status': 'to_review'})
        self.window = InvoiceReviewApp(path, splash=None)
        self.window._deferred_init()
        self.window.show()
        self.addCleanup(self.window.close)
        self.window._switch_main_page('review')
        self.window._change_filter('all')
        self.settle()

    def settle(self):
        _APP.processEvents()
        _APP.sendPostedEvents(None, QEvent.DeferredDelete)
        _APP.processEvents()

    def test_keyboard_assignment_preserves_later_page_identity(self):
        w = self.window
        w._load_invoices(append=True)
        w.table.selectRow(70)
        before = w.current_invoice['id']
        w._add_current_invoice_to_claim()
        self.assertEqual(w.current_invoice['id'], before)
        self.assertEqual(w.table.currentRow(), 70)
        self.assertEqual(w.table.rowCount(), 100)

    def test_export_issue_row_opens_matching_invoice(self):
        w = self.window
        invoice_id = w.invoices_list[0]['id']
        w.db.add_invoice_to_claim(self.claim, invoice_id)
        w._switch_main_page('export')
        self.settle()
        item = w.export_invoice_list.item(0)
        w._open_export_invoice(item)
        self.assertEqual(w.current_invoice['id'], invoice_id)
        self.assertEqual(w._current_page_key(), 'review')

    def test_export_refresh_inspects_each_original_once(self):
        w = self.window
        for row in w.invoices_list[:20]:
            w.db.add_invoice_to_claim(self.claim, row['id'])
        w._switch_main_page('export')
        self.settle()
        with patch.object(materials, 'inspect_original_attachment', wraps=materials.inspect_original_attachment) as check:
            w._refresh_export_page()
            self.assertEqual(check.call_count, 20)
        self.assertIsNone(w._export_material_snapshot)
