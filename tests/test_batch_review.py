import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.batch_review import (
    apply_batch_approval, apply_batch_ignore, batch_amount_summary,
    prepare_batch_approval, prepare_batch_ignore,
)
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.review_query import ReviewColumnFilter, ReviewQuery


class BatchReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root / 'original.xml'
        self.original.write_text('<invoice>synthetic</invoice>', encoding='utf-8')
        self.db = InvoiceDB(self.root / 'test.db')
        self.addCleanup(self.db.close)
        self.config = {'reimbursement': {'strict_buyer_check': True, 'buyer_name': 'TargetCorp'}}
        self.counter = 0

    def add(self, **fields):
        self.counter += 1
        invoice_id = self.db.insert_invoice({
            'invoice_number': f'SYN-{self.counter}', 'seller_name': 'Synthetic Seller',
            'buyer_name': 'TargetCorp', 'invoice_date': '2026-07-01', 'total_amount': '10.00',
            'attachment_path': str(self.original), 'parse_success': 1, 'review_status': 'to_review',
            'category': '交通', 'confirmed_note': f'Personal note {self.counter}', **fields,
        })
        self.assertIsNotNone(invoice_id)
        return invoice_id

    def plan(self, ids):
        return prepare_batch_approval(self.db, ids, self.config, self.root)

    def apply(self, plan):
        return apply_batch_approval(self.db, plan, self.config, self.root)

    def test_approval_deduplicates_ids_preserves_notes_and_timestamps(self):
        first, second = self.add(), self.add()
        before = {i: self.db.get_invoice(i) for i in (first, second)}
        plan = self.plan([first, first, second])
        self.assertEqual(plan.requested_ids, (first, second))
        self.assertTrue(all(row['review_status'] == 'to_review' for row in before.values()))
        result = self.apply(plan)
        self.assertEqual(result.changed_ids, (first, second))
        for i in (first, second):
            row = self.db.get_invoice(i)
            self.assertEqual(row['review_status'], 'approved')
            self.assertEqual(row['confirmed_note'], before[i]['confirmed_note'])
            self.assertTrue(row['confirmed_at'])
        self.assertFalse(self.db._conn.in_transaction)
        again = self.apply(plan)
        self.assertEqual(again.changed_ids, ())
        self.assertEqual(len(again.skipped), 2)

    def test_anomalies_are_skipped_without_overwriting_other_states(self):
        clean = self.add()
        cases = [
            ({'buyer_name': 'WrongCorp'}, '购买方或税号异常'),
            ({'missing_extra': 1}, '缺证明材料'),
            ({'extra_paths': ['missing.xml']}, '证明材料不可用'),
            ({'attachment_path': 'missing.xml'}, '原件缺失或不可用'),
            ({'amount': '10', 'tax_amount': '3', 'total_amount': '10'}, '税前金额 + 税额与价税合计不一致（容差 0.01 元）'),
            ({'buyer_tax_id': '123', 'buyer_tax_id_type': 'uscc'}, '购买方或税号异常'),
            ({'parse_success': 0}, '解析结果需逐张核对'),
            ({'expense_date': '2026-02-31'}, '费用日期缺失或无效'),
            ({'total_amount': 'NaN'}, '金额缺失或无效'),
            ({'invoice_number': ''}, '票号缺失，需逐张确认'),
            ({'seller_name': ''}, '销售方缺失'),
            ({'is_deleted': 1}, '记录已删除'),
            ({'review_status': 'approved'}, '不是待审核状态'),
            ({'review_status': 'ignored'}, '不是待审核状态'),
            ({'review_status': 'error'}, '不是待审核状态'),
        ]
        blocked = [(self.add(**fields), reason) for fields, reason in cases]
        before = {i: self.db.get_invoice(i, include_deleted=True) for i, _ in blocked}
        plan = self.plan([clean, *(i for i, _ in blocked), 99999])
        self.assertEqual(plan.eligible_ids, (clean,))
        skipped = {item.invoice_id: item.reasons for item in plan.skipped}
        for i, reason in blocked:
            with self.subTest(reason=reason):
                self.assertIn(reason, skipped[i])
        self.assertEqual(skipped[99999], ('记录不存在',))
        self.apply(plan)
        for i, _ in blocked:
            row = self.db.get_invoice(i, include_deleted=True)
            self.assertEqual(row['review_status'], before[i]['review_status'])
            self.assertEqual(row['confirmed_note'], before[i]['confirmed_note'])

    def test_unknown_legacy_tax_fields_are_not_assumed_invalid(self):
        old = self.add(buyer_tax_id=None, tax_amount=None, tax_rate=None, amount=None)
        self.assertEqual(self.plan([old]).eligible_ids, (old,))

    def test_pending_evidence_cannot_enter_batch_approval(self):
        evidence = self.add(invoice_number='', seller_name='', total_amount='',
                            invoice_type='待关联证明材料', parse_success=0)
        plan = self.plan([evidence])
        self.assertEqual(plan.eligible_ids, ())
        self.assertEqual(plan.skipped[0].reasons, ('待关联证明材料',))

    def test_duplicate_flags_protect_both_pending_receipts_and_duplicate_numbers(self):
        first = self.add(invoice_number='SAME', total_amount='10')
        second = self.add(invoice_number='SAME', total_amount='11')
        left, right = self.add(invoice_number=''), self.add(invoice_number='')
        plan = self.plan([first, second, left, right])
        self.assertEqual(plan.eligible_ids, ())
        reasons = {item.invoice_id: item.reasons for item in plan.skipped}
        self.assertIn('票号重复', reasons[first])
        self.assertIn('票号重复', reasons[second])
        self.assertIn('疑似重复待复核', reasons[left])
        self.assertIn('疑似重复待复核', reasons[right])
        candidate = self.db.list_duplicate_candidates()[0]
        self.db.resolve_duplicate_candidate(candidate['id'], 'distinct')
        self.db.refresh_duplicate_candidates()
        flags = self.db.review_duplicate_flags()
        self.assertNotIn(left, flags)
        self.assertNotIn(right, flags)

    def test_recheck_protects_changed_deleted_missing_and_now_invalid_records(self):
        ids = [self.add() for _ in range(6)]
        plan = self.plan(ids)
        self.db.update_invoice_note(ids[1], 'Edited during confirmation')
        self.db._conn.execute('UPDATE invoices SET is_deleted=1 WHERE id=?', (ids[2],))
        self.db._conn.execute('DELETE FROM invoices WHERE id=?', (ids[3],))
        self.db._conn.execute("UPDATE invoices SET buyer_name='WrongCorp' WHERE id=?", (ids[4],))
        self.db._conn.execute("UPDATE invoices SET review_status='error' WHERE id=?", (ids[5],))
        self.db._conn.commit()
        result = self.apply(plan)
        self.assertEqual(result.changed_ids, (ids[0],))
        self.assertEqual(len(result.skipped), 5)
        self.assertEqual(self.db.get_invoice(ids[1])['confirmed_note'], 'Edited during confirmation')
        self.assertEqual(self.db.get_invoice(ids[5])['review_status'], 'error')

    def test_new_duplicate_and_missing_original_are_checked_at_commit(self):
        first = self.add(invoice_number='MATCH')
        original = self.root / 'separate.xml'
        original.write_text('<invoice/>', encoding='utf-8')
        second = self.add(attachment_path=str(original))
        plan = self.plan([first, second])
        self.add(invoice_number='MATCH', total_amount='11')
        original.unlink()
        result = self.apply(plan)
        self.assertEqual(result.changed_ids, ())
        self.assertEqual(len(result.skipped), 2)

    def test_fixed_skipped_and_new_rows_are_outside_original_consent(self):
        clean, bad = self.add(), self.add(missing_extra=1)
        plan = self.plan([clean, bad])
        self.db._conn.execute('UPDATE invoices SET missing_extra=0 WHERE id=?', (bad,))
        self.db._conn.commit()
        new = self.add()
        self.assertEqual(self.apply(plan).changed_ids, (clean,))
        self.assertEqual(self.db.get_invoice(bad)['review_status'], 'to_review')
        self.assertEqual(self.db.get_invoice(new)['review_status'], 'to_review')

    def test_write_failure_rolls_back_entire_batch(self):
        first, second = self.add(), self.add()
        plan = self.plan([first, second])
        self.db._conn.execute(f"""CREATE TRIGGER fail_batch BEFORE UPDATE OF review_status ON invoices
            WHEN NEW.id={second} AND NEW.review_status='approved'
            BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END""")
        self.db._conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.apply(plan)
        for i in (first, second):
            self.assertEqual(self.db.get_invoice(i)['review_status'], 'to_review')
            self.assertFalse(self.db.get_invoice(i)['confirmed_at'])
        self.assertFalse(self.db._conn.in_transaction)

    def test_commit_failure_cannot_leave_approvals_pending_for_later_commit(self):
        ids = [self.add(), self.add()]
        plan = self.plan(ids)
        connection = self.db._conn
        class FailCommitOnce:
            outer = None
            failed = False
            def __getattr__(self, name):
                return getattr(connection, name)
            def execute(self, sql, *args):
                if self.outer is None and sql.startswith('SAVEPOINT '):
                    self.outer = sql.split()[1]
                if sql == 'RELEASE ' + str(self.outer) and not self.failed:
                    self.failed = True
                    raise sqlite3.OperationalError('synthetic commit failure')
                return connection.execute(sql, *args)
        self.db._conn = FailCommitOnce()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.apply(plan)
        finally:
            self.db._conn = connection
        self.assertFalse(connection.in_transaction)
        self.assertTrue(all(self.db.get_invoice(i)['review_status'] == 'to_review' for i in ids))
        connection.commit()
        self.assertTrue(all(self.db.get_invoice(i)['review_status'] == 'to_review' for i in ids))

    def test_duplicate_reconciliation_cannot_commit_outer_transaction(self):
        receipt = self.add(invoice_number='')
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with self.db.batch_review_transaction():
                self.db._conn.execute("UPDATE invoices SET seller_name='Changed' WHERE id=?", (receipt,))
                self.db.refresh_duplicate_candidates()
                raise RuntimeError('rollback')
        row = self.db.get_invoice(receipt)
        self.assertEqual(row['seller_name'], 'Synthetic Seller')
        self.assertIsNone(row['soft_fingerprint'])

    def test_batch_does_not_commit_or_discard_unrelated_pending_writes(self):
        invoice = self.add()
        plan = self.plan([invoice])
        self.db._conn.execute("UPDATE invoices SET confirmed_note='Pending unrelated edit' WHERE id=?", (invoice,))
        try:
            with self.assertRaisesRegex(RuntimeError, 'pending writes'):
                self.apply(plan)
            self.assertTrue(self.db._conn.in_transaction)
            self.assertEqual(self.db.get_invoice(invoice)['review_status'], 'to_review')
            self.assertEqual(self.db.get_invoice(invoice)['confirmed_note'], 'Pending unrelated edit')
        finally:
            self.db._conn.rollback()

    def test_full_filter_ids_ignore_paging_and_keep_scope_and_predicates(self):
        wanted = [self.add() for _ in range(110)]
        self.add(category='办公')
        self.add(review_status='approved')
        query = ReviewQuery(status='to_review', limit=50, column_filters=(ReviewColumnFilter('category', ('交通',)),))
        self.assertEqual(len(self.db.list_review_invoices(query)), 50)
        self.assertEqual(set(self.db.list_review_invoice_ids(query)), set(wanted))
        scoped = ReviewQuery(status='to_review', invoice_ids=tuple(wanted[:3]), limit=1)
        self.assertEqual(set(self.db.list_review_invoice_ids(scoped)), set(wanted[:3]))

    def test_batch_ignore_preserves_notes_and_rechecks_snapshot(self):
        first, second = self.add(review_status='approved'), self.add()
        note = self.db.get_invoice(first)['confirmed_note']
        plan = prepare_batch_ignore(self.db, [first, second])
        self.db.update_invoice_note(second, 'New note')
        result = apply_batch_ignore(self.db, plan)
        self.assertEqual(result.changed_ids, (first,))
        self.assertEqual(self.db.get_invoice(first)['review_status'], 'ignored')
        self.assertEqual(self.db.get_invoice(first)['confirmed_note'], note)
        self.assertEqual(self.db.get_invoice(second)['review_status'], 'to_review')

    def test_amount_summary_uses_separate_currency_totals_and_flags_invalid(self):
        text = batch_amount_summary([{'total_amount': '0.10'}, {'total_amount': '0.20'},
                                     {'total_amount': '3', 'currency': 'USD'}, {'total_amount': 'NaN'}])
        self.assertIn('¥0.30', text)
        self.assertIn('USD 3.00', text)
        self.assertIn('1 张金额待核对', text)


if __name__ == '__main__':
    unittest.main()
