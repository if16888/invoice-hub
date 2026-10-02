import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from scripts.invoice_fetch.gui.app import SingleTaskMailboxDialog


class MailboxInputDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mailbox_account_completion_and_provider_switch(self):
        dialog = SingleTaskMailboxDialog()
        try:
            dialog.txt_email.setText("123456789")
            self.assertIn("123456789@qq.com", dialog.email_preview.text())
            dialog.combo_provider.setCurrentIndex(dialog.combo_provider.findData("netease_163"))
            self.assertIn("123456789@163.com", dialog.email_preview.text())
            self.assertEqual(dialog.txt_server.text(), "imap.163.com")
            dialog._accept_form()
            account, secret = dialog.get_result_account()
            self.assertEqual(dialog.result(), QDialog.Accepted)
            self.assertEqual(account["address"], "123456789@163.com")
            self.assertEqual(account["provider"], "netease_163")
            self.assertEqual(account["search"]["months_back"], 3)
            self.assertEqual(secret, "")
        finally:
            dialog.close()

    def test_full_paste_preserves_alias_and_selects_provider(self):
        dialog = SingleTaskMailboxDialog()
        try:
            dialog.txt_email.setText("tester@hotmail.com")
            self.assertEqual(dialog.combo_provider.currentData(), "outlook")
            self.assertTrue(dialog.email_suffix.isHidden())
            dialog._accept_form()
            account, _ = dialog.get_result_account()
            self.assertEqual(account["address"], "tester@hotmail.com")
            self.assertEqual(account["imap"]["server"], "outlook.office365.com")
        finally:
            dialog.close()

    def test_custom_mailbox_preserves_saved_server_and_rejects_missing_domain(self):
        dialog = SingleTaskMailboxDialog(account={
            "provider": "custom",
            "address": "test@enterprise.invalid",
            "imap": {"server": "mail.enterprise.invalid", "port": 1993},
        })
        try:
            self.assertEqual(dialog.txt_server.text(), "mail.enterprise.invalid")
            self.assertEqual(dialog.spin_port.value(), 1993)
            dialog.txt_email.setText("incomplete")
            dialog._accept_form()
            self.assertNotEqual(dialog.result(), QDialog.Accepted)
            self.assertFalse(dialog.lbl_form_error.isHidden())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
