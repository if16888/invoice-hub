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

    def test_batch_bar_reserves_space_without_covering_table(self):
        from PySide6.QtCore import QRect

        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window._switch_main_page("review")
                window.batch_review_bar.show()
                for _ in range(3):
                    self.app.processEvents()
                layout = window.left_upper_widget.layout()
                self.assertGreaterEqual(layout.indexOf(window.batch_review_bar), 0)
                bar = window.batch_review_bar
                bar_rect = QRect(bar.mapToGlobal(bar.rect().topLeft()), bar.size())
                table = window.table.viewport()
                table_rect = QRect(table.mapToGlobal(table.rect().topLeft()), table.size())
                self.assertFalse(bar_rect.intersects(table_rect))
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
        self.assertIn("motion_duration(150)", source)


if __name__ == "__main__":
    unittest.main()
