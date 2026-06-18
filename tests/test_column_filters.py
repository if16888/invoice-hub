import unittest
from datetime import date

from scripts.invoice_fetch.gui.column_filters import apply_column_filters


class ColumnFilterTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "id": 1,
                "invoice_number": "INV-001",
                "expense_date": "2026-06-01",
                "invoice_date": "2026-05-31",
                "total_amount": "18.50",
                "seller_name": "Alpha Coffee",
                "category": "餐饮",
                "claim_group_name": "六月报销",
            },
            {
                "id": 2,
                "invoice_number": "INV-002",
                "expense_date": "",
                "invoice_date": "2026-06-02",
                "total_amount": "120.00",
                "seller_name": "Beta Hotel",
                "category": "住宿",
                "claim_group": "",
            },
            {
                "id": 3,
                "invoice_number": "TRIP-003",
                "expense_date": "2026-06-03",
                "invoice_date": "2026-06-03",
                "total_amount": "45.00",
                "seller_name": "Alpha Travel",
                "category": "交通",
                "claim_group": "六月报销",
            },
        ]

    def test_filters_category_values(self):
        result = apply_column_filters(self.rows, {"category": {"values": {"住宿"}}})
        self.assertEqual([row["id"] for row in result], [2])

    def test_filters_seller_values(self):
        result = apply_column_filters(self.rows, {"seller_name": {"values": {"Alpha Coffee"}}})
        self.assertEqual([row["id"] for row in result], [1])

    def test_filters_invoice_number_values(self):
        result = apply_column_filters(self.rows, {"invoice_number": {"values": {"TRIP-003"}}})
        self.assertEqual([row["id"] for row in result], [3])

    def test_filters_expense_date_with_invoice_date_fallback(self):
        result = apply_column_filters(self.rows, {"expense_date": {"values": {"2026-06-02"}}})
        self.assertEqual([row["id"] for row in result], [2])

    def test_filters_date_with_last_30_days_quick_filter(self):
        result = apply_column_filters(
            self.rows,
            {"expense_date": {"quick": "last_30_days"}},
            today=date(2026, 6, 15),
        )
        self.assertEqual([row["id"] for row in result], [1, 2, 3])

    def test_filters_amount_range(self):
        result = apply_column_filters(self.rows, {"total_amount": {"min": "20", "max": "100"}})
        self.assertEqual([row["id"] for row in result], [3])

    def test_amount_range_handles_decimal_and_blank_values(self):
        rows = [
            {"id": 10, "total_amount": "18.75"},
            {"id": 11, "total_amount": ""},
            {"id": 12, "total_amount": "21.25"},
        ]

        result = apply_column_filters(rows, {"total_amount": {"min": "18.5", "max": "20.0"}})
        self.assertEqual([row["id"] for row in result], [10])

    def test_combines_multiple_filters_with_and_logic(self):
        result = apply_column_filters(
            self.rows,
            {
                "category": {"values": {"交通"}},
                "seller_name": {"values": {"Alpha Travel"}},
                "total_amount": {"max": "50"},
            },
        )
        self.assertEqual([row["id"] for row in result], [3])

    def test_empty_checked_value_set_matches_no_rows(self):
        result = apply_column_filters(self.rows, {"category": {"values": set()}})
        self.assertEqual(result, [])

    def test_filters_claim_group_aliases(self):
        rows = [
            {"id": 11, "invoice_number": "CG-1", "claim_group_name": "test1"},
            {"id": 12, "invoice_number": "CG-2", "claim_group": "test2"},
            {"id": 13, "invoice_number": "CG-3", "claim_name": "test3"},
        ]

        result = apply_column_filters(rows, {"claim_name": {"values": {"test1"}}})
        self.assertEqual([row["id"] for row in result], [11])


if __name__ == "__main__":
    unittest.main()
