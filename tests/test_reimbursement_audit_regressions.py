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
        invoice_id = w.db.get_all_invoices(include_deleted=False)[0]['id']
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

    def test_dashboard_counts_do_not_hydrate_all_invoices(self):
        from scripts.invoice_fetch.gui.hci_v1 import _dashboard_counts
        w = self.window
        with patch.object(w.db, 'get_all_invoices', side_effect=AssertionError('full invoice hydration')):
            counts = _dashboard_counts(w)
        self.assertEqual(counts['to_review'], 110)

    def test_hidden_dashboard_does_not_collect_metrics(self):
        from scripts.invoice_fetch.gui.hci_v1 import _sync_dashboard_hci
        w = self.window
        with patch.object(w, '_collect_overview_metrics', side_effect=AssertionError('hidden refresh')):
            _sync_dashboard_hci(w)

    def test_small_window_keeps_claim_column_in_view(self):
        w = self.window
        w.resize(1280, 720)
        self.settle()
        header = w.table.horizontalHeader()
        self.assertLessEqual(header.sectionViewportPosition(6) + header.sectionSize(6), w.table.viewport().width())

    def test_native_narrow_viewport_keeps_assignment_and_restores_secondary_columns(self):
        w = self.window
        w.table.setFixedWidth(580)
        self.settle()
        w._adjust_column_4_width()
        header = w.table.horizontalHeader()
        self.assertLessEqual(header.sectionViewportPosition(6) + header.sectionSize(6), w.table.viewport().width())
        self.assertFalse(w.table.isColumnHidden(4))
        self.assertFalse(w.table.isColumnHidden(6))
        w.table.setFixedWidth(1000)
        self.settle()
        w._adjust_column_4_width()
        self.assertTrue(all(not w.table.isColumnHidden(column) for column in (1, 2, 5)))
