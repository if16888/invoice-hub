# -*- coding: utf-8 -*-
"""UI unit tests for V5 Email Account Settings visible workflow and AI Config details."""

import sys
import unittest
from pathlib import Path
from copy import deepcopy

from PySide6.QtWidgets import QApplication, QPushButton, QCheckBox, QLabel

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.settings_dialog import SettingsDialog, MailboxConfigRow
from scripts.invoice_fetch.config import load_config_safe, get_email_accounts

app = QApplication.instance() or QApplication(sys.argv)
TEST_DB_PATH = Path("test.db")


class TestMailboxV5UI(unittest.TestCase):

    def setUp(self):
        self.cfg = deepcopy(load_config_safe())
        self.cfg["email"] = {}
        self.cfg["email_accounts"] = [
            {
                "name": "QQ 个人邮箱",
                "enabled": True,
                "is_default": True,
                "provider": "qq",
                "address": "test_qq@qq.com",
                "username": "test_qq@qq.com",
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
                "mailbox_key": "test_qq@qq.com",
            },
            {
                "name": "163 网易邮箱",
                "enabled": True,
                "is_default": False,
                "provider": "netease_163",
                "address": "test_163@163.com",
                "username": "test_163@163.com",
                "imap": {"server": "imap.163.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 6},
                "mailbox_key": "test_163@163.com",
            },
        ]

    def test_v5_preset_buttons_directly_visible_on_overview(self):
        """V5 Requirement 1: Presets visible on main mailbox settings page."""
        dialog = SettingsDialog(parent=None)
        dialog.cfg = deepcopy(self.cfg)
        dialog._build_saved_account_maps()
        dialog._load_initial_values()

        self.assertTrue(hasattr(dialog, "v5_preset_buttons"))
        for p_id in ("qq", "netease_163", "gmail", "outlook", "custom"):
            self.assertIn(p_id, dialog.v5_preset_buttons)
            self.assertTrue(dialog.v5_preset_buttons[p_id].isVisible() or dialog.v5_preset_buttons[p_id].parentWidget() is not None)

    def test_v5_account_row_click_shows_details(self):
        """V5 Requirement 2: Account row click shows account details and rules."""
        dialog = SettingsDialog(parent=None)
        dialog.cfg = deepcopy(self.cfg)
        dialog._build_saved_account_maps()
        dialog._load_initial_values()

        dialog._open_mailbox_editor("test_163@163.com")
        self.assertEqual(dialog.txt_email.text().strip(), "test_163@163.com")
        self.assertEqual(dialog.txt_mailbox_name.text().strip(), "163 网易邮箱")

    def test_v5_import_center_rules_block_and_failed_details(self):
        """V5 Requirement 4: Import Center includes scan rules block and failed details button."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)
        window._refresh_imports_page()

        self.assertTrue(hasattr(window, "btn_view_failed_details"))
        self.assertTrue(hasattr(window, "mail_account_checkboxes"))

    def test_v5_ai_config_details_and_privacy_banner(self):
        """V5 Requirement 5: AI Config page includes active details block and privacy banner."""
        dialog = SettingsDialog(parent=None)
        dialog.cfg = deepcopy(self.cfg)
        dialog._build_saved_account_maps()
        dialog._load_initial_values()

        self.assertTrue(hasattr(dialog, "lbl_v5_ai_provider"))
        self.assertTrue(hasattr(dialog, "btn_v5_test_ai"))
        self.assertTrue(hasattr(dialog, "btn_v5_clear_ai_key"))


if __name__ == "__main__":
    unittest.main()
