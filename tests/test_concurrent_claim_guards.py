"""Concurrency guarantees for claim assignment, export finalization and edits."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from scripts.invoice_fetch.db import InvoiceDB, claim_members_digest


class ConcurrentClaimGuardTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.path = Path(self._temp.name) / "guards.db"
        with InvoiceDB(self.path) as db:
            self.claim_a = db.create_claim_group("A")
            self.claim_b = db.create_claim_group("B")
            self.invoice = db.insert_invoice({
                "invoice_number": "GUARD-001",
                "total_amount": "10.00",
                "seller_name": "Synthetic",
                "review_status": "to_review",
            })

    def _add_approved(self, db, number: str, **values) -> int:
        return db.insert_invoice({
            "invoice_number": number,
            "total_amount": "5.00",
            "seller_name": "Synthetic",
            "review_status": "approved",
            **values,
        })

    def test_concurrent_cross_claim_assignment_admits_only_one_connection(self):
        barrier = threading.Barrier(2)
        results: list[bool] = []
        results_lock = threading.Lock()

        def worker(claim_id: int) -> None:
            db = InvoiceDB(self.path)
            try:
                barrier.wait(timeout=5)
                accepted = db.add_invoice_to_claim(claim_id, self.invoice)
                with results_lock:
                    results.append(accepted)
            finally:
                db.close()

        threads = [
            threading.Thread(target=worker, args=(claim_id,))
            for claim_id in (self.claim_a, self.claim_b)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual(sorted(results), [False, True])
        with InvoiceDB(self.path) as db:
            self.assertEqual(db.count_claim_links(self.invoice), 1)

    def _snapshot(self, db, claim_id: int):
        rows = db.get_claim_invoices(claim_id)
        return rows, tuple(int(row["id"]) for row in rows), claim_members_digest(rows)

    def test_export_commit_rejects_membership_change_during_generation(self):
        with InvoiceDB(self.path) as db:
            first = self._add_approved(db, "TOCTOU-1")
            self.assertTrue(db.add_invoice_to_claim(self.claim_a, first))
            _, member_ids, digest = self._snapshot(db, self.claim_a)

            with InvoiceDB(self.path) as other:
                second = self._add_approved(other, "TOCTOU-2")
                self.assertTrue(other.add_invoice_to_claim(self.claim_a, second))

            with self.assertRaisesRegex(ValueError, "报销组成员已变化"):
                db.add_export_run(
                    self.claim_a,
                    "exports/toc-tou",
                    "generic_excel",
                    len(member_ids),
                    invoice_ids=member_ids,
                    expected_member_ids=member_ids,
                    expected_digest=digest,
                )
            self.assertEqual(db.list_export_runs(self.claim_a), [])

    def test_export_commit_rejects_removed_member_during_generation(self):
        with InvoiceDB(self.path) as db:
            keep = self._add_approved(db, "TOCTOU-KEEP")
            drop = self._add_approved(db, "TOCTOU-DROP")
            db.add_invoice_to_claim(self.claim_a, keep)
            db.add_invoice_to_claim(self.claim_a, drop)
            _, member_ids, digest = self._snapshot(db, self.claim_a)

            with InvoiceDB(self.path) as other:
                self.assertTrue(other.remove_invoice_from_claim(self.claim_a, drop))

            with self.assertRaisesRegex(ValueError, "报销组成员已变化"):
                db.add_export_run(
                    self.claim_a,
                    "exports/toc-tou-remove",
                    "generic_excel",
                    len(member_ids),
                    invoice_ids=member_ids,
                    expected_member_ids=member_ids,
                    expected_digest=digest,
                )

    def test_export_commit_rejects_field_edit_during_generation(self):
        with InvoiceDB(self.path) as db:
            invoice = self._add_approved(db, "TOCTOU-EDIT")
            db.add_invoice_to_claim(self.claim_a, invoice)
            _, member_ids, digest = self._snapshot(db, self.claim_a)

            with InvoiceDB(self.path) as other:
                self.assertTrue(other.update_invoice_fields(
                    invoice, "TOCTOU-EDIT", "2026-10-20", "Synthetic", "999.00", "其他",
                ))

            with self.assertRaisesRegex(ValueError, "报销组内容已变化"):
                db.add_export_run(
                    self.claim_a,
                    "exports/toc-tou-edit",
                    "generic_excel",
                    len(member_ids),
                    invoice_ids=member_ids,
                    expected_member_ids=member_ids,
                    expected_digest=digest,
                )

    def test_export_commit_accepts_an_unchanged_claim(self):
        with InvoiceDB(self.path) as db:
            invoice = self._add_approved(db, "TOCTOU-OK")
            db.add_invoice_to_claim(self.claim_a, invoice)
            _, member_ids, digest = self._snapshot(db, self.claim_a)

            export_run_id = db.add_export_run(
                self.claim_a,
                "exports/unchanged",
                "generic_excel",
                len(member_ids),
                invoice_ids=member_ids,
                expected_member_ids=member_ids,
                expected_digest=digest,
            )

            self.assertGreater(export_run_id, 0)
            self.assertEqual(db.get_claim_group(self.claim_a)["status"], "exported")
            self.assertEqual(len(db.list_export_runs(self.claim_a)), 1)

    def _run_with_claim_locked_by_other_connection(self, update_call):
        with InvoiceDB(self.path) as db:
            invoice = self._add_approved(db, "LOCK-1")
            db.add_invoice_to_claim(self.claim_a, invoice)

        export_started = threading.Event()

        def mark_exported() -> None:
            db = InvoiceDB(self.path)
            try:
                with db._atomic_savepoint():
                    db._conn.execute("UPDATE claim_groups SET id=id WHERE 0")
                    db._conn.execute(
                        "UPDATE claim_groups SET status='exported' WHERE id=?",
                        (self.claim_a,),
                    )
                    export_started.set()
                    time.sleep(0.5)
            finally:
                db.close()

        worker = threading.Thread(target=mark_exported)
        worker.start()
        self.assertTrue(export_started.wait(timeout=5))

        db = InvoiceDB(self.path)
        try:
            accepted = update_call(db, invoice)
        finally:
            db.close()
        worker.join(timeout=10)

        return invoice, accepted

    def test_financial_update_cannot_race_an_export_lock(self):
        invoice, accepted = self._run_with_claim_locked_by_other_connection(
            lambda db, invoice_id: db.update_invoice_financial_fields(
                invoice_id,
                amount="1.00",
                buyer_tax_id=None,
                tax_amount=None,
                tax_rate=None,
                invoice_code="",
            ),
        )
        self.assertFalse(accepted)
        with InvoiceDB(self.path) as db:
            stored = db.get_invoice(invoice)
        self.assertNotEqual(stored["amount"], "1.00")
        self.assertEqual(stored["total_amount"], "5.00")

    def test_reason_update_cannot_race_an_export_lock(self):
        invoice, accepted = self._run_with_claim_locked_by_other_connection(
            lambda db, invoice_id: db.update_invoice_reason(invoice_id, "late edit"),
        )
        self.assertFalse(accepted)
        with InvoiceDB(self.path) as db:
            self.assertIsNone(db.get_invoice(invoice)["custom_reason"])


if __name__ == "__main__":
    unittest.main()
