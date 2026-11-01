"""Regression tests for P2 batch 4 (settings segments, preview recovery)."""

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


class P2Batch4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / "p2b4.db", splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_settings_mode_switch_is_a_segment(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                segment = window.settings_mode_segment
                self.assertEqual(segment.objectName(), "SettingsModeSegment")
                self.assertEqual(segment.layout().count(), 2)
                for button in (
                    window.btn_settings_common_mode,
                    window.btn_settings_advanced_mode,
                ):
                    self.assertEqual(button.property("class"), "SegmentItem")
                    self.assertEqual(button.property("variant"), None)
                    self.assertEqual(button.height(), 30)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_preview_empty_state_exposes_recovery_actions(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window.current_preview_docs = [{"path": Path(td) / "synthetic.pdf"}]
                window._show_preview_status("文件不存在")
                self.assertIs(window.preview_stack.currentWidget(), window.preview_empty_page)
                self.assertTrue(window.btn_preview_recover_external.isEnabled())
                self.assertTrue(window.btn_preview_recover_locate.isEnabled())
                window.current_preview_docs = []
                window._show_preview_status("文件不存在")
                self.assertFalse(window.btn_preview_recover_external.isEnabled())
                self.assertFalse(window.btn_preview_recover_locate.isEnabled())
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
