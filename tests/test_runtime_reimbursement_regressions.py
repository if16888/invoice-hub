"""Financial summaries, truthful export readiness, and bounded page queries."""

import sqlite3
import os
import tempfile
import time
from unittest.mock import patch
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QTableWidgetSelectionRange

from scripts.invoice_fetch.claim_export import export_claim_package
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class RuntimeReimbursementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def settle(self):
        for _ in range(4):
            self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    @contextmanager
    def window(self, records, prepare=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / 'original.pdf'
            original.write_bytes(b'%PDF-1.4 synthetic invoice')
            path = root / 'review.db'
            with InvoiceDB(path) as db:
                ids = [db.insert_invoice({
                    'invoice_number': f'RUNTIME-{index}', 'seller_name': 'Synthetic Seller',
                    'invoice_date': datetime.now().strftime('%Y-%m-%d'), 'total_amount': '20.00',
                    'attachment_path': str(original), 'review_status': 'approved', **row,
                }) for index, row in enumerate(records)]
                if prepare:
                    prepare(db, ids, root)
            window = InvoiceReviewApp(path, splash=None)
            window._deferred_init()
            window.config = {'reimbursement': {}}
            window._export_dir = root / 'exports'
            window.resize(1440, 900)
            window.show()
            self.settle()
            try:
                yield window, ids, root
            finally:
                window._shutdown_background_workers(wait_ms=1000)
                window.close()
                window.deleteLater()
                self.settle()

    def mixed_rows(self):
        return [
            {'currency': 'CNY', 'total_amount': '20.00'},
            {'currency': 'USD', 'total_amount': '10.00'},
            {'currency': 'CNY', 'total_amount': '800.00', 'invoice_type': '待关联证明材料'},
        ]

    def select_claim(self, window, claim_id):
        for index in range(window.export_group_list.count()):
            if window.export_group_list.item(index).data(Qt.UserRole) == claim_id:
                window.export_group_list.setCurrentRow(index)
                window._sync_export_claim_selection()
                self.settle()
                return
        self.fail('Missing claim row')

    def test_selection_money_excludes_material_and_matches_batch_bar(self):
        with self.window(self.mixed_rows()) as (window, _, _):
            window._switch_main_page('review')
            window._change_filter('all')
            self.settle()
            window.table.clearSelection()
            window.table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 2, window.table.columnCount()-1), True)
            self.settle()
            self.assertEqual(window.lbl_status_middle.text(), '已选中 2 张｜合计 ¥20.00 / USD 10.00')
            self.assertIn('¥20.00 / USD 10.00', window.batch_review_bar.summary.text())

    def test_legacy_claim_material_never_contributes_to_group_money(self):
        def prepare(db, ids, root):
            claim = db.create_claim_group("Legacy group")
            db.add_invoice_to_claim(claim, ids[0])
            # Only old databases can contain a material as a claim member.
            db._conn.execute("INSERT INTO claim_group_items (claim_id,invoice_id,sort_order) VALUES (?,?,?)",
                             (claim, ids[1], 2))
            db._conn.commit()
        rows = [{"currency": "CNY"}, {"currency": "CNY", "invoice_type": "待关联证明材料", "total_amount": "800.00"}]
        with self.window(rows, prepare) as (window, _, _):
            self.assertIn("合计 ¥20.00", window.lbl_claim_total.text())
            window._switch_main_page("export")
            item = window.export_group_list.item(0)
            labels = [label.text() for label in window.export_group_list.itemWidget(item).findChildren(QLabel)]
            self.assertIn("1 张发票 · ¥20.00", labels)

    def test_month_money_excludes_material_and_preserves_currencies(self):
        with self.window(self.mixed_rows()) as (window, _, _):
            metrics = window._collect_overview_metrics()
            self.assertEqual(metrics['month_total_text'], '¥20.00 / USD 10.00')
            window._switch_main_page('overview')
            window._refresh_overview_page()
            labels = [label.text() for label in window.findChildren(QLabel) if '本月' in label.text()]
            self.assertTrue(any('本月 ¥20.00 / USD 10.00' in label for label in labels), labels)

    def test_completed_and_tax_blocked_claims_are_not_ready(self):
        claims = []
        def prepare(db, ids, root):
            for label, invoice in zip(('Ready', 'Paid', 'Tax mismatch'), ids):
                claim = db.create_claim_group(label)
                db.add_invoice_to_claim(claim, invoice)
                claims.append(claim)
            export_claim_package(db, claims[1], root, root, export_root=root / 'exports', reimbursement_config={})
            self.assertTrue(db.mark_claim_reimbursed(claims[1]))

        rows = [{}, {}, {'amount': '20.00', 'tax_amount': '5.00'}]
        with self.window(rows, prepare) as (window, _, root):
            self.assertEqual(window._collect_overview_metrics()['export_ready'], 1)
            window._switch_main_page('export')
            self.select_claim(window, claims[2])
            self.assertFalse(window.btn_run_export_page.isEnabled())
            self.assertIn('税前金额 + 税额', window.lbl_export_action_hint.text())
            self.assertIn('税前金额 + 税额', window.export_invoice_list.item(0).text())
            with self.assertRaisesRegex(ValueError, '税前金额'):
                export_claim_package(window.db, claims[2], root, root,
                    export_root=root / 'exports', reimbursement_config={})
            self.select_claim(window, claims[1])
            self.assertFalse(window.btn_run_export_page.isEnabled())

    def test_preflight_obeys_strict_tax_policy_and_does_not_write(self):
        claims = []
        def prepare(db, ids, root):
            claims.append(db.create_claim_group('Strict tax'))
            db.add_invoice_to_claim(claims[0], ids[0])

        with self.window([{'buyer_tax_id': ''}], prepare) as (window, ids, _):
            window.config = {'reimbursement': {'strict_buyer_tax_check': True, 'buyer_tax_id': '123456789012345'}}
            mutations = []
            def readonly(action, *args):
                if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                    mutations.append(action)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            window.db._conn.set_authorizer(readonly)
            try:
                self.assertEqual(window._collect_overview_metrics()['export_ready'], 0)
                window._switch_main_page('export')
                self.select_claim(window, claims[0])
                self.assertFalse(window.btn_run_export_page.isEnabled())
                self.assertIn('税号待核对', window.lbl_export_action_hint.text())
                self.assertEqual(mutations, [])
            finally:
                window.db._conn.set_authorizer(None)

    def test_confirmed_duplicate_disables_reimbursement_action(self):
        prepared = []
        def prepare(db, ids, root):
            claim = db.create_claim_group('Exported receipts')
            for invoice in ids:
                db.add_invoice_to_claim(claim, invoice)
            candidate = db.list_duplicate_candidates()[0]
            export_claim_package(db, claim, root, root, export_root=root / 'exports', reimbursement_config={})
            prepared.extend([claim, candidate['id']])

        with self.window([{'invoice_number': ''}, {'invoice_number': ''}], prepare) as (window, _, _):
            self.assertTrue(window.db.resolve_duplicate_candidate(prepared[1], 'duplicate'))
            window._switch_main_page('export')
            self.select_claim(window, prepared[0])
            self.assertFalse(window.btn_mark_claim_reimbursed.isEnabled())
            self.assertIn('已暂停核销', window.lbl_export_action_hint.text())

    def wait_for_preflight(self, window):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.settle()
            if not any(getattr(window, f'_{key}_preflight_worker', None) is not None for key in ('overview', 'export')):
                return
            time.sleep(0.01)
        self.fail('Material preflight did not finish')

    def test_slow_inspection_keeps_event_loop_responsive_and_reuses_result(self):
        self.check_async_inspection(change_material=False)

    def test_stale_material_result_is_discarded_before_enabling_export(self):
        self.check_async_inspection(change_material=True)

    def check_async_inspection(self, *, change_material):
        claims = []
        def prepare(db, ids, root):
            claims.append(db.create_claim_group('Large inspection'))
            for invoice in ids:
                db.add_invoice_to_claim(claims[0], invoice)

        with self.window([{} for _ in range(501)], prepare) as (window, ids, _):
            self.wait_for_preflight(window)
            checked = []
            def slow_inspection(rows, runtime):
                time.sleep(0.04)
                checked.extend(row['id'] for row in rows)
                return [{'attachment_available': True, 'attachment_reason': '',
                         'missing_extra': bool(row.get('missing_extra')), 'unavailable_extra': False} for row in rows]
            ticks = []
            timer = QTimer()
            timer.setInterval(10)
            timer.timeout.connect(lambda: ticks.append(1))
            with patch('scripts.invoice_fetch.claim_export.inspect_materials_for_invoices', side_effect=slow_inspection):
                timer.start()
                try:
                    window._switch_main_page('export')
                    self.assertIsNotNone(window._export_preflight_worker)
                    self.assertFalse(window.btn_run_export_page.isEnabled())
                    if change_material:
                        self.assertTrue(window.db.update_invoice_extra_flags(ids[0], has_extra=False, missing_extra=True))
                    self.wait_for_preflight(window)
                    self.assertGreaterEqual(len(ticks), 3)
                    self.assertEqual(window.btn_run_export_page.isEnabled(), not change_material)
                    self.assertEqual(len(checked), 501 * (2 if change_material else 1))
                finally:
                    timer.stop()

    def test_late_finished_callback_after_close_does_not_touch_deleted_worker(self):
        from scripts.invoice_fetch.gui.workers import MaterialPreflightWorker
        with self.window([]) as (window, _, root):
            worker = MaterialPreflightWorker([], root, (), parent=window)
            window._export_preflight_worker = worker
            worker.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            window._shutdown_requested = True
            window._material_preflight_finished("export", worker)
            self.assertIsNone(window._export_preflight_worker)

    def test_refresh_query_count_is_bounded_and_materials_are_reused(self):
        claims = []
        def prepare(db, ids, root):
            claim = db.create_claim_group('Large claim')
            claims.append(claim)
            for invoice in ids:
                db.add_invoice_to_claim(claim, invoice)

        with self.window([{} for _ in range(120)], prepare) as (window, _, _):
            window._switch_main_page('export')
            queries = []
            window.db._conn.set_trace_callback(lambda sql: queries.append(sql) if sql.lstrip().upper().startswith('SELECT') else None)
            try:
                window._refresh_export_page()
                self.assertLess(len(queries), 40, len(queries))
                queries.clear()
                self.select_claim(window, claims[0])
                self.assertLess(len(queries), 40, len(queries))
            finally:
                window.db._conn.set_trace_callback(None)


class ClaimMaterialBatchTests(unittest.TestCase):
    def test_shared_material_projection_survives_batch_boundary(self):
        with tempfile.TemporaryDirectory() as td, InvoiceDB(Path(td) / 'review.db') as db:
            claim = db.create_claim_group('Many receipts')
            ids = []
            for index in range(501):
                invoice = db.insert_invoice({'invoice_number': f'BATCH-{index}', 'total_amount': '10.00'})
                db.add_invoice_to_claim(claim, invoice)
                ids.append(invoice)
            source = db.insert_invoice({'record_role': 'evidence', 'attachment_path': 'shared.pdf'})
            self.assertEqual(db.link_evidence_to_invoices(ids, [source]), 501)
            queries = []
            db._conn.set_trace_callback(queries.append)
            rows = db.get_claim_invoices(claim)
            db._conn.set_trace_callback(None)
            self.assertEqual(len(rows), 501)
            for row in rows:
                material = row['linked_evidence'][0]
                self.assertEqual(material['evidence_id'], source)
                self.assertEqual(material['linked_count'], 501)
                self.assertEqual(material['attachment_path'], 'shared.pdf')
            self.assertLess(len(queries), 10, len(queries))
