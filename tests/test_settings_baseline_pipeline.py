import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.design_tokens import DESIGN_TOKEN_VERSION, DESIGN_V1_COLORS
from scripts.invoice_fetch.gui.page_layouts import SETTINGS_BASELINE_STAGES
from scripts.invoice_fetch.gui import (
    page_layouts,
    review_feedback_fixes,
    settings_baseline,
    settings_pages_baseline,
)


class SettingsBaselinePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scheduled_settings_pipeline_is_dropped_after_owner_shutdown_starts(self):
        owner = QWidget()
        page = QWidget(owner)
        try:
            with patch.object(page_layouts, "apply_settings_baseline_pipeline") as apply_pipeline:
                page_layouts.schedule_settings_baseline_pipeline(page)
                self.assertTrue(page.property("settingsBaselinePipelineScheduled"))

                # closeEvent establishes this authority before deferred Qt work
                # is drained. A queued settings migration must not touch UI from
                # that point onward, even while the C++ objects remain valid.
                owner._shutdown_requested = True
                self.app.processEvents()

                apply_pipeline.assert_not_called()
                self.assertFalse(page.property("settingsBaselinePipelineScheduled"))
                self.assertTrue(isValid(owner))
                self.assertTrue(isValid(page))
        finally:
            page.deleteLater()
            owner.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

    def test_direct_settings_pipeline_is_noop_after_owner_shutdown_starts(self):
        owner = QWidget()
        page = QWidget(owner)
        stage_calls = []
        try:
            owner._shutdown_requested = True
            with patch.object(
                page_layouts,
                "SETTINGS_BASELINE_STAGES",
                (("sentinel", lambda _page: stage_calls.append(True)),),
            ):
                page_layouts.apply_settings_baseline_pipeline(page)

            self.assertEqual(stage_calls, [])
            self.assertFalse(bool(page.property("settingsBaselinePipelineApplied")))
        finally:
            page.deleteLater()
            owner.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

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
                self.assertTrue(
                    window.settings_page.property("settingsSemanticStatusContractApplied")
                )
                self.assertEqual(
                    window.settings_page.property("settingsTokenContractVersion"),
                    DESIGN_TOKEN_VERSION,
                )
                stylesheet = window.settings_tabs.styleSheet()
                self.assertIn(DESIGN_V1_COLORS["success_surface"], stylesheet)
                self.assertIn(DESIGN_V1_COLORS["warning_surface"], stylesheet)
                self.assertIn(DESIGN_V1_COLORS["danger_surface"], stylesheet)
                self.assertIn(DESIGN_V1_COLORS["selected"], stylesheet)
                self.assertIn(DESIGN_V1_COLORS["muted_surface"], stylesheet)
            finally:
                window.close()

    def test_deferred_ui_refresh_is_noop_after_close_starts_while_window_is_valid(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "settings-closing.db")
            window.show()
            for _ in range(8):
                self.app.processEvents()

            guarded = settings_baseline._refresh_mailbox_visuals
            self.assertTrue(bool(getattr(guarded, "_settings_lifecycle_guard", False)))
            self.assertTrue(isValid(window))

            # closeEvent establishes the shutdown authority before Qt destroys
            # the owned settings widgets. This mirrors the failing mailbox test
            # teardown: close the window, then drain already-queued callbacks
            # while the top-level Qt object is still valid.
            window.close()
            self.assertTrue(getattr(window, "_shutdown_requested", False))
            self.assertTrue(isValid(window))
            self.app.processEvents()
            self.assertTrue(isValid(window))

            gate_property = "settingsMailboxRefreshInFlight"
            window.setProperty(gate_property, False)
            guarded(window)
            self.assertFalse(bool(window.property(gate_property)))

    def test_deferred_ui_refreshes_are_safe_after_window_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "settings-close.db")
            window.show()
            for _ in range(8):
                self.app.processEvents()

            guarded_callbacks = (
                settings_pages_baseline._normalize_ai,
                settings_baseline._refresh_mailbox_visuals,
                review_feedback_fixes._sync_seller_tooltips,
            )
            for guarded in guarded_callbacks:
                self.assertTrue(
                    bool(getattr(guarded, "_settings_lifecycle_guard", False))
                )

            window.db.close()
            window.hide()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
            self.assertFalse(isValid(window))

            # Every queued callback target must be a no-op rather than raising
            # "Internal C++ object already deleted" during shutdown.
            for guarded in guarded_callbacks:
                guarded(window)


if __name__ == "__main__":
    unittest.main()
