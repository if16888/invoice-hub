import json
import sys
import unittest
from unittest.mock import MagicMock, patch

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QWidget
except ImportError:
    Qt, QKeySequence, QTest = None, None, None
    QApplication, QDialog, QWidget = None, None, None


AUTH_CODE = "mail-auth-code-should-never-leak"
SAVED_AUTH_CODE = "saved-mail-auth-code"


class SettingsSecretPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def _make_parent(self):
        parent = QWidget()
        parent.config = {}
        parent.write_log = MagicMock()
        self.addCleanup(self._cleanup_widget, parent)
        return parent

    def _cleanup_widget(self, widget):
        widget.close()
        widget.deleteLater()
        self.app.processEvents()

    def _set_clipboard_or_skip(self, text):
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.app.processEvents()
        if clipboard.text() != text:
            self.skipTest("Windows clipboard is unavailable in this test session")

    def _make_dialog(self, *, saved=False):
        from scripts.invoice_fetch.gui.settings_dialog import SettingsDialog

        config = {
            "email": {"provider": "qq", "address": "tester@qq.com"},
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
            "ai": {"provider": "none", "model": "", "enabled": False},
        }
        parent = self._make_parent()
        with patch(
            "scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat",
            return_value=config,
        ), patch("scripts.invoice_fetch.credentials.has_auth_code", return_value=saved):
            dialog = SettingsDialog(parent)
        self.addCleanup(self._cleanup_widget, dialog)
        return dialog, parent

    def _save_dialog(self, dialog):
        with patch("scripts.invoice_fetch.config.save_config"), patch(
            "scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat",
            return_value={"loaded": True},
        ), patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), patch(
            "scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning"
        ), patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.critical"):
            dialog._save_mailbox_settings()

    def test_secure_password_field_blocks_copy_and_cut_methods(self):
        from scripts.invoice_fetch.gui.settings_dialog import SecurePasswordLineEdit

        field = SecurePasswordLineEdit()
        self.addCleanup(self._cleanup_widget, field)
        field.setText(AUTH_CODE)
        field.selectAll()
        self._set_clipboard_or_skip("clipboard-sentinel")

        field.copy()
        self.assertEqual(QApplication.clipboard().text(), "clipboard-sentinel")
        field.cut()
        self.assertEqual(QApplication.clipboard().text(), "clipboard-sentinel")
        self.assertEqual(field.text(), AUTH_CODE)

    def test_secure_password_field_blocks_copy_and_cut_shortcuts(self):
        from scripts.invoice_fetch.gui.settings_dialog import SecurePasswordLineEdit

        field = SecurePasswordLineEdit()
        self.addCleanup(self._cleanup_widget, field)
        field.show()
        field.setFocus()
        field.setText(AUTH_CODE)
        field.selectAll()
        self._set_clipboard_or_skip("clipboard-sentinel")

        QTest.keyClick(field, Qt.Key_C, Qt.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), "clipboard-sentinel")
        QTest.keyClick(field, Qt.Key_X, Qt.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), "clipboard-sentinel")
        self.assertEqual(field.text(), AUTH_CODE)

    def test_secure_password_field_keeps_paste_and_omits_copy_cut_menu_actions(self):
        from scripts.invoice_fetch.gui.settings_dialog import SecurePasswordLineEdit

        field = SecurePasswordLineEdit()
        self.addCleanup(self._cleanup_widget, field)
        self._set_clipboard_or_skip(AUTH_CODE)

        field.paste()
        self.assertEqual(field.text(), AUTH_CODE)
        menu = field.createStandardContextMenu()
        self.addCleanup(menu.deleteLater)
        labels = " ".join(action.text() for action in menu.actions())
        self.assertNotIn(QKeySequence(QKeySequence.Copy).toString(), labels)
        self.assertNotIn(QKeySequence(QKeySequence.Cut).toString(), labels)
        self.assertIn(QKeySequence(QKeySequence.Paste).toString(), labels)

    def test_existing_mail_credential_is_never_loaded_into_field(self):
        dialog, _parent = self._make_dialog(saved=True)

        self.assertEqual(dialog.txt_auth_code.text(), "")
        self.assertEqual(dialog.txt_auth_code.placeholderText(), "已安全保存，重新输入可覆盖")
        self.assertIn("已安全保存到系统凭据管理器", dialog.lbl_cred_status.text())

    def test_empty_field_uses_saved_credential_for_connection_test(self):
        dialog, _parent = self._make_dialog(saved=True)
        dialog.txt_auth_code.clear()

        with patch(
            "scripts.invoice_fetch.credentials.get_auth_code",
            return_value=SAVED_AUTH_CODE,
        ) as get_auth_code, patch("scripts.invoice_fetch.mail_fetcher.MailFetcher") as fetcher_cls:
            dialog._test_connection_clicked()
            worker = dialog._mailbox_test_worker
            self.assertIsNotNone(worker)
            self.assertTrue(worker.wait(2000), "mailbox test worker did not finish")
            self.app.processEvents()

        get_auth_code.assert_called_once_with("tester@qq.com")
        self.assertEqual(fetcher_cls.call_args.kwargs["auth_code"], SAVED_AUTH_CODE)
        self.assertTrue(dialog.test_success)

    def test_empty_field_uses_saved_credential_when_saving(self):
        dialog, _parent = self._make_dialog(saved=True)
        dialog.test_success = True
        dialog.txt_auth_code.clear()

        with patch(
            "scripts.invoice_fetch.credentials.get_auth_code",
            return_value=SAVED_AUTH_CODE,
        ) as get_auth_code, patch("scripts.invoice_fetch.credentials.set_auth_code") as set_auth_code:
            with patch("scripts.invoice_fetch.credentials.has_auth_code", return_value=True):
                self._save_dialog(dialog)

        get_auth_code.assert_called_once_with("tester@qq.com")
        set_auth_code.assert_not_called()
        self.assertIs(dialog.settings_stack.currentWidget(), dialog.page_settings_home)
        self.assertEqual(dialog.tab_widget.currentIndex(), 0)

    def test_new_credential_overwrites_saved_value_and_field_is_cleared(self):
        dialog, parent = self._make_dialog(saved=True)
        dialog.txt_auth_code.setText(AUTH_CODE)
        dialog.test_success = True

        with patch("scripts.invoice_fetch.credentials.set_auth_code") as set_auth_code:
            self._save_dialog(dialog)

        set_auth_code.assert_called_once_with("tester@qq.com", AUTH_CODE)
        self.assertEqual(dialog.txt_auth_code.text(), "")
        self.assertEqual(dialog.txt_auth_code.placeholderText(), "已安全保存，重新输入可覆盖")
        rendered_logs = " ".join(str(call) for call in parent.write_log.call_args_list)
        self.assertNotIn(AUTH_CODE, rendered_logs)
        self.assertNotIn(AUTH_CODE, json.dumps(dialog.cfg, ensure_ascii=False))

    def test_save_without_any_credential_does_not_claim_secret_is_saved(self):
        dialog, _parent = self._make_dialog(saved=False)
        dialog.test_success = True

        with patch("scripts.invoice_fetch.credentials.get_auth_code", return_value="") as get_auth_code, patch(
            "scripts.invoice_fetch.credentials.has_auth_code", return_value=False
        ):
            self._save_dialog(dialog)

        get_auth_code.assert_not_called()
        self.assertIn("尚未配置", dialog.lbl_cred_status.text())
        self.assertEqual(dialog.txt_auth_code.placeholderText(), "请输入邮箱授权码（非登录密码）")


if __name__ == "__main__":
    unittest.main()
