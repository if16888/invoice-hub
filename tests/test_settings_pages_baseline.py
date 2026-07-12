import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QPushButton

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.settings_pages_baseline import StructuredSettingsSurface, _normalize_ai
from scripts.invoice_fetch.gui.ui_components import ReadOnlyDetailPanel


class SettingsPagesBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "settings-pages.db")
        window.resize(1366, 768)
        window.show()
        for _ in range(4):
            self.app.processEvents()
        window._switch_main_page("settings")
        for _ in range(3):
            self.app.processEvents()
        return window

    def test_all_remaining_settings_pages_are_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for index in range(1, 6):
                    page = window.settings_tabs.widget(index)
                    self.assertTrue(page.property("settingsBaselineMigrated"), index)
            finally:
                window.close()

    def test_runtime_privacy_data_and_about_use_one_bounded_surface(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for index, attr in (
                    (2, "lbl_settings_runtime"),
                    (3, "lbl_settings_privacy"),
                    (4, "lbl_settings_data"),
                    (5, "lbl_settings_about"),
                ):
                    page = window.settings_tabs.widget(index)
                    surfaces = page.findChildren(QFrame, "SettingsDetailSurface")
                    self.assertEqual(len(surfaces), 1, index)
                    surface = getattr(window, attr)
                    self.assertIsInstance(surface, StructuredSettingsSurface)
                    self.assertEqual(surface.minimumWidth(), 560)
                    self.assertEqual(surface.maximumWidth(), 760)
                    self.assertEqual(page.findChildren(ReadOnlyDetailPanel), [])
            finally:
                window.close()

    def test_runtime_and_data_refresh_into_field_grid(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._refresh_settings_page()
                self.app.processEvents()
                runtime = window.lbl_settings_runtime
                data = window.lbl_settings_data
                self.assertNotEqual(runtime.values["数据库"].text(), "—")
                self.assertNotEqual(runtime.values["日志目录"].text(), "—")
                self.assertNotEqual(data.values["数据库大小"].text(), "—")
                self.assertNotEqual(data.values["数据目录"].text(), "—")
                self.assertTrue(runtime.values["数据库"].toolTip())
                self.assertTrue(data.values["数据目录"].toolTip())
            finally:
                window.close()

    def test_privacy_page_keeps_explicit_local_first_contract(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                privacy = window.lbl_settings_privacy
                self.assertEqual(privacy.values["处理方式"].text(), "本地处理")
                self.assertEqual(privacy.values["凭据存储"].text(), "Windows 凭据管理器")
                self.assertIn("脱敏", privacy.values["配置与日志"].text())
                buttons = [button.text() for button in privacy.findChildren(QPushButton)]
                self.assertIn("导出脱敏诊断包", buttons)
            finally:
                window.close()

    def test_ai_uses_one_integration_surface_and_product_copy(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                page = window.settings_tabs.widget(1)
                self.assertEqual(len(page.findChildren(QFrame, "AISettingsDetailSurface")), 1)
                self.assertEqual(page.findChildren(ReadOnlyDetailPanel), [])
                window.lbl_settings_ai_enabled.setText("开启")
                window.lbl_settings_ai_session_state.setText("正常")
                window.lbl_settings_ai_key_status.setText("provider")
                window.settings_ai_profile_list.addItem("Synthetic")
                _normalize_ai(window)
                self.assertEqual(window.lbl_settings_ai_key_status.text(), "已安全保存")
                self.assertEqual(window.lbl_settings_ai_status_badge.text(), "正常")
                self.assertEqual(window.lbl_settings_ai_credential_store.text(), "Windows 凭据管理器")
            finally:
                window.close()

    def test_settings_action_footers_remain_content_height(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for index in range(1, 6):
                    page = window.settings_tabs.widget(index)
                    footers = page.findChildren(QFrame, "SettingsActionFooter")
                    self.assertEqual(len(footers), 1, index)
                    self.assertGreaterEqual(footers[0].minimumHeight(), 52)
                    self.assertLessEqual(footers[0].sizeHint().height(), 80)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
