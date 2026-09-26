import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.review_layout import (
    PREVIEW_MIN_HEIGHT,
    RECORD_MAX_HEIGHT,
    RECORD_MIN_HEIGHT,
)


class ReviewWorkspaceVerticalLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "review-workspace-vertical-layout.db")
        window.resize(1600, 900)
        window.show()
        for _ in range(8):
            self.app.processEvents()
        window._switch_main_page("review")
        for _ in range(4):
            self.app.processEvents()
        return window


    def test_invoice_number_column_consumes_unused_table_width(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                table = window.table
                header = table.horizontalHeader()
                self.assertTrue(table.property("reviewRemainderFillApplied"))
                self.assertEqual(
                    header.sectionResizeMode(5),
                    QHeaderView.Interactive,
                )
                # The header now covers the viewport instead of ending after the
                # invoice-number text and leaving a large empty band.
                self.assertGreaterEqual(header.length(), table.viewport().width() - 4)
                self.assertGreaterEqual(table.columnWidth(4), 180)
                self.assertLessEqual(table.columnWidth(4), 320)
                self.assertGreaterEqual(table.columnWidth(5), 178)
            finally:
                window.close()

    def test_removed_legacy_evidence_action_cannot_float_over_summary(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                detail = window._detail_panel
                self.assertIsNone(detail.original_card)
                self.assertIsNone(detail.evidence_card)
                detail.update_evidence_row([{"path": "synthetic-proof.png"}])
                self.app.processEvents()
                self.assertFalse(detail.btn_open_extra_files.isVisible())
                self.assertIs(detail.btn_add_evidence.parentWidget(), detail.evidence_status_line)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
