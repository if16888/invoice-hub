import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog
from scripts.invoice_fetch.gui.app import SingleTaskMailboxDialog


def test_mailbox_account_completion_and_provider_switch():
    app = QApplication.instance() or QApplication([])
    dialog = SingleTaskMailboxDialog()
    dialog.txt_email.setText("123456789")
    assert "123456789@qq.com" in dialog.email_preview.text()
    dialog.combo_provider.setCurrentIndex(dialog.combo_provider.findData("netease_163"))
    assert "123456789@163.com" in dialog.email_preview.text()
    assert dialog.txt_server.text() == "imap.163.com"
    dialog._accept_form()
    account, secret = dialog.get_result_account()
    assert dialog.result() == QDialog.Accepted
    assert account["address"] == "123456789@163.com"
    assert account["provider"] == "netease_163"
    assert account["search"]["months_back"] == 3
    assert secret == ""


def test_full_paste_preserves_alias_and_selects_provider():
    app = QApplication.instance() or QApplication([])
    dialog = SingleTaskMailboxDialog()
    dialog.txt_email.setText("tester@hotmail.com")
    assert dialog.combo_provider.currentData() == "outlook"
    assert dialog.email_suffix.isHidden()
    dialog._accept_form()
    assert dialog.get_result_account()[0]["address"] == "tester@hotmail.com"
    assert dialog.get_result_account()[0]["imap"]["server"] == "outlook.office365.com"


def test_custom_mailbox_preserves_saved_server_and_rejects_missing_domain():
    app = QApplication.instance() or QApplication([])
    dialog = SingleTaskMailboxDialog(account={
        "provider": "custom", "address": "test@enterprise.invalid",
        "imap": {"server": "mail.enterprise.invalid", "port": 1993},
    })
    assert dialog.txt_server.text() == "mail.enterprise.invalid"
    assert dialog.spin_port.value() == 1993
    dialog.txt_email.setText("incomplete")
    dialog._accept_form()
    assert dialog.result() != QDialog.Accepted
    assert not dialog.lbl_form_error.isHidden()
