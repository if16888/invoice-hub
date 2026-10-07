"""Category learning, import boundaries and durable manual choices."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.db_backup import create_verified_database_backup, restore_verified_database_backup
from scripts.invoice_fetch.invoice_parser import InvoiceInfo
from scripts.invoice_fetch.migrations import check_and_migrate, validate_latest_schema
from scripts.invoice_fetch.reparse_reconciliation import reconcile_reparsed_invoice
from scripts.invoice_fetch.services import _classify, _import_local_pdf, _refresh_invoice_from_parse


class SellerCategoryPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'preferences.db'
        self.db = InvoiceDB(self.path)
        self.addCleanup(self.db.close)
        self.counter = 0

    def seed(self, **fields):
        self.counter += 1
        return self.db.insert_invoice({
            'invoice_number': f'PREF-{self.counter}', 'invoice_date': '2026-10-01',
            'seller_name': 'Synthetic Seller', 'buyer_name': 'Synthetic Buyer',
            'amount': '10.00', 'total_amount': '10.00', 'category': '其他',
            'parse_success': 1, 'review_status': 'to_review', 'confirmed_note': 'Original note',
            **fields,
        })

    def correct(self, invoice_id, category, remember=True, **changes):
        row = self.db.get_invoice(invoice_id)
        values = {key: row[key] for key in ('invoice_number', 'expense_date', 'seller_name',
                                          'buyer_name', 'total_amount')}
        return self.db.update_invoice_fields(
            invoice_id, category=category, note='Original note',
            remember_seller_category=remember, **(values | changes),
        )

    def parsed(self, invoice_id, category='餐饮', **changes):
        row = self.db.get_invoice(invoice_id)
        return dict(
            invoice_number=row['invoice_number'], invoice_code='', invoice_date='2026-10-02',
            amount='10.00', total_amount='10.00', seller_name=row['seller_name'],
            buyer_name='Synthetic Buyer', invoice_type='电子发票', category=category,
            has_extra=False, extra_type='', missing_extra=False, parse_success=True,
            parse_note='Synthetic reparse',
        ) | changes

    def make_v12(self):
        invoice_id = self.seed(category='Legacy category')
        self.db.close()
        with sqlite3.connect(self.path) as conn:
            conn.execute('DROP TABLE seller_category_preferences')
            conn.execute('ALTER TABLE invoices DROP COLUMN category_source')
            conn.execute('PRAGMA user_version=12')
        return invoice_id

    def test_v12_upgrade_preserves_legacy_category_without_inferred_learning(self):
        invoice_id = self.make_v12()
        for _ in range(2):
            with InvoiceDB(self.path) as db:
                validate_latest_schema(db._conn)
                self.assertEqual(db.get_invoice(invoice_id)['category'], 'Legacy category')
                self.assertEqual(db.get_invoice(invoice_id)['category_source'], 'unknown')
                self.assertEqual(db.list_seller_category_preferences(), [])

    def test_failed_v13_migration_rolls_back_table_and_version(self):
        self.make_v12()
        with sqlite3.connect(self.path) as conn:
            def authorize(action, *args):
                return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_ALTER_TABLE else sqlite3.SQLITE_OK
            conn.set_authorizer(authorize)
            with self.assertRaises(sqlite3.DatabaseError):
                check_and_migrate(conn)
            conn.set_authorizer(None)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 12)
            self.assertIsNone(conn.execute(
                "SELECT name FROM sqlite_master WHERE name='seller_category_preferences'"
            ).fetchone())
            check_and_migrate(conn)
            validate_latest_schema(conn)

    def test_manual_correction_learns_and_future_parsed_invoice_uses_it(self):
        old = self.seed()
        self.assertTrue(self.correct(old, '交通'))
        self.assertEqual(self.db.get_invoice(old)['category_source'], 'manual')
        new = self.seed(category='餐饮', extra_type='Synthetic proof', missing_extra=1)
        row = self.db.get_invoice(new)
        self.assertEqual(row['category'], '交通')
        self.assertEqual(row['category_source'], 'seller_preference')
        self.assertEqual(row['missing_extra'], 1)
        self.assertEqual(row['extra_type'], 'Synthetic proof')
        self.assertEqual(row['confirmed_note'], 'Original note')
        self.assertEqual(self.db.get_seller_category(' Synthetic Seller '), '交通')

    def test_full_names_and_canonical_unicode_match_without_fuzzy_aliases(self):
        invoice = self.seed(seller_name='Café Merchant')
        self.assertTrue(self.correct(invoice, '办公'))
        self.assertEqual(self.db.get_seller_category(' Cafe\u0301 Merchant '), '办公')
        for name in ('Café Merchant Branch', 'café Merchant', 'CaféMerchant', 'Café  Merchant', ''):
            with self.subTest(name=name):
                self.assertEqual(self.db.get_seller_category(name), '')

    def test_opt_out_preserves_existing_memory_and_current_manual_override(self):
        invoice = self.seed()
        self.assertTrue(self.correct(invoice, '交通'))
        one_off = self.seed()
        self.assertTrue(self.correct(one_off, '办公', remember=False))
        self.assertEqual(self.db.get_seller_category('Synthetic Seller'), '交通')
        self.assertTrue(self.db.update_invoice_parsed_metadata(one_off, **self.parsed(one_off)))
        self.assertEqual(self.db.get_invoice(one_off)['category'], '办公')
        self.assertEqual(self.db.get_invoice(one_off)['category_source'], 'manual')
        self.assertEqual(self.db.get_invoice(self.seed())['category'], '交通')

    def test_unrelated_field_save_does_not_train_or_touch_memory_timestamp(self):
        invoice = self.seed()
        self.assertTrue(self.correct(invoice, '其他', total_amount='12.00'))
        self.assertEqual(self.db.list_seller_category_preferences(), [])
        self.assertTrue(self.correct(invoice, '交通'))
        before = self.db.list_seller_category_preferences()
        self.assertTrue(self.correct(invoice, '交通', buyer_name='Edited buyer'))
        self.assertEqual(self.db.list_seller_category_preferences(), before)

    def test_empty_seller_unclassified_and_pending_evidence_never_train(self):
        for fields, category in [({'seller_name': ''}, '交通'), ({}, '未分类'), ({}, ''),
                                 ({'invoice_type': '待关联证明材料'}, '交通'),
                                 ({'parse_note': '待关联证明材料'}, '交通')]:
            with self.subTest(fields=fields, category=category):
                self.assertTrue(self.correct(self.seed(**fields), category))
        self.assertEqual(self.db.list_seller_category_preferences(), [])

    def test_pending_or_failed_parses_do_not_receive_merchant_memory(self):
        self.assertTrue(self.correct(self.seed(), '交通'))
        for fields in [{'parse_success': 0}, {'parse_success': None},
                       {'invoice_type': '待关联证明材料'}, {'parse_note': '待关联证明材料'}]:
            with self.subTest(fields=fields):
                row = self.db.get_invoice(self.seed(**fields))
                self.assertEqual(row['category'], '其他')
                self.assertEqual(row['category_source'], 'unknown')

    def test_unique_conflict_does_not_learn_or_change_existing_record(self):
        first = self.seed()
        second = self.seed(total_amount='20.00')
        before = self.db.get_invoice(second)
        self.assertFalse(self.correct(second, '交通', invoice_number=self.db.get_invoice(first)['invoice_number'],
                                      total_amount='10.00'))
        self.assertEqual(self.db.last_error, 'unique_conflict')
        self.assertEqual(self.db.get_invoice(second), before)
        self.assertEqual(self.db.list_seller_category_preferences(), [])

    def test_learning_write_failure_rolls_back_fields_and_preserves_other_memory(self):
        invoice = self.seed()
        self.assertTrue(self.correct(invoice, '交通'))
        before = self.db.get_invoice(invoice)
        memory = self.db.list_seller_category_preferences()
        self.db._conn.execute(
            "CREATE TRIGGER fail_learning BEFORE UPDATE ON seller_category_preferences "
            "BEGIN SELECT RAISE(ABORT, 'synthetic learning failure'); END"
        )
        self.db._conn.commit()
        self.assertFalse(self.correct(invoice, '办公', total_amount='30.00'))
        self.assertEqual(self.db.last_error, 'write_failed')
        self.assertEqual(self.db.get_invoice(invoice), before)
        self.assertEqual(self.db.list_seller_category_preferences(), memory)
        self.assertFalse(self.db._conn.in_transaction)

    def test_manual_save_does_not_commit_unrelated_outer_transaction(self):
        invoice = self.seed()
        self.db._conn.execute("UPDATE invoices SET confirmed_note='Uncommitted' WHERE id=?", (invoice,))
        self.assertTrue(self.correct(invoice, '交通'))
        self.assertTrue(self.db._conn.in_transaction)
        self.db._conn.rollback()
        self.assertEqual(self.db.get_invoice(invoice)['category'], '其他')
        self.assertEqual(self.db.get_invoice(invoice)['confirmed_note'], 'Original note')
        self.assertEqual(self.db.list_seller_category_preferences(), [])

    def test_latest_correction_changes_future_invoices_not_old_choices(self):
        old = self.seed()
        self.assertTrue(self.correct(old, '交通'))
        remembered = self.seed()
        self.assertTrue(self.correct(old, '办公'))
        self.assertEqual(self.db.get_invoice(remembered)['category'], '交通')
        self.assertEqual(self.db.get_invoice(self.seed())['category'], '办公')

    def test_forgetting_restores_rules_and_keeps_existing_manual_choices(self):
        invoice = self.seed()
        self.assertTrue(self.correct(invoice, '交通'))
        before = self.db.get_invoice(invoice)
        self.assertEqual(self.db.forget_seller_categories(['Synthetic Seller', ' Synthetic Seller ']), 1)
        self.assertEqual(self.db.get_invoice(invoice), before)
        self.assertEqual(self.db.get_invoice(self.seed(category='餐饮'))['category'], '餐饮')
        self.assertEqual(self.db.forget_seller_categories(['', 'Missing']), 0)

    def test_memory_overrides_keywords_without_erasing_proof_requirements(self):
        invoice = self.seed(seller_name='Synthetic Taxi')
        self.assertTrue(self.correct(invoice, '办公'))
        categories = {'taxi': {'keywords': ['taxi'], 'extra_name': '行程单'}}
        self.assertEqual(_classify('', '', 'Synthetic Taxi', categories, db=self.db), ('办公', '行程单', True))
        self.assertEqual(_classify('', '', 'Synthetic Taxi', categories), ('出租车', '行程单', True))
        self.assertEqual(_classify('', '', 'Synthetic Taxi', {}, item_name='餐饮服务', db=self.db)[0], '办公')

    def test_preferred_category_can_add_configured_proof_requirement(self):
        invoice = self.seed()
        self.assertTrue(self.correct(invoice, '出租车'))
        categories = {'taxi': {'keywords': ['taxi'], 'extra_name': '行程单'}}
        self.assertEqual(_classify('', '', 'Synthetic Seller', categories, db=self.db), ('出租车', '行程单', True))

    def test_safe_reimport_retains_existing_category_and_manual_override(self):
        old = self.seed(category='餐饮')
        learning = self.seed(seller_name='Synthetic Seller')
        self.assertTrue(self.correct(learning, '交通'))
        params = self.parsed(old, category='交通')
        params.pop('parse_success')
        self.assertTrue(_refresh_invoice_from_parse(self.db, self.db.get_invoice(old), **params))
        self.assertEqual(self.db.get_invoice(old)['category'], '餐饮')
        self.assertTrue(self.correct(old, '办公', remember=False))
        self.assertTrue(_refresh_invoice_from_parse(self.db, self.db.get_invoice(old), **params,
                                                  force_refresh_metadata=True))
        self.assertEqual(self.db.get_invoice(old)['category'], '办公')

    def test_reparse_applies_memory_and_keeps_manual_or_approved_category(self):
        self.assertTrue(self.correct(self.seed(), '交通'))
        automatic = self.seed()
        params = self.parsed(automatic)
        self.assertTrue(reconcile_reparsed_invoice(self.db, automatic, **params).success)
        self.assertEqual(self.db.get_invoice(automatic)['category_source'], 'seller_preference')
        self.assertTrue(self.correct(automatic, '办公', remember=False))
        self.assertTrue(reconcile_reparsed_invoice(self.db, automatic, **params).success)
        self.assertEqual(self.db.get_invoice(automatic)['category'], '办公')
        approved = self.seed(category='Approved choice', review_status='approved', category_source='manual')
        self.assertTrue(reconcile_reparsed_invoice(self.db, approved, **self.parsed(approved)).success)
        self.assertEqual(self.db.get_invoice(approved)['category'], 'Approved choice')

    def test_safe_backfill_keeps_explicitly_cleared_manual_category(self):
        invoice = self.seed()
        self.assertTrue(self.correct(invoice, '', remember=False))
        params = self.parsed(invoice)
        params.pop('parse_success')
        self.assertTrue(_refresh_invoice_from_parse(
            self.db, self.db.get_invoice(invoice), **params, force_refresh_metadata=True,
        ))
        self.assertEqual(self.db.get_invoice(invoice)['category'], '')
        self.assertEqual(self.db.get_invoice(invoice)['category_source'], 'manual')

    def test_download_retry_classifies_previous_unparsed_placeholder_from_memory(self):
        self.assertTrue(self.correct(self.seed(), '交通'))
        invoice = self.seed(parse_success=0, category='其他')
        params = self.parsed(invoice, category='交通')
        params.pop('parse_success')
        self.assertTrue(_refresh_invoice_from_parse(self.db, self.db.get_invoice(invoice), **params))
        row = self.db.get_invoice(invoice)
        self.assertEqual(row['category'], '交通')
        self.assertEqual(row['category_source'], 'seller_preference')
        self.assertEqual(row['parse_success'], 1)
        self.assertEqual(row['confirmed_note'], 'Original note')

    def test_claim_linked_duplicate_reparse_preserves_master_manual_category(self):
        master = self.seed()
        self.assertTrue(self.correct(master, '办公', remember=False))
        claim = self.db.create_claim_group('Synthetic claim')
        self.assertTrue(self.db.add_invoice_to_claim(claim, master))
        current = self.seed()
        result = reconcile_reparsed_invoice(self.db, current, **self.parsed(master))
        self.assertTrue(result.success)
        self.assertEqual(result.target_invoice_id, master)
        self.assertEqual(self.db.get_invoice(master)['category'], '办公')
        self.assertEqual(self.db.get_invoice(master)['category_source'], 'manual')

    def test_new_worker_connection_observes_updates_without_cache(self):
        invoice = self.seed()
        with InvoiceDB(self.path) as worker:
            self.assertEqual(worker.get_seller_category('Synthetic Seller'), '')
            self.assertTrue(self.correct(invoice, '交通'))
            self.assertEqual(worker.get_seller_category('Synthetic Seller'), '交通')
            self.assertTrue(self.correct(invoice, '办公'))
            self.assertEqual(worker.get_seller_category('Synthetic Seller'), '办公')

    def test_database_backup_restores_memory_and_manual_source(self):
        invoice = self.seed()
        self.assertTrue(self.correct(invoice, '交通'))
        self.db.close()
        backup_dir = self.root / 'backups'
        backup = create_verified_database_backup(self.path, backup_dir=backup_dir)
        with InvoiceDB(self.path) as db:
            db.forget_seller_categories(['Synthetic Seller'])
        restore_verified_database_backup(backup, self.path, backup_dir=backup_dir)
        with InvoiceDB(self.path) as db:
            self.assertEqual(db.get_seller_category('Synthetic Seller'), '交通')
            self.assertEqual(db.get_invoice(invoice)['category_source'], 'manual')

    def test_local_import_uses_memory_before_attachment_naming(self):
        self.assertTrue(self.correct(self.seed(), '办公'))
        source = self.root / 'new_invoice.pdf'
        source.write_bytes(b'Synthetic new invoice')
        info = InvoiceInfo(invoice_number='LOCAL-MEMORY', invoice_date='2026-10-02',
                           expense_date='2026-10-02', amount='10.00', total_amount='10.00',
                           seller_name='Synthetic Seller', buyer_name='Synthetic Buyer',
                           invoice_type='电子发票', parse_success=True, item_name='餐饮服务')
        parser = SimpleNamespace(parse_pdf=lambda path: info)
        result = _import_local_pdf(source.name, source, self.db, parser, {}, self.root / 'attachments')
        row = self.db.get_invoice(result.invoice_id)
        self.assertTrue(result.created)
        self.assertEqual(row['category'], '办公')
        self.assertEqual(row['category_source'], 'seller_preference')
        self.assertIn('办公', row['attachment_path'])

    def test_reparse_worker_reads_shared_memory_and_preserves_single_invoice_override(self):
        from scripts.invoice_fetch.gui.reparse_worker import InvoiceReparseRequest, run_invoice_reparse
        self.assertTrue(self.correct(self.seed(), '交通'))
        source = self.root / 'reparse.pdf'
        source.write_bytes(b'Synthetic reparse invoice')
        automatic = self.seed(attachment_path=str(source))
        manual = self.seed(attachment_path=str(source))
        self.assertTrue(self.correct(manual, '办公', remember=False))
        for invoice_id, expected in ((automatic, '交通'), (manual, '办公')):
            with self.subTest(expected=expected):
                request = InvoiceReparseRequest.from_values(
                    invoice_id, (self.db.get_invoice(invoice_id),), self.path, self.root, {},
                )
                info = InvoiceInfo(**{key: value for key, value in self.parsed(invoice_id).items()
                                     if key in InvoiceInfo.__dataclass_fields__})
                parser = SimpleNamespace(parse_pdf=lambda path: info)
                with patch('scripts.invoice_fetch.gui.reparse_worker.InvoiceParser', return_value=parser):
                    result = run_invoice_reparse(request)
                self.assertEqual(result['success_count'], 1)
                self.assertEqual(self.db.get_invoice(invoice_id)['category'], expected)

    def test_email_attachment_import_uses_memory_and_retains_proof_requirement(self):
        import email.message
        from scripts.invoice_fetch import services
        from scripts.invoice_fetch.attachment_handler import AttachmentHandler
        from scripts.invoice_fetch.mail_fetcher import MailMessage
        merchant = 'Synthetic Taxi'
        self.assertTrue(self.correct(self.seed(seller_name=merchant), '办公'))
        message = email.message.EmailMessage()
        message['Subject'] = 'Synthetic invoice'
        message['From'] = 'billing@example.invalid'
        message['Date'] = 'Thu, 01 Oct 2026 10:00:00 +0000'
        message.add_attachment(b'%PDF- Synthetic invoice', maintype='application', subtype='pdf', filename='invoice.pdf')
        info = InvoiceInfo(invoice_number='MAIL-MEMORY', invoice_date='2026-10-01',
                           total_amount='10.00', seller_name=merchant, invoice_type='电子发票', parse_success=True)
        parser = SimpleNamespace(parse_pdf=lambda path: info)
        downloader = SimpleNamespace(download_from_email=lambda *args, **kwargs: [])
        categories = {'taxi': {'keywords': ['taxi'], 'extra_name': '行程单'}}
        with patch.object(services, 'RUNTIME_DIR', self.root):
            result = services._process_email(
                MailMessage(uid=71, raw_msg=message), AttachmentHandler(self.root / 'attachments'),
                parser, downloader, self.db, categories,
            )
        self.assertEqual(int(result), 1)
        row = self.db.find_invoice_by_number_and_amount('MAIL-MEMORY', '10.00')
        self.assertEqual(row['category'], '办公')
        self.assertEqual(row['category_source'], 'seller_preference')
        self.assertEqual(row['missing_extra'], 1)
        self.assertIn('办公', row['attachment_path'])


if __name__ == '__main__':
    unittest.main()
