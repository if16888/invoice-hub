import copy
import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QWidget

from scripts.invoice_fetch import APP_VERSION
from tests.test_settings_dialog import SettingsDialogTestMixin


class SettingsCenterShellTests(SettingsDialogTestMixin, unittest.TestCase):


    def test_settings_home_has_runtime_and_privacy_pages(self):
        dialog = self._make_dialog()
        self.assertIsNotNone(dialog.page_rules_center)
        self.assertIsNotNone(dialog.page_runtime_center)
        self.assertIsNotNone(dialog.page_privacy_center)

    def test_settings_shell_geometry_and_section_switching(self):
        dialog = self._make_dialog()
        try:
            dialog.resize(1440, 900)
            dialog.show()
            QApplication.processEvents()

            self.assertEqual(len(dialog.settings_nav_buttons), 8)
            self.assertTrue(all(btn.isVisible() for btn in dialog.settings_nav_buttons.values()))
            self.assertIs(dialog.settings_content_stack.currentWidget(), dialog.page_mailbox_center)

            footer_rect = dialog.lbl_settings_footer_hint.geometry()
            content_rect = dialog.settings_content_stack.geometry()
            nav_rect = next(iter(dialog.settings_nav_buttons.values())).parentWidget().geometry()
            self.assertGreater(footer_rect.y(), content_rect.bottom() - 120)
            self.assertGreater(content_rect.height(), 0)
            self.assertGreater(nav_rect.height(), 0)

            for section, page in dialog.settings_pages.items():
                dialog._show_settings_home(section)
                QApplication.processEvents()
                self.assertIs(dialog.settings_content_stack.currentWidget(), page)
                self.assertTrue(page.isVisible())
        finally:
            dialog.close()
            QApplication.processEvents()


    def test_about_page_uses_central_version_metadata(self):
        dialog = self._make_dialog()
        dialog._show_settings_home("about")
        self.assertIn(f"Invoice Hub 设置中心 {APP_VERSION}", dialog.lbl_about_settings.text())

    def test_data_page_exposes_privacy_hint_for_local_paths(self):
        dialog = self._make_dialog()
        dialog._refresh_settings_center_pages()
        self.assertTrue(dialog.lbl_data_settings.text().strip())
        self.assertTrue(dialog.lbl_data_settings.toolTip().strip())

    def test_rules_page_lists_config_and_database_category_names(self):
        dialog = self._make_dialog(
            config={
                "email": {"provider": "qq", "address": "your_email@qq.com"},
                "ai": {"provider": "none", "model": "", "enabled": False},
                "categories": {
                    "taxi": {"name": "Taxi"},
                    "hotel": {"name": "Hotel"},
                },
            }
        )
        dialog.parent.db = MagicMock()
        dialog.parent.db.list_categories.return_value = ["Meals", "Transit"]
        dialog._refresh_settings_center_pages()

        text = dialog.lbl_category_dictionary.text()
        self.assertIn("Taxi", text)
        self.assertIn("Hotel", text)
        self.assertIn("Meals", text)
        self.assertIn("Transit", text)

    def test_rules_page_exposes_dictionary_controls_and_rule_boundary_copy(self):
        dialog = self._make_dialog()
        dialog._refresh_settings_center_pages()

        self.assertTrue(dialog.lbl_rules_flow.text().strip())
        self.assertTrue(dialog.lbl_rules_overview.text().strip())
        self.assertIn("固定规则为只读", dialog.lbl_rules_overview.text())
        self.assertIn("分类名称不是识别规则", dialog.lbl_category_dictionary_hint.text())
        self.assertTrue(dialog.combo_config_categories.isEnabled())
        self.assertTrue(dialog.txt_category_name.placeholderText().strip())

    def test_rules_page_uses_chinese_category_labels_and_manage_action(self):
        dialog = self._make_dialog(
            config={
                "email": {"provider": "qq", "address": "your_email@qq.com"},
                "ai": {"provider": "none", "model": "", "enabled": False},
                "categories": {
                    "hotel": {},
                    "meal": {"name": ""},
                    "telecom": "telecom",
                },
            }
        )
        dialog.parent.db = MagicMock()
        dialog.parent.db.list_categories.return_value = []
        dialog._refresh_settings_center_pages()
        dialog._show_settings_home("rules")
        dialog.show()
        QApplication.processEvents()

        text = dialog.lbl_category_dictionary.text()
        self.assertIn("住宿", text)
        self.assertIn("餐饮", text)
        self.assertIn("通讯", text)
        self.assertNotIn("hotel", text)
        self.assertNotIn("meal", text)
        self.assertNotIn("telecom", text)
        row_actions = [
            button.text()
            for button in dialog.category_dictionary_rows_host.findChildren(QPushButton)
            if button.isVisible()
        ]
        self.assertIn("编辑名称", row_actions)
        row_meta = [
            label.text()
            for label in dialog.category_dictionary_rows_host.findChildren(QLabel)
            if "配置分类" in label.text()
        ]
        self.assertTrue(row_meta)
        self.assertTrue(all("配置分类 / 配置分类" not in text for text in row_meta))


    def test_ai_and_runtime_status_do_not_claim_session_usable_when_key_missing(self):
        dialog = self._make_dialog(
            config={
                "email": {"provider": "qq", "address": "your_email@qq.com"},
                "ai": {
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "profile_id": "ai-one",
                    "enabled": True,
                },
                "ai_profiles": [
                    {
                        "profile_id": "ai-one",
                        "name": "报销分类",
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "enabled": True,
                    }
                ],
            }
        )
        dialog.parent.db = MagicMock()
        dialog.parent.db.get_email_stats.return_value = {"pending": 0, "unclassified": 0}
        dialog.parent.db.count_pending_manual_invoices.return_value = 0

        with patch("scripts.invoice_fetch.credentials.get_ai_api_key_source", return_value="missing"), \
             patch("scripts.invoice_fetch.ai_classifier.is_provider_session_paused", return_value=False):
            dialog._refresh_settings_center_pages()

        self.assertIn("缺少 Key", dialog.lbl_ai_summary.text())
        self.assertNotIn("本次会话可用", dialog.lbl_ai_summary.text())
        self.assertIn("待补全 Key", dialog.lbl_runtime_status.text())
        self.assertNotIn("会话可用", dialog.lbl_runtime_status.text())


    def test_privacy_page_explicitly_separates_sent_and_local_only_data(self):
        dialog = self._make_dialog()
        self.assertIn("掩码后的主题", dialog.lbl_privacy_sent_items.text())
        self.assertIn("附件、PDF、图片", dialog.lbl_privacy_local_items.text())
        self.assertIn("系统凭据管理器", dialog.lbl_privacy_storage_note.text())
        self.assertIn("保持待分类", dialog.lbl_privacy_storage_note.text())

    def test_category_dictionary_add_rename_and_disable_used_entry(self):
        dialog = self._make_dialog(
            config={
                "email": {"provider": "qq", "address": "your_email@qq.com"},
                "ai": {"provider": "none", "model": "", "enabled": False},
                "categories": {
                    "hotel": {"name": "住宿"},
                },
            }
        )
        dialog.parent.db = MagicMock()
        dialog.parent.db.list_categories.return_value = ["住宿"]
        dialog.parent.db.get_email_stats.return_value = {"pending": 0, "unclassified": 0}
        dialog.parent.db.count_pending_manual_invoices.return_value = 0

        with patch("scripts.invoice_fetch.config.save_config") as mock_save:
            new_key = dialog._add_category_dictionary_entry("差旅")
            renamed = dialog._rename_category_dictionary_entry(new_key, "商务差旅")
            outcome = dialog._delete_category_dictionary_entry("hotel")

        self.assertTrue(new_key)
        self.assertTrue(renamed)
        self.assertEqual(outcome, "disabled")
        self.assertEqual(dialog.cfg["categories"]["hotel"]["disabled"], True)
        self.assertIn("商务差旅", [item.get("name") for item in dialog.cfg["categories"].values()])
        self.assertGreaterEqual(mock_save.call_count, 3)


