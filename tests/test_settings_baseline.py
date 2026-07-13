import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel

from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class SettingsBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "settings-baseline.db")
        window.show()
        self.app.processEvents()
        self.app.processEvents()
        window._switch_main_page("settings")
        window.settings_tabs.setCurrentIndex(0)
        self.app.processEvents()
        return window

    def test_settings_contract_matches_design_baseline_v1(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                margins = window.settings_page.layout().contentsMargins()
                self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()), (24, 24, 24, 24))
                self.assertEqual(window.settings_page.layout().spacing(), 20)
                self.assertEqual(window.settings_tabs.maximumWidth(), 1120)
                self.assertEqual(window.settings_tabs.nav_list.width(), 168)
                self.assertEqual(window.settings_mailbox_list.width(), 280)
                self.assertEqual(window.mailbox_detail_surface.minimumWidth(), 560)
                self.assertEqual(window.mailbox_detail_surface.maximumWidth(), 760)
            finally:
                window.close()

    def test_mailbox_footer_is_inside_single_detail_surface(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                surface = window.mailbox_detail_surface
                self.assertEqual(surface.objectName(), "MailboxDetailSurface")
                footer = surface.findChild(QFrame, "MailboxActionFooter")
                self.assertIsNotNone(footer)
                self.assertGreaterEqual(footer.minimumHeight(), 52)
                self.assertIs(window.btn_settings_mailbox_scan.parentWidget(), footer)
                self.assertIs(window.btn_settings_mailbox_test.parentWidget(), footer)
                self.assertIs(window.btn_settings_mailbox_edit_config.parentWidget(), footer)
            finally:
                window.close()

    def test_mailbox_rows_keep_badges_on_title_line(self):
        account = {
            "mailbox_key": "synthetic@example.invalid",
            "name": "A deliberately long synthetic mailbox display name",
            "address": "synthetic@example.invalid",
            "enabled": True,
            "is_default": True,
        }
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                with patch.object(window, "_mailbox_accounts_for_settings", return_value=[account]), patch(
                    "scripts.invoice_fetch.gui.settings_baseline.has_auth_code", return_value=True
                ):
                    window.settings_mailbox_list.clear()
                    item = window.settings_mailbox_list.add_entity_row(
                        title=account["name"],
                        subtitle="sy***c@example.invalid",
                        status_badge="正常",
                        meta="默认",
                        user_data=account["mailbox_key"],
                    )
                    self.app.processEvents()
                    self.app.processEvents()

                    row = window.settings_mailbox_list.itemWidget(item)
                    self.assertEqual(row.objectName(), "MailboxAccountRow")
                    title = next(
                        label for label in row.findChildren(QLabel)
                        if label.property("class") == "MailboxAccountTitle"
                    )
                    address = next(
                        label for label in row.findChildren(QLabel)
                        if label.property("class") == "MailboxAccountAddress"
                    )
                    badges = [
                        label for label in row.findChildren(QLabel)
                        if label.property("class") == "StatusBadge"
                    ]
                    self.assertEqual(title.toolTip(), account["name"])
                    self.assertEqual(address.toolTip(), account["address"])
                    self.assertEqual({badge.text() for badge in badges}, {"默认", "正常"})
                    self.assertGreaterEqual(item.sizeHint().height(), 68)
            finally:
                window.close()

    def test_empty_mailbox_uses_one_actionable_state(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.settings_mailbox_list.clear()
                self.app.processEvents()
                self.app.processEvents()
                self.assertFalse(window.settings_mailbox_list.isVisible())
                self.assertTrue(window.settings_mailbox_empty_state.isVisible())
                self.assertTrue(window.btn_settings_mailbox_empty_add.isVisible())
                self.assertEqual(window.btn_settings_mailbox_empty_add.text(), "新增邮箱账号")
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
