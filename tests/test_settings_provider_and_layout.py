# -*- coding: utf-8 -*-
"""
Tests for provider state machine fixes in settings dialog and detail panel layout.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QWidget, QSizePolicy
from PySide6.QtCore import Qt, QPoint

from tests.test_settings_dialog import SettingsDialogTestMixin
from scripts.invoice_fetch.db import InvoiceDB


class TestSettingsProviderSwitching(SettingsDialogTestMixin, unittest.TestCase):
    """Verify provider switching state machine and validation in SettingsDialog."""

    def test_provider_switching_during_edit_mode(self):
        # 1. Start with a saved QQ mailbox
        config = {
            "email": {"provider": "qq", "address": "test_user@qq.com"},
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "email_accounts": [
                {
                    "provider": "qq",
                    "address": "test_user@qq.com",
                    "mailbox_key": "test_user@qq.com",
                    "name": "QQ",
                }
            ],
        }

        dialog = self._make_dialog(config, saved_addresses=("test_user@qq.com",))

        # Open the editor in edit mode for this mailbox
        dialog._open_mailbox_editor("test_user@qq.com")
        self.assertTrue(dialog._editing_existing_mailbox)
        self.assertEqual(dialog._get_selected_provider(), "qq")
        self.assertEqual(dialog.txt_email.text(), "test_user@qq.com")
        self.assertEqual(dialog.txt_mailbox_name.text(), "QQ")
        self.assertEqual(dialog._loaded_account_mailbox_key, "test_user@qq.com")

        # 2. Switch provider card to netease_163 by checking it and clicking it
        dialog.cards["netease_163"].setChecked(True)
        dialog._on_provider_card_clicked(dialog.cards["netease_163"])

        # 3. Assert provider switching rewrites domain & default name in edit mode
        self.assertEqual(dialog._get_selected_provider(), "netease_163")
        self.assertEqual(dialog.txt_email.text(), "test_user@163.com")
        self.assertEqual(dialog.txt_mailbox_name.text(), "163")
        self.assertEqual(dialog._loaded_account_provider, "netease_163")
        # Keep original mailbox_key to enable in-place saving
        self.assertEqual(dialog._loaded_account_mailbox_key, "test_user@qq.com")

    def test_domain_consistency_validation_and_next_button(self):
        dialog = self._make_dialog()

        # Case 1: Matching domain -> Next enabled
        dialog._select_provider_card("netease_163")
        dialog._active_provider = "netease_163"
        dialog._loading_account_values = True
        dialog.txt_email.setText("test@163.com")
        dialog._loading_account_values = False
        dialog._update_provider_hint()
        dialog._update_wizard_ui()
        self.app.processEvents()
        self.assertTrue(dialog.btn_next.isEnabled())
        self.assertNotIn("不一致", dialog.lbl_provider_hint.text())

        # Case 2: Mismatched domain (e.g. 126.com under 163 provider) -> Next blocked
        dialog._active_provider = "netease_163"
        dialog._loading_account_values = True
        dialog.txt_email.setText("test@126.com")
        dialog._loading_account_values = False
        dialog._update_provider_hint()
        dialog._update_wizard_ui()
        self.app.processEvents()
        self.assertFalse(dialog.btn_next.isEnabled())
        self.assertIn("不一致", dialog.lbl_provider_hint.text())

        # Case 3: Custom domain under netease_163 (hosted enterprise email) is now STRICTLY blocked
        dialog._active_provider = "netease_163"
        dialog._loading_account_values = True
        dialog.txt_email.setText("test@my-company.com")
        dialog._loading_account_values = False
        dialog._update_provider_hint()
        dialog._update_wizard_ui()
        self.app.processEvents()
        self.assertFalse(dialog.btn_next.isEnabled())
        self.assertIn("不一致", dialog.lbl_provider_hint.text())

    def test_direct_next_step_call_cannot_bypass_mismatch(self):
        dialog = self._make_dialog()
        dialog.current_step = 1
        dialog._select_provider_card("netease_163")
        dialog._active_provider = "netease_163"
        dialog._loading_account_values = True
        dialog.txt_email.setText("test@my-company.com")
        dialog._loading_account_values = False

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn:
            dialog._goto_next_step()
            mock_warn.assert_called_once()
            # Assert step did not advance
            self.assertEqual(dialog.current_step, 1)

    def test_save_mailbox_settings_cannot_save_mismatched_domain(self):
        dialog = self._make_dialog()
        dialog._select_provider_card("netease_163")
        dialog._active_provider = "netease_163"
        dialog._loading_account_values = True
        dialog.txt_email.setText("test@my-company.com")
        dialog._loading_account_values = False

        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn, \
             patch("scripts.invoice_fetch.config.save_config") as mock_save:
            dialog._save_mailbox_settings()
            mock_warn.assert_called_once()
            mock_save.assert_not_called()

    def test_edit_qq_to_163_requires_retest_to_save(self):
        config = {
            "email": {"provider": "qq", "address": "test_user@qq.com"},
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "email_accounts": [
                {
                    "provider": "qq",
                    "address": "test_user@qq.com",
                    "mailbox_key": "test_user@qq.com",
                    "name": "QQ",
                }
            ],
        }

        dialog = self._make_dialog(config, saved_addresses=("test_user@qq.com",))

        # Open the editor in edit mode
        dialog._open_mailbox_editor("test_user@qq.com")
        self.assertTrue(dialog._editing_existing_mailbox)

        # Switch to 163
        dialog.cards["netease_163"].setChecked(True)
        dialog._on_provider_card_clicked(dialog.cards["netease_163"])

        # Try saving immediately without connection test (test_success is False)
        with patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.warning") as mock_warn, \
             patch("scripts.invoice_fetch.config.save_config") as mock_save:
            dialog._save_mailbox_settings()
            mock_warn.assert_called_once_with(
                dialog,
                "设置验证失败",
                "检测到敏感配置变更（邮箱地址、提供商或 IMAP 服务器已修改），必须重新输入授权码并测试连接成功后方可保存。"
            )
            mock_save.assert_not_called()

        # Input auth code and set test_success = True
        dialog.txt_auth_code.setText("dummy_auth_code")
        dialog.test_success = True

        with patch("scripts.invoice_fetch.config.save_config") as mock_save, \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information") as mock_info:
            dialog._save_mailbox_settings()
            mock_save.assert_called_once()
            mock_info.assert_called_once()

    def test_save_preserves_mailbox_key_without_duplicates(self):
        config = {
            "email": {"provider": "qq", "address": "test_user@qq.com"},
            "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
            "search": {"folder": "INBOX", "months_back": 3},
            "ai": {"provider": "none", "model": "", "enabled": False},
            "email_accounts": [
                {
                    "provider": "qq",
                    "address": "test_user@qq.com",
                    "mailbox_key": "test_user@qq.com",
                    "name": "QQ",
                }
            ],
        }

        dialog = self._make_dialog(config, saved_addresses=("test_user@qq.com",))
        dialog._open_mailbox_editor("test_user@qq.com")

        # Switch provider to 163
        dialog.cards["netease_163"].setChecked(True)
        dialog._on_provider_card_clicked(dialog.cards["netease_163"])

        dialog.txt_auth_code.setText("dummy_auth_code")
        dialog.test_success = True

        with patch("scripts.invoice_fetch.config.save_config") as mock_save, \
             patch("scripts.invoice_fetch.gui.settings_dialog.QMessageBox.information") as mock_info:
            dialog._save_mailbox_settings()
            mock_save.assert_called_once()
            mock_info.assert_called_once()
            saved_config = mock_save.call_args[0][0]
            accounts = saved_config.get("email_accounts", [])
            # Assert only 1 account exists (no duplicate added)
            self.assertEqual(len(accounts), 1)
            # Assert original mailbox_key is preserved
            self.assertEqual(accounts[0]["mailbox_key"], "test_user@qq.com")
            # Assert provider is updated
            self.assertEqual(accounts[0]["provider"], "netease_163")


class TestInvoiceDetailPanelLayout(unittest.TestCase):
    """Verify geometry / size policy adjustments in InvoiceDetailPanel."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def setUp(self):
        from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel
        self.panel = InvoiceDetailPanel()

    def tearDown(self):
        if hasattr(self, "panel") and self.panel is not None:
            self.panel.close()
            self.panel.deleteLater()
            if self.app:
                self.app.processEvents()

    def test_detail_workbench_size_policy_and_layout_margins(self):
        # 1. detail_workbench should be expanding vertically, not fixed
        self.assertEqual(
            self.panel.detail_workbench.sizePolicy().verticalPolicy(),
            QSizePolicy.Expanding
        )

        # 2. right_content_layout top and bottom margins must be 0 for proper vertical alignment
        margins = self.panel.right_layout.contentsMargins()
        self.assertEqual(margins.top(), 0)
        self.assertEqual(margins.bottom(), 0)

        # 3. Verify no extra addStretch is added outside the workbench card layout
        count = self.panel.right_layout.count()
        stretch_exists = False
        for i in range(count):
            item = self.panel.right_layout.itemAt(i)
            if item.spacerItem() is not None:
                stretch_exists = True
                break
        self.assertFalse(stretch_exists, "right_layout should not have a spacer/stretch pushing detail_workbench up")


