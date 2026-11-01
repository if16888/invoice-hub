"""Regression tests for the UI P0 accessibility batch."""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.styles import build_canonical_application_stylesheet
from scripts.invoice_fetch.gui.ui_components import ActivityTimeline


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class ActivityTimelineGhostingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_clear_reparents_rows_before_deleting_them(self):
        timeline = ActivityTimeline()
        try:
            first = timeline.add_entry("今天", "导入", "3 张")
            second = timeline.add_entry("昨天", "审核", "2 张")
            timeline.clear()

            self.assertEqual(timeline._layout.count(), 0)
            for row in (first, second):
                self.assertFalse(row.isVisible())
                self.assertIsNone(row.parentWidget())
        finally:
            timeline.deleteLater()
            self.app.processEvents()


class FocusRingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_canonical_stylesheet_has_keyboard_focus_rules(self):
        stylesheet = build_canonical_application_stylesheet()
        for selector in (
            "QPushButton:focus",
            "QToolButton:focus",
            "QLineEdit:focus",
            'QPushButton[variant="toolbar"]:focus',
            "QTableView::item:focus",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, stylesheet)
        self.assertIn("Keyboard focus ring", stylesheet)


class ReviewPageStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from pathlib import Path

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        return InvoiceReviewApp(Path(directory) / "ui-p0.db", splash=None)

    def test_review_header_stays_visible_and_cross_workflow_actions_stay(self):
        from scripts.invoice_fetch.gui.page_layouts import apply_global_design_baseline
        from scripts.invoice_fetch.gui.review_layout import (
            apply_design_v1_review_task_closure,
        )

        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                window.show()
                for _ in range(5):
                    self.app.processEvents()
                apply_global_design_baseline(window.review_page)
                apply_design_v1_review_task_closure(window.review_page)
                for _ in range(5):
                    self.app.processEvents()

                self.assertTrue(window.review_header.isVisible())
                self.assertTrue(window.review_header.property("reviewCompactHeader"))
                for attr in ("btn_import_local", "btn_scan_email", "btn_toolbar_export"):
                    button = getattr(window, attr)
                    self.assertTrue(button.property("reviewCrossWorkflowActionCompact"))
                    self.assertIsInstance(button.text(), str)
                self.assertTrue(hasattr(window, "action_soft_duplicate_review"))
                window.db.close()
            finally:
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
