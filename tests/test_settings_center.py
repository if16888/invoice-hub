import copy
import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from tests.test_settings_dialog import SettingsDialogTestMixin


class SettingsCenterMailboxTests(SettingsDialogTestMixin, unittest.TestCase):

    def test_dialog_opens_on_settings_home(self):
        dialog = self._make_dialog()
        self.assertIs(dialog.settings_stack.currentWidget(), dialog.page_settings_home)

    def test_mailbox_rows_show_each_accounts_scan_range(self):
        dialog = self._make_dialog()
        dialog.cfg["email_accounts"] = [
            {
                "mailbox_key": "work@qq.com",
                "name": "工作邮箱",
                "enabled": True,
                "provider": "qq",
                "address": "work@qq.com",
                "username": "work@qq.com",
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
            },
            {
                "mailbox_key": "history@163.com",
                "name": "历史邮箱",
                "enabled": True,
                "provider": "netease_163",
                "address": "history@163.com",
                "username": "history@163.com",
                "imap": {"server": "imap.163.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 12},
            },
        ]
        dialog._refresh_mailbox_list()
        row_text = [row.summary_text() for row in dialog.mailbox_rows]
        self.assertIn("最近 3 个月", row_text[0])
        self.assertIn("最近 12 个月", row_text[1])

    def test_edit_routes_by_mailbox_key_not_provider(self):
        dialog = self._make_dialog()
        dialog.cfg["email_accounts"] = [
            {
                "mailbox_key": "second@qq.com",
                "name": "QQ2",
                "enabled": True,
                "provider": "qq",
                "address": "second@qq.com",
                "username": "second@qq.com",
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
            }
        ]
        dialog._build_saved_account_maps()
        dialog._open_mailbox_editor("second@qq.com")
        self.assertEqual(dialog._loaded_account_mailbox_key, "second@qq.com")
        self.assertIs(dialog.settings_stack.currentWidget(), dialog.page_mailbox_editor)

    def test_disable_one_of_two_enabled_mailboxes_succeeds(self):
        dialog = self._make_dialog()
        dialog.cfg["email_accounts"] = [
            {
                "mailbox_key": "qq1",
                "name": "QQ1",
                "enabled": True,
                "provider": "qq",
                "address": "qq1@qq.com",
                "username": "qq1@qq.com",
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
            },
            {
                "mailbox_key": "qq2",
                "name": "QQ2",
                "enabled": True,
                "provider": "qq",
                "address": "qq2@qq.com",
                "username": "qq2@qq.com",
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
            }
        ]
        dialog._build_saved_account_maps()
        with patch("scripts.invoice_fetch.config.save_config") as mock_save:
            dialog._set_mailbox_enabled("qq1", False)
        mock_save.assert_called_once()
        self.assertFalse(dialog.cfg["email_accounts"][0]["enabled"])
        self.assertTrue(dialog.cfg["email_accounts"][1]["enabled"])

    def test_disable_last_enabled_mailbox_is_rejected(self):
        dialog = self._make_dialog()
        dialog.cfg["email_accounts"] = [
            {
                "mailbox_key": "qq1",
                "name": "QQ1",
                "enabled": True,
                "provider": "qq",
                "address": "qq1@qq.com",
                "username": "qq1@qq.com",
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
            }
        ]
        dialog._build_saved_account_maps()
        with patch("scripts.invoice_fetch.config.save_config") as mock_save, \
             patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            dialog._set_mailbox_enabled("qq1", False)
        mock_warn.assert_called_once()
        mock_save.assert_not_called()
        self.assertTrue(dialog.cfg["email_accounts"][0]["enabled"])

    def test_enable_disabled_mailbox_succeeds(self):
        dialog = self._make_dialog()
        dialog.cfg["email_accounts"] = [
            {
                "mailbox_key": "qq1",
                "name": "QQ1",
                "enabled": True,
                "provider": "qq",
                "address": "qq1@qq.com",
                "username": "qq1@qq.com",
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
            },
            {
                "mailbox_key": "disabled-key",
                "name": "QQ2",
                "enabled": False,
                "provider": "qq",
                "address": "qq2@qq.com",
                "username": "qq2@qq.com",
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
            }
        ]
        dialog._build_saved_account_maps()
        with patch("scripts.invoice_fetch.config.save_config") as mock_save:
            dialog._set_mailbox_enabled("disabled-key", True)
        mock_save.assert_called_once()
        self.assertTrue(dialog.cfg["email_accounts"][1]["enabled"])

    def test_mailbox_rows_rendered_immediately_on_init(self):
        config = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "email_accounts": [
                {
                    "mailbox_key": "work@qq.com",
                    "name": "工作邮箱",
                    "enabled": True,
                    "provider": "qq",
                    "address": "work@qq.com",
                    "username": "work@qq.com",
                    "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                    "search": {"folder": "INBOX", "months_back": 3},
                },
                {
                    "mailbox_key": "history@163.com",
                    "name": "历史邮箱",
                    "enabled": True,
                    "provider": "netease_163",
                    "address": "history@163.com",
                    "username": "history@163.com",
                    "imap": {"server": "imap.163.com", "port": 993, "ssl": True},
                    "search": {"folder": "INBOX", "months_back": 12},
                },
            ],
            "ai": {"provider": "none", "model": "", "enabled": False},
        }
        dialog = self._make_dialog(config=config)
        from scripts.invoice_fetch.gui.settings_dialog import MailboxConfigRow
        self.assertEqual(len(dialog.mailbox_rows), 2)
        self.assertIsInstance(dialog.mailbox_rows[0], MailboxConfigRow)
        self.assertIsInstance(dialog.mailbox_rows[1], MailboxConfigRow)

    def test_mailbox_tab_shows_empty_state_immediately_on_init(self):
        config = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "email_accounts": [],
            "ai": {"provider": "none", "model": "", "enabled": False},
        }
        dialog = self._make_dialog(config=config)
        from PySide6.QtWidgets import QLabel
        self.assertEqual(len(dialog.mailbox_rows), 1)
        self.assertIsInstance(dialog.mailbox_rows[0], QLabel)
        self.assertEqual(dialog.mailbox_rows[0].text(), "尚未配置任何邮箱账号，请点击上方“新增邮箱账号”。")


