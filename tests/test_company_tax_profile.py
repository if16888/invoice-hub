import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.company_tax_profile import (
    CompanyTaxProfileDialog,
    format_company_tax_info,
    normalize_company_tax_profile,
    save_company_tax_profile,
)
from scripts.invoice_fetch.reimbursement import buyer_warning, normalize_tax_id


class CompanyTaxProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_profile_normalizes_copy_ready_fields(self):
        profile = normalize_company_tax_profile(
            {
                "buyer_name": "  Example Company  ",
                "buyer_tax_id": "91 32-abcd-001",
                "registered_address": "  Example Road 1  ",
                "bank_account": " 6222 0000 1111 ",
                "strict_buyer_check": 1,
            }
        )
        self.assertEqual(profile["buyer_name"], "Example Company")
        self.assertEqual(profile["buyer_tax_id"], "9132ABCD001")
        self.assertEqual(profile["registered_address"], "Example Road 1")
        self.assertEqual(profile["bank_account"], "622200001111")
        self.assertTrue(profile["strict_buyer_check"])
        self.assertFalse(profile["strict_buyer_tax_check"])

    def test_buyer_name_check_defaults_to_enabled_when_a_profile_is_created(self):
        profile = normalize_company_tax_profile({"buyer_name": "Example Company"})
        self.assertTrue(profile["strict_buyer_check"])

    def test_copy_text_omits_blank_optional_fields(self):
        text = format_company_tax_info(
            {
                "buyer_name": "Example Company",
                "buyer_tax_id": "91320000123456789X",
                "bank_name": "Example Bank",
            }
        )
        self.assertEqual(
            text,
            "单位名称：Example Company\n"
            "纳税人识别号：91320000123456789X\n"
            "开户行：Example Bank",
        )
        self.assertNotIn("注册地址", text)
        self.assertNotIn("银行账号", text)

    def test_buyer_warning_combines_name_and_tax_mismatches(self):
        cfg = {
            "reimbursement": {
                "buyer_name": "Expected Company",
                "buyer_tax_id": "91320000123456789X",
                "strict_buyer_check": True,
                "strict_buyer_tax_check": True,
            }
        }
        warning = buyer_warning(
            {
                "buyer_name": "Actual Company",
                "buyer_tax_id": "91320000999999999X",
            },
            cfg,
        )
        self.assertIn("购买方抬头不匹配", warning)
        self.assertIn("购买方税号不匹配", warning)

    def test_legacy_invoice_without_tax_field_does_not_warn_permanently(self):
        cfg = {
            "reimbursement": {
                "buyer_name": "Expected Company",
                "buyer_tax_id": "91320000123456789X",
                "strict_buyer_check": True,
                "strict_buyer_tax_check": True,
            }
        }
        self.assertEqual(
            buyer_warning({"buyer_name": "Expected Company"}, cfg),
            "",
        )
        self.assertEqual(normalize_tax_id("91-32 0000 abcd"), "91320000ABCD")

    def test_dialog_loads_all_company_fields(self):
        dialog = CompanyTaxProfileDialog(
            {
                "buyer_name": "Example Company",
                "buyer_tax_id": "91320000123456789X",
                "registered_address": "Example Road 1",
                "registered_phone": "010-12345678",
                "bank_name": "Example Bank",
                "bank_account": "622200001111",
                "strict_buyer_check": True,
                "strict_buyer_tax_check": True,
            }
        )
        try:
            self.assertEqual(dialog.txt_buyer_name.text(), "Example Company")
            self.assertEqual(dialog.txt_tax_id.text(), "91320000123456789X")
            self.assertEqual(dialog.txt_registered_address.text(), "Example Road 1")
            self.assertEqual(dialog.txt_registered_phone.text(), "010-12345678")
            self.assertEqual(dialog.txt_bank_name.text(), "Example Bank")
            self.assertEqual(dialog.txt_bank_account.text(), "622200001111")
            self.assertTrue(dialog.chk_strict_name.isChecked())
            self.assertTrue(dialog.chk_strict_tax.isChecked())
        finally:
            dialog.close()

    def test_save_preserves_other_local_config_sections(self):
        window = SimpleNamespace(
            config={"email_accounts": [{"address": "synthetic@example.com"}], "reimbursement": {}},
            _desktop_settings_cfg={},
        )
        with patch("scripts.invoice_fetch.gui.company_tax_profile.save_config") as save:
            saved = save_company_tax_profile(
                window,
                {
                    "buyer_name": "Example Company",
                    "buyer_tax_id": "91320000123456789X",
                    "registered_address": "Example Road 1",
                    "strict_buyer_check": True,
                },
            )
        self.assertEqual(saved["buyer_name"], "Example Company")
        self.assertEqual(window.config["reimbursement"]["buyer_tax_id"], "91320000123456789X")
        self.assertEqual(window.config["email_accounts"][0]["address"], "synthetic@example.com")
        save.assert_called_once_with(window.config)

    def test_review_pipeline_keeps_profile_check_without_settings_shortcut(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "company-profile.db")
            window.resize(1600, 900)
            window.show()
            window._switch_main_page("review")
            for _ in range(8):
                self.app.processEvents()
            try:
                detail = window._detail_panel
                self.assertTrue(window.review_page.property("companyTaxProfileApplied"))
                self.assertTrue(
                    window.review_page.property("designV1ReviewTaskClosureApplied")
                )
                self.assertTrue(detail.buyer_warning_action_row.isHidden())
                self.assertTrue(detail.btn_edit_reimbursement_title.isHidden())
                self.assertTrue(
                    detail.btn_edit_reimbursement_title.property(
                        "reviewCompanyActionRemoved"
                    )
                )
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
