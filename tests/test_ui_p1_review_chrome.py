"""Regression tests for P1-1 (review toolbar) and P1-4 (elastic detail pane)."""

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


class ReviewChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / "p1c.db", splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_search_has_stable_width_and_durable_actions(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                search = window.txt_search
                self.assertGreaterEqual(search.minimumWidth(), 280)
                self.assertLessEqual(search.maximumWidth(), 320)
                self.assertTrue(window.btn_scan_email.isHidden())
                self.assertTrue(window.btn_toolbar_export.isHidden())
                self.assertTrue(window.btn_import_local.isHidden())
                self.assertIn(window.action_import_local, window.more_menu.actions())
                self.assertIn(window.action_scan_email, window.more_menu.actions())
                self.assertIn(window.action_toolbar_export, window.more_menu.actions())
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_detail_pane_is_elastic_320_to_420(self):
        from scripts.invoice_fetch.gui.review_layout import (
            DETAIL_MAX_WIDTH,
            DETAIL_MIN_WIDTH,
        )

        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                detail = window._detail_panel
                self.assertEqual(detail.minimumWidth(), DETAIL_MIN_WIDTH)
                self.assertEqual(detail.maximumWidth(), DETAIL_MAX_WIDTH)
                self.assertEqual((DETAIL_MIN_WIDTH, DETAIL_MAX_WIDTH), (320, 420))
                sizes = window.main_splitter.sizes()
                if len(sizes) > 1 and sizes[1] > 0:
                    self.assertLessEqual(sizes[1], DETAIL_MAX_WIDTH)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
