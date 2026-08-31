import copy
import threading
import sys
import unittest
from unittest.mock import MagicMock, patch

try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
except ImportError:
    QApplication, QMessageBox, QWidget = None, None, None


class SettingsDialogTestMixin:
    @classmethod
    def setUpClass(cls):
        try:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def setUp(self):
        super().setUp() if hasattr(super(), "setUp") else None
        self._saved_addresses = set()
        # Mock keyring completely to avoid accessing the live Windows Credential Vault
        self._keyring_patches = [
            patch("keyring.get_password", side_effect=lambda svc, username: "dummy_pass" if username in self._saved_addresses else None),
            patch("keyring.set_password", side_effect=lambda svc, username, password: self._saved_addresses.add(username)),
            patch("keyring.delete_password", side_effect=lambda svc, username: self._saved_addresses.discard(username)),
        ]
        for p in self._keyring_patches:
            p.start()

        # Globally mock QMessageBox calls to prevent blocking GUI popups during test execution
        self._qmessagebox_patches = [
            patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning", return_value=QMessageBox.Ok),
            patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information", return_value=QMessageBox.Ok),
            patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.critical", return_value=QMessageBox.Ok),
            patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes),
        ]
        for p in self._qmessagebox_patches:
            p.start()

    def tearDown(self):
        for p in self._qmessagebox_patches:
            p.stop()
        for p in self._keyring_patches:
            p.stop()
        super().tearDown() if hasattr(super(), "tearDown") else None

    def _cleanup_widget(self, widget):
        widget.close()
        widget.deleteLater()
        self.app.processEvents()

    def _make_dialog(self, config=None, *, saved_addresses=()):
        from scripts.invoice_fetch.gui.settings_dialog import SettingsDialog

        config = config or {
            "email": {"provider": "qq", "address": "if16888@qq.com"},
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
            "ai": {"provider": "none", "model": "", "enabled": False},
        }
        self._saved_addresses = set(saved_addresses)
        parent = QWidget()
        parent.config = {}
        parent.write_log = MagicMock()
        self.addCleanup(self._cleanup_widget, parent)
        with patch(
            "scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat",
            return_value=config,
        ):
            dialog = SettingsDialog(parent)
        self.addCleanup(self._cleanup_widget, dialog)
        return dialog

    def _select(self, dialog, provider):
        dialog.cards[provider].click()
        self.app.processEvents()


