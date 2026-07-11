import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QBoxLayout, QPushButton

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.mobile_upload_dialog import MobileUploadDialog


class IHDS08Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "invoices.db")
        window.show(); self.app.processEvents()
        return window

    def test_collapsed_nav_footer_is_icon_only(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.resize(1366, 768); self.app.processEvents()
                for button in (window.btn_shortcut_help, window.btn_collapse_nav):
                    self.assertEqual(button.text(), "")
                    self.assertEqual((button.width(), button.height()), (40, 40))
                    self.assertTrue(button.toolTip())
                    self.assertTrue(button.accessibleName())
            finally: window.close()

    def test_import_page_has_no_visible_mail_summary_strip(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertFalse(window.imports_summary_strip.isVisible())
                self.assertEqual(window.imports_summary_strip.maximumHeight(), 0)
            finally: window.close()

    def test_mobile_source_is_embedded_and_does_not_open_dialog(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                with patch.object(MobileUploadDialog, "exec", side_effect=AssertionError("modal opened")):
                    window._select_import_source("mobile")
                    self.app.processEvents()
                self.assertIs(window.import_task_stack.currentWidget(), window.import_mobile_task_card)
                self.assertFalse(window.mobile_upload_panel.isHidden())
                self.assertIs(window.mobile_upload_panel.stack.currentWidget(), window.mobile_upload_panel.idle_page)
            finally: window.close()

    def test_mobile_start_active_and_stop_idle(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                panel = window.mobile_upload_panel
                session = SimpleNamespace(upload_url="http://192.168.1.2:1234/u/test", host="192.168.1.2", port=1234)
                with patch.object(panel.controller, "qr_png", return_value=b""):
                    panel.controller.started.emit(session)
                self.assertIs(panel.stack.currentWidget(), panel.active_page)
                self.assertIn("/u/", panel.txt_url.text())
                panel.controller.stopped.emit()
                self.assertIs(panel.stack.currentWidget(), panel.idle_page)
            finally: window.close()

    def test_controller_is_shared_with_legacy_dialog(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            dialog = None
            try:
                with patch.object(window.mobile_upload_controller, "start", return_value=None):
                    with patch.object(MobileUploadDialog, "_start_server"):
                        dialog = MobileUploadDialog(window, window.db_path)
                self.assertIs(dialog.controller, window.mobile_upload_controller)
            finally:
                if dialog: dialog.close()
                window.close()

    def test_import_layout_adapts_below_1200(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._apply_workbench_metrics(1100, 800)
                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                window._apply_workbench_metrics(1600, 900)
                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.LeftToRight)
            finally: window.close()

    def test_mobile_task_has_at_most_one_primary(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                primaries = [b for b in window.mobile_upload_panel.findChildren(QPushButton)
                             if b.isVisible() and b.property("class") == "PrimaryBtn"]
                self.assertLessEqual(len(primaries), 1)
            finally: window.close()


if __name__ == "__main__":
    unittest.main()
