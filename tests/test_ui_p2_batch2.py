"""Regression tests for P2 batch 2 (zoom, record header, imports scroll)."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


_QAPP = None


class P2Batch2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / "p2b2.db", splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_zoom_shortcuts_and_live_label(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertEqual(window.shortcut_zoom_in.key(), QKeySequence(QKeySequence.ZoomIn))
                self.assertEqual(window.shortcut_zoom_out.key(), QKeySequence(QKeySequence.ZoomOut))
                self.assertEqual(window.shortcut_zoom_reset.key(), QKeySequence("Ctrl+0"))
                window._refresh_zoom_percent()
                self.assertEqual(window.btn_zoom_100.text(), "100%")
                self.assertIn("Ctrl + 0", window.btn_zoom_100.toolTip())
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_record_header_hides_permanent_hint_and_funnel_scroll(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertTrue(window.lbl_record_sort.isHidden())
                self.assertIn("排序", window.lbl_record_section_title.toolTip())
                self.assertEqual(
                    window.import_mail_accounts_scroll.horizontalScrollBarPolicy(),
                    Qt.ScrollBarAlwaysOff,
                )
                from PySide6.QtWidgets import QFrame

                self.assertEqual(window.import_mail_accounts_scroll.frameShape(), QFrame.NoFrame)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
