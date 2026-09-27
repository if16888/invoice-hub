import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.buyer_warning_readability import (
    BUYER_WARNING_HORIZONTAL_PADDING,
    BUYER_WARNING_VERTICAL_PADDING,
)
from scripts.invoice_fetch.gui.buyer_warning_controller import (
    BUYER_WARNING_MAX_HEIGHT,
    BUYER_WARNING_MIN_HEIGHT,
)
from scripts.invoice_fetch.gui.design_v1_review_task_closure import (
    _refresh_compact_buyer_warning,
)
from scripts.invoice_fetch.gui.review_baseline_pipeline import REVIEW_BASELINE_STAGES
from scripts.invoice_fetch.gui.styles import APP_STYLESHEET


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

    def test_buyer_warning_uses_one_tokenized_controller_contract(self):
        names = [name for name, _stage in REVIEW_BASELINE_STAGES]
        self.assertNotIn("buyer_warning_readability", names)
        self.assertIn("task_ownership", names)
        self.assertNotIn(
            f"max-height: {BUYER_WARNING_MAX_HEIGHT}px",
            APP_STYLESHEET,
        )
        self.assertIn(
            f"min-height: {BUYER_WARNING_MIN_HEIGHT}px",
            APP_STYLESHEET,
        )
        self.assertNotIn("max-height: 64px", APP_STYLESHEET)

    def test_long_buyer_warning_keeps_full_text_inside_bounded_scroll_viewport(self):
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
                scroll = detail.buyer_warning_scroll
                self.assertEqual(label.property("buyerWarningLayout"), "tokenized")
                self.assertIn(
                    f"padding: {BUYER_WARNING_VERTICAL_PADDING}px "
                    f"{BUYER_WARNING_HORIZONTAL_PADDING}px",
                    APP_STYLESHEET,
                )
                self.assertIn("margin-top: 0px", APP_STYLESHEET)
                self.assertIn("margin-bottom: 0px", APP_STYLESHEET)
                self.assertNotIn(
                    f"max-height: {BUYER_WARNING_MAX_HEIGHT}px",
                    APP_STYLESHEET,
                )
                self.assertIs(scroll.widget(), label)
                self.assertEqual(scroll.maximumHeight(), BUYER_WARNING_MAX_HEIGHT)
                self.assertGreater(label.maximumHeight(), BUYER_WARNING_MAX_HEIGHT)
                self.assertEqual(scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

                window.config["reimbursement"]["buyer_name"] = "默认开票主体" * 24
                window.current_invoice["buyer_name"] = "当前发票购买方" * 24
                _refresh_compact_buyer_warning(window)
                for _ in range(4):
                    self.app.processEvents()
                self.assertGreater(label.heightForWidth(label.width()), scroll.viewport().height())
                self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
                self.assertIn("当前发票购买方" * 24, label.text())
                self.assertIn("默认开票主体" * 24, label.text())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
