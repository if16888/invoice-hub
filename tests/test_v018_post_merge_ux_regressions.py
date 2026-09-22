from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel

from scripts.invoice_fetch.gui import startup_lifecycle
from scripts.invoice_fetch.gui.settings_dialog import SettingsDialog
from scripts.invoice_fetch.gui.mobile_upload_session import (
    MobileUploadSessionController,
    MobileUploadSessionPanel,
)


class V018PostMergeUxRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_import_panel_construction_does_not_query_windows_firewall(self):
        with tempfile.TemporaryDirectory(prefix="invoice-hub-import-no-firewall-") as td:
            controller = MobileUploadSessionController(Path(td) / "invoices.db")
            with patch.object(
                controller,
                "refresh_firewall_status",
                side_effect=AssertionError("Imports construction must not query Windows Firewall"),
            ):
                panel = MobileUploadSessionPanel(controller)
            try:
                self.assertIn("启动手机上传后检查", panel.lbl_idle_firewall.text())
            finally:
                panel.close()
                controller.shutdown(timeout_ms=50)
                self.qt_app.processEvents()

    def test_intake_format_copy_does_not_claim_xml_support(self):
        with tempfile.TemporaryDirectory(prefix="invoice-hub-format-copy-") as td:
            window = startup_lifecycle.FirstPaintDeferredInvoiceReviewApp(
                Path(td) / "startup.db",
                splash=None,
            )
            controller = MobileUploadSessionController(Path(td) / "mobile.db")
            panel = MobileUploadSessionPanel(controller)
            dialog = SettingsDialog(parent=None)
            try:
                window._switch_main_page("imports")
                for _ in range(4):
                    self.qt_app.processEvents()
                window._switch_main_page("settings")
                for _ in range(4):
                    self.qt_app.processEvents()
                visible_copy = [
                    window.import_local_types.lbl_value.text(),
                    window.lbl_detail_attachment_types.text(),
                    panel.lbl_idle_network.text(),
                ]
                visible_copy.extend(
                    label.text()
                    for label in dialog.findChildren(QLabel)
                    if "附件提取类型" in label.text()
                )

                self.assertEqual(len(visible_copy), 4)
                self.assertIn("PDF / OFD / PNG / JPG / HEIC / ZIP", visible_copy[0])
                self.assertIn("PDF / OFD / PNG / JPG / HEIC / ZIP", visible_copy[2])
                for text in visible_copy:
                    self.assertNotIn("XML", text.upper())
            finally:
                dialog.close()
                panel.close()
                controller.shutdown(timeout_ms=50)
                window.close()
                self.qt_app.processEvents()

    def test_wide_dashboard_uses_available_width_and_four_task_columns(self):
        with tempfile.TemporaryDirectory(prefix="invoice-hub-dashboard-wide-") as td:
            window = startup_lifecycle.FirstPaintDeferredInvoiceReviewApp(
                Path(td) / "startup.db",
                splash=None,
            )
            try:
                # Exercise layout geometry without relying on the hosted runner's
                # physical desktop size. This is the same product viewport the
                # responsive contract is intended to handle.
                window.resize(1600, 900)
                window.show()
                for _ in range(4):
                    self.qt_app.processEvents()
                window._nav_collapsed_manual = True
                window._apply_workbench_metrics(1600, 900)
                window._switch_main_page("overview")
                for _ in range(6):
                    self.qt_app.processEvents()

                self.assertGreaterEqual(window.overview_content_host.width(), 900)
                self.assertEqual(window.hci_dashboard_task_cards_row.column_count(), 4)
                self.assertEqual(
                    window.hci_dashboard_task_cards["to_review"].lbl_title.text(),
                    "待审核",
                )
                self.assertNotEqual(
                    window.hci_dashboard_task_cards["to_review"].lbl_title.text(),
                    "新票待确认",
                )
            finally:
                window.close()
                self.qt_app.processEvents()


if __name__ == "__main__":
    unittest.main()
