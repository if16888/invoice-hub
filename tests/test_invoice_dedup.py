"""Unit tests for InvoiceDB deduplication logic (is_duplicate).

Verifies deduplication behavior for:
1. Numbered invoices (exact number/amount match, no fall-through to seller+amount).
2. Unnumbered invoices without date or hash (must return False).
3. Unnumbered invoices with date (must match on seller + amount + date).
4. Unnumbered invoices with file_hash.
5. Soft-deleted invoice handling with include_deleted=False vs include_deleted=True.
6. Insertion of distinct unnumbered invoices with same seller and amount.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.db import InvoiceDB


class TestNumberedInvoiceDeduplication(unittest.TestCase):
    """Tests for numbered invoices (invoice_number is non-empty)."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db = InvoiceDB(self.temp_dir / "test_dedup.db")
        self.db.__enter__()

    def tearDown(self):
        self.db.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_same_number_and_amount_is_duplicate(self):
        """Numbered invoice with identical number and amount must be duplicate."""
        self.db.insert_invoice({
            "invoice_number": "INV-001",
            "total_amount": "100.00",
            "seller_name": "北京科技有限公司",
            "expense_date": "2026-01-10",
        })
        self.assertTrue(self.db.is_duplicate("INV-001", "100.00", "北京科技有限公司"))
        self.assertTrue(self.db.is_duplicate("INV-001", "100.00"))

    def test_same_number_without_amount_query_is_duplicate(self):
        """Numbered invoice checked by number alone should return True if number exists."""
        self.db.insert_invoice({
            "invoice_number": "INV-001",
            "total_amount": "100.00",
            "seller_name": "北京科技有限公司",
        })
        self.assertTrue(self.db.is_duplicate("INV-001"))

    def test_same_number_different_amount_is_not_duplicate(self):
        """Numbered invoice with same number but different amount is not duplicate."""
        self.db.insert_invoice({
            "invoice_number": "INV-001",
            "total_amount": "100.00",
            "seller_name": "北京科技有限公司",
        })
        self.assertFalse(self.db.is_duplicate("INV-001", "200.00"))

    def test_different_number_same_seller_and_amount_is_not_duplicate(self):
        """CRITICAL: Two invoices with distinct numbers from the same seller for the same amount

        MUST NOT be flagged as duplicates (no fall-through to seller+amount).
        """
        self.db.insert_invoice({
            "invoice_number": "INV-001",
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
        })
        # Distinct invoice number INV-002 from same seller for same amount
        self.assertFalse(
            self.db.is_duplicate("INV-002", "50.00", "中国移动"),
            "Different invoice number from same seller with same amount must NOT be duplicate",
        )

    def test_numbered_invoice_whitespace_stripping(self):
        """Whitespace in invoice_number and total_amount should be stripped."""
        self.db.insert_invoice({
            "invoice_number": "INV-001",
            "total_amount": "100.00",
            "seller_name": "北京科技有限公司",
        })
        self.assertTrue(self.db.is_duplicate("  INV-001  ", "  100.00  "))


class TestUnnumberedInvoiceDeduplication(unittest.TestCase):
    """Tests for unnumbered invoices (invoice_number is empty or missing)."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db = InvoiceDB(self.temp_dir / "test_dedup.db")
        self.db.__enter__()

    def tearDown(self):
        self.db.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unnumbered_without_date_or_hash_is_not_duplicate(self):
        """Calling is_duplicate("", "50.00", "中国移动") without date or hash MUST return False."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
        })
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动"),
            "Unnumbered invoice without date or hash must return False",
        )
        self.assertFalse(
            self.db.is_duplicate("   ", "50.00", "中国移动"),
            "Whitespace-only invoice number without date or hash must return False",
        )

    def test_unnumbered_same_seller_amount_different_dates_is_not_duplicate(self):
        """Unnumbered invoices with same seller and amount but different dates are NOT duplicates."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
        })
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-02-01"),
            "Different expense date must not be flagged as duplicate",
        )
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", invoice_date="2026-02-01"),
            "Different invoice date must not be flagged as duplicate",
        )

    def test_unnumbered_same_seller_amount_and_date_is_duplicate(self):
        """Unnumbered invoices with same seller, amount, and date ARE duplicates."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
        })
        self.assertTrue(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-01-01"),
            "Same seller, amount, and expense_date must be duplicate",
        )
        self.assertTrue(
            self.db.is_duplicate("", "50.00", "中国移动", invoice_date="2026-01-01"),
            "Matching date via invoice_date parameter must be duplicate",
        )

    def test_unnumbered_inserted_with_invoice_date_matches(self):
        """Invoice inserted with invoice_date (which populates expense_date) matches correctly."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "35.50",
            "seller_name": "滴滴出行",
            "invoice_date": "2026-03-15",
        })
        self.assertTrue(
            self.db.is_duplicate("", "35.50", "滴滴出行", invoice_date="2026-03-15"),
        )
        self.assertTrue(
            self.db.is_duplicate("", "35.50", "滴滴出行", expense_date="2026-03-15"),
        )
        self.assertFalse(
            self.db.is_duplicate("", "35.50", "滴滴出行", expense_date="2026-03-16"),
        )

    def test_unnumbered_missing_seller_or_amount_returns_false(self):
        """Composite check requires both seller_name and total_amount."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
        })
        self.assertFalse(self.db.is_duplicate("", "", "中国移动", expense_date="2026-01-01"))
        self.assertFalse(self.db.is_duplicate("", "50.00", "", expense_date="2026-01-01"))
        self.assertFalse(self.db.is_duplicate("", "", "", expense_date="2026-01-01"))


