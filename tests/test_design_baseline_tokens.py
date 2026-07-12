import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.design_baseline_styles import BASELINE_COLORS


class DesignBaselineTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_baseline_palette_matches_source_of_truth(self):
        self.assertEqual(BASELINE_COLORS["page"], "#F7F8FA")
        self.assertEqual(BASELINE_COLORS["surface"], "#FFFFFF")
        self.assertEqual(BASELINE_COLORS["selected"], "#EFF6FF")
        self.assertEqual(BASELINE_COLORS["border"], "#E5E7EB")
        self.assertEqual(BASELINE_COLORS["text"], "#182230")
        self.assertEqual(BASELINE_COLORS["muted"], "#667085")
        self.assertEqual(BASELINE_COLORS["accent"], "#2563EB")
        self.assertEqual(BASELINE_COLORS["success"], "#16803C")
        self.assertEqual(BASELINE_COLORS["warning"], "#B54708")
        self.assertEqual(BASELINE_COLORS["danger"], "#B42318")

    def test_page_archetypes_use_24px_margin_and_16px_gap(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "baseline-tokens.db")
            try:
                window.show()
                for _ in range(4):
                    self.app.processEvents()
                for page in (window.overview_page, window.imports_page, window.export_page):
                    margins = page.layout().contentsMargins()
                    self.assertEqual(
                        (margins.left(), margins.top(), margins.right(), margins.bottom()),
                        (24, 24, 24, 24),
                    )
                    self.assertEqual(page.layout().spacing(), 16)
                self.assertTrue(window.property("designBaselineV1Applied"))
                self.assertIn("#2563EB", window.styleSheet())
                self.assertIn("font-size: 22px", window.styleSheet())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
