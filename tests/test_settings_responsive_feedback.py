import os
import tempfile
import unittest
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from scripts.dev.capture_design_v1 import _synthetic_config, _synthetic_credential_context
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.hci_v1 import _history_recheck_finished
from scripts.invoice_fetch.gui.mailbox_feedback import connection_feedback, forget_connection_result
from scripts.invoice_fetch.gui.settings_pages_baseline import LONG_VALUE_FIELDS
from scripts.invoice_fetch.hci_v1_services import recheck_known_email_history


class SettingsResponsiveFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def settle(self):
        for _ in range(15):
            self.app.processEvents()
        QTest.qWait(100)  # item views schedule their resize layout on a timer

    @contextmanager
    def window(self):
        cfg = _synthetic_config()
        second = deepcopy(cfg["email_accounts"][0])
        second.update(mailbox_key="other", address="other@example.invalid", is_default=False)
        cfg["email_accounts"].append(second)
        cfg["ai_profiles"] = [dict(profile_id="fixture-ai", name="Synthetic AI", provider="gemini",
                                   model="gemini-2.5-flash", enabled=True),
                              dict(profile_id="second-ai", name="Secondary AI", provider="deepseek",
                                   model="deepseek-chat", enabled=False)]
        with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
            stack.enter_context(_synthetic_credential_context("settings-mailbox", "default"))
            stack.enter_context(patch("keyring.get_password", side_effect=AssertionError("real credentials touched")))
            stack.enter_context(patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=cfg))
            stack.enter_context(patch("scripts.invoice_fetch.config.load_config_safe", return_value=cfg))
            stack.enter_context(patch("scripts.invoice_fetch.gui.workbench_settings.RUNTIME_DIR", Path(td)))
            stack.enter_context(patch("scripts.invoice_fetch.gui.app.migrate_legacy_workbench_settings", return_value=True))
            stack.enter_context(patch("scripts.invoice_fetch.credentials.get_ai_api_key_source", return_value="profile"))
            stack.enter_context(patch("scripts.invoice_fetch.credentials.has_ai_api_key", return_value=True))
            window = InvoiceReviewApp(Path(td) / "review.db")
            window.resize(1366, 768)
            window.show()
            self.settle()
            window._switch_main_page("settings")
            self.settle()
            try:
                yield window, cfg
            finally:
                window.close()
                window.deleteLater()
                self.settle()

    def test_actual_settings_shell_wraps_and_scrolls_all_pages(self):
        with self.window() as (window, _):
            window.btn_settings_ai_test.click()
            window.lbl_settings_mailbox_test_status.setText("测试连接失败：" + "请检查授权码与服务器设置。" * 12)
            for attr in ("lbl_settings_runtime", "lbl_settings_privacy", "lbl_settings_data", "lbl_settings_about"):
                surface = getattr(window, attr)
                for key in surface.values:
                    if key in LONG_VALUE_FIELDS:
                        surface.set_value(key, "用于验证窄窗口下完整可读的长说明。" * 8)
            # A wide outer window can contain a narrow centered settings shell.
            # Exercise that case and effective widths at 125%/150% scaling.
            for width in (1120, 900, 720, 600):
                window.settings_page.setFixedWidth(width + 48)
                for index in range(window.settings_tabs.stack.count()):
                    with self.subTest(width=width, page=index):
                        if index < window.settings_tabs.count():
                            window.settings_tabs.setCurrentIndex(index)
                        else:
                            window.settings_tabs.nav_list.setCurrentRow(1)  # company page
                        self.settle()
                        if index == 1:
                            window.btn_settings_ai_test.click()
                            self.settle()
                            self.assertTrue(window.lbl_settings_ai_failure_status.isVisible())
                        scroll = window.settings_tabs.scroll_area
                        page = window.settings_tabs.stack.currentWidget()
                        self.assertLessEqual(window.settings_tabs.width(), width)
                        self.assertLessEqual(page.width(), scroll.viewport().width())
                        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                        for label in page.findChildren(QLabel):
                            if not label.isVisible():
                                continue
                            pos = label.mapTo(page, QPoint(0, 0))
                            self.assertGreaterEqual(pos.x(), 0, label.text()[:18])
                            self.assertLessEqual(pos.x() + label.width(), page.width(), label.text()[:18])
                            if label.wordWrap() and label.text():
                                self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()),
                                                        label.text()[:25])
                        if index in (0, 1) and width == 600:
                            self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
            for name in ("lbl_settings_ai_validation_status", "lbl_settings_ai_send_boundary",
                         "lbl_settings_ai_log_redaction", "lbl_settings_ai_failure_status"):
                label = getattr(window, name)
                self.assertTrue(label.wordWrap())
                self.assertTrue(label.sizePolicy().hasHeightForWidth())
                self.assertGreater(label.maximumHeight(), label.minimumHeight())

    def test_saved_secret_is_not_connection_success_and_results_follow_account(self):
        with self.window() as (window, cfg):
            self.assertEqual(window.lbl_detail_header_status.text(), "尚未验证")
            with patch("scripts.invoice_fetch.credentials.get_auth_code", return_value="synthetic-secret"), \
                 patch("scripts.invoice_fetch.mail_fetcher.MailFetcher") as fetcher:
                window._test_settings_mailbox_connection()
                self.settle()
                fetcher.return_value.connect.assert_called_once()
                fetcher.return_value.disconnect.assert_called_once()
            self.assertIn("成功", window.lbl_settings_mailbox_test_status.text())
            window.settings_mailbox_list.setCurrentRow(1)
            self.settle()
            self.assertNotIn("成功", window.lbl_settings_mailbox_test_status.text())
            window.settings_mailbox_list.setCurrentRow(0)
            self.settle()
            self.assertIn("成功", window.lbl_settings_mailbox_test_status.text())
            forget_connection_result(window, cfg["email_accounts"][0])
            window._refresh_settings_mailbox_page()
            self.assertIn("尚未验证", window.lbl_settings_mailbox_test_status.text())

    def test_wrong_secret_reports_failure_not_saved_or_previous_success(self):
        with self.window() as (window, cfg):
            with patch("scripts.invoice_fetch.credentials.get_auth_code", return_value="synthetic-secret"), \
                 patch("scripts.invoice_fetch.mail_fetcher.MailFetcher") as fetcher:
                fetcher.return_value.connect.side_effect = RuntimeError("LOGIN failed synthetic-secret")
                window._test_settings_mailbox_connection()
                self.settle()
                fetcher.return_value.disconnect.assert_called_once()
            self.assertEqual(window.lbl_detail_header_status.text(), "连接失败")
            message = window.lbl_settings_mailbox_test_status.text()
            self.assertIn("LOGIN failed", message)
            self.assertNotIn("synthetic-secret", message)
            edited = deepcopy(cfg["email_accounts"][0])
            edited["imap"]["server"] = "changed.example.invalid"
            self.assertEqual(connection_feedback(window, edited, True)[0], "尚未验证")
            self.assertEqual(connection_feedback(window, cfg["email_accounts"][0], False)[0], "需要授权")

    def test_empty_history_is_noop_not_mailbox_validation_or_success_activity(self):
        with self.window() as (window, cfg):
            with patch("scripts.invoice_fetch.hci_v1_services.load_config_safe", return_value=cfg), \
                 patch("scripts.invoice_fetch.__main__._reprocess_email_records") as reprocess, \
                 patch("scripts.invoice_fetch.mail_fetcher.MailFetcher") as fetcher:
                result = recheck_known_email_history(window.db_path, since="2026-01-01")
                reprocess.assert_not_called()
                fetcher.assert_not_called()
            with patch.object(window, "_record_import_activity") as record:
                _history_recheck_finished(window, result)
                self.settle()
                record.assert_not_called()
            self.assertIn("本次未连接邮箱", window.lbl_import_scan_status.text())
            self.assertNotIn("同步完成", window.lbl_import_scan_status.text())
            window._refresh_imports_page()
            self.settle()
            self.assertIn("暂无可重新检查", window.lbl_import_scan_status.text())
            self.assertEqual(window._hci_history_terminal_card[0], "暂无可重新检查的历史邮件")

    def test_history_backend_failure_reaches_terminal_card_and_activity(self):
        with self.window() as (window, cfg):
            window.db._conn.execute(
                "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
                "VALUES ('synthetic-mailbox', 901, 'Synthetic', 'fixture', '2026-06-01', 1, 0)"
            )
            window.db._conn.commit()
            with patch("scripts.invoice_fetch.hci_v1_services.load_config_safe", return_value=cfg), \
                 patch("scripts.invoice_fetch.__main__._reprocess_email_records", return_value={"failed": 1}):
                result = recheck_known_email_history(window.db_path, since="2026-01-01")
            self.assertEqual(result["failed"], 1)
            with patch.object(window, "_record_import_activity") as record:
                _history_recheck_finished(window, result)
                self.settle()
                self.assertEqual(record.call_args.kwargs["failed"], 1)
                self.assertEqual(record.call_args.kwargs["status"], "failed")
            window._refresh_imports_page()
            self.settle()
            self.assertIn("失败 1 封", window.lbl_import_scan_status.text())
            self.assertNotIn("同步完成", window.lbl_import_scan_status.text())
            self.assertEqual(window._hci_scan_presentation_state, "failed")


if __name__ == "__main__":
    unittest.main()