class TestFileHashDeduplication(unittest.TestCase):
    """Tests for file_hash deduplication on unnumbered invoices."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db = InvoiceDB(self.temp_dir / "test_dedup.db")
        self.db.__enter__()

    def tearDown(self):
        self.db.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_same_file_hash_is_duplicate(self):
        """Unnumbered invoice with matching file_hash must return True."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
            "file_hash": "sha256_hash_1111",
        })
        self.assertTrue(
            self.db.is_duplicate("", "50.00", "中国移动", file_hash="sha256_hash_1111"),
        )
        # Even without seller or amount, matching hash alone indicates duplicate content
        self.assertTrue(
            self.db.is_duplicate("", file_hash="sha256_hash_1111"),
        )

    def test_different_file_hash_is_not_duplicate(self):
        """Unnumbered invoice with different file_hash and different date must return False."""
        self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
            "file_hash": "sha256_hash_1111",
        })
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", file_hash="sha256_hash_2222"),
        )


class TestSoftDeleteDeduplication(unittest.TestCase):
    """Tests for soft-deleted invoice handling with include_deleted=False vs True."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db = InvoiceDB(self.temp_dir / "test_dedup.db")
        self.db.__enter__()

    def tearDown(self):
        self.db.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_numbered_invoice_soft_deleted(self):
        """Soft-deleted numbered invoice is excluded by default, included when include_deleted=True."""
        row_id = self.db.insert_invoice({
            "invoice_number": "INV-DEL-01",
            "total_amount": "80.00",
            "seller_name": "测试销方",
        })
        self.assertIsNotNone(row_id)
        self.db.soft_delete_invoice(row_id)

        self.assertFalse(
            self.db.is_duplicate("INV-DEL-01", "80.00", include_deleted=False),
            "Soft-deleted invoice must NOT be considered duplicate by default",
        )
        self.assertTrue(
            self.db.is_duplicate("INV-DEL-01", "80.00", include_deleted=True),
            "Soft-deleted invoice MUST be recognized when include_deleted=True",
        )

    def test_unnumbered_file_hash_soft_deleted(self):
        """Soft-deleted unnumbered invoice with file_hash respects include_deleted flag."""
        row_id = self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "file_hash": "deleted_hash_123",
        })
        self.assertIsNotNone(row_id)
        self.db.soft_delete_invoice(row_id)

        self.assertFalse(
            self.db.is_duplicate("", file_hash="deleted_hash_123", include_deleted=False),
        )
        self.assertTrue(
            self.db.is_duplicate("", file_hash="deleted_hash_123", include_deleted=True),
        )

    def test_unnumbered_composite_key_soft_deleted(self):
        """Soft-deleted unnumbered invoice with composite key respects include_deleted flag."""
        row_id = self.db.insert_invoice({
            "invoice_number": None,
            "total_amount": "99.00",
            "seller_name": "中国电信",
            "expense_date": "2026-04-01",
        })
        self.assertIsNotNone(row_id)
        self.db.soft_delete_invoice(row_id)

        self.assertFalse(
            self.db.is_duplicate("", "99.00", "中国电信", expense_date="2026-04-01", include_deleted=False),
        )
        self.assertTrue(
            self.db.is_duplicate("", "99.00", "中国电信", expense_date="2026-04-01", include_deleted=True),
        )


class TestMultipleUnnumberedInvoicesInsert(unittest.TestCase):
    """End-to-end database storage tests for multiple distinct unnumbered receipts."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db = InvoiceDB(self.temp_dir / "test_dedup.db")
        self.db.__enter__()

    def tearDown(self):
        self.db.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multiple_unnumbered_receipts_from_same_seller_and_amount(self):
        """Verifies that multiple receipts from the same seller with the same amount but different dates

        can both be inserted without violating database constraints or deduplication false-positives.
        """
        id1 = self.db.insert_invoice({
            "invoice_number": "",
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-01-01",
            "file_hash": "hash_jan",
        })
        self.assertIsNotNone(id1, "First unnumbered receipt should be inserted successfully")

        # Second receipt (February telecom bill) - same seller, same amount, different date & hash
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-02-01", file_hash="hash_feb"),
            "Second receipt with different date/hash must not be duplicate",
        )

        id2 = self.db.insert_invoice({
            "invoice_number": "",
            "total_amount": "50.00",
            "seller_name": "中国移动",
            "expense_date": "2026-02-01",
            "file_hash": "hash_feb",
        })
        self.assertIsNotNone(id2, "Second unnumbered receipt should be inserted successfully")
        self.assertNotEqual(id1, id2)

        # Both records must be present in the database
        all_invoices = self.db.get_all_invoices()
        self.assertEqual(len(all_invoices), 2)

        # Re-checking January receipt -> must be duplicate
        self.assertTrue(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-01-01"),
        )
        # Re-checking February receipt -> must be duplicate
        self.assertTrue(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-02-01"),
        )
        # March receipt -> must NOT be duplicate
        self.assertFalse(
            self.db.is_duplicate("", "50.00", "中国移动", expense_date="2026-03-01"),
        )


if __name__ == "__main__":
    unittest.main()
