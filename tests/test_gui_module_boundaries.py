import unittest


class GuiModuleBoundaryTests(unittest.TestCase):
    def test_app_keeps_legacy_exports_after_module_split(self):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp, SettingsDialog
        from scripts.invoice_fetch.gui.log_diagnostics_mixin import LogDiagnosticsMixin
        from scripts.invoice_fetch.gui.preview_mixin import PreviewMixin
        from scripts.invoice_fetch.gui.settings_dialog import (
            SettingsDialog as ExtractedSettingsDialog,
        )

        self.assertTrue(issubclass(InvoiceReviewApp, PreviewMixin))
        self.assertTrue(issubclass(InvoiceReviewApp, LogDiagnosticsMixin))
        self.assertIs(SettingsDialog, ExtractedSettingsDialog)


if __name__ == "__main__":
    unittest.main()
