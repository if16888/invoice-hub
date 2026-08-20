import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.dev.capture_design_v1 import _synthetic_config, _synthetic_credential_context
from scripts.invoice_fetch import credentials as credentials_module
from scripts.invoice_fetch.gui import app as app_module
from scripts.invoice_fetch.gui import settings_baseline, settings_dialog
from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class CaptureCredentialIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_window_construction_cannot_reach_real_credential_backend(self):
        def fail_if_real_backend_is_called(_address):
            raise AssertionError("capture construction called the real credential backend")

        with tempfile.TemporaryDirectory() as td:
            with patch.object(credentials_module, "has_auth_code", fail_if_real_backend_is_called), \
                patch.object(settings_baseline, "has_auth_code", fail_if_real_backend_is_called), \
                patch.object(settings_dialog, "has_auth_code", fail_if_real_backend_is_called, create=True), \
                patch.object(
                    app_module,
                    "load_config_safe",
                    return_value=_synthetic_config("settings-mailbox", "default"),
                ):
                with _synthetic_credential_context("settings-mailbox", "default") as synthetic_has_auth_code:
                    self.assertIs(credentials_module.has_auth_code, synthetic_has_auth_code)
                    self.assertIs(settings_baseline.has_auth_code, synthetic_has_auth_code)
                    self.assertIs(settings_dialog.has_auth_code, synthetic_has_auth_code)

                    window = InvoiceReviewApp(Path(td) / "capture-credentials.db")
                    try:
                        window.show()
                        self.app.processEvents()
                        window._switch_main_page("settings")
                        window.settings_tabs.nav_list.setCurrentRow(0)
                        self.app.processEvents()
                        self.assertGreater(window.settings_mailbox_list.count(), 0)
                    finally:
                        window.close()
                        self.app.processEvents()

                self.assertIs(credentials_module.has_auth_code, fail_if_real_backend_is_called)
                self.assertIs(settings_baseline.has_auth_code, fail_if_real_backend_is_called)
                self.assertIs(settings_dialog.has_auth_code, fail_if_real_backend_is_called)


if __name__ == "__main__":
    unittest.main()