class TestInvoiceReviewAppGeometry(unittest.TestCase):
    """Verify real geometry alignment of components in InvoiceReviewApp."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def test_main_window_vertical_alignment_with_real_record(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_gui_geometry.db"
            with InvoiceDB(db_path) as db:
                db.insert_invoice({
                    "invoice_number": "CAT001",
                    "total_amount": "88.00",
                    "seller_name": "Geometry Seller",
                    "invoice_date": "2026-05-24",
                    "category": "餐饮",
                    "review_status": "to_review",
                })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            cfg = {
                "reimbursement": {
                    "buyer_name": "示例公司",
                    "strict_buyer_check": False,
                }
            }
            with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=cfg):
                window = InvoiceReviewApp(db_path, splash=None)

            try:
                window._deferred_init()
                self.app.processEvents()

                # Resize to 1680x1050 to ensure the viewport is taller than detail_workbench minimum height
                window.resize(1680, 1050)
                window.show()
                self.app.processEvents()

                # Select row to show detail_workbench
                window.table.selectRow(0)
                self.app.processEvents()

                # Verify detail_workbench is visible
                self.assertTrue(window._detail_panel.detail_workbench.isVisible())

                table_top = window.table.mapToGlobal(QPoint(0, 0)).y()
                workbench_top = window._detail_panel.detail_workbench.mapToGlobal(QPoint(0, 0)).y()

                preview_bottom = window.preview_panel.mapToGlobal(QPoint(0, 0)).y() + window.preview_panel.height()
                workbench_bottom = window._detail_panel.detail_workbench.mapToGlobal(QPoint(0, 0)).y() + window._detail_panel.detail_workbench.height()

                # Assert top/bottom coordinates align within a small tolerance.
                self.assertLessEqual(abs(table_top - workbench_top), 6, "detail_workbench top is offset from table top by > 6px")
                self.assertLessEqual(abs(preview_bottom - workbench_bottom), 6, "detail_workbench bottom is offset from preview_panel bottom by > 6px")

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_detail_row_alignment_uses_shared_left_edge_and_fixed_action_cluster(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_gui_geometry_rows.db"
            with InvoiceDB(db_path) as db:
                db.insert_invoice({
                    "invoice_number": "CAT002",
                    "total_amount": "66.00",
                    "seller_name": "Geometry Seller 2",
                    "invoice_date": "2026-05-25",
                    "category": "餐饮",
                    "review_status": "to_review",
                })

            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            cfg = {
                "reimbursement": {
                    "buyer_name": "示例公司",
                    "strict_buyer_check": False,
                }
            }
            with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=cfg):
                window = InvoiceReviewApp(db_path, splash=None)

            try:
                window._deferred_init()
                self.app.processEvents()
                window.resize(1680, 1050)
                window.show()
                self.app.processEvents()
                window.table.selectRow(0)
                self.app.processEvents()

                panel = window._detail_panel
                self.assertFalse(hasattr(panel, "lbl_evidence_dot"))
                panel.set_note("示例备注")
                panel.update_evidence_row([])
                self.app.processEvents()

                core_x = panel.txt_number.mapToGlobal(QPoint(0, 0)).x()
                amount_x = panel.txt_amount.mapToGlobal(QPoint(0, 0)).x()
                buyer_x = panel.txt_buyer.mapToGlobal(QPoint(0, 0)).x()
                path_x = panel.txt_path.mapToGlobal(QPoint(0, 0)).x()
                claim_x = panel.combo_claims.mapToGlobal(QPoint(0, 0)).x()
                note_x = panel.txt_note.mapToGlobal(QPoint(0, 0)).x()
                missing_x = panel.lbl_evidence_missing.mapToGlobal(QPoint(0, 0)).x()

                self.assertLessEqual(abs(core_x - amount_x), 4)
                self.assertLessEqual(abs(core_x - buyer_x), 4)
                self.assertLessEqual(abs(path_x - claim_x), 4)
                self.assertLessEqual(abs(path_x - note_x), 4)
                self.assertLessEqual(abs(path_x - missing_x), 6)

                panel.update_evidence_row([
                    {"label": "proof.pdf", "path": "/tmp/proof.pdf"}
                ])
                self.app.processEvents()
                filename_x = panel.lbl_evidence_name.mapToGlobal(QPoint(0, 0)).x()
                self.assertLessEqual(abs(path_x - filename_x), 6)

                claim_actions_x = panel.claim_actions_widget.mapToGlobal(QPoint(0, 0)).x()
                claim_combo_right = claim_x + panel.combo_claims.width()
                self.assertGreaterEqual(claim_actions_x, claim_combo_right - 2)
                self.assertGreaterEqual(panel.claim_actions_widget.layout().indexOf(panel.btn_delete_claim), 0)
                self.assertEqual(panel.claim_summary_row.indexOf(panel.btn_delete_claim), -1)
                self.assertGreater(panel.detail_workbench.height(), 0)

            finally:
                if hasattr(window, "db") and window.db is not None:
                    window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()
