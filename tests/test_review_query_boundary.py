import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.review_query import ReviewColumnFilter, ReviewQuery
from scripts.invoice_fetch.review_status import APPROVED, TO_REVIEW


class ReviewQueryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = InvoiceDB(Path(self.temp_dir.name) / "review-query.db")
        self.addCleanup(self.db.close)

    def _insert_rows(self, count: int) -> None:
        rows = [
            (
                f"SYN-{index:05d}",
                f"2026-08-{(index % 28) + 1:02d}",
                f"2026-08-{(index % 28) + 1:02d}",
                f"{index + 1}.00",
                "Alpha" if index % 3 == 0 else "Beta",
                "餐饮" if index % 2 == 0 else "住宿",
                TO_REVIEW if index % 4 else APPROVED,
                f"subject {index}",
                f"file-{index}.pdf",
            )
            for index in range(count)
        ]
        self.db._conn.executemany(
            """
            INSERT INTO invoices (
                invoice_number, expense_date, invoice_date, total_amount,
                seller_name, buyer_name, category, review_status,
                mail_subject, attachment_path
            ) VALUES (?, ?, ?, ?, ?, '测试买方', ?, ?, ?, ?)
            """,
            rows,
        )
        self.db._conn.commit()

    def test_page_boundaries_are_complete_stable_and_disjoint(self):
        self._insert_rows(120)
        query = ReviewQuery(limit=50)
        pages = [
            self.db.list_review_invoices(replace(query, offset=offset))
            for offset in (0, 50, 100)
        ]
        ids = [row["id"] for page in pages for row in page]

        self.assertEqual([len(page) for page in pages], [50, 50, 20])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), self.db.count_review_invoices(query))
        self.assertEqual(ids, [row["id"] for row in self.db.list_review_invoices(replace(query, limit=120))])

    def test_zero_fifty_and_fifty_one_rows(self):
        self.assertEqual(self.db.count_review_invoices(ReviewQuery()), 0)
        self.assertEqual(self.db.list_review_invoices(ReviewQuery()), [])
        self._insert_rows(51)
        first = self.db.list_review_invoices(ReviewQuery(limit=50))
        second = self.db.list_review_invoices(ReviewQuery(limit=50, offset=50))
        self.assertEqual((len(first), len(second)), (50, 1))

    def test_search_column_filters_and_count_share_the_predicate(self):
        self._insert_rows(300)
        query = ReviewQuery(
            status=TO_REVIEW,
            search_text="alpha",
            column_filters=(
                ReviewColumnFilter("category", values=("餐饮",)),
                ReviewColumnFilter("total_amount", minimum="20", maximum="250"),
            ),
            limit=50,
            today=date(2026, 8, 30),
        )
        rows = []
        for offset in range(0, self.db.count_review_invoices(query), 50):
            rows.extend(self.db.list_review_invoices(replace(query, offset=offset)))

        self.assertEqual(len(rows), self.db.count_review_invoices(query))
        self.assertTrue(rows)
        self.assertTrue(all(row["review_status"] == TO_REVIEW for row in rows))
        self.assertTrue(all(row["seller_name"] == "Alpha" and row["category"] == "餐饮" for row in rows))

    def test_invalid_amount_boundary_is_ignored_but_invalid_row_amount_is_not_matched(self):
        valid_id = self.db.insert_invoice({
            "invoice_number": "VALID", "expense_date": "2026-08-01",
            "total_amount": "12.50", "seller_name": "Seller",
        })
        self.db.insert_invoice({
            "invoice_number": "INVALID", "expense_date": "2026-08-01",
            "total_amount": "not-money", "seller_name": "Other",
        })
        query = ReviewQuery(
            column_filters=(ReviewColumnFilter("total_amount", minimum="not-a-number"),),
            limit=50,
        )
        self.assertEqual([row["id"] for row in self.db.list_review_invoices(query)], [valid_id])

    def test_literal_search_characters_are_not_like_wildcards(self):
        self.db.insert_invoice({
            "invoice_number": "A%_B", "expense_date": "2026-08-01",
            "total_amount": "1", "seller_name": "Seller",
        })
        self.db.insert_invoice({
            "invoice_number": "AXXB", "expense_date": "2026-08-01",
            "total_amount": "2", "seller_name": "Seller 2",
        })
        rows = self.db.list_review_invoices(ReviewQuery(search_text="%_", limit=50))
        self.assertEqual([row["invoice_number"] for row in rows], ["A%_B"])

    def test_scope_preserves_requested_order_and_pages_in_sql(self):
        self._insert_rows(60)
        requested = tuple(row["id"] for row in self.db.list_review_invoices(ReviewQuery(limit=60)))[::-1]
        query = ReviewQuery(invoice_ids=requested, limit=50)
        first = self.db.list_review_invoices(query)
        second = self.db.list_review_invoices(replace(query, offset=50))
        self.assertEqual([row["id"] for row in first + second], list(requested))
        self.assertEqual(self.db.count_review_invoices(query), 60)

    def test_quick_date_and_derived_status_filters_match_existing_labels(self):
        normal_id = self.db.insert_invoice({
            "invoice_number": "NORMAL", "expense_date": "2026-08-31",
            "total_amount": "10", "seller_name": "Seller", "attachment_path": "normal.pdf",
        })
        self.db.insert_invoice({
            "invoice_number": "MISSING", "expense_date": "2026-07-01",
            "total_amount": "", "seller_name": "Seller", "attachment_path": "missing.pdf",
        })
        query = ReviewQuery(
            column_filters=(
                ReviewColumnFilter("expense_date", quick="month"),
                ReviewColumnFilter("status", values=("正常",)),
            ),
            limit=50,
            today=date(2026, 8, 15),
        )
        rows = self.db.list_review_invoices(query)
        self.assertEqual([row["id"] for row in rows], [normal_id])
        self.assertEqual(self.db.count_review_invoices(query), 1)

    def test_page_query_executes_limit_and_offset(self):
        self._insert_rows(300)
        statements = []
        self.db._conn.set_trace_callback(statements.append)
        try:
            rows = self.db.list_review_invoices(ReviewQuery(search_text="alpha", limit=50, offset=50))
        finally:
            self.db._conn.set_trace_callback(None)
        self.assertLessEqual(len(rows), 50)
        select = next(statement for statement in statements if statement.lstrip().upper().startswith("SELECT"))
        self.assertIn("LIMIT 50 OFFSET 50", select)

    def test_main_status_query_uses_v8_review_index(self):
        statements = []
        self.db._conn.set_trace_callback(statements.append)
        try:
            self.db.list_review_invoices(ReviewQuery(status=TO_REVIEW, limit=50))
        finally:
            self.db._conn.set_trace_callback(None)
        production_sql = next(
            statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
        )
        plan = self.db._conn.execute("EXPLAIN QUERY PLAN " + production_sql).fetchall()
        detail = " ".join(str(row["detail"]) for row in plan)
        self.assertIn("idx_invoices_review_order", detail)

    def test_large_datasets_return_only_requested_pages(self):
        for size in (1_000, 10_000):
            with self.subTest(size=size):
                self.db._conn.execute("DELETE FROM invoices")
                self._insert_rows(size)
                first = self.db.list_review_invoices(ReviewQuery(limit=50))
                second = self.db.list_review_invoices(ReviewQuery(limit=50, offset=50))
                self.assertEqual((len(first), len(second)), (50, 50))
                self.assertTrue(set(row["id"] for row in first).isdisjoint(row["id"] for row in second))
                self.assertEqual(self.db.count_review_invoices(ReviewQuery()), size)


if __name__ == "__main__":
    unittest.main()
