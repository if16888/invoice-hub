import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.buyer_warning_readability import (
    BUYER_WARNING_HORIZONTAL_PADDING,
    BUYER_WARNING_VERTICAL_PADDING,
)
from scripts.invoice_fetch.gui.design_v1_review_task_closure import (
    _refresh_compact_buyer_warning,
)
from scripts.invoice_fetch.gui.review_baseline_pipeline import REVIEW_BASELINE_STAGES


class BuyerWarningReadabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td: str) -> InvoiceReviewApp:
        window = InvoiceReviewApp(Path(td) / "buyer-warning-readability.db")
        window.resize(1600, 900)
        window.show()
        for _ in range(8):
            self.app.processEvents()
        window._switch_main_page("review")
        for _ in range(4):
            self.app.processEvents()
        return window

    def test_readability_stage_runs_after_task_ownership(self):
        names = [name for name, _stage in REVIEW_BASELINE_STAGES]
        self.assertLess(
            names.index("task_ownership"),
            names.index("buyer_warning_readability"),
        )
        self.assertLess(
            names.index("buyer_warning_readability"),
            names.index("visual_language_v11"),
        )

    def test_long_buyer_warning_fits_inside_compact_height(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.config = {
                    "reimbursement": {
                        "buyer_name": "示例科技有限公司",
                        "strict_buyer_check": True,
                    }
                }
                window.current_invoice = {
                    "buyer_name": "上海远景科创智能科技有限公司"
                }
                _refresh_compact_buyer_warning(window)
                for _ in range(4):
                    self.app.processEvents()

                detail = window._detail_panel
                label = detail.lbl_buyer_warning
                self.assertEqual(
                    window.review_page.property("buyerWarningReadabilityApplied"),
                    True,
                )
                self.assertEqual(label.property("buyerWarningLayout"), "readable")
                self.assertIn(
                    f"padding: {BUYER_WARNING_VERTICAL_PADDING}px "
                    f"{BUYER_WARNING_HORIZONTAL_PADDING}px",
                    label.styleSheet(),
                )
                self.assertIn("margin-top: 0px", label.styleSheet())
                self.assertIn("margin-bottom: 0px", label.styleSheet())

                label.setFixedWidth(300)
                for _ in range(4):
                    self.app.processEvents()
                required_height = label.heightForWidth(label.width())
                self.assertGreater(required_height, 0)
                self.assertLessEqual(required_height, label.maximumHeight())
                self.assertIn("上海远景科创智能科技有限公司", label.text())
                self.assertIn("示例科技有限公司", label.text())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
