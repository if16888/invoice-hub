"""Declared ID schemes, migration, filters, export and restore share one contract."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.claim_export import export_claim_package
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.db_backup import create_verified_database_backup, restore_verified_database_backup
from scripts.invoice_fetch.migrations import check_and_migrate, validate_latest_schema
from scripts.invoice_fetch.reimbursement import buyer_warning
from scripts.invoice_fetch.review_query import ReviewColumnFilter, ReviewQuery
from scripts.invoice_fetch.tax_id_validation import check_tax_id

# Synthetic example with a valid GB 32100 check character; no registration claim.
VALID_USCC = '91350211M000100Y46'
BAD_USCC = '91350211M000100Y47'


class TaxIdValidationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_uscc_valid_character_set_and_checksum(self):
        self.assertEqual(check_tax_id(VALID_USCC, 'uscc').status, 'checksum_valid')
        self.assertEqual(check_tax_id(VALID_USCC.lower(), 'uscc').status, 'checksum_valid')
        self.assertEqual(check_tax_id(' 91350211M000100Y46 ', 'uscc').status, 'checksum_valid')
        for value in (BAD_USCC, VALID_USCC[:-1], VALID_USCC + '6', 'I' + VALID_USCC[1:],
                      'O' + VALID_USCC[1:], VALID_USCC[:5] + '-' + VALID_USCC[6:]):
            with self.subTest(value=value):
                self.assertTrue(check_tax_id(value, 'uscc').blocking)

    def test_no_length_inference_and_missing_is_distinct(self):
        for value in ('SHORT', BAD_USCC, '123456789012345', 'FOREIGN/ID'):
            self.assertEqual(check_tax_id(value).status, 'unverified')
            self.assertEqual(check_tax_id(value, 'other').status, 'unverified')
        self.assertEqual(check_tax_id(None, 'uscc').status, 'unknown')
        self.assertEqual(check_tax_id('', 'uscc').status, 'missing')
        self.assertTrue(check_tax_id(VALID_USCC, 'made_up_type').blocking)

    def test_legacy_taxpayer_ids_allow_organization_letters(self):
        self.assertEqual(check_tax_id('110108B33162958', 'legacy15').status, 'format_valid')
        self.assertEqual(check_tax_id('110108123456789', 'legacy15').status, 'format_valid')
        self.assertTrue(check_tax_id('SHORT', 'legacy15').blocking)
        self.assertTrue(check_tax_id('A10108B33162958', 'legacy15').blocking)

    def make_v10(self, path):
        with InvoiceDB(path) as db:
            invoice = db.insert_invoice({'invoice_number': 'LEGACY', 'buyer_tax_id': BAD_USCC,
                                         'total_amount': '10'})
        with sqlite3.connect(path) as conn:
            conn.execute('ALTER TABLE invoices DROP COLUMN buyer_tax_id_type')
            conn.execute('PRAGMA user_version=10')
        return invoice

    def test_v10_migration_preserves_value_without_guessing_type(self):
        path = self.root / 'legacy.db'
        invoice = self.make_v10(path)
        for _ in range(2):
            with InvoiceDB(path) as db:
                validate_latest_schema(db._conn)
                row = db.get_invoice(invoice)
                self.assertEqual(row['buyer_tax_id'], BAD_USCC)
                self.assertEqual(row['buyer_tax_id_type'], 'unknown')
                self.assertEqual(buyer_warning(row, {}), '')

    def test_migration_rolls_back_ddl_if_version_write_fails(self):
        path = self.root / 'rollback.db'
        self.make_v10(path)
        with sqlite3.connect(path) as conn:
            def authorize(action, arg1, arg2, database, trigger):
                if action == sqlite3.SQLITE_PRAGMA and arg1 == 'user_version' and arg2 == '11':
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorize)
            with self.assertRaises(sqlite3.DatabaseError):
                check_and_migrate(conn)
            conn.set_authorizer(None)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 10)
            self.assertNotIn('buyer_tax_id_type', {row[1] for row in conn.execute('PRAGMA table_info(invoices)')})
            check_and_migrate(conn)
            validate_latest_schema(conn)

    def test_buyer_warning_filter_uses_declared_type(self):
        with InvoiceDB(self.root / 'filter.db') as db:
            for number, value, scheme in [('VALID', VALID_USCC, 'uscc'), ('BAD', BAD_USCC, 'uscc'),
                                          ('UNKNOWN', BAD_USCC, 'unknown'), ('LEGACY', '110108B33162958', 'legacy15')]:
                db.insert_invoice({'invoice_number': number, 'buyer_name': 'Buyer',
                                   'buyer_tax_id': value, 'buyer_tax_id_type': scheme, 'total_amount': '10'})
            db.set_buyer_warning_checker(lambda row: bool(buyer_warning(row, {})))
            query = ReviewQuery(column_filters=(ReviewColumnFilter('buyer_warning', ('异常',)),))
            self.assertEqual(db.count_review_invoices(query), 1)
            self.assertEqual(db.list_review_invoices(query)[0]['invoice_number'], 'BAD')

    def test_export_invalid_declared_id_fails_closed_without_strict_comparison(self):
        (self.root / 'original.pdf').write_bytes(b'synthetic invoice')
        with InvoiceDB(self.root / 'export.db') as db:
            claim = db.create_claim_group('Tax ID')
            invoice = db.insert_invoice({'invoice_number': 'TAX-ID', 'total_amount': '10',
                'buyer_tax_id': BAD_USCC, 'buyer_tax_id_type': 'uscc',
                'review_status': 'approved', 'attachment_path': 'original.pdf'})
            self.assertTrue(db.add_invoice_to_claim(claim, invoice))
            exports = self.root / 'exports'
            with self.assertRaisesRegex(ValueError, '校验位'):
                export_claim_package(db, claim, self.root, self.root, reimbursement_config={}, export_root=exports)
            self.assertFalse(exports.exists())
            self.assertTrue(db.update_invoice_financial_fields(invoice, amount=None, tax_amount=None,
                tax_rate=None, invoice_code='', buyer_tax_id=VALID_USCC, buyer_tax_id_type='uscc'))
            package = export_claim_package(db, claim, self.root, self.root, reimbursement_config={}, export_root=exports)
            item = json.loads((package / 'manifest.json').read_text())['items'][0]
            self.assertEqual(item['buyer_tax_id_type'], 'uscc')
            self.assertEqual(item['buyer_tax_id_validation'], 'checksum_valid')

    def test_backup_restore_and_omitted_type_preserve_declared_scheme(self):
        path = self.root / 'restore.db'
        with InvoiceDB(path) as db:
            invoice = db.insert_invoice({'invoice_number': 'RESTORE', 'buyer_tax_id': VALID_USCC,
                                         'buyer_tax_id_type': 'uscc', 'total_amount': '10'})
            self.assertTrue(db.update_invoice_financial_fields(invoice, amount=None, tax_amount=None,
                tax_rate=None, invoice_code='', buyer_tax_id=VALID_USCC))
            self.assertEqual(db.get_invoice(invoice)['buyer_tax_id_type'], 'uscc')
        directory = self.root / 'backups'
        backup = create_verified_database_backup(path, backup_dir=directory)
        with InvoiceDB(path) as db:
            self.assertTrue(db.update_invoice_financial_fields(invoice, amount=None, tax_amount=None,
                tax_rate=None, invoice_code='', buyer_tax_id=VALID_USCC, buyer_tax_id_type='other'))
        restore_verified_database_backup(backup, path, backup_dir=directory)
        with InvoiceDB(path) as db:
            self.assertEqual(db.get_invoice(invoice)['buyer_tax_id_type'], 'uscc')
            with self.assertRaises(ValueError):
                db.update_invoice_financial_fields(invoice, amount=None, tax_amount=None,
                    tax_rate=None, invoice_code='', buyer_tax_id=VALID_USCC, buyer_tax_id_type='invalid')
