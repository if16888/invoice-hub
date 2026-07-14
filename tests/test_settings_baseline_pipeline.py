import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.design_tokens import DESIGN_TOKEN_VERSION, DESIGN_V1_COLORS
from scripts.invoice_fetch.gui.settings_baseline_pipeline import SETTINGS_BASELINE_STAGES
from scripts.invoice_fetch.gui import settings_baseline, settings_pages_baseline


class SettingsBaselinePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_migrations_run_once_in_declared_order(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "settings-pipeline.db")
            try:
                window.show()
                for _ in range(8):
                    self.app.processEvents()
                expected = tuple(name for name, _stage in SETTINGS_BASELINE_STAGES)
                self.assertTrue(window.settings_page.property("settingsBaselinePipelineApplied"))
                self.assertFalse(window.settings_page.property("settingsBaselinePipelineScheduled"))
                self.assertEqual(
                    tuple(window.settings_page.property("settingsBaselinePipelineStages")),
                    expected,
                )
                self.assertEqual(
                    window.settings_page.property("settingsBaselinePipelineFailedStage"),
                    "",
                )
                self.assertTrue(window.settings_page.property("settingsRefreshGuardInstalled"))
                self.assertTrue(window.settings_page.property("settingsTokenContractApplied"))
                self.assertEqual(
                    window.settings_page.property("settingsTokenContractVersion"),
                    DESIGN_TOKEN_VERSION,
                )
                stylesheet = window.settings_tabs.styleSheet()
                self.assertIn(DESIGN_V1_COLORS["success_surface"], stylesheet)
                self.assertIn(DESIGN_V1_COLORS["warning_surface"], stylesheet)
                self.assertIn(DESIGN_V1_COLORS["muted_surface"], stylesheet)
            finally:
                window.close()

    def test_deferred_settings_refreshes_are_safe_after_window_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "settings-close.db")
            window.show()
            for _ in range(8):
                self.app.processEvents()

            guarded_normalize = settings_pages_baseline._normalize_ai
            guarded_mailbox_refresh = settings_baseline._refresh_mailbox_visuals
            for guarded in (guarded_normalize, guarded_mailbox_refresh):
                self.assertTrue(
                    bool(getattr(guarded, "_settings_lifecycle_guard", False))
                )

            window.db.close()
            window.hide()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
            self.assertFalse(isValid(window))

            # Both queued callback targets must be no-ops rather than raising
            # "Internal C++ object already deleted" during shutdown.
            guarded_normalize(window)
            guarded_mailbox_refresh(window)


if __name__ == "__main__":
    unittest.main()
