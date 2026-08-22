import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QBoxLayout, QSizePolicy

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.workbench_settings import (
    sync_workbench_settings,
    workbench_settings,
)


class ImportCenterGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        s = workbench_settings()
        s.remove("nav_collapsed_manual")
        sync_workbench_settings(s)

    def tearDown(self):
        s = workbench_settings()
        s.remove("nav_collapsed_manual")
        sync_workbench_settings(s)

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "invoices.db")
        window.show()
        self.app.processEvents()
        return window

    def test_test9_import_responsive_geometry_across_window_sizes(self):
        """TEST 9: Verify responsive layout states for Wide, Medium, and Narrow desktop viewports."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._switch_main_page("imports")
                self.app.processEvents()

                # 1. Wide Desktop (1440x900) - mail source has ample space for side-by-side main row
                window.resize(1440, 900)
                window._apply_import_workspace_layout(1440)
                self.app.processEvents()

                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(window.import_source_card.body_layout.direction(), QBoxLayout.LeftToRight)
                self.assertEqual(window.import_main_row_layout.direction(), QBoxLayout.LeftToRight)
                self.assertLessEqual(window.import_task_stack.maximumWidth(), 900)
                self.assertIn(window.import_mail_recent_card.width(), [320, 340, 360])

                # 2. Medium Desktop (1100x800) - vertically stacked main row
                window.resize(1100, 800)
                window._apply_import_workspace_layout(1100)
                self.app.processEvents()

                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(window.import_source_card.body_layout.direction(), QBoxLayout.LeftToRight)
                self.assertEqual(window.import_main_row_layout.direction(), QBoxLayout.TopToBottom)

                # 3. Narrow Desktop (800x600) - vertically stacked
                window.resize(800, 600)
                window._apply_import_workspace_layout(800)
                self.app.processEvents()

                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(window.import_main_row_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(window.import_mail_recent_card.sizePolicy().verticalPolicy(), QSizePolicy.Maximum)
            finally:
                window.close()

    def test_imports_workspace_layout_medium_desktop_1276x875(self):
        """Verify 1276x875 medium desktop layout with expanded sidebar for mobile and local sources."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._switch_main_page("imports")
                window.resize(1276, 875)
                window._nav_collapsed_manual = False
                window._apply_workbench_metrics(1276, 875)
                self.app.processEvents()

                # 1. Source = mobile at 1276x875 with expanded sidebar (mobile active)
                window._select_import_source("mobile")
                panel = window.mobile_upload_panel
                session = SimpleNamespace(
                    upload_url="http://192.168.1.100:8080/u/test_token_12345678",
                    host="192.168.1.100",
                    port=8080,
                )
                with patch.object(panel.controller, "qr_png", return_value=b"fake_qr_png"):
                    panel.controller.started.emit(session)
                window._apply_import_workspace_layout(1276)
                self.app.processEvents()

                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(window.import_main_row_layout.direction(), QBoxLayout.TopToBottom)
                # Recent card is located below the task card, not to its right
                self.assertGreaterEqual(
                    window.import_mail_recent_card.y(),
                    window.import_task_stack.y() + window.import_task_stack.height() - 10,
                )

                # 2. Source = local at 1276x875 with expanded sidebar
                window._select_import_source("local")
                window._apply_import_workspace_layout(1276)
                self.app.processEvents()

                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(window.import_main_row_layout.direction(), QBoxLayout.TopToBottom)
                # Local import card is compact and does not stretch vertically to fill the page
                self.assertLess(window.import_local_task_card.height(), 300)
                self.assertGreaterEqual(
                    window.import_mail_recent_card.y(),
                    window.import_task_stack.y() + window.import_task_stack.height() - 10,
                )
            finally:
                window.close()

    def test_imports_workspace_layout_wide_desktop_1920x1080(self):
        """Verify 1920x1080 wide desktop layout allows side-by-side for mobile and local tasks."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._switch_main_page("imports")
                window.resize(1920, 1080)
                window._nav_collapsed_manual = False
                window._apply_workbench_metrics(1920, 1080)
                self.app.processEvents()

                # 1. Source = mobile at 1920x1080 with expanded sidebar (mobile active)
                window._select_import_source("mobile")
                panel = window.mobile_upload_panel
                session = SimpleNamespace(
                    upload_url="http://192.168.1.100:8080/u/test_token_12345678",
                    host="192.168.1.100",
                    port=8080,
                )
                with patch.object(panel.controller, "qr_png", return_value=b"fake_qr_png"):
                    panel.controller.started.emit(session)
                window._apply_import_workspace_layout(1920)
                self.app.processEvents()

                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(window.import_main_row_layout.direction(), QBoxLayout.LeftToRight)
                self.assertGreaterEqual(window.import_task_stack.width(), 900)
                self.assertGreaterEqual(window.import_mail_recent_card.width(), 300)
                # Side-by-side: recent card x is to the right of task stack
                self.assertGreaterEqual(
                    window.import_mail_recent_card.x(),
                    window.import_task_stack.x() + window.import_task_stack.width() - 1,
                )

                # 2. Source = local at 1920x1080 with expanded sidebar
                window._select_import_source("local")
                window._apply_import_workspace_layout(1920)
                self.app.processEvents()

                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(window.import_main_row_layout.direction(), QBoxLayout.LeftToRight)
                self.assertGreaterEqual(window.import_task_stack.width(), 780)
                self.assertLess(window.import_local_task_card.height(), 300)
                self.assertGreaterEqual(window.import_mail_recent_card.width(), 300)
                self.assertGreaterEqual(
                    window.import_mail_recent_card.x(),
                    window.import_task_stack.x() + window.import_task_stack.width() - 1,
                )
            finally:
                window.close()

    def test_test10_mobile_desktop_responsive_geometry_qr_size(self):
        """TEST 10: Mobile QR code preserves readable dimensions without text overlapping."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._select_import_source("mobile")
                self.app.processEvents()

                panel = window.mobile_upload_panel
                session = SimpleNamespace(
                    upload_url="http://192.168.1.100:8080/u/test_token_12345678",
                    host="192.168.1.100",
                    port=8080,
                )
                with patch.object(panel.controller, "qr_png", return_value=b"fake_qr_png"):
                    panel.controller.started.emit(session)
                self.app.processEvents()

                # At 1440x900 (Wide)
                window.resize(1440, 900)
                panel.resize(760, 500)
                self.app.processEvents()
                self.assertGreaterEqual(panel.lbl_qr.width(), 200)
                self.assertGreaterEqual(panel.lbl_qr.height(), 200)

                # At 1100x800 (Medium)
                window.resize(1100, 800)
                panel.resize(600, 500)
                self.app.processEvents()
                self.assertGreaterEqual(panel.lbl_qr.width(), 200)
                self.assertGreaterEqual(panel.lbl_qr.height(), 200)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
