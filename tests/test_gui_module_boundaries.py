import unittest


class GuiModuleBoundaryTests(unittest.TestCase):
    def test_app_keeps_legacy_exports_after_module_split(self):
        from scripts.invoice_fetch.gui.app import (
            EmailScanWorker,
            InvoiceReviewApp,
            LocalImportWorker,
            MobileUploadDialog,
            SettingsDialog,
        )
        from scripts.invoice_fetch.gui.log_diagnostics_mixin import LogDiagnosticsMixin
        from scripts.invoice_fetch.gui.mobile_upload_dialog import (
            MobileUploadDialog as ExtractedMobileUploadDialog,
        )
        from scripts.invoice_fetch.gui.preview_mixin import PreviewMixin
        from scripts.invoice_fetch.gui.settings_dialog import (
            SettingsDialog as ExtractedSettingsDialog,
        )
        from scripts.invoice_fetch.gui.workers import (
            EmailScanWorker as ExtractedEmailScanWorker,
            LocalImportWorker as ExtractedLocalImportWorker,
        )

        self.assertTrue(issubclass(InvoiceReviewApp, PreviewMixin))
        self.assertTrue(issubclass(InvoiceReviewApp, LogDiagnosticsMixin))
        self.assertIs(SettingsDialog, ExtractedSettingsDialog)
        self.assertIs(MobileUploadDialog, ExtractedMobileUploadDialog)
        self.assertIs(LocalImportWorker, ExtractedLocalImportWorker)
        self.assertIs(EmailScanWorker, ExtractedEmailScanWorker)


if __name__ == "__main__":
    unittest.main()