class SettingsCenterMailboxTests(SettingsDialogTestMixin, unittest.TestCase):


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


class SettingsCenterAIProfileTests(SettingsDialogTestMixin, unittest.TestCase):


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


    def test_save_ai_profile_clear_key_does_not_raise(self):
        dialog = self._make_dialog()
        dialog._open_new_ai_editor()
        dialog.txt_ai_name.setText("My New AI")
        dialog.txt_ai_key.setText("new-secret-key")
        with patch("scripts.invoice_fetch.config.save_config") as mock_save, \
             patch("PySide6.QtWidgets.QMessageBox.information"), \
             patch("scripts.invoice_fetch.credentials.set_ai_api_key") as mock_set_key:
            dialog._save_ai_profile_settings(activate=True)
            mock_set_key.assert_called_once()
            mock_save.assert_called_once()
            self.assertEqual(dialog.txt_ai_key.text(), "")


    def test_ai_profile_rows_use_accent_actions_for_provider_and_missing_keys(self):
        config = {
            "email": {"provider": "qq", "address": "your_email@qq.com"},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "ai_profiles": [
                {
                    "profile_id": "deepseek-official",
                    "name": "DeepSeek 官方配置",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": False,
                },
                {
                    "profile_id": "gemini-official",
                    "name": "Gemini 官方配置",
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "enabled": False,
                },
            ],
        }

        def fake_key_source(provider, profile_id):
            if provider == "deepseek":
                return "provider"
            if provider == "gemini":
                return "missing"
            return "missing"

        with patch("scripts.invoice_fetch.credentials.get_ai_api_key_source", side_effect=fake_key_source):
            dialog = self._make_dialog(config=config)
            from scripts.invoice_fetch.gui.styles import APP_STYLESHEET
            dialog.setStyleSheet(APP_STYLESHEET)
            dialog.resize(650, 580)
            dialog.tab_widget.setCurrentIndex(1)
            dialog.show()
            QApplication.processEvents()

        self.assertEqual(len(dialog.ai_rows), 2)
        deepseek_row, gemini_row = dialog.ai_rows

        self.assertEqual(deepseek_row.btn_activate.text(), "启用 AI")
        self.assertEqual(gemini_row.btn_activate.text(), "配置 Key")
        self.assertEqual(deepseek_row.btn_activate.property("variant"), "accent")
        self.assertEqual(gemini_row.btn_activate.property("variant"), "accent")
        self.assertNotIn("primary", {deepseek_row.btn_activate.property("variant"), gemini_row.btn_activate.property("variant")})

        for row in (deepseek_row, gemini_row):
            self.assertTrue(row.btn_activate.isVisible())
            self.assertTrue(row.btn_activate.text())
            self.assertFalse(row.btn_activate.text().strip() == "")
            self.assertEqual(row.btn_edit.property("variant"), "secondary")
            self.assertEqual(row.btn_delete.property("variant"), "danger")
            center_color = row.btn_activate.grab().toImage().pixelColor(
                row.btn_activate.width() // 2,
                row.btn_activate.height() // 2,
            )
            self.assertNotEqual(center_color.name().lower(), "#ffffff")

            children = [w for w in row.findChildren(QPushButton) if w.isVisible()]
            self.assertTrue(all(btn.text().strip() for btn in children))
            self.assertTrue(all(btn.property("variant") != "primary" for btn in children))

        deepseek_key_rect = deepseek_row.lbl_key_status.geometry()
        deepseek_activate_rect = deepseek_row.btn_activate.geometry()
        deepseek_edit_rect = deepseek_row.btn_edit.geometry()
        deepseek_delete_rect = deepseek_row.btn_delete.geometry()
        self.assertLessEqual(deepseek_key_rect.x() + deepseek_key_rect.width(), deepseek_activate_rect.x())
        self.assertLessEqual(deepseek_activate_rect.x() + deepseek_activate_rect.width(), deepseek_edit_rect.x())
        self.assertLessEqual(deepseek_edit_rect.x() + deepseek_edit_rect.width(), deepseek_delete_rect.x())

        gemini_key_rect = gemini_row.lbl_key_status.geometry()
        gemini_activate_rect = gemini_row.btn_activate.geometry()
        gemini_edit_rect = gemini_row.btn_edit.geometry()
        gemini_delete_rect = gemini_row.btn_delete.geometry()
        self.assertLessEqual(gemini_key_rect.x() + gemini_key_rect.width(), gemini_activate_rect.x())
        self.assertLessEqual(gemini_activate_rect.x() + gemini_activate_rect.width(), gemini_edit_rect.x())
        self.assertLessEqual(gemini_edit_rect.x() + gemini_edit_rect.width(), gemini_delete_rect.x())

        self.assertIs(dialog.settings_stack.currentWidget(), dialog.page_settings_home)
        gemini_row.btn_activate.click()
        self.assertIs(dialog.settings_stack.currentWidget(), dialog.page_ai_editor)


if __name__ == "__main__":
    unittest.main()
