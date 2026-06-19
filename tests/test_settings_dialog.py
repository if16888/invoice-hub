import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


class SettingsDialogTestMixin:
    @classmethod
    def setUpClass(cls):
        try:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def _cleanup_widget(self, widget):
        widget.close()
        widget.deleteLater()
        self.app.processEvents()

    def _make_dialog(self):
        from scripts.invoice_fetch.gui.settings_dialog import SettingsDialog

        config = {
            "email": {"provider": "qq", "address": "if16888@qq.com"},
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
            "ai": {"provider": "none", "model": "", "enabled": False},
        }
        parent = QWidget()
        parent.config = {}
        parent.write_log = MagicMock()
        self.addCleanup(self._cleanup_widget, parent)
        with patch(
            "scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat",
            return_value=config,
        ), patch("scripts.invoice_fetch.credentials.has_auth_code", return_value=False):
            dialog = SettingsDialog(parent)
        self.addCleanup(self._cleanup_widget, dialog)
        return dialog

    def _select(self, dialog, provider):
        dialog.cards[provider].click()
        self.app.processEvents()


class SettingsDialogProviderTests(SettingsDialogTestMixin, unittest.TestCase):

    def test_switching_known_provider_rewrites_only_email_domain(self):
        dialog = self._make_dialog()

        self._select(dialog, "outlook")
        self.assertEqual(dialog.txt_email.text(), "if16888@outlook.com")
        self._select(dialog, "gmail")
        self.assertEqual(dialog.txt_email.text(), "if16888@gmail.com")
        self._select(dialog, "qq")
        self.assertEqual(dialog.txt_email.text(), "if16888@qq.com")

    def test_outlook_keeps_hotmail_and_live_family_domains(self):
        dialog = self._make_dialog()
        for email in ("abc@hotmail.com", "abc@live.com"):
            dialog.txt_email.setText(email)

            self._select(dialog, "outlook")

            self.assertEqual(dialog.txt_email.text(), email)

    def test_outlook_keeps_custom_domain_and_shows_oauth_warning(self):
        dialog = self._make_dialog()
        dialog.txt_email.setText("abc@company.com")

        self._select(dialog, "outlook")

        self.assertEqual(dialog.txt_email.text(), "abc@company.com")
        self.assertIn("Microsoft 365", dialog.lbl_provider_hint.text())
        self.assertIn("OAuth2", dialog.lbl_provider_hint.text())

    def test_custom_provider_never_rewrites_email_domain(self):
        dialog = self._make_dialog()
        dialog.txt_email.setText("abc@qq.com")

        self._select(dialog, "custom")

        self.assertEqual(dialog.txt_email.text(), "abc@qq.com")

    def test_provider_detection_requires_an_exact_known_domain(self):
        dialog = self._make_dialog()
        self._select(dialog, "outlook")

        dialog.txt_email.setText("abc@qq.com.example")

        self.assertEqual(dialog._get_selected_provider(), "outlook")
        self.assertIn("Microsoft 365", dialog.lbl_provider_hint.text())

    def test_empty_email_uses_provider_specific_placeholder(self):
        dialog = self._make_dialog()
        dialog.txt_email.clear()

        self._select(dialog, "outlook")

        self.assertEqual(dialog.txt_email.text(), "")
        self.assertEqual(dialog.txt_email.placeholderText(), "请输入完整 Outlook 邮箱地址")

    def test_outlook_switch_applies_secure_imap_defaults(self):
        dialog = self._make_dialog()

        self._select(dialog, "outlook")

        self.assertEqual(dialog.txt_imap_server.text(), "outlook.office365.com")
        self.assertEqual(dialog.txt_imap_port.text(), "993")
        self.assertIn("SSL/TLS", dialog.lbl_imap_security.text())
        self.assertIn("启用", dialog.lbl_imap_security.text())

    def test_manual_advanced_settings_require_confirmation_before_reset(self):
        dialog = self._make_dialog()
        dialog.advanced_group.setVisible(True)
        dialog.txt_imap_server.setText("imap.company.example")
        dialog.txt_imap_port.setText("1993")

        with patch(
            "scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question",
            return_value=QMessageBox.No,
        ):
            self._select(dialog, "outlook")

        self.assertEqual(dialog._get_selected_provider(), "qq")
        self.assertEqual(dialog.txt_imap_server.text(), "imap.company.example")
        self.assertEqual(dialog.txt_imap_port.text(), "1993")

    def test_outlook_inline_guidance_and_help_dialog_are_specific(self):
        dialog = self._make_dialog()
        self._select(dialog, "outlook")

        self.assertIn("个人 Outlook/Hotmail/Live", dialog.lbl_outlook_guidance.text())
        self.assertIn("OAuth2/Graph", dialog.lbl_outlook_guidance.text())
        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information") as info:
            dialog._show_auth_code_help()

        help_text = info.call_args.args[2]
        self.assertIn("完整邮箱地址", help_text)
        self.assertIn("outlook.office365.com", help_text)
        self.assertIn("993", help_text)
        self.assertIn("OAuth2", help_text)


class OutlookConnectionDiagnosticsTests(SettingsDialogTestMixin, unittest.TestCase):
    AUTH_CODE = "outlook-secret-must-not-leak"

    def _run_failure(self, message):
        dialog = self._make_dialog()
        self._select(dialog, "outlook")
        dialog.txt_auth_code.setText(self.AUTH_CODE)
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher") as fetcher_cls:
            fetcher_cls.return_value.connect.side_effect = RuntimeError(message)
            dialog._test_connection_clicked()
        return dialog.lbl_test_result.text()

    def test_outlook_auth_failure_is_actionable_and_sanitized(self):
        result = self._run_failure(f"authentication failed: {self.AUTH_CODE}")

        self.assertIn("认证失败", result)
        self.assertIn("邮箱地址完整", result)
        self.assertNotIn(self.AUTH_CODE, result)

    def test_outlook_oauth_required_failure_is_classified_before_auth_failure(self):
        result = self._run_failure("LOGIN disabled: Basic authentication disabled, OAuth2 required")

        self.assertIn("需要 OAuth2", result)
        self.assertIn("当前版本暂不支持", result)

    def test_outlook_timeout_has_network_proxy_and_firewall_guidance(self):
        result = self._run_failure("connection timed out")

        self.assertIn("outlook.office365.com:993", result)
        self.assertIn("网络、代理或防火墙", result)


if __name__ == "__main__":
    unittest.main()
