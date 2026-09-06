from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.reparse_reconciliation import (
    MERGED_INTO_CLAIMED_DUPLICATE,
    REPLACED_UNLINKED_DUPLICATE,
    UPDATED_CURRENT,
    reconcile_reparsed_invoice,
)


class ReparseAtomicConsistencyTests(unittest.TestCase):
    def _record(
        self,
        number: str,
        total: str,
        seller: str,
        *,
        buyer: str = "旧购买方",
        category: str = "旧分类",
    ) -> dict:
        return {
            "mailbox_key": "test",
            "invoice_number": number,
            "invoice_code": "OLD-CODE",
            "invoice_date": "2026-09-01",
            "expense_date": "2026-09-01",
            "date_source": "invoice_date",
            "amount": total,
            "total_amount": total,
            "seller_name": seller,
            "buyer_name": buyer,
            "invoice_type": "电子发票",
            "category": category,
            "has_extra": False,
            "extra_type": "",
            "missing_extra": False,
            "parse_success": True,
            "parse_note": "old",
            "attachment_path": "attachments/test.pdf",
            "extra_paths": [],
            "download_url": "",
            "item_name": "",
        }

    def _parsed(self, number: str, total: str, seller: str) -> dict:
        return {
            "invoice_number": number,
            "invoice_code": "NEW-CODE",
            "invoice_date": "2026-09-02",
            "amount": total,
            "total_amount": total,
            "seller_name": seller,
            "buyer_name": "新购买方",
            "invoice_type": "电子发票",
            "category": "交通",
            "has_extra": False,
            "extra_type": "",
            "missing_extra": False,
            "parse_success": True,
            "parse_note": "重新解析",
            "item_name": "行程",
            "expense_date": "2026-09-03",
            "date_source": "travel_date",
        }

    def _invoice(self, db_path: Path, invoice_id: int) -> dict | None:
        with InvoiceDB(db_path) as db:
            return db.get_invoice(invoice_id, include_deleted=True)

    def test_updates_current_invoice_without_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "reparse.db"
            with InvoiceDB(db_path) as db:
                current_id = db.insert_invoice(self._record("OLD-1", "10.00", "旧商户"))
                self.assertIsNotNone(current_id)

                result = reconcile_reparsed_invoice(
                    db,
                    int(current_id),
                    **self._parsed("NEW-1", "12.50", "新商户"),
                )

                self.assertTrue(result.success)
                self.assertEqual(result.action, UPDATED_CURRENT)
                self.assertEqual(result.target_invoice_id, current_id)
                self.assertIsNone(result.duplicate_invoice_id)

            persisted = self._invoice(db_path, int(current_id))
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["invoice_number"], "NEW-1")
            self.assertEqual(persisted["buyer_name"], "新购买方")
            self.assertEqual(persisted["category"], "交通")
            self.assertEqual(persisted["is_deleted"], 0)

    def test_unlinked_duplicate_is_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "reparse.db"
            with InvoiceDB(db_path) as db:
                current_id = db.insert_invoice(self._record("OLD-2", "20.00", "当前商户"))
                duplicate_id = db.insert_invoice(self._record("DUP-2", "22.00", "目标商户"))
                self.assertIsNotNone(current_id)
                self.assertIsNotNone(duplicate_id)

                result = reconcile_reparsed_invoice(
                    db,
                    int(current_id),
                    **self._parsed("DUP-2", "22.00", "目标商户"),
                )

                self.assertTrue(result.success)
                self.assertEqual(result.action, REPLACED_UNLINKED_DUPLICATE)
                self.assertEqual(result.target_invoice_id, current_id)
                self.assertEqual(result.duplicate_invoice_id, duplicate_id)

            with InvoiceDB(db_path) as verify:
                current = verify.get_invoice(int(current_id), include_deleted=True)
                duplicate = verify.get_invoice(int(duplicate_id), include_deleted=True)
                self.assertIsNotNone(current)
                self.assertEqual(current["invoice_number"], "DUP-2")
                self.assertEqual(current["category"], "交通")
                self.assertIsNone(duplicate)

    def test_unlinked_duplicate_delete_rolls_back_when_metadata_update_fails(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "reparse.db"
            with InvoiceDB(db_path) as db:
                current_id = db.insert_invoice(self._record("OLD-3", "30.00", "当前商户"))
                duplicate_id = db.insert_invoice(self._record("DUP-3", "33.00", "目标商户"))
                self.assertIsNotNone(current_id)
                self.assertIsNotNone(duplicate_id)
                db._conn.execute(
                    "CREATE TRIGGER fail_reparse_metadata BEFORE UPDATE ON invoices "
                    f"WHEN OLD.id = {int(current_id)} AND NEW.invoice_number = 'DUP-3' "
                    "BEGIN SELECT RAISE(ABORT, 'injected metadata failure'); END"
                )
                db._conn.commit()

                result = reconcile_reparsed_invoice(
                    db,
                    int(current_id),
                    **self._parsed("DUP-3", "33.00", "目标商户"),
                )

                self.assertFalse(result.success)
                self.assertIn(result.error, {"integrity_error", "db_error"})

            with InvoiceDB(db_path) as verify:
                current = verify.get_invoice(int(current_id), include_deleted=True)
                duplicate = verify.get_invoice(int(duplicate_id), include_deleted=True)
                self.assertIsNotNone(current)
                self.assertIsNotNone(duplicate)
                self.assertEqual(current["invoice_number"], "OLD-3")
                self.assertEqual(current["category"], "旧分类")
                self.assertEqual(duplicate["invoice_number"], "DUP-3")

    def test_claim_linked_duplicate_keeps_master_and_soft_deletes_current(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "reparse.db"
            with InvoiceDB(db_path) as db:
                current_id = db.insert_invoice(self._record("OLD-4", "40.00", "当前商户"))
                master_id = db.insert_invoice(self._record("DUP-4", "44.00", "目标商户"))
                self.assertIsNotNone(current_id)
                self.assertIsNotNone(master_id)
                claim_id = db.create_claim_group("差旅报销")
                self.assertTrue(db.add_invoice_to_claim(claim_id, int(master_id)))

                result = reconcile_reparsed_invoice(
                    db,
                    int(current_id),
                    **self._parsed("DUP-4", "44.00", "目标商户"),
                )

                self.assertTrue(result.success)
                self.assertEqual(result.action, MERGED_INTO_CLAIMED_DUPLICATE)
                self.assertEqual(result.target_invoice_id, master_id)
                self.assertEqual(result.duplicate_invoice_id, master_id)

            with InvoiceDB(db_path) as verify:
                master = verify.get_invoice(int(master_id), include_deleted=True)
                current = verify.get_invoice(int(current_id), include_deleted=True)
                self.assertIsNotNone(master)
                self.assertIsNotNone(current)
                self.assertEqual(master["buyer_name"], "新购买方")
                self.assertEqual(master["category"], "交通")
                self.assertEqual(master["is_deleted"], 0)
                self.assertEqual(current["is_deleted"], 1)
                self.assertEqual(verify.count_claim_links(int(master_id)), 1)
                claim_invoice_ids = {
                    row["id"] for row in verify.get_claim_invoices(claim_id)
                }
                self.assertIn(int(master_id), claim_invoice_ids)

    def test_claim_linked_master_update_rolls_back_when_soft_delete_fails(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "reparse.db"
            with InvoiceDB(db_path) as db:
                current_id = db.insert_invoice(self._record("OLD-5", "50.00", "当前商户"))
                master_id = db.insert_invoice(self._record("DUP-5", "55.00", "目标商户"))
                self.assertIsNotNone(current_id)
                self.assertIsNotNone(master_id)
                claim_id = db.create_claim_group("差旅报销")
                self.assertTrue(db.add_invoice_to_claim(claim_id, int(master_id)))
                db._conn.execute(
                    "CREATE TRIGGER fail_reparse_soft_delete "
                    "BEFORE UPDATE OF is_deleted ON invoices "
                    f"WHEN OLD.id = {int(current_id)} AND NEW.is_deleted = 1 "
                    "BEGIN SELECT RAISE(ABORT, 'injected soft delete failure'); END"
                )
                db._conn.commit()

                result = reconcile_reparsed_invoice(
                    db,
                    int(current_id),
                    **self._parsed("DUP-5", "55.00", "目标商户"),
                )

                self.assertFalse(result.success)
                self.assertIn(result.error, {"integrity_error", "db_error"})

            with InvoiceDB(db_path) as verify:
                master = verify.get_invoice(int(master_id), include_deleted=True)
                current = verify.get_invoice(int(current_id), include_deleted=True)
                self.assertIsNotNone(master)
                self.assertIsNotNone(current)
                self.assertEqual(master["buyer_name"], "旧购买方")
                self.assertEqual(master["category"], "旧分类")
                self.assertEqual(current["is_deleted"], 0)
                self.assertEqual(verify.count_claim_links(int(master_id)), 1)
                claim_invoice_ids = {
                    row["id"] for row in verify.get_claim_invoices(claim_id)
                }
                self.assertIn(int(master_id), claim_invoice_ids)

    def test_unique_conflict_rolls_back_without_partial_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "reparse.db"
            with InvoiceDB(db_path) as db:
                current_id = db.insert_invoice(self._record("OLD-6", "60.00", "当前商户"))
                hidden_id = db.insert_invoice(self._record("DUP-6", "66.00", "目标商户"))
                self.assertIsNotNone(current_id)
                self.assertIsNotNone(hidden_id)
                self.assertTrue(db.soft_delete_invoice(int(hidden_id)))

                result = reconcile_reparsed_invoice(
                    db,
                    int(current_id),
                    **self._parsed("DUP-6", "66.00", "目标商户"),
                )

                self.assertFalse(result.success)
                self.assertEqual(result.error, "unique_conflict")

            with InvoiceDB(db_path) as verify:
                current = verify.get_invoice(int(current_id), include_deleted=True)
                hidden = verify.get_invoice(int(hidden_id), include_deleted=True)
                self.assertIsNotNone(current)
                self.assertIsNotNone(hidden)
                self.assertEqual(current["invoice_number"], "OLD-6")
                self.assertEqual(current["category"], "旧分类")
                self.assertEqual(current["is_deleted"], 0)
                self.assertEqual(hidden["invoice_number"], "DUP-6")
                self.assertEqual(hidden["is_deleted"], 1)

    def test_later_invoice_failure_does_not_roll_back_prior_invoice(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "reparse.db"
            with InvoiceDB(db_path) as db:
                first_id = db.insert_invoice(self._record("OLD-A", "70.00", "商户A"))
                second_id = db.insert_invoice(self._record("OLD-B", "80.00", "商户B"))
                duplicate_id = db.insert_invoice(self._record("DUP-B", "88.00", "目标B"))
                self.assertIsNotNone(first_id)
                self.assertIsNotNone(second_id)
                self.assertIsNotNone(duplicate_id)

                first = reconcile_reparsed_invoice(
                    db,
                    int(first_id),
                    **self._parsed("NEW-A", "77.00", "目标A"),
                )
                self.assertTrue(first.success)

                db._conn.execute(
                    "CREATE TRIGGER fail_second_reparse BEFORE UPDATE ON invoices "
                    f"WHEN OLD.id = {int(second_id)} AND NEW.invoice_number = 'DUP-B' "
                    "BEGIN SELECT RAISE(ABORT, 'injected second failure'); END"
                )
                db._conn.commit()

                second = reconcile_reparsed_invoice(
                    db,
                    int(second_id),
                    **self._parsed("DUP-B", "88.00", "目标B"),
                )
                self.assertFalse(second.success)

            with InvoiceDB(db_path) as verify:
                first = verify.get_invoice(int(first_id), include_deleted=True)
                second = verify.get_invoice(int(second_id), include_deleted=True)
                duplicate = verify.get_invoice(int(duplicate_id), include_deleted=True)
                self.assertEqual(first["invoice_number"], "NEW-A")
                self.assertEqual(first["category"], "交通")
                self.assertEqual(second["invoice_number"], "OLD-B")
                self.assertEqual(second["category"], "旧分类")
                self.assertIsNotNone(duplicate)
                self.assertEqual(duplicate["invoice_number"], "DUP-B")


class ReparseAtomicBoundaryTests(unittest.TestCase):
    @staticmethod
    def _calls_in_function(path: Path, function_name: str) -> list[str]:
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        target = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        )
        calls = []
        for node in ast.walk(target):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
        return calls

    def test_async_reparse_uses_one_atomic_reconciliation_write_boundary(self):
        root = Path(__file__).resolve().parents[1]
        gui_calls = self._calls_in_function(
            root / "scripts" / "invoice_fetch" / "gui" / "app.py",
            "_reparse_selected_invoices",
        )
        worker_calls = self._calls_in_function(
            root / "scripts" / "invoice_fetch" / "gui" / "reparse_worker.py",
            "run_invoice_reparse",
        )
        legacy_writes = {
            "find_invoice_by_unique_fields",
            "count_claim_links",
            "delete_invoice_permanently",
            "update_invoice_parsed_metadata",
            "soft_delete_invoice",
        }

        self.assertEqual(gui_calls.count("reconcile_reparsed_invoice"), 0)
        self.assertTrue(legacy_writes.isdisjoint(gui_calls))
        self.assertEqual(worker_calls.count("reconcile_reparsed_invoice"), 1)
        self.assertTrue(legacy_writes.isdisjoint(worker_calls))


if __name__ == "__main__":
    unittest.main()
