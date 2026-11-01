"""Regression tests for P1 batch 3 (preview toolbar persistence, settings canvas)."""

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


class P1Batch3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / "p1b3.db", splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_preview_toolbar_stays_visible_while_a_document_is_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window._switch_main_page("review")
                for _ in range(4):
                    self.app.processEvents()
                window.current_preview_docs = [{"path": Path(td) / "synthetic.pdf"}]
                window._show_overlay_toolbar()
                window._start_hide_overlay_timer()
                self.app.processEvents()
                self.assertFalse(window.overlay_toolbar.isHidden())

                window.current_preview_docs = []
                window._start_hide_overlay_timer()
                self.app.processEvents()
                self.assertFalse(window.overlay_toolbar.isVisible())
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_common_settings_uses_readable_scroll_column(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertEqual(window.settings_common_page.objectName(), "SettingsScroll")
                self.assertEqual(window.settings_common_widget.maximumWidth(), 760)
                self.assertTrue(window.settings_mode_hint.isHidden())
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