class SettingsDialogProviderTests(SettingsDialogTestMixin, unittest.TestCase):

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

    def test_saved_outlook_account_is_loaded_when_selecting_outlook(self):
        dialog = self._make_dialog(self._multi_account_config())

        self._select(dialog, "outlook")

        self.assertEqual(dialog.txt_email.text(), "abc@outlook.com")
        self.assertEqual(dialog.txt_months.text(), "6")
        self.assertEqual(dialog.txt_imap_server.text(), "outlook.office365.com")

    def test_saved_outlook_account_name_is_loaded_into_editor(self):
        config = self._multi_account_config("abc@outlook.com")
        config["email_accounts"][1]["name"] = "海外报销邮箱"
        dialog = self._make_dialog(config)

        self._select(dialog, "outlook")

        self.assertEqual(dialog.txt_mailbox_name.text(), "海外报销邮箱")

    def test_selecting_outlook_does_not_rewrite_saved_qq_email_when_no_outlook_account_exists(self):
        dialog = self._make_dialog()

        self._select(dialog, "outlook")

        self.assertNotEqual(dialog.txt_email.text(), "if16888@outlook.com")

    def test_selecting_outlook_with_no_saved_account_clears_email_and_sets_placeholder(self):
        dialog = self._make_dialog()

        self._select(dialog, "outlook")

        self.assertEqual(dialog.txt_email.text(), "")
        self.assertEqual(dialog.txt_email.placeholderText(), "请输入完整 Outlook 邮箱地址")
        self.assertIn("未找到已保存的 Outlook 邮箱", dialog.lbl_provider_hint.text())

    def test_saved_hotmail_live_accounts_load_as_outlook_family(self):
        for email in ("abc@hotmail.com", "abc@live.com"):
            dialog = self._make_dialog(self._multi_account_config(email))

            self._select(dialog, "outlook")

            self.assertEqual(dialog.txt_email.text(), email)

    def test_saved_company_domain_outlook_account_loads_as_is_and_shows_oauth_hint(self):
        dialog = self._make_dialog(self._multi_account_config("abc@company.com"))

        self._select(dialog, "outlook")

        self.assertEqual(dialog.txt_email.text(), "abc@company.com")
        self.assertIn("Microsoft 365", dialog.lbl_provider_hint.text())
        self.assertIn("OAuth2", dialog.lbl_provider_hint.text())

    def test_manual_draft_email_can_rewrite_suffix(self):
        dialog = self._make_dialog()
        dialog.txt_email.setText("new-user@qq.com")

        self._select(dialog, "outlook")

        self.assertEqual(dialog.txt_email.text(), "new-user@outlook.com")

    def test_typing_outlook_email_applies_outlook_defaults(self):
        dialog = self._make_dialog()

        dialog.txt_email.setText("new-user@outlook.com")
        self.app.processEvents()

        self.assertEqual(dialog._get_selected_provider(), "outlook")
        self.assertEqual(dialog.txt_imap_server.text(), "outlook.office365.com")
        self.assertEqual(dialog.txt_imap_port.text(), "993")

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

    def test_outlook_provider_card_marks_oauth_required(self):
        from PySide6.QtWidgets import QLabel
        dialog = self._make_dialog()
        card = dialog.cards["outlook"]
        labels = card.findChildren(QLabel)
        self.assertTrue(any("需要 OAuth2，当前版本暂不支持" in lbl.text() for lbl in labels))

    def test_selecting_outlook_disables_auth_code_flow(self):
        dialog = self._make_dialog()
        self._select(dialog, "outlook")
        self.assertFalse(dialog.btn_next.isEnabled())
        self.assertFalse(dialog.lbl_outlook_step1_warning.isHidden())

    def test_outlook_next_step_blocked_with_oauth_message(self):
        dialog = self._make_dialog()
        self._select(dialog, "outlook")
        dialog.txt_email.setText("test@outlook.com")
        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn:
            dialog._goto_next_step()
            mock_warn.assert_called_once()
            self.assertIn("暂不支持", mock_warn.call_args[0][2])
            self.assertEqual(dialog.current_step, 1)

    def test_saved_outlook_account_is_shown_as_unsupported_not_tested(self):
        config = self._multi_account_config("abc@outlook.com")
        dialog = self._make_dialog(config)
        self._select(dialog, "outlook")
        self.assertIn("已保存 Outlook 账号，但当前版本暂不支持测试/扫描", dialog.lbl_cred_status.text())

    def test_unsaved_outlook_email_does_not_show_saved_status(self):
        dialog = self._make_dialog()
        self._select(dialog, "outlook")
        dialog.txt_email.setText("new_unsaved@outlook.com")
        status_text = dialog.lbl_cred_status.text()
        self.assertNotIn("已保存", status_text)
        self.assertIn("Outlook 当前版本暂不支持配置/测试", status_text)

    def test_saved_outlook_email_shows_saved_but_unsupported_status(self):
        config = self._multi_account_config("abc@outlook.com")
        dialog = self._make_dialog(config)
        self._select(dialog, "outlook")
        status_text = dialog.lbl_cred_status.text()
        self.assertIn("已保存 Outlook 账号，但当前版本暂不支持测试/扫描", status_text)

    def test_auth_code_help_text_has_no_typo(self):
        dialog = self._make_dialog()
        self._select(dialog, "qq")
        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information") as info:
            dialog._show_auth_code_help()
            help_text = info.call_args.args[2]
            self.assertIn("读取邮件的专属密码", help_text)
            self.assertNotIn("读取邮件 of 专属密码", help_text)

    def test_app_password_guidance_removed_from_outlook_help(self):
        dialog = self._make_dialog()
        self._select(dialog, "outlook")
        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information") as info:
            dialog._show_auth_code_help()
            help_text = info.call_args.args[2]
            self.assertNotIn("应用密码", help_text)
            self.assertNotIn("可尝试", help_text)
            self.assertIn("暂不支持", help_text)

    def test_existing_qq_163_126_gmail_custom_imap_flows_remain_unchanged(self):
        dialog = self._make_dialog()
        suffixes = {
            "qq": "qq.com",
            "netease_163": "163.com",
            "netease_126": "126.com",
            "gmail": "gmail.com",
            "custom": "example.com"
        }
        for provider in ("qq", "netease_163", "netease_126", "gmail", "custom"):
            self._select(dialog, provider)
            dialog.txt_email.setText(f"test@{suffixes[provider]}")
            self.app.processEvents()
            self.assertTrue(dialog.btn_next.isEnabled())
            self.assertTrue(dialog.lbl_outlook_step1_warning.isHidden())

    def test_credential_status_uses_exact_loaded_email(self):
        config = self._multi_account_config("saved@hotmail.com")
        with patch("scripts.invoice_fetch.credentials.has_auth_code") as has_auth_code:
            has_auth_code.side_effect = lambda address: address == "saved@hotmail.com"
            dialog = self._make_dialog(config)
            has_auth_code.reset_mock()

            self._select(dialog, "outlook")

        self.assertIn("已保存 Outlook 账号，但当前版本暂不支持测试/扫描", dialog.lbl_cred_status.text())

    def _save_without_side_effects(self, dialog):
        dialog.test_success = True
        persisted_cfg = copy.deepcopy(dialog.cfg)

        def fake_save(cfg, path=None):
            nonlocal persisted_cfg
            persisted_cfg = copy.deepcopy(cfg)

        def fake_load(path=None):
            return copy.deepcopy(persisted_cfg)

        with patch("scripts.invoice_fetch.config.save_config", side_effect=fake_save), patch(
            "scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat",
            side_effect=fake_load,
        ), patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"), patch(
            "scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning"
        ), patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.critical"), patch(
            "scripts.invoice_fetch.credentials.has_auth_code", return_value=False
        ):
            dialog._save_mailbox_settings()

    def test_saving_outlook_preserves_existing_qq_account_in_email_accounts(self):
        dialog = self._make_dialog(self._multi_account_config())
        self._select(dialog, "outlook")

        self._save_without_side_effects(dialog)

        addresses = {account["address"] for account in dialog.cfg["email_accounts"]}
        self.assertEqual(addresses, {"if16888@qq.com", "abc@outlook.com"})
        outlook = next(
            account for account in dialog.cfg["email_accounts"]
            if account["address"] == "abc@outlook.com"
        )
        self.assertEqual(outlook["mailbox_key"], "outlook-primary")

    def test_saving_mailbox_returns_to_settings_home_page(self):
        dialog = self._make_dialog()
        dialog._open_new_mailbox_editor()
        dialog.txt_email.setText("tester@qq.com")
        dialog.txt_auth_code.setText("new-auth-code")
        dialog.test_success = True

        persisted_cfg = copy.deepcopy(dialog.cfg)

        def fake_save(cfg, path=None):
            nonlocal persisted_cfg
            persisted_cfg = copy.deepcopy(cfg)

        def fake_load():
            return copy.deepcopy(persisted_cfg)

        with patch("scripts.invoice_fetch.config.save_config", side_effect=fake_save) as mock_save, \
             patch("scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat", side_effect=fake_load), \
             patch("scripts.invoice_fetch.credentials.set_auth_code"), \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information"):
            dialog._save_mailbox_settings()

        mock_save.assert_called_once()
        self.assertIs(dialog.settings_stack.currentWidget(), dialog.page_settings_home)
        self.assertEqual(dialog.tab_widget.currentIndex(), 0)

    def test_typing_new_outlook_account_preserves_loaded_qq_account(self):
        # Under v0.1.3 safety rules, saving a new Outlook account is blocked
        dialog = self._make_dialog()
        dialog.txt_email.setText("new-user@outlook.com")
        dialog.test_success = True

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn:
            dialog._save_mailbox_settings()
            mock_warn.assert_called_once()

        # The new outlook account should not be in the config
        addresses = {account["address"] for account in dialog.cfg.get("email_accounts", [])}
        self.assertNotIn("new-user@outlook.com", addresses)


    def test_saving_qq_preserves_existing_outlook_account_in_email_accounts(self):
        dialog = self._make_dialog(self._multi_account_config())
        self._select(dialog, "qq")

        self._save_without_side_effects(dialog)

        addresses = {account["address"] for account in dialog.cfg["email_accounts"]}
        self.assertEqual(addresses, {"if16888@qq.com", "abc@outlook.com"})


