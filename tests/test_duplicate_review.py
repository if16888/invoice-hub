"""Weak matches create an independent, reversible review queue."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.claim_export import export_claim_package
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.db_backup import create_verified_database_backup, restore_verified_database_backup
from scripts.invoice_fetch.duplicate_review import soft_invoice_fingerprint


class DuplicateReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def receipt(self, db, **changes):
        values = dict(seller_name='Taxi Seller', invoice_date='2026-10-07', total_amount='10.00',
                      review_status='approved', attachment_path='original.pdf')
        values.update(changes)
        return db.insert_invoice(values)

    def test_fingerprint_normalizes_without_rounding_or_number_length_guess(self):
        row = dict(seller_name=' Taxi Seller ', invoice_date='2026-10-07', total_amount='10.00')
        same = {**row, 'seller_name': 'taxi seller', 'total_amount': '10'}
        self.assertEqual(soft_invoice_fingerprint(row), soft_invoice_fingerprint(same))
        for change in ({'invoice_number': '1'}, {'seller_name': ''}, {'total_amount': 'NaN'},
                       {'invoice_date': 'bad'}, {'total_amount': None}):
            self.assertIsNone(soft_invoice_fingerprint({**row, **change}))
        for change in ({'currency': 'USD'}, {'invoice_date': '2026-10-08'}, {'total_amount': '10.01'}):
            self.assertNotEqual(soft_invoice_fingerprint(row), soft_invoice_fingerprint({**row, **change}))
        large = {**row, 'total_amount': '123456789012345678901234567890.01'}
        self.assertNotEqual(soft_invoice_fingerprint(large),
                            soft_invoice_fingerprint({**large, 'total_amount': '123456789012345678901234567890.02'}))

    def test_match_does_not_drop_or_change_status_and_distinct_survives_reopen(self):
        path = self.root / 'queue.db'
        with InvoiceDB(path) as db:
            first = self.receipt(db, review_status='to_review')
            second = self.receipt(db)
            candidates = db.list_duplicate_candidates()
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]['reference_id'], first)
            self.assertEqual(candidates[0]['invoice_id'], second)
            self.assertEqual(db.count_invoices(), 2)
            self.assertEqual(db.get_invoice(first)['review_status'], 'to_review')
            self.assertTrue(db.resolve_duplicate_candidate(candidates[0]['id'], 'distinct'))
            self.assertEqual(db.get_invoice(second)['review_status'], 'approved')
            self.assertEqual(db.list_duplicate_candidates(), [])
        with InvoiceDB(path) as db:
            self.assertEqual(db.list_duplicate_candidates(), [])
            self.assertEqual(len(db.list_duplicate_candidates('distinct')), 1)

    def test_metadata_change_invalidates_stale_candidate_and_requeues_new_match(self):
        with InvoiceDB(self.root / 'change.db') as db:
            self.receipt(db)
            second = self.receipt(db)
            candidate = db.list_duplicate_candidates()[0]
            db._conn.execute('UPDATE invoices SET total_amount=? WHERE id=?', ('11', second))
            db._conn.commit()
            self.assertFalse(db.resolve_duplicate_candidate(candidate['id'], 'duplicate'))
            self.assertEqual(db.list_duplicate_candidates(), [])
            third = self.receipt(db, total_amount='11')
            new = db.list_duplicate_candidates()
            self.assertEqual(len(new), 1)
            self.assertEqual(new[0]['invoice_id'], third)
            self.assertEqual(new[0]['reference_id'], second)

    def test_numbered_missing_fields_and_deleted_receipts_do_not_enter_queue(self):
        with InvoiceDB(self.root / 'skip.db') as db:
            self.receipt(db)
            other = self.receipt(db)
            self.assertTrue(db.soft_delete_invoice(other))
            self.receipt(db, invoice_number='1')
            self.receipt(db, seller_name='')
            self.assertEqual(db.list_duplicate_candidates(), [])

    def test_large_same_day_group_has_linear_candidate_count(self):
        with InvoiceDB(self.root / 'many.db') as db:
            for _ in range(50):
                self.assertIsNotNone(self.receipt(db))
            self.assertEqual(len(db.list_duplicate_candidates()), 49)
            self.assertEqual(len(db.list_duplicate_candidates()), 49)

    def test_confirmed_duplicate_blocks_export_but_pending_and_distinct_allow_it(self):
        (self.root / 'original.pdf').write_bytes(b'synthetic invoice')
        with InvoiceDB(self.root / 'export.db') as db:
            first, second = self.receipt(db), self.receipt(db)
            claim = db.create_claim_group('Receipts')
            self.assertTrue(db.add_invoice_to_claim(claim, first))
            self.assertTrue(db.add_invoice_to_claim(claim, second))
            candidate = db.list_duplicate_candidates()[0]
            kwargs = dict(reimbursement_config={}, export_root=self.root / 'exports')
            package = export_claim_package(db, claim, self.root, self.root, **kwargs)
            items = json.loads((package / 'manifest.json').read_text())['items']
            self.assertIn('pending', {item['duplicate_review'] for item in items})
            self.assertTrue(db.resolve_duplicate_candidate(candidate['id'], 'duplicate'))
            self.assertEqual(db.get_invoice(second)['review_status'], 'approved')
            with self.assertRaisesRegex(ValueError, '已确认重复'):
                export_claim_package(db, claim, self.root, self.root, **kwargs)
            self.assertTrue(db.reset_duplicate_candidate(candidate['id']))
            self.assertTrue(db.resolve_duplicate_candidate(candidate['id'], 'distinct'))
            package = export_claim_package(db, claim, self.root, self.root, **kwargs)
            items = json.loads((package / 'manifest.json').read_text())['items']
            self.assertIn('distinct', {item['duplicate_review'] for item in items})

    def test_backup_restores_review_decision(self):
        path = self.root / 'backup.db'
        with InvoiceDB(path) as db:
            self.receipt(db)
            self.receipt(db)
            candidate = db.list_duplicate_candidates()[0]
            self.assertTrue(db.resolve_duplicate_candidate(candidate['id'], 'distinct'))
        directory = self.root / 'backups'
        backup = create_verified_database_backup(path, backup_dir=directory)
        with InvoiceDB(path) as db:
            self.assertTrue(db.reset_duplicate_candidate(candidate['id']))
        restore_verified_database_backup(backup, path, backup_dir=directory)
        with InvoiceDB(path) as db:
            self.assertEqual(db.list_duplicate_candidates(), [])
            self.assertEqual(len(db.list_duplicate_candidates('distinct')), 1)

    def test_distinct_from_first_peer_does_not_hide_duplicate_with_later_peer(self):
        with InvoiceDB(self.root / 'three.db') as db:
            first, second, third = [self.receipt(db) for _ in range(3)]
            initial = db.list_duplicate_candidates()
            self.assertEqual(len(initial), 2)
            for row in initial:
                self.assertEqual(row['reference_id'], first)
                self.assertTrue(db.resolve_duplicate_candidate(row['id'], 'distinct'))
            remaining = db.list_duplicate_candidates()
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0]['invoice_id'], third)
            self.assertEqual(remaining[0]['reference_id'], second)
            self.assertTrue(db.resolve_duplicate_candidate(remaining[0]['id'], 'duplicate'))
            self.assertEqual(db.list_duplicate_candidates(), [])

    def test_v11_upgrade_and_failed_queue_migration_preserve_receipts(self):
        import sqlite3
        from scripts.invoice_fetch.migrations import check_and_migrate, validate_latest_schema
        path = self.root / 'legacy.db'
        with InvoiceDB(path) as db:
            self.receipt(db)
            self.receipt(db)
        with sqlite3.connect(path) as conn:
            conn.execute('DROP INDEX idx_invoices_soft_fingerprint')
            conn.execute('DROP TABLE duplicate_review_candidates')
            conn.execute('ALTER TABLE invoices DROP COLUMN soft_fingerprint')
            conn.execute('PRAGMA user_version=11')
        with sqlite3.connect(path) as conn:
            def authorize(action, arg1, arg2, database, trigger):
                if action == sqlite3.SQLITE_CREATE_TABLE and arg1 == 'duplicate_review_candidates':
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorize)
            with self.assertRaises(sqlite3.DatabaseError):
                check_and_migrate(conn)
            conn.set_authorizer(None)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 11)
            self.assertNotIn('soft_fingerprint', {row[1] for row in conn.execute('PRAGMA table_info(invoices)')})
            check_and_migrate(conn)
            validate_latest_schema(conn)
        with InvoiceDB(path) as db:
            self.assertEqual(db.count_invoices(), 2)
            self.assertEqual(len(db.list_duplicate_candidates()), 1)
