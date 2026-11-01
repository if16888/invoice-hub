"""Regression tests for P1-3 (flat workspace) and P1-7 (export hierarchy)."""

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


class P1StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / "p1s.db", splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_workspace_uses_separators_instead_of_nested_cards(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        self.assertIn("QSplitter#WorkbenchMainSplitter::handle", APP_STYLESHEET)
        table_rule = APP_STYLESHEET.split("QFrame#InvoiceTableCard", 1)[1].split("}", 1)[0]
        self.assertIn("border: none", table_rule)
        self.assertIn("border-radius: 0", table_rule)
        preview_rule = APP_STYLESHEET.split("QFrame#PreviewPanel", 1)[1].split("}", 1)[0]
        self.assertIn("border-radius: 0", preview_rule)

        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertEqual(window.preview_panel.objectName(), "PreviewPanel")
                self.assertEqual(window.main_splitter.objectName(), "WorkbenchMainSplitter")
                self.assertEqual(window.main_splitter.handleWidth(), 1)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_export_hierarchy_has_one_command_bar_and_neutral_zero(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertEqual(
                    window.export_group_card.body_layout.indexOf(window.btn_edit_claim_reason),
                    -1,
                )
                self.assertEqual(
                    window.export_group_card.body_layout.indexOf(window.btn_export_filename),
                    -1,
                )
                more_texts = [a.text() for a in window.export_group_more_menu.actions()]
                self.assertIn("编辑报销信息", more_texts)
                self.assertIn("导出文件名模板", more_texts)
                self.assertEqual(window.btn_export_create_group.property("variant"), "primary")
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