class OutlookConnectionDiagnosticsTests(SettingsDialogTestMixin, unittest.TestCase):

    def test_outlook_test_does_not_call_imaplib_login(self):
        dialog = self._make_dialog()
        self._select(dialog, "outlook")
        dialog.txt_email.setText("tester@outlook.com")
        dialog.txt_auth_code.setText("dummy")
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher") as fetcher_cls, \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn:
            dialog._test_connection_clicked()
            fetcher_cls.assert_not_called()
            mock_warn.assert_called_once()
            self.assertIn("暂不支持", mock_warn.call_args[0][2])

    def test_custom_imap_outlook_host_reports_oauth_required(self):
        dialog = self._make_dialog()
        self._select(dialog, "custom")
        dialog.txt_email.setText("tester@custom.com")
        dialog.txt_auth_code.setText("dummy")
        dialog.txt_imap_server.setText("outlook.office365.com")
        dialog.txt_imap_port.setText("993")
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher") as fetcher_cls, \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn:
            dialog._test_connection_clicked()
            fetcher_cls.assert_not_called()
            mock_warn.assert_called_once()
            self.assertIn("检测到 Outlook IMAP 服务器", mock_warn.call_args[0][2])


class MailboxConnectionAsyncTests(SettingsDialogTestMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication is None:
            raise unittest.SkipTest("Skipping async mailbox GUI tests: Qt widgets unavailable")
        super().setUpClass()
        try:
            from PySide6.QtCore import QCoreApplication, QTimer
        except Exception as exc:  # pragma: no cover - host GUI dependency
            raise unittest.SkipTest(f"Skipping async mailbox GUI tests: {exc}")
        cls.QCoreApplication = QCoreApplication
        cls.QTimer = QTimer

    def _prepare_dialog(self):
        dialog = self._make_dialog()
        dialog.txt_email.setText("worker@qq.com")
        dialog.txt_auth_code.setText("secret-auth-code")
        dialog._update_summary_fields()
        return dialog

    @staticmethod
    def _controlled_fetcher(*, failure=None):
        class ControlledFetcher:
            instances = []
            started = threading.Event()
            release = threading.Event()
            failure = None

            def __init__(self, **kwargs):
                self.control = kwargs["control"]
                self.cancel_called = False
                self.disconnected = False
                type(self).instances.append(self)
                self.control.register_fetcher(self)

            def connect(self):
                type(self).started.set()
                while not type(self).release.wait(0.01):
                    if self.control.cancelled:
                        raise RuntimeError("cancelled")
                if type(self).failure is not None:
                    raise type(self).failure

            def disconnect(self):
                self.disconnected = True
                self.control.unregister_fetcher(self)

            def cancel(self):
                self.cancel_called = True
                type(self).release.set()

        ControlledFetcher.failure = failure
        return ControlledFetcher

    @staticmethod
    def _blocked_connect_fetcher():
        class BlockedConnectFetcher:
            instances = []
            started = threading.Event()
            external_release = threading.Event()

            def __init__(self, **kwargs):
                self.control = kwargs["control"]
                self.cancel_called = False
                self.disconnected = False
                type(self).instances.append(self)
                self.control.register_fetcher(self)

            def connect(self):
                type(self).started.set()
                type(self).external_release.wait()
                if self.control.cancelled:
                    raise RuntimeError("cancelled")

            def disconnect(self):
                self.disconnected = True
                self.control.unregister_fetcher(self)

            def cancel(self):
                self.cancel_called = True

        return BlockedConnectFetcher

    def _finish_worker(self, dialog, *, release=True):
        worker = dialog._mailbox_test_worker
        self.assertIsNotNone(worker)
        fetcher_cls = self.fetcher_cls
        if release:
            fetcher_cls.release.set()
        self.assertTrue(worker.wait(2000), "mailbox test worker did not finish")
        self.QCoreApplication.processEvents()
        return worker

    def test_connection_test_returns_to_event_loop_while_network_waits(self):
        dialog = self._prepare_dialog()
        self.fetcher_cls = self._controlled_fetcher()
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher", self.fetcher_cls):
            dialog._test_connection_clicked()
            self.assertTrue(self.fetcher_cls.started.wait(2))
            ticks = []
            self.QTimer.singleShot(0, lambda: ticks.append(True))
            self.QCoreApplication.processEvents()
            self.assertEqual(ticks, [True])
            self.assertIsNotNone(dialog._mailbox_test_worker)
            self.assertFalse(dialog.test_success)
            self._finish_worker(dialog)
        self.assertTrue(dialog.test_success)
        self.assertTrue(dialog.btn_test.isEnabled())
        self.assertIn("已连接到", dialog.lbl_test_result.text())

    def test_failure_is_sanitized_and_restores_test_button(self):
        dialog = self._prepare_dialog()
        self.fetcher_cls = self._controlled_fetcher(
            failure=RuntimeError("login failed secret-auth-code")
        )
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher", self.fetcher_cls):
            dialog._test_connection_clicked()
            self.assertTrue(self.fetcher_cls.started.wait(2))
            self._finish_worker(dialog)
        self.assertFalse(dialog.test_success)
        self.assertTrue(dialog.btn_test.isEnabled())
        self.assertNotIn("secret-auth-code", dialog.lbl_test_result.text())
        self.assertIn("授权码", dialog.lbl_test_result.text())

    def test_close_requests_cancel_and_queued_success_is_ignored(self):
        dialog = self._prepare_dialog()
        from scripts.invoice_fetch.gui.workers import MailboxConnectionTestWorker

        class QueuedSuccessWorker(MailboxConnectionTestWorker):
            emitted = threading.Event()
            release = threading.Event()

            def run(self):
                self.success.emit(self.request_id)
                type(self).emitted.set()
                type(self).release.wait()

            def request_cancel(self):
                super().request_cancel()
                type(self).release.set()

        with patch(
            "scripts.invoice_fetch.gui.workers.MailboxConnectionTestWorker",
            QueuedSuccessWorker,
        ):
            dialog._test_connection_clicked()
            self.assertTrue(QueuedSuccessWorker.emitted.wait(2))
            worker = dialog._mailbox_test_worker
            dialog.close()
            self.assertTrue(dialog._closing)
            self.assertIs(dialog._mailbox_test_worker, worker)
            self.assertTrue(worker.wait(2000), "queued success worker did not finish")
            self.QCoreApplication.processEvents()
        self.assertFalse(dialog.test_success)
        self.assertIsNone(dialog._mailbox_test_worker)

    def test_close_cancels_running_network_test_before_dialog_shutdown(self):
        dialog = self._prepare_dialog()
        self.fetcher_cls = self._controlled_fetcher()
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher", self.fetcher_cls):
            dialog._test_connection_clicked()
            self.assertTrue(self.fetcher_cls.started.wait(2))
            worker = dialog._mailbox_test_worker
            dialog.close()
            self.assertTrue(self.fetcher_cls.instances[0].cancel_called)
            self.assertIs(dialog._mailbox_test_worker, worker)
            self.assertTrue(worker.wait(2000), "mailbox test worker did not finish")
            self.QCoreApplication.processEvents()
        self.assertFalse(worker.isRunning())
        self.assertIsNone(dialog._mailbox_test_worker)

    def test_close_defers_until_blocked_connect_releases(self):
        dialog = self._prepare_dialog()
        self.fetcher_cls = self._blocked_connect_fetcher()
        self.addCleanup(self.fetcher_cls.external_release.set)
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher", self.fetcher_cls):
            dialog._test_connection_clicked()
            self.assertTrue(self.fetcher_cls.started.wait(2))
            worker = dialog._mailbox_test_worker
            self.assertIsNotNone(worker)

            ticks = []
            self.QTimer.singleShot(0, lambda: ticks.append(True))
            dialog.close()

            self.assertTrue(dialog._closing)
            self.assertTrue(self.fetcher_cls.instances[0].cancel_called)
            self.assertIs(dialog._mailbox_test_worker, worker)
            self.assertTrue(worker.isRunning())
            self.QCoreApplication.processEvents()
            self.assertEqual(ticks, [True])
            self.assertFalse(dialog.test_success)

            self.fetcher_cls.external_release.set()
            self.assertTrue(worker.wait(2000), "blocked-connect worker did not finish")
            for _ in range(4):
                self.QCoreApplication.processEvents()

        self.assertIsNone(dialog._mailbox_test_worker)
        self.assertIsNone(dialog._mailbox_test_pending_close_action)
        self.assertFalse(dialog.test_success)

    def test_navigation_does_not_wait_for_blocked_connect(self):
        dialog = self._prepare_dialog()
        self.fetcher_cls = self._blocked_connect_fetcher()
        self.addCleanup(self.fetcher_cls.external_release.set)
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher", self.fetcher_cls):
            dialog._test_connection_clicked()
            self.assertTrue(self.fetcher_cls.started.wait(2))
            worker = dialog._mailbox_test_worker
            ticks = []
            self.QTimer.singleShot(0, lambda: ticks.append(True))

            dialog._show_settings_home("mailboxes")

            self.assertIs(
                dialog.settings_stack.currentWidget(),
                dialog.page_settings_home,
            )
            self.assertTrue(self.fetcher_cls.instances[0].cancel_called)
            self.assertIs(dialog._mailbox_test_worker, worker)
            self.assertTrue(worker.isRunning())
            self.QCoreApplication.processEvents()
            self.assertEqual(ticks, [True])

            self.fetcher_cls.external_release.set()
            self.assertTrue(worker.wait(2000), "blocked-connect worker did not finish")
            for _ in range(4):
                self.QCoreApplication.processEvents()

        self.assertIsNone(dialog._mailbox_test_worker)
        self.assertIsNone(dialog._mailbox_test_context)

    def test_queued_error_after_close_is_ignored(self):
        dialog = self._prepare_dialog()
        from scripts.invoice_fetch.gui.workers import MailboxConnectionTestWorker

        class QueuedErrorWorker(MailboxConnectionTestWorker):
            emitted = threading.Event()
            release = threading.Event()

            def run(self):
                self.error.emit("login failed secret-auth-code")
                type(self).emitted.set()
                type(self).release.wait()

            def request_cancel(self):
                super().request_cancel()
                type(self).release.set()

        with patch(
            "scripts.invoice_fetch.gui.workers.MailboxConnectionTestWorker",
            QueuedErrorWorker,
        ):
            dialog._test_connection_clicked()
            self.assertTrue(QueuedErrorWorker.emitted.wait(2))
            dialog.close()
            self.QCoreApplication.processEvents()
        self.assertFalse(dialog.test_success)
        self.assertNotIn("secret-auth-code", dialog.lbl_test_result.text())

    def test_stale_success_after_form_change_does_not_mark_test_success(self):
        dialog = self._prepare_dialog()
        self.fetcher_cls = self._controlled_fetcher()
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher", self.fetcher_cls):
            dialog._test_connection_clicked()
            self.assertTrue(self.fetcher_cls.started.wait(2))
            dialog.txt_email.setText("changed@qq.com")
            self._finish_worker(dialog)
        self.assertFalse(dialog.test_success)
        self.assertTrue(dialog.btn_test.isEnabled())

    def test_second_click_does_not_start_another_worker(self):
        dialog = self._prepare_dialog()
        self.fetcher_cls = self._controlled_fetcher()
        with patch("scripts.invoice_fetch.mail_fetcher.MailFetcher", self.fetcher_cls):
            dialog._test_connection_clicked()
            self.assertTrue(self.fetcher_cls.started.wait(2))
            first_worker = dialog._mailbox_test_worker
            dialog._test_connection_clicked()
            self.assertIs(dialog._mailbox_test_worker, first_worker)
            self.assertEqual(len(self.fetcher_cls.instances), 1)
            self._finish_worker(dialog)


if __name__ == "__main__":
    unittest.main()
