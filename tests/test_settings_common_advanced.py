import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class SettingsCommonAdvancedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_common_settings_are_default_and_show_high_frequency_values(self):
        with tempfile.TemporaryDirectory() as td:
            export_dir = Path(td) / "exports"
            export_dir.mkdir()
            cfg = {
                "reimbursement": {
                    "buyer_name": "Example Ltd.",
                    "buyer_tax_id": "91310000MA00000000",
                },
                "export": {"output_dir": str(export_dir)},
                "email_accounts": [
                    {"name": "Work", "address": "work@example.com", "enabled": True}
                ],
            }
            with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=cfg):
                window = InvoiceReviewApp(Path(td) / "settings.db")
            try:
                window.resize(1280, 800)
                window.show()
                self.app.processEvents()
                window._switch_main_page("settings")
                window.config = cfg
                window._desktop_settings_cfg = cfg
                window._export_dir = export_dir
                window._refresh_common_settings_page()
                self.app.processEvents()

                self.assertEqual(window.settings_mode_stack.currentIndex(), 0)
                self.assertEqual(window.lbl_common_profile_name.text(), "Example Ltd.")
                self.assertEqual(window.lbl_common_profile_tax_id.text(), "91310000MA00000000")
                self.assertEqual(window.lbl_common_export_path.text(), str(export_dir))
                self.assertIn("1 个启用账号", window.lbl_common_mailbox_status.text())
                self.assertFalse(window.settings_tabs.isVisible())
            finally:
                window.close()
                self.app.processEvents()

    def test_advanced_mode_preserves_existing_settings_navigation_and_routes(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value={}):
                window = InvoiceReviewApp(Path(td) / "settings.db")
            try:
                window.resize(1280, 800)
                window.show()
                self.app.processEvents()
                window._switch_main_page("settings")
                window.btn_settings_advanced_mode.click()
                self.app.processEvents()

                self.assertEqual(window.settings_mode_stack.currentIndex(), 1)
                self.assertTrue(window.settings_tabs.isVisible())
                self.assertEqual(window.settings_tabs.tabText(0), "邮箱账户")
                self.assertEqual(window.settings_tabs.tabText(1), "AI 配置")

                window._switch_main_page("settings", sub_tab=2)
                self.assertEqual(window.settings_mode_stack.currentIndex(), 1)
                self.assertEqual(window.settings_tabs.currentIndex(), 1)

                window._switch_main_page("settings")
                window.btn_common_mailbox_manage.click()
                self.assertEqual(window.settings_mode_stack.currentIndex(), 1)
                self.assertEqual(window.settings_tabs.currentIndex(), 0)
            finally:
                window.close()
                self.app.processEvents()

    def test_common_export_folder_action_persists_the_selected_directory(self):
        with tempfile.TemporaryDirectory() as td:
            export_dir = Path(td) / "new-export-location"
            export_dir.mkdir()
            with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value={}):
                window = InvoiceReviewApp(Path(td) / "settings.db")
            try:
                window.config = {"reimbursement": {"buyer_name": "Example"}}
                window._desktop_settings_cfg = window.config
                window._refresh_export_page = Mock()
                with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value={}), patch(
                    "scripts.invoice_fetch.gui.app.QFileDialog.getExistingDirectory",
                    return_value=str(export_dir),
                ), patch("scripts.invoice_fetch.gui.app.save_config") as save:
                    window._choose_common_export_directory()

                save.assert_called_once()
                saved = save.call_args.args[0]
                self.assertEqual(saved["export"]["output_dir"], str(export_dir))
                self.assertEqual(window._export_dir, export_dir)
                self.assertEqual(window.lbl_common_export_path.text(), str(export_dir))
                window._refresh_export_page.assert_called_once()
            finally:
                window.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
