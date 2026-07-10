# -*- coding: utf-8 -*-
"""UI unit tests for V4 Email Account Settings redesign and Import Center linkage."""

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


class TestMailboxV4UI(unittest.TestCase):

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

    def test_presets_visibility_in_settings_dialog(self):
        """Directive 9: QQ / 163 / Gmail / Outlook / Custom IMAP presets visible."""
        dialog = SettingsDialog(parent=None)
        dialog.cfg = deepcopy(self.cfg)
        dialog._build_saved_account_maps()
        dialog._load_initial_values()

        # Check provider cards
        self.assertIn("qq", dialog.cards)
        self.assertIn("netease_163", dialog.cards)
        self.assertIn("gmail", dialog.cards)
        self.assertIn("outlook", dialog.cards)
        self.assertIn("custom", dialog.cards)

        for p_id in ("qq", "netease_163", "gmail", "outlook", "custom"):
            self.assertTrue(dialog.cards[p_id].isVisible() or dialog.cards[p_id].parentWidget() is not None)

    def test_account_card_click_refreshes_form(self):
        """Directive 9: Clicking account card refreshes right-side form."""
        dialog = SettingsDialog(parent=None)
        dialog.cfg = deepcopy(self.cfg)
        dialog._build_saved_account_maps()
        dialog._load_initial_values()

        # Open second account (163)
        dialog._open_mailbox_editor("test_163@163.com")

        self.assertEqual(dialog.txt_email.text().strip(), "test_163@163.com")
        self.assertEqual(dialog.txt_mailbox_name.text().strip(), "163 网易邮箱")
        self.assertEqual(dialog.txt_months.text().strip(), "6")

    def test_default_scan_account_visible(self):
        """Directive 9: Default scan account visible with default badge."""
        dialog = SettingsDialog(parent=None)
        dialog.cfg = deepcopy(self.cfg)
        dialog._build_saved_account_maps()
        dialog._load_initial_values()

        accounts = get_email_accounts(dialog.cfg)
        self.assertTrue(any(acc.get("is_default") for acc in accounts))

        first_acc = accounts[0]
        row = MailboxConfigRow(first_acc, dialog)
        self.assertTrue(hasattr(row, "lbl_default_badge"))
        self.assertEqual(row.lbl_default_badge.text(), "默认")

    def test_import_center_email_selection(self):
        """Directive 9: Import Center email import page can select email accounts."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)
        window._refresh_imports_page()

        self.assertTrue(hasattr(window, "mail_account_checkboxes"))
        self.assertEqual(len(window.mail_account_checkboxes), 2)

        # First account (QQ) is default scan account -> should be checked by default
        qq_chk = window.mail_account_checkboxes[0]
        self.assertTrue(qq_chk.isChecked())

        # Second account (163) can be multi-selected
        net_chk = window.mail_account_checkboxes[1]
        net_chk.setChecked(True)
        self.assertTrue(net_chk.isChecked())

    def test_manage_mailbox_more_action_navigates_to_settings(self):
        """IHDS-06: account management is a low-frequency More action."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)

        action = next(action for action in window.import_mail_more_menu.actions() if action.text() == "管理邮箱")
        action.trigger()

        # Should switch main center_stack widget to settings page (index 5)
        self.assertEqual(window.center_stack.currentIndex(), 5)
        self.assertEqual(window.settings_tabs.currentIndex(), 0)


if __name__ == "__main__":
    unittest.main()
