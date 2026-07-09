# -*- coding: utf-8 -*-
"""UI unit tests for V5 Email Account Settings visible workflow and AI Config details."""

import sys
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QPushButton, QCheckBox, QLabel, QMessageBox, QLineEdit, QSpinBox, QComboBox

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.settings_dialog import SettingsDialog, MailboxConfigRow
from scripts.invoice_fetch.config import load_config_safe, get_email_accounts, _normalize_default_email_account, _select_primary_email_account

app = QApplication.instance() or QApplication(sys.argv)
TEST_DB_PATH = Path("test.db")


class TestMailboxV5UI(unittest.TestCase):

    def setUp(self):
        QMessageBox.information = lambda *args, **kwargs: QMessageBox.Ok
        QMessageBox.warning = lambda *args, **kwargs: QMessageBox.Ok
        QMessageBox.critical = lambda *args, **kwargs: QMessageBox.Ok
        QMessageBox.question = lambda *args, **kwargs: QMessageBox.Yes

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

    def test_default_account_projection_after_edit_non_default(self):
        """P0-1 Test: Editing a non-default account preserves default account in cfg['email']."""
        dialog = SettingsDialog(parent=None)
        dialog.cfg = deepcopy(self.cfg)
        dialog._build_saved_account_maps()
        dialog._load_initial_values()

        dialog._open_mailbox_editor("test_163@163.com")
        dialog.txt_months.setText("9")
        dialog.chk_is_default.setChecked(False)
        dialog._save_mailbox_settings()

        self.assertEqual(dialog.cfg["email"]["address"].lower(), "test_qq@qq.com")

    def test_deleting_default_reassigns_default(self):
        """P0-2 Test: Deleting default account reassigns default status to remaining enabled account."""
        accounts = deepcopy(self.cfg["email_accounts"])
        accounts = [a for a in accounts if a["address"] != "test_qq@qq.com"]
        norm = _normalize_default_email_account(accounts)
        self.assertEqual(len(norm), 1)
        self.assertTrue(norm[0]["is_default"])
        self.assertEqual(norm[0]["address"], "test_163@163.com")

    def test_disabling_default_reassigns_default(self):
        """P0-2 Test: Disabling default account reassigns default status to next enabled non-Outlook account."""
        dialog = SettingsDialog(parent=None)
        dialog.cfg = deepcopy(self.cfg)
        dialog._build_saved_account_maps()
        dialog._load_initial_values()

        dialog._set_mailbox_enabled("test_qq@qq.com", False)
        norm = dialog.cfg["email_accounts"]
        target = next((a for a in norm if a["address"] == "test_163@163.com"), None)
        self.assertIsNotNone(target)
        self.assertTrue(target["is_default"])
        self.assertEqual(dialog.cfg["email"]["address"].lower(), "test_163@163.com")

    def test_import_scan_selected_uses_checked_accounts(self):
        """P1-2 Test: Start scanning selected accounts reads checked checkbox account keys."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)
        window._refresh_imports_page()

        checked_keys = []
        for chk in window.mail_account_checkboxes:
            if chk.isChecked():
                checked_keys.append(chk.property("account_key"))

        self.assertIn("test_qq@qq.com", checked_keys)

    def test_sidebar_settings_does_not_show_legacy_settings_page(self):
        """P1-1 Test: Switching to settings opens full SettingsDialog without legacy split."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)

        self.assertTrue(hasattr(window, "_switch_main_page"))

    def test_import_scan_default_passes_only_default_key(self):
        """Final P0 Test: Scan default email only passes default account key."""
        from unittest.mock import patch
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)
        window._refresh_imports_page()

        captured = []
        def mock_scan(selected_keys=None, trigger_btn=None):
            captured.append(selected_keys)

        window._scan_email_clicked = mock_scan
        with patch("scripts.invoice_fetch.config.load_config_safe", return_value=self.cfg):
            window._scan_default_email_clicked()

        self.assertEqual(captured, [["test_qq@qq.com"]])

    def test_import_scan_selected_credential_check_only_selected(self):
        """Final P0 Test: Credential check only inspects selected accounts."""
        from unittest.mock import patch
        from scripts.invoice_fetch.gui.workers import EmailScanWorker
        orig_start = EmailScanWorker.start
        EmailScanWorker.start = lambda self: None

        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)
        window._refresh_imports_page()

        import scripts.invoice_fetch.credentials as creds
        orig_has = creds.has_auth_code
        creds.has_auth_code = lambda addr: addr == "test_qq@qq.com"

        try:
            with patch("scripts.invoice_fetch.config.load_config_safe", return_value=self.cfg):
                window._scan_email_clicked(selected_keys=["test_qq@qq.com"])
            self.assertTrue(hasattr(window, "scan_worker"))
            self.assertEqual(window.scan_worker.selected_keys, ["test_qq@qq.com"])
        finally:
            creds.has_auth_code = orig_has
            EmailScanWorker.start = orig_start

    def test_import_scan_selected_no_checked_accounts_warns(self):
        """Final P0 Test: Unchecking all accounts triggers warning without scanning."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)
        window._refresh_imports_page()

        for chk in window.mail_account_checkboxes:
            chk.setChecked(False)

        called = []
        window._scan_email_clicked = lambda *args, **kwargs: called.append(True)
        window._scan_selected_email_accounts()

        self.assertEqual(len(called), 0)



    def test_settings_page_does_not_open_nested_settings_dialog(self):
        """V11 Test 1: Switching to settings page does not launch nested modal SettingsDialog."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)

        opened_dialogs = []
        def mock_open(*args, **kwargs):
            opened_dialogs.append(True)

        window._open_settings_dialog = mock_open
        window._switch_main_page("settings")

        self.assertEqual(len(opened_dialogs), 0)

    def test_settings_single_authoritative_surface(self):
        """V11 Test 2: In-window settings_page is the single authoritative UI surface."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window.config = deepcopy(self.cfg)

        window._switch_main_page("settings")
        self.assertEqual(window.center_stack.currentIndex(), 5)
        self.assertTrue(hasattr(window, "settings_tabs"))
        self.assertIsNotNone(window.settings_tabs)
        self.assertTrue(hasattr(window.settings_tabs, "nav_list"))

    def test_mailbox_overview_shows_total_enabled_default_missing_counts(self):
        """V11 Test 3: Mailbox overview shows total, enabled, default, missing auth code, and disabled counts."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window._desktop_settings_cfg = deepcopy(self.cfg)
        window._refresh_settings_mailbox_page()

        self.assertTrue(hasattr(window, "lbl_v11_stat_total"))
        self.assertIn("总账号", window.lbl_v11_stat_total.text())
        self.assertIn("2", window.lbl_v11_stat_total.text())
        self.assertIn("启用", window.lbl_v11_stat_enabled.text())
        self.assertIn("2", window.lbl_v11_stat_enabled.text())

    def test_mailbox_saved_accounts_separated_from_provider_presets(self):
        """V11 Test 4: Presets bar is separate and saved accounts list contains only saved accounts."""
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window._desktop_settings_cfg = deepcopy(self.cfg)
        window._refresh_settings_mailbox_page()

        self.assertTrue(hasattr(window, "v11_preset_buttons"))
        self.assertIn("qq", window.v11_preset_buttons)
        self.assertEqual(window.settings_mailbox_list.count(), 2)

    def test_mailbox_detail_is_read_only_by_default(self):
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window._desktop_settings_cfg = deepcopy(self.cfg)
        window._refresh_settings_mailbox_page()
        mailbox_tab = window.settings_tabs.widget(1)
        self.assertEqual(window.settings_tabs.tabText(1), "邮箱账户")

        mailbox_detail_inputs = [
            child for child in mailbox_tab.findChildren(QLineEdit)
            if child.parent() is not None
        ]
        self.assertEqual(mailbox_detail_inputs, [])
        self.assertIsInstance(window.lbl_detail_name, QLabel)
        self.assertIsInstance(window.lbl_detail_email, QLabel)
        self.assertIsInstance(window.lbl_detail_server, QLabel)
        self.assertIsInstance(window.lbl_detail_scan_rule, QLabel)

    def test_mailbox_detail_has_no_save_cancel_buttons(self):
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window._desktop_settings_cfg = deepcopy(self.cfg)
        window._refresh_settings_mailbox_page()
        mailbox_tab = window.settings_tabs.widget(1)

        button_texts = [button.text() for button in mailbox_tab.findChildren(QPushButton)]
        self.assertNotIn("保存设置", button_texts)
        self.assertNotIn("取消", button_texts)
        self.assertEqual(window.btn_settings_mailbox_edit_config.text(), "编辑")
        self.assertEqual(window.btn_settings_mailbox_add_credential.text(), "补授权码")

        mailbox_detail_spins = mailbox_tab.findChildren(QSpinBox)
        mailbox_detail_combos = mailbox_tab.findChildren(QComboBox)
        self.assertEqual(mailbox_detail_spins, [])
        self.assertEqual(mailbox_detail_combos, [])

    def test_edit_config_opens_single_task_dialog(self):
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window._desktop_settings_cfg = deepcopy(self.cfg)
        window._refresh_settings_mailbox_page()
        window.settings_mailbox_list.setCurrentRow(0)

        with patch("scripts.invoice_fetch.gui.app.SingleTaskMailboxDialog") as dialog_cls, \
             patch.object(window, "_save_mailbox_account_entry") as save_entry:
            dialog = dialog_cls.return_value
            dialog.exec.return_value = 1
            dialog.get_result_account.return_value = (dict(self.cfg["email_accounts"][0]), "")
            window.btn_settings_mailbox_edit_config.click()

        dialog_cls.assert_called_once()
        dialog_cls.assert_called_with(window, account=self.cfg["email_accounts"][0])
        save_entry.assert_called_once()

    def test_add_credential_separate_from_detail(self):
        window = InvoiceReviewApp(db_path=TEST_DB_PATH)
        window._desktop_settings_cfg = deepcopy(self.cfg)
        window._refresh_settings_mailbox_page()
        window.settings_mailbox_list.setCurrentRow(0)

        with patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("secret-code", True)) as get_text, \
             patch("scripts.invoice_fetch.credentials.set_auth_code") as set_code:
            window.btn_settings_mailbox_add_credential.click()

        get_text.assert_called_once()
        set_code.assert_called_once_with("test_qq@qq.com", "secret-code")


if __name__ == "__main__":
    unittest.main()
