import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.review_workspace_closure import (
    PREVIEW_MIN_HEIGHT,
    RECORD_MAX_HEIGHT,
    RECORD_MIN_HEIGHT,
)


class ReviewWorkspaceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "review-workspace-closure.db")
        window.resize(1600, 900)
        window.show()
        for _ in range(8):
            self.app.processEvents()
        window._switch_main_page("review")
        for _ in range(4):
            self.app.processEvents()
        return window

    def test_real_vertical_splitter_owns_list_and_preview(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                splitter = window.left_splitter
                self.assertTrue(window.review_page.property("reviewWorkspaceClosureApplied"))
                self.assertEqual(splitter.objectName(), "ReviewVerticalSplitter")
                self.assertEqual(splitter.orientation(), Qt.Vertical)
                self.assertEqual(splitter.count(), 2)
                self.assertIs(splitter.widget(0), window.left_upper_widget)
                self.assertIs(splitter.widget(1), window.preview_panel)
                self.assertEqual(window.left_upper_widget.minimumHeight(), RECORD_MIN_HEIGHT)
                self.assertEqual(window.left_upper_widget.maximumHeight(), RECORD_MAX_HEIGHT)
                self.assertEqual(window.preview_panel.minimumHeight(), PREVIEW_MIN_HEIGHT)
                self.assertTrue(all(size > 0 for size in splitter.sizes()))
            finally:
                window.close()

    def test_load_all_is_removed_from_visible_product_surface(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                button = window.btn_load_all
                parent_layout = button.parentWidget().layout()
                self.assertTrue(button.property("designBaselineRemoved"))
                self.assertEqual(parent_layout.indexOf(button), -1)
                self.assertTrue(button.testAttribute(Qt.WA_DontShowOnScreen))
            finally:
                window.close()

    def test_invoice_number_column_consumes_unused_table_width(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                table = window.table
                header = table.horizontalHeader()
                self.assertTrue(table.property("reviewRemainderFillApplied"))
                self.assertEqual(
                    header.sectionResizeMode(5),
                    QHeaderView.Stretch,
                )
                # The header now covers the viewport instead of ending after the
                # invoice-number text and leaving a large empty band.
                self.assertGreaterEqual(header.length(), table.viewport().width() - 4)
                self.assertGreaterEqual(table.columnWidth(4), 180)
                self.assertGreaterEqual(table.columnWidth(5), 178)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
