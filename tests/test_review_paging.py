import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView, QLabel, QPushButton, QWidget

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp, SORT_ID_ROLE
from scripts.invoice_fetch.gui.review_paging import (
    ReviewPagingController,
    install_review_paging,
)
from scripts.invoice_fetch.review_status import TO_REVIEW

_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class ReviewPagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _events(self):
        for _ in range(12):
            self.app.processEvents()

    def _stub_page(self):
        window = QWidget()
        page = QWidget(window)
        window.invoices_list = []
        window._record_total_matching = 0
        window.lbl_record_count = QLabel(window)
        window.lbl_status_left = QLabel(window)
        window.lbl_status_left.show()
        window._load_invoices = Mock()
        window.search_reload_timer = QTimer(window)
        window.search_reload_timer.timeout.connect(lambda: None)
        install_review_paging(page)
        self.addCleanup(window.deleteLater)
        return window

    def _window(self, td, count=125):
        window = InvoiceReviewApp(Path(td) / "paging.db")
        window.show()
        self._events()
        install_review_paging(window.review_page)
        for index in range(count):
            self.assertIsNotNone(window.db.insert_invoice({
                "invoice_number": f"PAGING-{index:04d}",
                "invoice_date": "2026-07-01", "expense_date": "2026-07-01",
                "total_amount": f"{index + 1}.00", "seller_name": f"Synthetic {index}",
                "buyer_name": "Synthetic Buyer", "review_status": TO_REVIEW,
            }))
        window._review_page_limit = 50
        window.review_paging.load_first_page()
        self._events()
        return window

    def test_installer_owns_controller_copy_timer_and_legacy_status_contract(self):
        window = self._stub_page()
        self.assertIsInstance(window.review_paging, ReviewPagingController)
        self.assertEqual(window._review_page_limit, 50)
        self.assertIsNone(window._review_paging_signature)
        self.assertTrue(window.lbl_status_left.isHidden())
        self.assertTrue(window.lbl_status_left.property("pagingCountDetached"))

        window.invoices_list = [{"id": 1}]
        window._record_total_matching = 2
        window._refresh_review_paging_copy()
        self.assertEqual(window.lbl_record_count.text(), "已加载 1 / 共 2 张")

        window.invoices_list.append({"id": 2})
        window._refresh_review_paging_copy()
        self.assertEqual(window.lbl_record_count.text(), "已加载全部，共 2 张")

        window.search_reload_timer.timeout.emit()
        window._load_invoices.assert_called_once_with()

    def test_formal_method_is_not_monkey_patched(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertIs(window._append_next_invoice_batch.__func__, InvoiceReviewApp._append_next_invoice_batch)
            finally:
                window.close()

    def test_load_next_preserves_middle_selection(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                queries = []
                original_list = window.db.list_review_invoices

                def record_query(query):
                    queries.append(query)
                    return original_list(query)

                window.db.list_review_invoices = record_query
                window.table.selectRow(25)
                window._on_table_selection_changed()
                selected = window.current_invoice["id"]
                first_page_ids = [invoice["id"] for invoice in window.invoices_list]
                window.review_paging.load_next_page()
                self._events()
                self.assertGreaterEqual(len(window.invoices_list), 100)
                self.assertEqual(
                    [invoice["id"] for invoice in window.invoices_list[:50]],
                    first_page_ids,
                )
                self.assertEqual(window.current_invoice["id"], selected)
                self.assertEqual([(query.limit, query.offset) for query in queries], [(50, 50)])
            finally:
                window.close()

    def test_mouse_click_then_arrow_keys_updates_current_invoice(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window.activateWindow()
                self._events()
                window.txt_search.setFocus()
                index = window.table.model().index(1, 3)
                QTest.mouseClick(window.table.viewport(), Qt.LeftButton,
                                 pos=window.table.visualRect(index).center())
                self._events()
                self.assertTrue(window.table.hasFocus())
                self.assertEqual(window.table.currentRow(), 1)
                for row in (2, 3):
                    QTest.keyClick(window.table, Qt.Key_Down)
                    self._events()
                    self.assertEqual(window.table.currentRow(), row)
                    self.assertEqual(window.current_invoice['id'], window.invoices_list[row]['id'])
                QTest.keyClick(window.table, Qt.Key_Up)
                self._events()
                self.assertEqual(window.table.currentRow(), 2)
                window.txt_search.setFocus()
                QTest.keyClick(window.txt_search, Qt.Key_Down)
                self._events()
                self.assertEqual(window.table.currentRow(), 2)
            finally:
                window.close()

    def test_boundary_selection_enters_next_batch(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window.table.selectRow(49)
                window._on_table_selection_changed()
                window.table.setFocus()
                QTest.keyClick(window.table, Qt.Key_Down)
                self._events()
                self.assertGreaterEqual(window.table.currentRow(), 50)
                self.assertGreaterEqual(len(window.invoices_list), 100)
            finally:
                window.close()

    def test_filtered_scope_resets_and_pages(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td, 60)
            try:
                window.current_filter_status = TO_REVIEW
                window.review_paging.reset_scope(("status", TO_REVIEW))
                window.review_paging.load_first_page()
                self._events()
                self.assertEqual(len(window.invoices_list), 50)
                window.review_paging.load_next_page()
                self._events()
                self.assertEqual(len(window.invoices_list), 60)
            finally:
                window.close()

    def test_search_scope_reset_returns_to_first_page(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td, 60)
            try:
                window.txt_search.setText("PAGING-0059")
                window.search_reload_timer.stop()
                window.review_paging.reset_scope(("search", "PAGING-0059"))
                window.review_paging.load_first_page()
                self._events()
                self.assertEqual(len(window.invoices_list), 1)
                self.assertEqual(window.invoices_list[0]["invoice_number"], "PAGING-0059")

                window.txt_search.setText("")
                window.search_reload_timer.stop()
                window.review_paging.reset_scope(("search", ""))
                window.review_paging.load_first_page()
                self._events()
                self.assertEqual(len(window.invoices_list), 50)
            finally:
                window.close()

    def test_keyboard_selection_crosses_page_boundary_in_both_directions(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td, 60)
            try:
                window.table.selectRow(49)
                window._on_table_selection_changed()
                window._move_invoice_selection(1)
                self._events()
                self.assertEqual(window.table.currentRow(), 50)
                self.assertEqual(window.current_invoice["id"], window.invoices_list[50]["id"])

                window._move_invoice_selection(-1)
                self._events()
                self.assertEqual(window.table.currentRow(), 49)
                self.assertEqual(window.current_invoice["id"], window.invoices_list[49]["id"])
            finally:
                window.close()

    def test_double_trigger_is_guarded(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window.review_paging.loading = True
                window.review_paging.load_next_page()
                self.assertEqual(len(window.invoices_list), 50)
            finally:
                window.close()

    def test_scroll_towards_bottom_loads_next_page_and_preserves_scroll_position(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td, count=125)
            try:
                window.table.selectRow(7)
                window._on_table_selection_changed()
                self._events()
                selected_id = window.current_invoice["id"]
                sb = window.table.verticalScrollBar()
                self.assertGreater(sb.maximum(), 0)

                # Simulate scrolling down towards the bottom
                sb.setValue(sb.maximum())
                self._events()
                saved_scroll = sb.value()

                # Trigger scroll check
                window._maybe_load_more_invoices(sb.value())
                QTest.qWait(150)
                self._events()

                self.assertGreaterEqual(len(window.invoices_list), 100)
                self.assertEqual(window.current_invoice["id"], selected_id)
                self.assertEqual(window.table.currentRow(), 7)
                self.assertEqual(sb.value(), saved_scroll)
            finally:
                window.close()

    def test_click_record_count_loads_all_invoices(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td, count=125)
            try:
                self.assertEqual(len(window.invoices_list), 50)
                QTest.mouseClick(window.lbl_record_count, Qt.LeftButton)
                self._events()
                self.assertEqual(len(window.invoices_list), 125)
                self.assertIn("125", window.lbl_record_count.text())
            finally:
                window.close()

    def _wait_for(self, predicate, description):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
            self.app.processEvents()
        self.assertTrue(predicate(), description)

    def _click(self, widget):
        self.assertTrue(widget.isVisible() and widget.isEnabled())
        QTest.mouseClick(widget, Qt.LeftButton)
        self._events()

    def _visible_window(self, td, count):
        path = Path(td) / "visible-paging.db"
        ids = {}
        with InvoiceDB(path) as db:
            for n in range(1, count + 1):
                ids[n] = db.insert_invoice({
                    "invoice_number": f"VISIBLE-{n:04d}", "invoice_date": "2026-07-01",
                    "expense_date": "2026-07-01", "total_amount": f"{n}.00", "currency": "CNY",
                    "seller_name": f"合成商户{n:04d}", "buyer_name": "合成购方",
                    "category": "办公", "review_status": TO_REVIEW,
                })
                self.assertIsNotNone(ids[n])
        window = InvoiceReviewApp(path)
        try:
            window.resize(1500, 900)
            window.show()
            window.activateWindow()
            self._wait_for(lambda: window._deferred_init_done, "initial workbench load")
            self._click(window.workbench_nav_buttons["review"])
            self._wait_for(lambda: window.table.isVisible() and len(window.invoices_list) == 50,
                           "visible first review page")
            return window, ids, path
        except BaseException:
            window.close()
            raise

    def _invoice_snapshot(self, path):
        with sqlite3.connect(path) as db:
            return db.execute("SELECT id, invoice_number, invoice_date, expense_date, total_amount, "
                              "currency, seller_name, buyer_name, review_status, confirmed_note "
                              "FROM invoices ORDER BY id").fetchall()

    def _assert_table_rows(self, window, numbers, ids):
        numbers = list(numbers)
        self.assertEqual(window.table.columnCount(), 7)
        self.assertEqual(window.table.rowCount(), len(numbers))
        self.assertEqual([inv["id"] for inv in window.invoices_list], [ids[n] for n in numbers])
        for row, n in enumerate(numbers):
            expected = ["待审核", "缺原件", "2026-07-01", f"¥{n}.00", f"合成商户{n:04d}",
                        f"VISIBLE-{n:04d}", "—"]
            for col, text in enumerate(expected):
                item = window.table.item(row, col)
                self.assertIsNotNone(item, f"local row {row}, column {col} was not populated")
                self.assertEqual(item.data(SORT_ID_ROLE), ids[n], f"wrong invoice at local row {row}, column {col}")
                self.assertEqual(item.text(), text)

    def _assert_selected(self, window, row, number, ids):
        self.assertEqual(window.table.currentRow(), row)
        self.assertEqual([index.row() for index in window.table.selectionModel().selectedRows()], [row])
        self.assertEqual(window.table.item(row, 5).data(SORT_ID_ROLE), ids[number])
        self.assertEqual(window.current_invoice["id"], ids[number])
        self.assertEqual(window.txt_number.text(), f"VISIBLE-{number:04d}")

    def _click_table_row(self, window, row):
        table = window.table
        index = table.model().index(row, 0)
        # Let any queued view layout and selection restore finish before
        # locating the row in the actual viewport.
        QTest.qWait(20)
        table.scrollTo(index, QAbstractItemView.PositionAtCenter)
        self._events()
        rect = table.visualRect(index).intersected(table.viewport().rect())
        self.assertFalse(rect.isEmpty(), f"row {row} is outside the viewport")
        QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        self._events()

    def _click_amount_header(self, window, *, filter_popup=False):
        header = window.table.horizontalHeader()
        width = header.sectionSize(3)
        point = QPoint(header.sectionViewportPosition(3) + (width - 8 if filter_popup else width // 3),
                       header.height() // 2)
        self.assertEqual(header.logicalIndexAt(point), 3)
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self._events()

    def _record_queries(self, window):
        queries = []
        original_list = window.db.list_review_invoices

        def record_query(query):
            queries.append(query)
            return original_list(query)

        window.db.list_review_invoices = record_query
        return queries

    def _scroll_to_end(self, window, expected_count):
        scrollbar = window.table.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setFocus()
        QTest.keyClick(scrollbar, Qt.Key_End)
        self._wait_for(lambda: len(window.invoices_list) == expected_count and not window._is_loading_more_invoices,
                       "scrollbar End should append the remaining review rows")

    def test_visible_nonfirst_scroll_append_populates_every_cell_and_keeps_selection(self):
        with tempfile.TemporaryDirectory() as td:
            window, ids, path = self._visible_window(td, 130)
            before = self._invoice_snapshot(path)
            try:
                self._assert_table_rows(window, range(130, 80, -1), ids)
                queries = self._record_queries(window)
                self._click(window.btn_review_next_page)
                self.assertEqual(window._review_window_start, 50)
                self._assert_table_rows(window, range(80, 30, -1), ids)
                old_items = [window.table.item(row, col) for row in range(50) for col in range(7)]
                self._click_table_row(window, 12)
                self._assert_selected(window, 12, 68, ids)
                self._scroll_to_end(window, 80)

                self.assertEqual(window._review_window_start, 50)
                self.assertEqual(window.lbl_record_count.text(), "第 51–130 / 共 130 张")
                self._assert_table_rows(window, range(80, 0, -1), ids)
                self.assertEqual([window.table.item(row, col) for row in range(50) for col in range(7)], old_items)
                self._assert_selected(window, 12, 68, ids)
                self._click_table_row(window, 52)
                self._assert_selected(window, 52, 28, ids)
                self.assertEqual([(q.limit, q.offset) for q in queries], [(50, 50), (50, 100)])

                # Return to the first window and append normally from there;
                # the explicit terminal page must still start at SQL row 100.
                self._click(window.btn_review_previous_page)
                self.assertEqual(window._review_window_start, 0)
                self._assert_table_rows(window, range(130, 80, -1), ids)
                window.table.verticalScrollBar().setFocus()
                QTest.keyClick(window.table.verticalScrollBar(), Qt.Key_Home)
                self._click_table_row(window, 0)
                self._scroll_to_end(window, 100)
                self._assert_table_rows(window, range(130, 30, -1), ids)
                self._assert_selected(window, 0, 130, ids)
                self._click(window.btn_review_next_page)
                self.assertEqual(window._review_window_start, 100)
                self._assert_table_rows(window, range(30, 0, -1), ids)
                self.assertFalse(window.btn_review_next_page.isEnabled())
                self.assertEqual([(q.limit, q.offset) for q in queries], [(50, 50), (50, 100), (50, 0), (50, 50), (50, 100)])
            finally:
                window.close()
                self._events()
            self.assertEqual(self._invoice_snapshot(path), before)

    def test_visible_filtered_sorted_nonfirst_keyboard_append_keeps_row_identity(self):
        with tempfile.TemporaryDirectory() as td:
            window, ids, path = self._visible_window(td, 145)
            before = self._invoice_snapshot(path)
            try:
                # Use the real table-header filter and sort interactions, not
                # direct assignments to the query/controller state.
                self._click_amount_header(window, filter_popup=True)
                popup = window._column_filter_popup
                self.assertIsNotNone(popup)
                self.assertTrue(popup.isVisible())
                self.assertEqual(popup.key, "total_amount")
                QTest.keyClicks(popup.max_edit, "130")
                self._click(next(button for button in popup.findChildren(QPushButton) if button.text() == "应用"))
                self.assertEqual(window._record_total_matching, 130)
                self._assert_table_rows(window, range(130, 80, -1), ids)
                self._click(window.btn_review_next_page)
                self._click_table_row(window, 12)
                self._assert_selected(window, 12, 68, ids)
                self._click_amount_header(window)
                self.assertEqual(window._review_window_start, 50)
                self.assertEqual(window._column_sort_state, (3, Qt.AscendingOrder))
                self._assert_table_rows(window, range(51, 101), ids)
                self._assert_selected(window, 17, 68, ids)
                queries = self._record_queries(window)

                # Isolate the keyboard trigger from the competing 100 ms
                # scrollbar append during positioning. Restore the real
                # signal before pressing ↓; neither rendering nor keyboard
                # paging is mocked (the other test covers actual scrolling).
                scroll_signal = window.table.verticalScrollBar().valueChanged
                scroll_signal.disconnect(window._maybe_load_more_invoices)
                try:
                    self._click_table_row(window, 49)
                finally:
                    scroll_signal.connect(window._maybe_load_more_invoices)
                self.assertEqual(len(window.invoices_list), 50)
                window.table.setFocus()
                self._assert_selected(window, 49, 100, ids)
                QTest.keyClick(window.table, Qt.Key_Down)
                self._wait_for(lambda: len(window.invoices_list) == 80, "Down should cross the nonfirst page boundary")
                self._events()
                self._assert_table_rows(window, range(51, 131), ids)
                self._assert_selected(window, 50, 101, ids)
                for key, row, number in ((Qt.Key_Up, 49, 100), (Qt.Key_Down, 50, 101)):
                    QTest.keyClick(window.table, key)
                    self._events()
                    self._assert_selected(window, row, number, ids)
                self._click_table_row(window, 52)
                self._assert_selected(window, 52, 103, ids)
                self.assertEqual([(q.limit, q.offset) for q in queries], [(50, 100)])
                self.assertEqual(queries[0].sort_key, "total_amount")
                self.assertFalse(queries[0].sort_descending)
                self.assertEqual(queries[0].column_filters[0].maximum, "130")
            finally:
                window.close()
                self._events()
            self.assertEqual(self._invoice_snapshot(path), before)


if __name__ == "__main__":
    unittest.main()