class SettingsCenterAIProfileTests(SettingsDialogTestMixin, unittest.TestCase):

    def test_no_enabled_profile_shows_ai_disabled(self):
        dialog = self._make_dialog()
        dialog.cfg["ai_profiles"] = [{
            "profile_id": "ai-one",
            "name": "备用模型",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": False,
        }]
        dialog._refresh_ai_profile_list()
        self.assertEqual(dialog.lbl_ai_global_status.text(), "AI 功能未启用")

    def test_set_current_disables_every_other_profile(self):
        dialog = self._make_dialog()
        dialog.cfg["email_accounts"] = [{
            "name": "默认邮箱",
            "enabled": True,
            "provider": "qq",
            "address": "if16888@qq.com",
            "username": "if16888@qq.com",
            "mailbox_key": "if16888@qq.com",
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
        }]
        dialog.cfg["ai_profiles"] = [
            {"profile_id": "one", "name": "一", "provider": "deepseek", "model": "m1", "enabled": True},
            {"profile_id": "two", "name": "二", "provider": "gemini", "model": "m2", "enabled": False},
        ]
        persisted_cfg = copy.deepcopy(dialog.cfg)

        def fake_save(cfg, path=None):
            nonlocal persisted_cfg
            persisted_cfg = copy.deepcopy(cfg)

        def fake_load():
            return copy.deepcopy(persisted_cfg)

        with patch("scripts.invoice_fetch.credentials.has_ai_api_key", return_value=True), \
             patch("scripts.invoice_fetch.config.save_config", side_effect=fake_save) as mock_save, \
             patch("scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat", side_effect=fake_load):
            dialog._set_active_ai_profile("two")
        mock_save.assert_called_once()
        enabled = [p["profile_id"] for p in dialog.cfg["ai_profiles"] if p["enabled"]]
        self.assertEqual(enabled, ["two"])
        self.assertEqual(dialog.cfg["ai"]["profile_id"], "two")

    def test_disable_ai_keeps_profiles_and_clears_active_projection(self):
        dialog = self._make_dialog()
        dialog.cfg["email_accounts"] = [{
            "name": "默认邮箱",
            "enabled": True,
            "provider": "qq",
            "address": "if16888@qq.com",
            "username": "if16888@qq.com",
            "mailbox_key": "if16888@qq.com",
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
        }]
        dialog.cfg["ai_profiles"] = [
            {"profile_id": "one", "name": "一", "provider": "deepseek", "model": "m1", "enabled": True},
        ]
        before = len(dialog.cfg["ai_profiles"])
        persisted_cfg = copy.deepcopy(dialog.cfg)

        def fake_save(cfg, path=None):
            nonlocal persisted_cfg
            persisted_cfg = copy.deepcopy(cfg)

        def fake_load():
            return copy.deepcopy(persisted_cfg)

        with patch("scripts.invoice_fetch.config.save_config", side_effect=fake_save) as mock_save, \
             patch("scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat", side_effect=fake_load):
            dialog._disable_ai()
        mock_save.assert_called_once()
        self.assertEqual(len(dialog.cfg["ai_profiles"]), before)
        self.assertFalse(any(p["enabled"] for p in dialog.cfg["ai_profiles"]))
        self.assertEqual(dialog.cfg["ai"]["provider"], "none")

    def test_new_ai_provider_choices_do_not_include_none(self):
        dialog = self._make_dialog()
        dialog._open_new_ai_editor()
        providers = [dialog.combo_ai_provider.itemText(i) for i in range(dialog.combo_ai_provider.count())]
        self.assertEqual(providers, ["deepseek", "gemini"])

    def test_ai_rows_rendered_immediately_on_init(self):
        config = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "ai_profiles": [
                {
                    "profile_id": "ai-one",
                    "name": "测试 AI",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": True,
                }
            ],
        }
        with patch("scripts.invoice_fetch.credentials.get_ai_api_key_source", return_value="env"):
            dialog = self._make_dialog(config=config)
        from scripts.invoice_fetch.gui.settings_dialog import AIProfileRow
        self.assertEqual(len(dialog.ai_rows), 1)
        self.assertIsInstance(dialog.ai_rows[0], AIProfileRow)

    def test_ai_current_step_initialized_on_dialog_creation(self):
        dialog = self._make_dialog()
        self.assertTrue(hasattr(dialog, "ai_current_step"))
        self.assertEqual(dialog.ai_current_step, 1)
        # Should not raise AttributeError
        dialog._update_ai_wizard_ui()

    def test_open_existing_ai_editor_does_not_raise_before_step_initialized(self):
        config = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "ai_profiles": [
                {
                    "profile_id": "ai-one",
                    "name": "测试 AI",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": True,
                }
            ],
        }
        dialog = self._make_dialog(config=config)
        # Should not raise AttributeError
        dialog._open_ai_editor("ai-one")
        self.assertEqual(dialog.ai_current_step, 1)

    def test_save_ai_profile_clear_key_does_not_raise(self):
        dialog = self._make_dialog()
        dialog._open_new_ai_editor()
        dialog.txt_ai_name.setText("My New AI")
        dialog.txt_ai_key.setText("new-secret-key")
        with patch("scripts.invoice_fetch.config.save_config"), \
             patch("PySide6.QtWidgets.QMessageBox.information"), \
             patch("scripts.invoice_fetch.credentials.set_ai_api_key"):
            # Triggering save, should clear key and not raise AttributeError
            dialog._save_ai_profile_settings(activate=True)

    def test_disabled_ai_profile_row_has_visible_activate_button(self):
        from scripts.invoice_fetch.gui.settings_dialog import AIProfileRow
        profile = {
            "profile_id": "ai-one",
            "name": "测试 AI",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": False,
        }
        dialog = self._make_dialog()
        row = AIProfileRow(profile, key_source="env", parent=dialog)
        self.assertFalse(row.btn_activate.isHidden())
        self.assertTrue(row.btn_activate.isEnabled())
        self.assertEqual(row.btn_activate.text(), "启用")
        self.assertTrue(row.btn_activate.minimumWidth() >= 76)

        emitted = False
        def on_activate(pid):
            nonlocal emitted
            emitted = True
            self.assertEqual(pid, "ai-one")
        row.activate_requested.connect(on_activate)
        row.btn_activate.click()
        self.assertTrue(emitted)

    def test_disable_ai_button_hidden_or_disabled_when_no_active_profile(self):
        config_inactive = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "ai_profiles": [
                {
                    "profile_id": "ai-one",
                    "name": "测试 AI",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": False,
                }
            ],
        }
        dialog_inactive = self._make_dialog(config=config_inactive)
        self.assertTrue(dialog_inactive.btn_disable_ai_action.isHidden())

        config_active = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "ai": {"provider": "deepseek", "model": "deepseek-chat", "profile_id": "ai-one", "enabled": True},
            "ai_profiles": [
                {
                    "profile_id": "ai-one",
                    "name": "测试 AI",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": True,
                }
            ],
        }
        dialog_active = self._make_dialog(config=config_active)
        self.assertFalse(dialog_active.btn_disable_ai_action.isHidden())
        self.assertTrue(dialog_active.btn_disable_ai_action.isEnabled())

    def test_ai_enable_button_integration(self):
        config = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "ai_profiles": [
                {
                    "profile_id": "ai-one",
                    "name": "测试 AI",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": False,
                }
            ],
        }
        dialog = self._make_dialog(config=config)
        persisted_cfg = copy.deepcopy(dialog.cfg)

        def fake_save(cfg, path=None):
            nonlocal persisted_cfg
            persisted_cfg = copy.deepcopy(cfg)

        def fake_load():
            return copy.deepcopy(persisted_cfg)

        with patch("scripts.invoice_fetch.credentials.has_ai_api_key", return_value=True), \
             patch("scripts.invoice_fetch.config.save_config", side_effect=fake_save) as mock_save, \
             patch("scripts.invoice_fetch.gui.settings_dialog._load_config_safe_compat", side_effect=fake_load):
            self.assertEqual(len(dialog.ai_rows), 1)
            row = dialog.ai_rows[0]
            self.assertEqual(row.btn_activate.text(), "启用")
            row.btn_activate.click()
            mock_save.assert_called_once()
            self.assertTrue(dialog.cfg["ai_profiles"][0]["enabled"])
            self.assertEqual(dialog.cfg["ai"]["provider"], "deepseek")
            self.assertEqual(dialog.cfg["ai"]["profile_id"], "ai-one")

    def test_disabled_ai_profile_row_geometry(self):
        config = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "ai_profiles": [
                {
                    "profile_id": "ai-one",
                    "name": "测试 AI",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": False,
                }
            ],
        }
        dialog = self._make_dialog(config=config)
        dialog.tab_widget.setCurrentIndex(1)
        dialog.show()
        QApplication.processEvents()

        self.assertEqual(len(dialog.ai_rows), 1)
        row = dialog.ai_rows[0]
        self.assertTrue(row.btn_activate.isVisible())
        self.assertEqual(row.btn_activate.text(), "启用")
        self.assertTrue(row.btn_activate.geometry().width() >= row.btn_activate.sizeHint().width())

    def test_active_ai_profile_row_geometry(self):
        config = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "ai": {"provider": "deepseek", "model": "deepseek-chat", "profile_id": "ai-one", "enabled": True},
            "ai_profiles": [
                {
                    "profile_id": "ai-one",
                    "name": "测试 AI",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": True,
                }
            ],
        }
        dialog = self._make_dialog(config=config)
        dialog.tab_widget.setCurrentIndex(1)
        dialog.show()
        QApplication.processEvents()

        self.assertEqual(len(dialog.ai_rows), 1)
        row = dialog.ai_rows[0]
        self.assertTrue(hasattr(row, "lbl_active"))
        self.assertEqual(row.lbl_active.text(), "当前生效")
        self.assertTrue(row.lbl_active.isVisible())
        self.assertTrue(row.lbl_active.geometry().width() >= row.lbl_active.sizeHint().width())

    def test_status_badge_styles_present(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET
        self.assertIn('QLabel.StatusBadge[variant="active"]', APP_STYLESHEET)
        self.assertIn('QLabel.StatusBadge[variant="success"]', APP_STYLESHEET)
        self.assertIn('QLabel.StatusBadge[variant="warning"]', APP_STYLESHEET)
        self.assertIn('QLabel.StatusBadge[variant="info"]', APP_STYLESHEET)

    def test_disabled_ai_row_geometric_order(self):
        config = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "ai_profiles": [
                {
                    "profile_id": "ai-one",
                    "name": "测试 AI",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": False,
                }
            ],
        }
        dialog = self._make_dialog(config=config)
        dialog.tab_widget.setCurrentIndex(1)
        dialog.show()
        QApplication.processEvents()

        self.assertEqual(len(dialog.ai_rows), 1)
        row = dialog.ai_rows[0]

        # Get visual rectangles/geometries
        key_badge_rect = row.lbl_key_status.geometry()
        btn_activate_rect = row.btn_activate.geometry()
        btn_edit_rect = row.btn_edit.geometry()

        self.assertTrue(btn_activate_rect.width() > 0)
        self.assertTrue(key_badge_rect.x() + key_badge_rect.width() <= btn_activate_rect.x())
        self.assertTrue(btn_activate_rect.x() + btn_activate_rect.width() <= btn_edit_rect.x())

    def test_combobox_popup_styles_present(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET
        self.assertIn("QComboBox QAbstractItemView", APP_STYLESHEET)
        self.assertIn("selection-background-color", APP_STYLESHEET)
        self.assertIn("selection-color", APP_STYLESHEET)


if __name__ == "__main__":
    unittest.main()
