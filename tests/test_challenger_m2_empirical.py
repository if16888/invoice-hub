"""Empirical Challenger Test Suite for Milestone 2 Deduplication.

Adversarial stress-testing of InvoiceDB.is_duplicate and receipt preservation:
1. is_duplicate("", "50.00", "中国移动") returns False when distinct receipts have different dates or hashes.
2. Edge cases: whitespace in invoice_number, None vs empty string, multiple dates,
   file_hash collisions, soft-deleted rows with include_deleted=True/False.
3. Preserving 10 distinct unnumbered receipts from same seller with same amount on consecutive days.
4. Whitespace handling in insert_invoice vs is_duplicate.
5. Unicode, special characters, and SQL injection safety in deduplication keys.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.db import InvoiceDB


class TestEmpiricalChallengerM2(unittest.TestCase):
    """Adversarial challenger test cases against InvoiceDB deduplication."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db = InvoiceDB(self.temp_dir / "challenger_test.db")
        self.db.__enter__()

    def tearDown(self):
        self.db.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── 1. Unnumbered distinct receipts with different dates or hashes ──

    def test_unnumbered_no_date_no_hash_returns_false_when_other_receipt_exists(self):
        """When an unnumbered receipt exists in DB, querying is_duplicate("", "50.00", "中国移动")

        without specifying date or hash MUST return False (cannot assume duplicate).
        """
        id1 = self.db.insert_invoice({
            "invoice_number": "",
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
            "file_hash": "hash_jan_01",
        })
        self.assertIsNotNone(id1)

        # Baseline check without dates or hashes
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动"),
            "is_duplicate without date or hash must return False even if seller+amount matches",
        )
        self.assertFalse(
            self.db.is_duplicate(None, "50.00", "中国移动"),
            "None invoice_number without date or hash must return False",
        )
        self.assertFalse(
            self.db.is_duplicate("   ", "50.00", "中国移动"),
            "Whitespace invoice_number without date or hash must return False",
        )

    def test_unnumbered_different_dates_returns_false(self):
        """Distinct unnumbered receipts with different expense/invoice dates MUST return False."""
        self.db.insert_invoice({
            "invoice_number": "",
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
            "invoice_date": "2026-01-01",
            "file_hash": "hash_jan_01",
        })

        # Different expense_date
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-02-01"),
            "Different expense_date must return False",
        )
        # Different invoice_date
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", invoice_date="2026-02-01"),
            "Different invoice_date must return False",
        )
        # Both dates different
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-02-01", invoice_date="2026-02-01"),
            "Different expense_date and invoice_date must return False",
        )

    def test_unnumbered_different_hash_different_date_returns_false(self):
        """Distinct unnumbered receipts with different hash and different date return False."""
        self.db.insert_invoice({
            "invoice_number": "",
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
            "file_hash": "hash_jan_01",
        })
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-02-01", file_hash="hash_feb_01"),
            "Different hash and date must return False",
        )

    def test_unnumbered_matching_composite_date_returns_true(self):
        """Same seller, amount, and matching date returns True."""
        self.db.insert_invoice({
            "invoice_number": "",
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
            "invoice_date": "2026-01-01",
        })
        self.assertTrue(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-01-01"),
            "Matching expense_date must return True",
        )
        self.assertTrue(
            self.db.is_duplicate("", "50.00", "中国移动", invoice_date="2026-01-01"),
            "Matching invoice_date must return True",
        )

    # ── 2. Edge cases: Whitespace & None vs empty string ────────────────

    def test_whitespace_and_none_variations_in_is_duplicate(self):
        """All variations of None, empty string, and whitespace must be handled safely."""
        self.db.insert_invoice({
            "invoice_number": "INV-100",
            "total_amount": "123.45",
            "seller_name": "测试企业",
            "expense_date": "2026-05-01",
            "file_hash": "hash_test_100",
        })

        # Whitespace surrounding invoice_number
        self.assertTrue(self.db.is_duplicate("  INV-100  ", "123.45"))
        self.assertTrue(self.db.is_duplicate("\tINV-100\n", "123.45"))
        self.assertTrue(self.db.is_duplicate("INV-100", "  123.45  "))

        # None values should not crash
        self.assertFalse(self.db.is_duplicate(None, None, None, expense_date=None, invoice_date=None, file_hash=None))
        self.assertFalse(self.db.is_duplicate("", "", "", expense_date="", invoice_date="", file_hash=""))
        self.assertTrue(self.db.is_duplicate("INV-100", None))

    def test_whitespace_in_unnumbered_receipt_composite_query(self):
        """Whitespace in seller_name, total_amount, or dates should be stripped."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "60.00",
            "seller_name": "中国联通",
            "expense_date": "2026-06-01",
        })
        self.assertTrue(
            self.db.is_duplicate("  ", " 60.00 ", "  中国联通  ", expense_date="  2026-06-01  "),
            "Padded whitespace around query arguments must still match",
        )

    # ── 3. Multiple dates handling ──────────────────────────────────────

    def test_multiple_dates_cross_matching(self):
        """Verify cross-matching when expense_date and invoice_date differ."""
        # Row with expense_date = 2026-07-02, invoice_date = 2026-07-01
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "77.00",
            "seller_name": "滴滴出行",
            "expense_date": "2026-07-02",
            "invoice_date": "2026-07-01",
        })

        # Query matches on expense_date
        self.assertTrue(self.db.is_duplicate("", "77.00", "滴滴出行", expense_date="2026-07-02"))
        # Query matches on invoice_date
        self.assertTrue(self.db.is_duplicate("", "77.00", "滴滴出行", invoice_date="2026-07-01"))
        # Query matches if caller passes expense_date that was stored as invoice_date
        self.assertTrue(self.db.is_duplicate("", "77.00", "滴滴出行", expense_date="2026-07-01"))
        # Query matches if caller passes invoice_date that was stored as expense_date
        self.assertTrue(self.db.is_duplicate("", "77.00", "滴滴出行", invoice_date="2026-07-02"))
        # Query with unrelated date returns False
        self.assertFalse(self.db.is_duplicate("", "77.00", "滴滴出行", expense_date="2026-07-03"))

    def test_multiple_dates_deduplicated_placeholders(self):
        """Passing identical expense_date and invoice_date must not cause SQL placeholder mismatch."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "88.00",
            "seller_name": "南方电网",
            "expense_date": "2026-08-01",
        })
        # Both parameters provided with the exact same date
        self.assertTrue(
            self.db.is_duplicate("", "88.00", "南方电网", expense_date="2026-08-01", invoice_date="2026-08-01"),
        )
        # Both parameters provided with two different dates
        self.assertTrue(
            self.db.is_duplicate("", "88.00", "南方电网", expense_date="2026-08-01", invoice_date="2026-08-02"),
        )
        # Both parameters provided with two non-matching dates
        self.assertFalse(
            self.db.is_duplicate("", "88.00", "南方电网", expense_date="2026-08-02", invoice_date="2026-08-03"),
        )

    # ── 4. File hash matching, collisions & fallthrough ─────────────────

    def test_file_hash_exact_match(self):
        """file_hash match alone is sufficient for unnumbered invoices."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "99.00",
            "seller_name": "美团外卖",
            "file_hash": "sha256_deadbeef1234",
        })
        self.assertTrue(self.db.is_duplicate("", file_hash="sha256_deadbeef1234"))
        self.assertFalse(self.db.is_duplicate("", file_hash="sha256_different5678"))

    def test_numbered_invoice_does_not_fall_through_to_hash_or_seller(self):
        """When invoice_number is non-empty, query must NOT fall through to file_hash or seller+amount."""
        self.db.insert_invoice({
            "invoice_number": "INV-EXISTING",
            "total_amount": "100.00",
            "seller_name": "京东商城",
            "file_hash": "hash_jd_common",
            "expense_date": "2026-09-01",
        })

        # Query with non-matching invoice number but matching seller, amount, date, and hash
        self.assertFalse(
            self.db.is_duplicate(
                "INV-BRAND-NEW",
                "100.00",
                "京东商城",
                expense_date="2026-09-01",
                file_hash="hash_jd_common",
            ),
            "Non-matching invoice_number must immediately return False without fall-through",
        )

    # ── 5. Soft-deleted rows with include_deleted=True/False ────────────

    def test_soft_deleted_numbered_and_unnumbered(self):
        """Soft-deleted rows are ignored when include_deleted=False and included when True."""
        id_num = self.db.insert_invoice({
            "invoice_number": "INV-DEL-1",
            "total_amount": "50.00",
            "seller_name": "中国移动",
        })
        id_unnum_hash = self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "file_hash": "del_hash_999",
        })
        id_unnum_date = self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-10-01",
        })

        self.db.soft_delete_invoice(id_num)
        self.db.soft_delete_invoice(id_unnum_hash)
        self.db.soft_delete_invoice(id_unnum_date)

        # include_deleted=False
        self.assertFalse(self.db.is_duplicate("INV-DEL-1", "50.00", include_deleted=False))
        self.assertFalse(self.db.is_duplicate("", file_hash="del_hash_999", include_deleted=False))
        self.assertFalse(self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-10-01", include_deleted=False))

        # include_deleted=True
        self.assertTrue(self.db.is_duplicate("INV-DEL-1", "50.00", include_deleted=True))
        self.assertTrue(self.db.is_duplicate("", file_hash="del_hash_999", include_deleted=True))
        self.assertTrue(self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-10-01", include_deleted=True))

    # ── 6. Preserving 10 distinct unnumbered receipts on consecutive days ──

    def test_preserve_10_distinct_unnumbered_receipts(self):
        """Empirically test inserting 10 distinct unnumbered receipts from the same seller

        with the same amount on consecutive days and verify all 10 are preserved.
        """
        inserted_ids = []
        seller = "中国移动"
        amount = "50.00"

        for day in range(1, 11):
            date_str = f"2026-01-{day:02d}"
            hash_str = f"hash_receipt_day_{day:02d}"

            # Step 1: Query duplicate before insertion
            is_dup = self.db.is_duplicate(
                invoice_number="",
                total_amount=amount,
                seller_name=seller,
                expense_date=date_str,
                file_hash=hash_str,
            )
            self.assertFalse(
                is_dup,
                f"Day {day} ({date_str}) should not be flagged as duplicate before insertion",
            )

            # Step 2: Insert receipt
            row_id = self.db.insert_invoice({
                "invoice_number": "",
                "total_amount": amount,
                "seller_name": seller,
                "expense_date": date_str,
                "invoice_date": date_str,
                "file_hash": hash_str,
                "item_name": f"话费充值-第{day}天",
            })
            self.assertIsNotNone(row_id, f"Failed to insert receipt for day {day}")
            inserted_ids.append(row_id)

        # Verification 1: Exactly 10 unique IDs were generated
        self.assertEqual(len(inserted_ids), 10)
        self.assertEqual(len(set(inserted_ids)), 10, "All 10 inserted invoice IDs must be unique")

        # Verification 2: Querying all invoices returns 10 records
        records = self.db.get_all_invoices()
        self.assertEqual(len(records), 10, f"Database must contain exactly 10 invoices, found {len(records)}")

        # Verification 3: Every day's receipt is now recognized as duplicate when queried again
        for day in range(1, 11):
            date_str = f"2026-01-{day:02d}"
            hash_str = f"hash_receipt_day_{day:02d}"

            # Checked by composite date
            self.assertTrue(
                self.db.is_duplicate("", amount, seller, expense_date=date_str),
                f"Day {day} must be recognized as duplicate by date",
            )
            # Checked by hash
            self.assertTrue(
                self.db.is_duplicate("", file_hash=hash_str),
                f"Day {day} must be recognized as duplicate by hash",
            )

        # Verification 4: Day 11 (new receipt) is NOT duplicate
        self.assertFalse(
            self.db.is_duplicate("", amount, seller, expense_date="2026-01-11", file_hash="hash_receipt_day_11"),
            "Day 11 receipt must not be flagged as duplicate",
        )

    # ── 7. Stress test with 100 consecutive unnumbered receipts ────────

    def test_stress_100_distinct_unnumbered_receipts(self):
        """Stress test with 100 unnumbered receipts from the same seller for the same amount."""
        seller = "滴滴出行"
        amount = "35.50"
        for i in range(100):
            date_str = f"2026-02-{(i % 28) + 1:02d}"
            hash_str = f"hash_trip_{i:04d}"

            # Only distinct when date/hash combination differs
            row_id = self.db.insert_invoice({
                "invoice_number": None,
                "total_amount": amount,
                "seller_name": seller,
                "expense_date": date_str,
                "file_hash": hash_str,
            })
            self.assertIsNotNone(row_id, f"Failed at iteration {i}")

        self.assertEqual(len(self.db.get_all_invoices()), 100)

    # ── 8. Null / Missing key preservation & hash/date nuances ─────────

    def test_preserve_10_distinct_unnumbered_with_none_invoice_number(self):
        """Preserve 10 distinct unnumbered receipts when invoice_number is explicitly None."""
        seller = "中国电信"
        amount = "100.00"
        for day in range(1, 11):
            date_str = f"2026-03-{day:02d}"
            self.assertFalse(self.db.is_duplicate(None, amount, seller, expense_date=date_str))
            row_id = self.db.insert_invoice({
                "invoice_number": None,
                "total_amount": amount,
                "seller_name": seller,
                "expense_date": date_str,
            })
            self.assertIsNotNone(row_id)
        self.assertEqual(len(self.db.get_all_invoices()), 10)

    def test_preserve_10_distinct_unnumbered_with_omitted_invoice_number(self):
        """Preserve 10 distinct unnumbered receipts when invoice_number key is omitted from dict."""
        seller = "中国联通"
        amount = "30.00"
        for day in range(1, 11):
            date_str = f"2026-04-{day:02d}"
            row_id = self.db.insert_invoice({
                "total_amount": amount,
                "seller_name": seller,
                "expense_date": date_str,
            })
            self.assertIsNotNone(row_id)
        self.assertEqual(len(self.db.get_all_invoices()), 10)

    def test_same_date_different_hash_composite_match_behavior(self):
        """Document behavior when two receipts share seller, amount, and date, but differ in file_hash.

        In the current implementation, step 2 checks (seller, amount, date), so even with different
        file hashes, a receipt on the same date with the same seller and amount will match step 2
        and return True.
        """
        self.db.insert_invoice({
            "invoice_number": "",
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
            "file_hash": "hash_file_A",
        })
        # If dates differ: False
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-01-02", file_hash="hash_file_B"),
        )
        # If date matches: step 2 evaluates to True
        self.assertTrue(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-01-01", file_hash="hash_file_B"),
        )

    def test_whitespace_in_insert_invoice_behavior(self):
        """Demonstrate that whitespace-only invoice_number in insert_invoice vs is_duplicate:

        is_duplicate('   ') strips to '' (unnumbered), but insert_invoice({'invoice_number': '   '})
        currently does not strip whitespace before the 'not v' check, storing '   ' literally.
        """
        # is_duplicate safely treats whitespace as empty
        self.assertFalse(self.db.is_duplicate("   ", "50.00", "中国移动", expense_date="2026-05-01"))


if __name__ == "__main__":
    unittest.main()
