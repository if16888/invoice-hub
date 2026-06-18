import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch.db import InvoiceDB


class GuiColumnFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            import sys

            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def _make_window(self, rows):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "column_filters.db"
        with InvoiceDB(db_path) as db:
            for row in rows:
                payload = {
                    "invoice_number": row.get("invoice_number", "INV"),
                    "expense_date": row.get("expense_date", "2026-06-01"),
                    "invoice_date": row.get("invoice_date", "2026-06-01"),
                    "total_amount": row.get("total_amount", "10.00"),
                    "seller_name": row.get("seller_name", "Seller"),
                    "buyer_name": row.get("buyer_name", "Buyer"),
                    "category": row.get("category", "餐饮"),
                    "review_status": row.get("review_status", "to_review"),
                    "mail_uid": row.get("mail_uid"),
                    "mail_sender": row.get("mail_sender", ""),
                    "attachment_path": row.get("attachment_path", ""),
                }
                db.insert_invoice(payload)

        config = {"reimbursement": {"strict_buyer_check": False}}
        config_patch = patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        window = InvoiceReviewApp(db_path, splash=None)
        window._deferred_init()
        self.app.processEvents()

        def close_window():
            if getattr(window, "db", None) is not None:
                window.db.close()
            window.close()
            window.deleteLater()
            self.app.processEvents()

        self.addCleanup(close_window)
        return window

    def _numbers(self, window):
        return [row.get("invoice_number") for row in window.invoices_list]

    def test_categorical_filter_by_category(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "category": "餐饮"},
            {"invoice_number": "HOTEL", "category": "住宿"},
        ])

        window._set_column_filter("category", {"values": {"住宿"}})

        self.assertEqual(self._numbers(window), ["HOTEL"])

    def test_text_filters_by_seller_and_invoice_number(self):
        window = self._make_window([
            {"invoice_number": "INV-A", "seller_name": "Alpha"},
            {"invoice_number": "INV-B", "seller_name": "Beta"},
        ])

        window._set_column_filter("seller_name", {"values": {"Alpha"}})
        self.assertEqual(self._numbers(window), ["INV-A"])
        window._set_column_filter("seller_name", {})
        window._set_column_filter("invoice_number", {"values": {"INV-B"}})
        self.assertEqual(self._numbers(window), ["INV-B"])

    def test_date_and_amount_filters(self):
        window = self._make_window([
            {"invoice_number": "LOW", "expense_date": "2026-06-01", "total_amount": "10"},
            {"invoice_number": "MID", "expense_date": "2026-06-02", "total_amount": "50"},
            {"invoice_number": "HIGH", "expense_date": "2026-06-02", "total_amount": "200"},
        ])

        window._set_column_filter("expense_date", {"values": {"2026-06-02"}})
        window._set_column_filter("total_amount", {"min": "20", "max": "100"})

        self.assertEqual(self._numbers(window), ["MID"])

    def test_multiple_filters_and_global_search_combine(self):
        window = self._make_window([
            {"invoice_number": "ALPHA-FOOD", "seller_name": "Alpha", "category": "餐饮"},
            {"invoice_number": "ALPHA-HOTEL", "seller_name": "Alpha", "category": "住宿"},
            {"invoice_number": "BETA-FOOD", "seller_name": "Beta", "category": "餐饮"},
        ])

        window.txt_search.setText("Alpha")
        window.search_reload_timer.stop()
        window._set_column_filter("category", {"values": {"餐饮"}})

        self.assertEqual(self._numbers(window), ["ALPHA-FOOD"])

    def test_reset_clears_filters_and_header_indicator(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "category": "餐饮"},
            {"invoice_number": "HOTEL", "category": "住宿"},
        ])

        window._set_column_filter("category", {"values": {"住宿"}})
        self.assertIn("●", window.table.horizontalHeaderItem(5).text())
        window._reset_invoice_filters()

        self.assertEqual(window.column_filters, {})
        self.assertNotIn("●", window.table.horizontalHeaderItem(5).text())
        self.assertEqual(set(self._numbers(window)), {"FOOD", "HOTEL"})

    def test_supported_headers_open_compact_filter_popup(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "category": "餐饮"},
            {"invoice_number": "HOTEL", "category": "住宿"},
        ])

        self.assertEqual(window.table.columnCount(), 8)
        self.assertTrue(all("▾" in window.table.horizontalHeaderItem(i).text() for i in range(8)))
        window._show_column_filter_popup(5)
        self.app.processEvents()

        popup = window._column_filter_popup
        self.assertEqual(popup.key, "category")
        self.assertEqual(popup.search_edit.placeholderText(), "搜索值")
        self.assertEqual(popup.value_list.count(), 2)
        popup.close()

    def test_empty_value_selection_remains_active_when_popup_reopens(self):
        from PySide6.QtCore import Qt

        window = self._make_window([
            {"invoice_number": "FOOD", "category": "餐饮"},
            {"invoice_number": "HOTEL", "category": "住宿"},
        ])

        window._set_column_filter("category", {"values": set()})
        self.assertEqual(window.table.rowCount(), 0)
        self.assertIn("●", window.table.horizontalHeaderItem(5).text())
        window._show_column_filter_popup(5)
        self.app.processEvents()

        popup = window._column_filter_popup
        self.assertFalse(popup.select_all.isChecked())
        self.assertTrue(all(
            popup.value_list.item(i).checkState() == Qt.Unchecked
            for i in range(popup.value_list.count())
        ))
        popup.close()

    def test_selection_is_preserved_when_selected_invoice_remains_visible(self):
        window = self._make_window([
            {"invoice_number": "FOOD-A", "category": "餐饮", "expense_date": "2026-06-03"},
            {"invoice_number": "FOOD-B", "category": "餐饮", "expense_date": "2026-06-02"},
            {"invoice_number": "HOTEL", "category": "住宿", "expense_date": "2026-06-01"},
        ])
        window.table.selectRow(1)
        self.app.processEvents()
        selected_id = window.current_invoice["id"]

        window._set_column_filter("category", {"values": {"餐饮"}})
        self.app.processEvents()

        self.assertEqual(window.current_invoice["id"], selected_id)

    def test_selection_falls_back_to_nearest_visible_row(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "category": "餐饮", "expense_date": "2026-06-03"},
            {"invoice_number": "HOTEL-A", "category": "住宿", "expense_date": "2026-06-02"},
            {"invoice_number": "HOTEL-B", "category": "住宿", "expense_date": "2026-06-01"},
        ])
        window.table.selectRow(0)
        self.app.processEvents()

        window._set_column_filter("category", {"values": {"住宿"}})
        self.app.processEvents()

        self.assertEqual(window.table.currentRow(), 0)
        self.assertEqual(window.current_invoice["invoice_number"], "HOTEL-A")

    def test_filtering_and_load_all_cover_rows_beyond_first_100(self):
        rows = []
        for index in range(130):
            rows.append({
                "invoice_number": f"ROW-{index:03d}",
                "category": "目标" if index < 105 else "其他",
                "expense_date": f"2026-06-{(index % 28) + 1:02d}",
            })
        window = self._make_window(rows)
        self.assertEqual(window.table.rowCount(), 100)

        window._set_column_filter("category", {"values": {"目标"}})

        self.assertEqual(window.table.rowCount(), 100)
        self.assertEqual(window._limited_first_load_total, 105)
        self.assertIn("100 / 105", window._format_status_count_prefix())
        self.assertFalse(window.btn_load_all.isHidden())
        window._load_all_invoices_clicked()
        self.assertEqual(window.table.rowCount(), 105)
        self.assertTrue(all(row["category"] == "目标" for row in window.invoices_list))


if __name__ == "__main__":
    unittest.main()
