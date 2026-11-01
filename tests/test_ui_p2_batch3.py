"""Regression tests for P2 batch 3 (segments, status bar, source cards, terms)."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


_QAPP = None


class P2Batch3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / "p2b3.db", splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_source_card_shows_checkmark_when_selected(self):
        from scripts.invoice_fetch.gui.ui_components import SelectableSourceCard

        card = SelectableSourceCard("mail", "邮箱", "扫描已配置的发票邮箱。")
        try:
            self.assertFalse(card.lbl_check.isVisible())
            card.set_selected(True)
            self.assertEqual(card.property("selected"), True)
            self.assertFalse(card.lbl_check.isHidden())
            card.set_selected(False)
            self.assertTrue(card.lbl_check.isHidden())
        finally:
            card.deleteLater()
            self.app.processEvents()

    def test_segment_control_uses_grey_track_and_white_pill(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        self.assertIn("QWidget#SegmentControl", APP_STYLESHEET)
        segment_rules = APP_STYLESHEET.split("QWidget#SegmentControl", 1)[1]
        self.assertIn("#F2F4F7", segment_rules)
        self.assertIn("background: #FFFFFF", segment_rules)

    def test_status_bar_puts_selection_on_the_right_and_terms_are_unified(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertTrue(window.lbl_status_middle.alignment() & Qt.AlignRight)
                self.assertTrue(window.lbl_status_left.alignment() & Qt.AlignLeft)
                text = window.action_approve_selected.text()
                self.assertTrue(text.startswith("通过所选"))
                self.assertIn("…", text)
                source = (
                    Path(__file__).resolve().parents[1]
                    / "scripts/invoice_fetch/gui/app.py"
                ).read_text(encoding="utf-8")
                self.assertNotIn("资料状态", source)
                self.assertIn("材料状态", source)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
