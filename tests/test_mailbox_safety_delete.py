import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from tests.test_settings_dialog import SettingsDialogTestMixin
from scripts.invoice_fetch.config import is_outlook_like_account



class MailboxSafetyDeleteTests(SettingsDialogTestMixin, unittest.TestCase):

    def _multi_account_config(self, outlook_address="abc@outlook.com"):
        return {
            "email": {"provider": "qq", "address": "if16888@qq.com"},
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
            "email_accounts": [
                {
                    "name": "QQ",
                    "enabled": True,
                    "provider": "qq",
                    "address": "if16888@qq.com",
                    "username": "if16888@qq.com",
                    "mailbox_key": "qq-primary",
                    "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                    "search": {"folder": "INBOX", "months_back": 3},
                },
                {
                    "name": "Outlook",
                    "enabled": True,
                    "provider": "outlook",
                    "address": outlook_address,
                    "username": outlook_address,
                    "mailbox_key": "outlook-primary",
                    "imap": {"server": "outlook.office365.com", "port": 993, "ssl": True},
                    "search": {"folder": "INBOX", "months_back": 6},
                },
            ],
            "ai": {"provider": "none", "model": "", "enabled": False},
        }

    def _save_without_side_effects(self, dialog):
        dialog.test_success = True
        with patch("scripts.invoice_fetch.config.save_config"), patch(
            "scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat",
            return_value={"loaded": True},
        ), patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), patch(
            "scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning"
        ), patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.critical"), patch(
            "scripts.invoice_fetch.credentials.has_auth_code", return_value=False
        ):
            dialog._save_mailbox_settings()

    # 1. Outlook-like custom IMAP tests
    def test_outlook_like_detection_applies_to_provider_address_and_server(self):
        # provider
        self.assertTrue(is_outlook_like_account("outlook", "test@test.com", "imap.test.com"))
        # server
        self.assertTrue(is_outlook_like_account("custom", "test@test.com", "outlook.office365.com"))
        self.assertTrue(is_outlook_like_account("custom", "test@test.com", "imap-mail.outlook.com"))
        self.assertTrue(is_outlook_like_account("custom", "test@test.com", "office365.example.com"))
        self.assertTrue(is_outlook_like_account("custom", "test@test.com", "hotmail.com"))
        self.assertTrue(is_outlook_like_account("custom", "test@test.com", "outlook-server.com"))
        # address domain
        self.assertTrue(is_outlook_like_account("custom", "test@outlook.com", "imap.custom.com"))
        self.assertTrue(is_outlook_like_account("custom", "test@hotmail.com", "imap.custom.com"))
        self.assertTrue(is_outlook_like_account("custom", "test@live.com", "imap.custom.com"))
        self.assertTrue(is_outlook_like_account("custom", "test@msn.com", "imap.custom.com"))
        # Non-outlook
        self.assertFalse(is_outlook_like_account("custom", "outlook-test@company.com", "imap.company.com"))
        self.assertFalse(is_outlook_like_account("qq", "test@qq.com", "imap.qq.com"))

    def test_custom_imap_outlook_host_cannot_be_saved_as_enabled(self):
        dialog = self._make_dialog()
        self._select(dialog, "custom")
        dialog.txt_email.setText("tester@outlook-custom.com")
        dialog.txt_imap_server.setText("outlook.office365.com")
        dialog.txt_imap_port.setText("993")
        dialog.test_success = True

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn, \
             patch("scripts.invoice_fetch.config.save_config") as mock_save:
            dialog._save_mailbox_settings()
            mock_warn.assert_called_once()
            mock_save.assert_not_called()

    def test_custom_imap_outlook_host_save_shows_oauth2_warning(self):
        dialog = self._make_dialog()
        self._select(dialog, "custom")
        dialog.txt_email.setText("tester@custom.com")
        dialog.txt_imap_server.setText("imap-mail.outlook.com")
        dialog.txt_imap_port.setText("993")
        dialog.test_success = True

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn:
            dialog._save_mailbox_settings()
            mock_warn.assert_called_once()
            self.assertIn("需要 OAuth2/XOAUTH2", mock_warn.call_args[0][2])

    def test_blocked_outlook_like_save_does_not_write_keyring_secret(self):
        dialog = self._make_dialog()
        self._select(dialog, "custom")
        dialog.txt_email.setText("tester@outlook.com")
        dialog.txt_auth_code.setText("mypassword")
        dialog.test_success = True

        with patch("scripts.invoice_fetch.credentials.set_auth_code") as mock_keyring, \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn:
            dialog._save_mailbox_settings()
            mock_keyring.assert_not_called()
            mock_warn.assert_called_once()

    def test_blocked_outlook_like_save_does_not_append_email_accounts(self):
        dialog = self._make_dialog()
        orig_len = len(dialog.cfg.get("email_accounts", []))
        self._select(dialog, "outlook")
        dialog.txt_email.setText("new-tester@outlook.com")
        dialog.test_success = True

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn:
            dialog._save_mailbox_settings()
            self.assertEqual(len(dialog.cfg.get("email_accounts", [])), orig_len)

    def test_provider_custom_non_outlook_imap_can_still_save(self):
        dialog = self._make_dialog()
        self._select(dialog, "custom")
        dialog.txt_email.setText("tester@mycompany.com")
        dialog.txt_imap_server.setText("imap.mycompany.com")
        dialog.txt_imap_port.setText("993")
        dialog.txt_auth_code.setText("dummy")
        dialog.test_success = True

        with patch("scripts.invoice_fetch.config.save_config") as mock_save, \
             patch("scripts.invoice_fetch.credentials.set_auth_code"), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"):
            dialog._save_mailbox_settings()
            mock_save.assert_called_once()

    def test_custom_imap_outlook_host_scan_is_skipped(self):
        from scripts.invoice_fetch.__main__ import _scan_mailboxes_with_db
        db = MagicMock()
        cfg = {
            "email_accounts": [
                {
                    "mailbox_key": "custom-outlook",
                    "address": "test@custom.com",
                    "provider": "custom",
                    "enabled": True,
                    "imap": {"server": "outlook.office365.com", "port": 993, "ssl": True},
                    "search": {"months_back": 3},
                    "auth_code": "dummy",
                }
            ]
        }
        logs = []
        result = _scan_mailboxes_with_db(db, Path("invoices.db"), cfg, log_callback=logs.append)
        self.assertTrue(any("跳过 Outlook/Microsoft 邮箱" in log for log in logs))

    # 2. Delete mailbox config tests
    def test_delete_current_mailbox_removes_only_that_account(self):
        dialog = self._make_dialog(self._multi_account_config(), saved_addresses=("if16888@qq.com", "abc@outlook.com"))
        dialog.txt_email.setText("if16888@qq.com")
        self.app.processEvents()

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information") as mock_info, \
             patch("scripts.invoice_fetch.config.save_config") as mock_save, \
             patch("scripts.invoice_fetch.credentials.delete_auth_code") as mock_delete:
            dialog._delete_current_mailbox()
            self.assertEqual(len(dialog.cfg["email_accounts"]), 1)
            self.assertEqual(dialog.cfg["email_accounts"][0]["address"], "abc@outlook.com")
            mock_delete.assert_called_once_with("if16888@qq.com")
            mock_info.assert_called_once()

    def test_delete_current_mailbox_removes_keyring_secret(self):
        dialog = self._make_dialog(self._multi_account_config(), saved_addresses=("if16888@qq.com",))
        dialog.txt_email.setText("if16888@qq.com")
        self.app.processEvents()

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code") as mock_delete:
            dialog._delete_current_mailbox()
            mock_delete.assert_called_once_with("if16888@qq.com")

    def test_delete_current_mailbox_preserves_other_same_provider_accounts(self):
        config = {
            "email_accounts": [
                {
                    "mailbox_key": "qq1",
                    "address": "qq1@qq.com",
                    "provider": "qq",
                    "enabled": True,
                    "imap": {"server": "imap.qq.com"},
                },
                {
                    "mailbox_key": "qq2",
                    "address": "qq2@qq.com",
                    "provider": "qq",
                    "enabled": True,
                    "imap": {"server": "imap.qq.com"},
                },
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com", "qq2@qq.com"))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()
            self.assertEqual(len(dialog.cfg["email_accounts"]), 1)
            self.assertEqual(dialog.cfg["email_accounts"][0]["address"], "qq2@qq.com")

    def test_delete_current_mailbox_preserves_imported_invoices_and_attachments(self):
        db = MagicMock()
        db._normalize_mailbox_key = lambda k: k or "legacy"
        
        from scripts.invoice_fetch.db import InvoiceDB
        InvoiceDB.remove_mailbox_scan_state(db, "my_mailbox")
        
        db._conn.execute.assert_any_call("DELETE FROM emails WHERE mailbox_key = ?", ("my_mailbox",))
        db._conn.execute.assert_any_call("DELETE FROM processed_emails WHERE mailbox_key = ?", ("my_mailbox",))
        for call_args in db._conn.execute.call_args_list:
            self.assertNotIn("invoices", call_args[0][0].lower())

    def test_deleting_primary_account_selects_next_enabled_supported_account(self):
        config = {
            "email": {"provider": "qq", "address": "qq1@qq.com"},
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"},
                {"address": "qq2@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq2"},
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com", "qq2@qq.com"))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()
        
        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()
            self.assertEqual(dialog.cfg["email"]["address"], "qq2@qq.com")

    def test_deleting_last_account_clears_email_form(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"}
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com",))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()
            self.assertEqual(dialog.txt_email.text(), "")
            self.assertEqual(dialog.txt_months.text(), "3")

    def test_delete_button_disabled_for_unsaved_email(self):
        dialog = self._make_dialog()
        dialog.txt_email.setText("unsaved@qq.com")
        self.app.processEvents()
        self.assertFalse(dialog.btn_delete_mailbox.isEnabled())

    def test_delete_mailbox_without_existing_keyring_secret_is_safe(self):
        dialog = self._make_dialog(self._multi_account_config(), saved_addresses=())
        dialog.txt_email.setText("if16888@qq.com")
        self.app.processEvents()

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("keyring.delete_password", side_effect=Exception("Password not found")):
            dialog._delete_current_mailbox()

    def test_remove_mailbox_scan_state_does_not_delete_invoice_rows(self):
        db = MagicMock()
        db._normalize_mailbox_key = lambda k: k or "legacy"
        from scripts.invoice_fetch.db import InvoiceDB
        InvoiceDB.remove_mailbox_scan_state(db, "my_mailbox")
        
        for call in db._conn.execute.call_args_list:
            query = call[0][0].lower()
            self.assertNotIn("invoices", query)

    # 3. Multiple same-provider accounts tests
    def test_saving_second_qq_account_appends_not_overwrites_first(self):
        dialog = self._make_dialog()
        dialog.txt_email.setText("b@qq.com")
        dialog.test_success = True
        
        with patch("scripts.invoice_fetch.config.save_config") as mock_save, \
             patch("scripts.invoice_fetch.credentials.set_auth_code"), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"):
            dialog._save_mailbox_settings()
            addresses = [acc["address"] for acc in dialog.cfg["email_accounts"]]
            self.assertIn("if16888@qq.com", addresses)
            self.assertIn("b@qq.com", addresses)

    def test_saving_existing_email_updates_that_account_only(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1", "search": {"months_back": 3}}
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com",))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()
        
        dialog.txt_months.setText("12")
        dialog.test_success = True
        
        with patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.set_auth_code"), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"):
            dialog._save_mailbox_settings()
            self.assertEqual(len(dialog.cfg["email_accounts"]), 1)
            self.assertEqual(dialog.cfg["email_accounts"][0]["search"]["months_back"], 12)

    def test_deleting_one_qq_account_keeps_other_qq_account(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"},
                {"address": "qq2@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq2"},
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com", "qq2@qq.com"))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()
            self.assertEqual(len(dialog.cfg["email_accounts"]), 1)
            self.assertEqual(dialog.cfg["email_accounts"][0]["address"], "qq2@qq.com")

    def test_provider_card_selection_does_not_treat_provider_as_unique_identity(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"},
                {"address": "qq2@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq2"},
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com", "qq2@qq.com"))
        dialog.txt_email.setText("qq2@qq.com")
        self.app.processEvents()
        
        dialog._on_provider_card_clicked(dialog.cards["qq"])
        self.assertEqual(dialog.txt_email.text(), "qq2@qq.com")

    def test_disabled_outlook_legacy_account_is_not_returned_for_runtime_scan(self):
        from scripts.invoice_fetch.config import get_email_accounts
        cfg = {
            "email_accounts": [
                {"address": "qq@qq.com", "provider": "qq", "enabled": True},
                {"address": "old@outlook.com", "provider": "outlook", "enabled": False},
            ]
        }
        accounts = get_email_accounts(cfg)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["address"], "qq@qq.com")


    def test_deleting_outlook_account_disables_delete_button_when_no_saved_outlook_remains(self):
        config = {
            "email_accounts": [
                {"address": "tester@outlook.com", "provider": "outlook", "enabled": True, "mailbox_key": "outlook1"}
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("tester@outlook.com",))
        dialog.txt_email.setText("tester@outlook.com")
        self.app.processEvents()
        self.assertTrue(dialog.btn_delete_mailbox.isEnabled())

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()

        # No saved Outlook account remains
        self.assertFalse(dialog.btn_delete_mailbox.isEnabled())

    def test_deleting_account_loads_next_enabled_supported_account(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"},
                {"address": "qq2@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq2"},
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com", "qq2@qq.com"))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()

        # Should load the other QQ account
        self.assertEqual(dialog.txt_email.text(), "qq2@qq.com")

    def test_deleting_last_account_clears_form_and_disables_delete(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"}
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com",))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()
        self.assertTrue(dialog.btn_delete_mailbox.isEnabled())

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()

        self.assertEqual(dialog.txt_email.text(), "")
        self.assertFalse(dialog.btn_delete_mailbox.isEnabled())

    def test_delete_button_disabled_for_empty_email_after_delete(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"}
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com",))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()

        self.assertEqual(dialog.txt_email.text(), "")
        self.assertFalse(dialog.btn_delete_mailbox.isEnabled())

    def test_delete_button_disabled_for_unsaved_outlook_provider_state(self):
        dialog = self._make_dialog()
        self._select(dialog, "outlook")
        dialog.txt_email.setText("unsaved@outlook.com")
        self.app.processEvents()
        self.assertFalse(dialog.btn_delete_mailbox.isEnabled())

    def test_deleted_account_removed_from_saved_maps(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"}
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com",))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()

        self.assertIn("qq1@qq.com", dialog._saved_accounts_by_address)

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()

        self.assertNotIn("qq1@qq.com", dialog._saved_accounts_by_address)

    def test_stale_current_loaded_account_cleared_after_delete(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"}
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com",))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()

        self.assertEqual(dialog._loaded_account_address, "qq1@qq.com")

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()

        self.assertEqual(dialog._loaded_account_address, "")
        self.assertEqual(dialog._loaded_account_mailbox_key, "")

    def test_qq_flow_still_works_after_deleting_outlook(self):
        config = {
            "email_accounts": [
                {"address": "tester@outlook.com", "provider": "outlook", "enabled": True, "mailbox_key": "outlook1"},
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"}
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("tester@outlook.com", "qq1@qq.com"))
        dialog.txt_email.setText("tester@outlook.com")
        self.app.processEvents()

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), \
             patch("scripts.invoice_fetch.config.save_config"), \
             patch("scripts.invoice_fetch.credentials.delete_auth_code"):
            dialog._delete_current_mailbox()

        # Should load the QQ account
        self.assertEqual(dialog.txt_email.text(), "qq1@qq.com")
        self.assertEqual(dialog._get_selected_provider(), "qq")
        self.assertTrue(dialog.btn_next.isEnabled())

    def test_switching_to_provider_without_saved_account_disables_delete_button(self):
        config = {
            "email_accounts": [
                {"address": "qq1@qq.com", "provider": "qq", "enabled": True, "mailbox_key": "qq1"}
            ]
        }
        dialog = self._make_dialog(config, saved_addresses=("qq1@qq.com",))
        dialog.txt_email.setText("qq1@qq.com")
        self.app.processEvents()
        self.assertTrue(dialog.btn_delete_mailbox.isEnabled())

        # Switch to outlook which has no saved account
        self._select(dialog, "outlook")
        self.app.processEvents()
        self.assertFalse(dialog.btn_delete_mailbox.isEnabled())


if __name__ == "__main__":
    unittest.main()
