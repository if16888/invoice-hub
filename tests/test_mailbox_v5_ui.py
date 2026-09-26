# -*- coding: utf-8 -*-
"""UI unit tests for V5 Email Account Settings visible workflow and AI Config details."""

import sys
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QPushButton, QCheckBox, QLabel, QMessageBox, QLineEdit, QSpinBox, QComboBox
from shiboken6 import isValid

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.settings_dialog import SettingsDialog, MailboxConfigRow
from scripts.invoice_fetch.config import load_config_safe, get_email_accounts, _normalize_default_email_account, _select_primary_email_account

app = QApplication.instance() or QApplication(sys.argv)


class TestMailboxV5UI(unittest.TestCase):

    def tearDown(self):
        # This module historically left many top-level InvoiceReviewApp and
        # SettingsDialog instances alive.  Their deferred Qt callbacks can
        # starve the next module's mobile-upload worker in the full suite.
        widgets = [
            widget
            for widget in list(app.topLevelWidgets())
            if widget is not None and isValid(widget)
        ]
        for widget in widgets:
            close = getattr(widget, "close", None)
            if isValid(widget) and callable(close):
                close()
        app.processEvents()

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.db_path = Path(self._temp_dir.name) / "test.db"

        for method_name, ret_val in (
            ("information", QMessageBox.Ok),
            ("warning", QMessageBox.Ok),
            ("critical", QMessageBox.Ok),
            ("question", QMessageBox.Yes),
        ):
            p = patch.object(QMessageBox, method_name, return_value=ret_val)
            p.start()
            self.addCleanup(p.stop)

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


    def test_import_center_uses_more_menu_for_low_frequency_actions(self):
        """IHDS-06: low-frequency account and failure actions are not duplicated."""
        window = InvoiceReviewApp(db_path=self.db_path)
        window.config = deepcopy(self.cfg)
        window._refresh_imports_page()

        self.assertTrue(hasattr(window, "mail_account_checkboxes"))
        action_texts = [action.text() for action in window.import_mail_more_menu.actions()]
        self.assertIn("管理邮箱", action_texts)
        self.assertIn("失败明细", action_texts)
        self.assertFalse(hasattr(window, "btn_view_failed_details"))

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


    def test_import_scan_default_passes_only_default_key(self):
        """Final P0 Test: Scan default email only passes default account key."""
        from unittest.mock import patch
        window = InvoiceReviewApp(db_path=self.db_path)
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

        window = InvoiceReviewApp(db_path=self.db_path)
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
        window = InvoiceReviewApp(db_path=self.db_path)
        window.config = deepcopy(self.cfg)
        window._refresh_imports_page()

        for chk in window.mail_account_checkboxes:
            chk.setChecked(False)

        called = []
        window._scan_email_clicked = lambda *args, **kwargs: called.append(True)
        window._scan_selected_email_accounts()

        self.assertEqual(len(called), 0)


    def test_mailbox_overview_uses_master_detail_without_summary_duplication(self):
        """IHDS-09: account identity and status live in the master-detail surface."""
        window = InvoiceReviewApp(db_path=self.db_path)
        window._desktop_settings_cfg = deepcopy(self.cfg)
        window._refresh_settings_mailbox_page()

        self.assertFalse(hasattr(window, "stat_box_overview"))
        self.assertEqual(window.settings_mailbox_list.count(), 2)
        self.assertTrue(hasattr(window, "lbl_detail_email"))


    def test_mailbox_detail_has_no_save_cancel_buttons(self):
        window = InvoiceReviewApp(db_path=self.db_path)
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
        window = InvoiceReviewApp(db_path=self.db_path)
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
        window = InvoiceReviewApp(db_path=self.db_path)
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
