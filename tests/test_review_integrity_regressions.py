"""User workflows that must retain invoice identity and unedited data."""
from __future__ import annotations

import gc
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QWidget

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.review_query import ReviewQuery


class ReviewIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def settle(self):
        for _ in range(4):
            self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    @contextmanager
    def window(self, count=3):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoices.db"
            with InvoiceDB(path) as db:
                for i in range(count):
                    db.insert_invoice({
                        "invoice_number": f"INV-{i:03}",
                        "invoice_date": "2026-10-30", "total_amount": str(i + 1),
                        "category": "交通", "seller_name": f"Seller {i}",
                        "buyer_name": "Buyer", "review_status": "to_review",
                    })
            window = InvoiceReviewApp(path, splash=None)
            window._deferred_init()
            window.resize(1280, 720)
            window.show()
            window._switch_main_page("review")
            window._change_filter("all")
            self.settle()
            try:
                yield window
            finally:
                window.close()
                window.deleteLater()
                self.settle()

    def test_sorted_selection_updates_the_displayed_invoice_only(self):
        with self.window() as window:
            window._sort_review_table_by(3)
            window.table.selectRow(0)
            self.settle()
            displayed = window.table.item(0, 5).text()
            self.assertEqual(window.current_invoice["invoice_number"], displayed)
            expected_id = window.current_invoice["id"]
            window._set_selected_status("ignored")
            rows = window.db.get_all_invoices()
            self.assertEqual([row["id"] for row in rows if row["review_status"] == "ignored"], [expected_id])
            for row_index, invoice in enumerate(window.invoices_list):
                self.assertEqual(window.table.item(row_index, 5).text(), invoice["invoice_number"])

    def test_sort_applies_before_pagination_and_append_keeps_order(self):
        with self.window(130) as window:
            window._sort_review_table_by(3)
            self.assertEqual(len(window.invoices_list), 50)
            self.assertEqual(float(window.invoices_list[0]["total_amount"]), 1)
            window._load_invoices(append=True)
            amounts = [float(row["total_amount"]) for row in window.invoices_list]
            self.assertEqual(amounts, list(range(1, 101)))
            self.assertEqual(len({row["id"] for row in window.invoices_list}), 100)
            window._sort_review_table_by(3)
            self.assertEqual(float(window.invoices_list[0]["total_amount"]), 130)
            self.assertEqual(len(window.invoices_list), 50)
            with self.assertRaises(ValueError):
                window.db.list_review_invoices(ReviewQuery(sort_key="id; DELETE FROM invoices"))

    def test_inline_amount_preserves_category_in_database(self):
        with self.window() as window:
            window.table.selectRow(0)
            self.settle()
            invoice_id = window.current_invoice["id"]
            panel = window._detail_panel
            panel._begin_inline_edit("amount")
            panel.inline_edit_input.setText("22.00")
            panel._commit_inline_edit()
            saved = window.db.get_invoice(invoice_id)
            self.assertEqual(saved["total_amount"], "22.00")
            self.assertEqual(saved["category"], "交通")

    def test_switching_invoice_cancels_pending_inline_edit(self):
        with self.window() as window:
            window.table.selectRow(0)
            self.settle()
            before = {row["id"]: row["seller_name"] for row in window.db.get_all_invoices()}
            panel = window._detail_panel
            panel._begin_inline_edit("seller")
            panel.inline_edit_input.setText("Must not reach another invoice")
            window.table.selectRow(1)
            self.settle()
            self.assertTrue(panel.inline_edit_bar.isHidden())
            panel._commit_inline_edit()
            self.assertEqual({row["id"]: row["seller_name"] for row in window.db.get_all_invoices()}, before)

    def test_programmatic_detail_rebind_cancels_pending_inline_edit(self):
        from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel

        panel = InvoiceDetailPanel()
        try:
            panel.set_form_fields(inv_id="1", seller="First seller", category="交通")
            panel._begin_inline_edit("seller")
            panel.inline_edit_input.setText("Stale edit")
            panel.set_form_fields(inv_id="2", seller="Second seller", category="餐饮")
            panel._commit_inline_edit()
            self.assertEqual(panel.txt_seller.text(), "Second seller")
            self.assertEqual(panel.combo_category.currentText(), "餐饮")
            self.assertTrue(panel.inline_edit_bar.isHidden())
            panel._begin_inline_edit("seller")
            panel.clear_detail()
            panel._commit_inline_edit()
            self.assertEqual(panel.txt_seller.text(), "")
        finally:
            panel.deleteLater()
            self.settle()

    def test_loaded_preview_keeps_toolbar_and_zoom_label_current(self):
        with self.window() as window:
            path = Path(window.db._path).parent / "invoice.png"
            image = QImage(500, 800, QImage.Format_RGB32)
            image.fill(QColor("white"))
            self.assertTrue(image.save(str(path)))
            window.current_preview_docs = [{"path": path, "type": "invoice", "title": "Original"}]
            window.current_preview_index = 0
            window._update_document_preview()
            self.settle()
            self.assertFalse(window.overlay_toolbar.isHidden())
            window._zoom_in()
            self.assertEqual(window.btn_zoom_100.text(), "120%")
            window._zoom_fit_width()
            self.assertEqual(window.btn_zoom_100.text(), "适宽")
            window._zoom_fit_page()
            self.assertEqual(window.btn_zoom_100.text(), "适页")
            window._zoom_100()
            self.assertEqual(window.btn_zoom_100.text(), "100%")

    def test_pdf_load_and_zoom_transitions_keep_actions_current(self):
        from PySide6.QtGui import QPainter, QPdfWriter
        from PySide6.QtTest import QTest

        with self.window() as window:
            path = window.db._path.parent / "original.pdf"
            writer = QPdfWriter(str(path))
            painter = QPainter(writer)
            painter.drawText(100, 100, "Invoice")
            painter.end()
            del writer
            window.current_preview_docs = [{"path": path, "type": "invoice", "title": "PDF"}]
            window.current_preview_index = 0
            window._update_document_preview()
            for _ in range(100):
                self.app.processEvents()
                if window.pdf_view is not None:
                    break
                QTest.qWait(10)
            self.assertIsNotNone(window.pdf_view)
            self.assertEqual(window.btn_zoom_100.text(), "适宽")
            self.assertFalse(window.overlay_toolbar.isHidden())
            window._zoom_100()
            self.assertEqual(window.btn_zoom_100.text(), "100%")
            window._zoom_in()
            self.assertEqual(window.btn_zoom_100.text(), "120%")
            window._zoom_fit_page()
            self.assertEqual(window.btn_zoom_100.text(), "适页")
            window.current_preview_docs = []
            window._update_document_preview()
            self.assertTrue(window.overlay_toolbar.isHidden())

    def test_dark_window_and_late_local_styles_are_rendered_dark(self):
        from scripts.invoice_fetch.gui.dark_mode import apply_app_theme
        palette = self.app.palette()
        try:
            with patch.dict(os.environ, {"INVOICE_HUB_THEME": "dark"}):
                with self.window() as window:
                    window._switch_main_page("settings")
                    self.settle()
                    self.assertIn("#161A20", window.styleSheet())
                    self.assertNotIn("#182230", window.styleSheet())
                    from scripts.invoice_fetch.gui.icon_provider import IconProvider
                    icon = IconProvider.icon("settings").pixmap(18, 18).toImage()
                    visible = [icon.pixelColor(x, y) for x in range(icon.width())
                               for y in range(icon.height()) if icon.pixelColor(x, y).alpha() > 128]
                    self.assertTrue(visible)
                    self.assertGreater(min(color.lightness() for color in visible), 150)
                    # A later style replacement must be mapped too, exactly once.
                    child = QWidget(window)
                    child.setGeometry(20, 20, 40, 40)
                    child.setStyleSheet("background-color: #ffffff; color: #667085;")
                    child.show()
                    self.settle()
                    self.assertEqual(child.grab().toImage().pixelColor(10, 10).name(), "#161a20")
                    self.assertIn("#98A2B3", child.styleSheet())
                    apply_app_theme(self.app)
                    self.assertIn("#98A2B3", child.styleSheet())
                    child.setStyleSheet("background-color: #ffffff; color: #667085;")
                    self.settle()
                    self.assertEqual(child.grab().toImage().pixelColor(10, 10).name(), "#161a20")
        finally:
            self.app.setPalette(palette)

    def test_standard_button_translation_survives_discarded_return_value(self):
        from scripts.invoice_fetch.gui.i18n import install_chinese_translations
        existing = getattr(self.app, "_invoice_hub_translator", None)
        install_chinese_translations(self.app)
        gc.collect()
        buttons = QDialogButtonBox(QDialogButtonBox.Yes | QDialogButtonBox.No)
        try:
            self.assertIn("是", buttons.button(QDialogButtonBox.Yes).text())
            self.assertIn("否", buttons.button(QDialogButtonBox.No).text())
            self.assertIs(install_chinese_translations(self.app), self.app._invoice_hub_translator)
        finally:
            buttons.deleteLater()
            if existing is None:
                self.app.removeTranslator(self.app._invoice_hub_translator)
                self.app._invoice_hub_translator.deleteLater()
                del self.app._invoice_hub_translator


class ReviewDatabaseSortingTests(unittest.TestCase):
    def test_equal_amounts_are_stable_across_pages_with_scope_and_status(self):
        from dataclasses import replace

        with tempfile.TemporaryDirectory() as directory:
            with InvoiceDB(Path(directory) / "sorting.db") as db:
                ids = []
                for i, (amount, status) in enumerate((("10", "ignored"), ("10", "approved"),
                                                      ("-3", "to_review"), ("2", "error"))):
                    ids.append(db.insert_invoice({"invoice_number": f"TIE-{i}",
                        "total_amount": amount, "review_status": status}))
                query = ReviewQuery(sort_key="total_amount", limit=2, invoice_ids=tuple(ids))
                first = db.list_review_invoices(query)
                second = db.list_review_invoices(replace(query, offset=2))
                self.assertEqual([row["id"] for row in first + second], [ids[2], ids[3], ids[0], ids[1]])
                rows = db.list_review_invoices(replace(query, sort_key="review_status", limit=4))
                self.assertEqual([row["review_status"] for row in rows],
                                 ["to_review", "approved", "ignored", "error"])
                filtered = db.list_review_invoices(replace(query, status="approved"))
                self.assertEqual([row["id"] for row in filtered], [ids[1]])
