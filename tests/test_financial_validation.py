import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.claim_export import export_claim_package
from scripts.invoice_fetch.financial_validation import check_tax_balance, normalize_tax_rate
from scripts.invoice_fetch.invoice_parser import InvoiceParser
from scripts.invoice_fetch.reimbursement import buyer_warning
from scripts.invoice_fetch.review_query import ReviewColumnFilter, ReviewQuery


class FinancialValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_decimal_balance_rounding_credit_and_missing(self):
        for amount, tax, total, expected in [
            ('100', '13', '113', 'valid'), ('0.1', '0.2', '0.3', 'valid'),
            ('100', '13', '113.01', 'valid'), ('100', '13', '113.02', 'mismatch'),
            ('-100', '-13', '-113', 'valid'), ('100', '0', '100', 'valid'),
            ('100', None, '100', 'unknown'), ('100', '', '100', 'unknown'),
            ('NaN', '0', '100', 'invalid'), ('100', 'Infinity', '100', 'invalid'),
            ('100', 'NaN', None, 'invalid'), ('1e999999999', '0', '1', 'invalid'),
        ]:
            with self.subTest(amount=amount, tax=tax, total=total):
                self.assertEqual(check_tax_balance({'amount': amount, 'tax_amount': tax,
                                                    'total_amount': total}).status, expected)

    def test_explicit_rate_units_and_exempt_multi_rate(self):
        for raw, expected in [(None, None), ('', ''), ('免税', '免税'), ('多税率', '多税率'),
                              ('13.00％', '13%'), ('6%、13%', '6%, 13%'), ('0%', '0%')]:
            self.assertEqual(normalize_tax_rate(raw), expected)
        for raw in ('0.13', '13', '101%', '-1%', 'NaN%', '13%,'):
            with self.assertRaises(ValueError):
                normalize_tax_rate(raw)

    def test_exemption_and_invalid_rate_fail_closed(self):
        self.assertTrue(check_tax_balance({'amount': '100', 'tax_amount': '13',
                                          'total_amount': '113', 'tax_rate': '免税'}).blocking)
        self.assertTrue(check_tax_balance({'amount': '100', 'tax_amount': '13',
                                          'total_amount': '113', 'tax_rate': '0.13'}).blocking)
        self.assertEqual(check_tax_balance({'amount': '100', 'tax_amount': '13',
                                           'total_amount': '113', 'tax_rate': '多税率'}).status, 'valid')

    def test_v9_migration_does_not_invent_financial_values(self):
        path = self.root / 'legacy.db'
        with InvoiceDB(path) as db:
            invoice = db.insert_invoice({'invoice_number': 'LEGACY', 'amount': '100', 'total_amount': '113'})
        with sqlite3.connect(path) as conn:
            for key in ('buyer_tax_id', 'tax_amount', 'tax_rate'):
                conn.execute(f'ALTER TABLE invoices DROP COLUMN {key}')
            conn.execute('PRAGMA user_version=9')
        for _ in range(2):
            with InvoiceDB(path) as db:
                row = db.get_invoice(invoice)
                for key in ('buyer_tax_id', 'tax_amount', 'tax_rate'):
                    self.assertIsNone(row[key])
                self.assertEqual(row['amount'], '100')
                self.assertEqual(check_tax_balance(row).status, 'unknown')

    def test_strict_tax_filter_matches_known_empty_and_mismatch_not_legacy_unknown(self):
        cfg = {'strict_buyer_tax_check': True, 'buyer_tax_id': 'EXPECTED15'}
        with InvoiceDB(self.root / 'filter.db') as db:
            for number, value in [('UNKNOWN', None), ('OK', 'EXPECTED15'), ('EMPTY', ''), ('BAD', 'OTHER')]:
                db.insert_invoice({'invoice_number': number, 'buyer_name': 'Company',
                                   'buyer_tax_id': value, 'total_amount': '113'})
            db.set_buyer_warning_checker(lambda invoice: bool(buyer_warning(invoice, cfg)))
            query = ReviewQuery(column_filters=(ReviewColumnFilter('buyer_warning', ('异常',)),))
            self.assertEqual(db.count_review_invoices(query), 2)
            self.assertEqual({row['invoice_number'] for row in db.list_review_invoices(query)}, {'EMPTY', 'BAD'})

    def test_xml_captures_buyer_id_and_explicit_total_tax_only(self):
        path = self.root / 'invoice.xml'
        path.write_text('<EInvoice><BuyerInformation><BuyerName>Buyer</BuyerName>'
                        '<BuyerIdNum>BUYER15</BuyerIdNum></BuyerInformation>'
                        '<SellerInformation><SellerTaxID>SELLER</SellerTaxID></SellerInformation>'
                        '<InvoiceNumber>26322000000000000001</InvoiceNumber><IssueTime>2026-10-07T10:00:00</IssueTime><TotalAmWithoutTax>100.00</TotalAmWithoutTax>'
                        '<TotalTaxAm>13.00</TotalTaxAm><TotalTax-includedAmount>113.00</TotalTax-includedAmount></EInvoice>')
        info = InvoiceParser().parse_pdf(str(path))
        self.assertTrue(info.parse_success)
        self.assertEqual(info.buyer_tax_id, 'BUYER15')
        self.assertEqual(info.tax_amount, '13.00')
        self.assertIsNone(info.tax_rate)

    def test_export_blocks_balance_or_strict_tax_without_creating_package(self):
        (self.root / 'original.pdf').write_bytes(b'synthetic invoice')
        with InvoiceDB(self.root / 'invoice.db') as db:
            claim = db.create_claim_group('Finance')
            invoice = db.insert_invoice({'invoice_number': 'FINANCE', 'amount': '100', 'tax_amount': '13',
                'total_amount': '120', 'review_status': 'approved', 'attachment_path': 'original.pdf'})
            self.assertTrue(db.add_invoice_to_claim(claim, invoice))
            exports = self.root / 'exports'
            with self.assertRaisesRegex(ValueError, '价税合计不一致'):
                export_claim_package(db, claim, self.root, self.root, reimbursement_config={}, export_root=exports)
            self.assertFalse(exports.exists())
            self.assertTrue(db.update_invoice_financial_fields(invoice, amount='107', tax_amount='13',
                tax_rate='13%', buyer_tax_id='OTHER', invoice_code='CODE'))
            cfg = {'strict_buyer_tax_check': True, 'buyer_tax_id': 'EXPECTED'}
            with self.assertRaisesRegex(ValueError, '税号'):
                export_claim_package(db, claim, self.root, self.root, reimbursement_config=cfg, export_root=exports)
            self.assertFalse(exports.exists())
            package = export_claim_package(db, claim, self.root, self.root, reimbursement_config={}, export_root=exports)
            manifest = json.loads((package / 'manifest.json').read_text())
            self.assertEqual(manifest['items'][0]['tax_amount'], '13')
            self.assertEqual(manifest['items'][0]['tax_balance_status'], 'valid')

    def test_local_import_persists_parser_financial_data(self):
        from unittest.mock import patch
        from scripts.invoice_fetch import services
        from scripts.invoice_fetch.invoice_parser import InvoiceInfo
        source_dir = self.root / 'source'
        source_dir.mkdir()
        (source_dir / 'invoice.pdf').write_bytes(b'%PDF- synthetic invoice')
        runtime = self.root / 'runtime'

        class Parser:
            def parse_pdf(self, path):
                return InvoiceInfo(invoice_number='LOCAL-FINANCE', invoice_date='2026-10-07',
                                   amount='100', total_amount='113', seller_name='Seller',
                                   buyer_name='Buyer', buyer_tax_id='BUYER15', tax_amount='13',
                                   tax_rate='13%', parse_success=True)

        with InvoiceDB(runtime / 'invoice.db') as db, patch.object(services, 'RUNTIME_DIR', runtime):
            stats = services._import_local_directory(import_dir=source_dir, db=db, parser=Parser(),
                                                    categories={}, att_dir=runtime / 'attachments')
            self.assertEqual(stats['added'], 1)
            row = db.get_all_invoices()[0]
            self.assertEqual(row['buyer_tax_id'], 'BUYER15')
            self.assertEqual(row['tax_amount'], '13')
            self.assertEqual(row['tax_rate'], '13%')

    def test_backfill_and_reparse_preserve_known_fields_when_not_collected(self):
        from scripts.invoice_fetch.services import _refresh_invoice_from_parse
        from scripts.invoice_fetch.reparse_reconciliation import reconcile_reparsed_invoice
        params = dict(invoice_number='REPARSE-FINANCE', invoice_code='', invoice_date='2026-10-07',
                      amount='100', total_amount='113', seller_name='Seller', buyer_name='Buyer',
                      invoice_type='电子发票', category='其他', has_extra=False, extra_type='',
                      missing_extra=False, parse_note='')
        with InvoiceDB(self.root / 'reparse.db') as db:
            invoice = db.insert_invoice(params)
            self.assertTrue(_refresh_invoice_from_parse(db, db.get_invoice(invoice), **params,
                                                       buyer_tax_id='BUYER15', tax_amount='13', tax_rate='13%'))
            self.assertEqual(db.get_invoice(invoice)['tax_amount'], '13')
            self.assertTrue(_refresh_invoice_from_parse(db, db.get_invoice(invoice), **params, tax_amount='99'))
            self.assertEqual(db.get_invoice(invoice)['tax_amount'], '13')
            result = reconcile_reparsed_invoice(db, invoice, **params, parse_success=True, tax_amount=None)
            self.assertTrue(result.success)
            self.assertEqual(db.get_invoice(invoice)['tax_amount'], '13')

    def test_v10_migration_failure_rolls_back_then_retries(self):
        from scripts.invoice_fetch.migrations import check_and_migrate, validate_latest_schema
        path = self.root / 'failure.db'
        with InvoiceDB(path):
            pass
        with sqlite3.connect(path) as conn:
            for key in ('buyer_tax_id', 'tax_amount', 'tax_rate'):
                conn.execute(f'ALTER TABLE invoices DROP COLUMN {key}')
            conn.execute('PRAGMA user_version=9')
        with sqlite3.connect(path) as conn:
            count = 0
            def authorize(action, arg1, arg2, database, trigger):
                nonlocal count
                if action == sqlite3.SQLITE_ALTER_TABLE:
                    count += 1
                    if count == 2:
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorize)
            with self.assertRaises(sqlite3.DatabaseError):
                check_and_migrate(conn)
            conn.set_authorizer(None)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 9)
            self.assertNotIn('buyer_tax_id', {r[1] for r in conn.execute('PRAGMA table_info(invoices)')})
            check_and_migrate(conn)
            validate_latest_schema(conn)
