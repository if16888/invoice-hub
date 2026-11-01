"""Regression tests for P2 batch 6 (floating batch bar, reduced motion)."""

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


class P2Batch6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / "p2b6.db", splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_batch_bar_floats_without_entering_the_card_layout(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                layout = window.left_upper_widget.layout()
                self.assertEqual(layout.indexOf(window.batch_review_bar), -1)
                window.batch_review_bar.show()
                window._position_batch_review_bar()
                bar = window.batch_review_bar
                self.assertEqual(bar.x(), 6)
                self.assertLessEqual(
                    bar.geometry().bottom(), window.left_upper_widget.height() - 6
                )
                table_height = window.left_stack.height()
                window.batch_review_bar.hide()
                window._position_batch_review_bar()
                self.assertEqual(window.left_stack.height(), table_height)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_reduced_motion_collapses_animation_duration(self):
        from scripts.invoice_fetch.gui import motion

        original = motion.animations_enabled
        try:
            motion.animations_enabled = lambda: False
            self.assertEqual(motion.motion_duration(190), 0)
            motion.animations_enabled = lambda: True
            self.assertEqual(motion.motion_duration(190), 190)
        finally:
            motion.animations_enabled = original
        source = (
            Path(__file__).resolve().parents[1]
            / "scripts/invoice_fetch/gui/app.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("setDuration(190)", source)
        self.assertIn("motion_duration(190)", source)


if __name__ == "__main__":
    unittest.main()
