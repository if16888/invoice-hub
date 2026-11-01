"""Regression tests for P1 batch 2 (overview tone, restore hierarchy, icon targets)."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


_QAPP = None


class P1Batch2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory, name="p1b2.db"):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / name, splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_overview_neutral_counter_is_not_warning_tinted(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                states = {
                    key: card.property("state")
                    for key, card in window.overview_value_labels.items()
                }
                self.assertEqual(states["to_review"], "muted")
                self.assertEqual(states["error"], "danger")
                self.assertEqual(states["needs_fix"], "warning")
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_restore_is_danger_toned_and_details_icons_are_labelled(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertEqual(
                    window.btn_restore_complete_backup.property("tone"), "danger"
                )
                detail = window._detail_panel
                self.assertEqual(detail.btn_inline_more.accessibleName(), "更多发票操作")
                self.assertTrue(detail.btn_inline_more.toolTip())
                self.assertGreaterEqual(window.btn_toggle_review_detail.height(), 28)
                self.assertTrue(window.btn_toggle_review_detail.toolTip())
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
