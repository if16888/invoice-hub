# -*- coding: utf-8 -*-
"""
Tests for provider state machine fixes in settings dialog and detail panel layout.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QWidget, QSizePolicy
from PySide6.QtCore import Qt

from tests.test_settings_dialog import SettingsDialogTestMixin


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

        # Case 3: Custom domain under netease_163 (hosted enterprise email) -> Next allowed
        dialog._active_provider = "netease_163"
        dialog._loading_account_values = True
        dialog.txt_email.setText("test@my-company.com")
        dialog._loading_account_values = False
        dialog._update_provider_hint()
        dialog._update_wizard_ui()
        self.app.processEvents()
        self.assertTrue(dialog.btn_next.isEnabled())
        self.assertNotIn("不一致", dialog.lbl_provider_hint.text())


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

        # 2. right_content_layout top margin must be 0 for proper vertical alignment
        margins = self.panel.right_layout.contentsMargins()
        self.assertEqual(margins.top(), 0)

        # 3. Verify no extra addStretch is added outside the workbench card layout
        # (Only 1 item should be in right_layout layout after detail_workbench, or detail_workbench is added directly)
        count = self.panel.right_layout.count()
        # Find if any stretch item exists in right_layout
        stretch_exists = False
        for i in range(count):
            item = self.panel.right_layout.itemAt(i)
            if item.spacerItem() is not None:
                stretch_exists = True
                break
        self.assertFalse(stretch_exists, "right_layout should not have a spacer/stretch pushing detail_workbench up")
