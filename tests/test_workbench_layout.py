# -*- coding: utf-8 -*-
"""
Tests for deterministic workbench policy and Qt structural contracts.

Native desktop geometry observations are owned by
``tests.test_workbench_native_geometry``.
"""

import unittest
from decimal import Decimal
from pathlib import Path

from scripts.invoice_fetch.gui.workbench_layout import (
    WorkbenchMetrics,
    clamp_vertical_split,
    metrics_for_size,
)


# ---------------------------------------------------------------------------
# Integration tests — require PySide6 and InvoiceReviewApp
# ---------------------------------------------------------------------------

try:
    from PySide6.QtCore import Qt, QSettings
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QLineEdit,
        QPushButton,
    )
    from scripts.invoice_fetch.gui.workbench_settings import workbench_settings

    _HAS_PYSIDE6 = True
except (ImportError, OSError, RuntimeError):
    _HAS_PYSIDE6 = False

import sys
import tempfile
from unittest.mock import patch

_QAPP = None


def _get_app():
    global _QAPP
    if not _HAS_PYSIDE6:
        return None
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class TestWorkbenchShellIntegration(unittest.TestCase):
    """Integration tests for the composed workbench shell (Task 3).

    These tests spin up InvoiceReviewApp with a temporary database, resize
    to a target resolution, process events, then assert structural contracts.
    All tests are skipped gracefully when PySide6 is not available.
    """

    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        self._settings_dir = tempfile.TemporaryDirectory(
            prefix="invoice-hub-workbench-settings-"
        )
        self.addCleanup(self._settings_dir.cleanup)
        self._settings_patch = patch(
            "scripts.invoice_fetch.gui.app.workbench_settings",
            side_effect=lambda runtime_dir=None: workbench_settings(
                runtime_dir or Path(self._settings_dir.name)
            ),
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)
        _get_app()
        settings = self._settings()
        settings.remove("nav_collapsed_manual")
        settings.remove("shortcut_help_expanded")
        settings.sync()

    def tearDown(self):
        if _HAS_PYSIDE6:
            QApplication.processEvents()
            settings = self._settings()
            settings.remove("nav_collapsed_manual")
            settings.remove("shortcut_help_expanded")
            settings.sync()

    def _settings(self):
        return workbench_settings(Path(self._settings_dir.name))

    def _make_window(self, td: str):
        """Create a minimal InvoiceReviewApp against a temp database."""
        try:
            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        except (ImportError, OSError, RuntimeError) as exc:
            self.skipTest(f"InvoiceReviewApp import failed: {exc}")
        db_path = Path(td) / "workbench_test.db"
        window = InvoiceReviewApp(db_path, splash=None)
        return window

    @staticmethod
    def _close_window(window):
        """Close a test window without touching an already-deleted QObject."""
        try:
            from shiboken6 import isValid
        except ImportError:
            isValid = lambda _object: True
        try:
            if not isValid(window):
                return
            db = getattr(window, "db", None)
            if db is not None and getattr(db, "is_open", False):
                db.close()
            window.close()
            window.deleteLater()
            QApplication.processEvents()
        except (AttributeError, RuntimeError):
            pass

    def _visible_primary_buttons(self, root):
        from scripts.invoice_fetch.gui.ui_components import is_visual_primary
        return [
            button
            for button in root.findChildren(QPushButton)
            if button.isVisible() and is_visual_primary(button)
        ]


    # ------------------------------------------------------------------
    # Splitter hierarchy and orientation
    # ------------------------------------------------------------------


    def test_detail_panel_minimum_width_at_1920(self):
        """At 1920×1080 the decision panel stays within the compact token width."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                active_metrics = metrics_for_size(window.width(), window.height())
                self.assertGreaterEqual(
                    window._detail_panel.minimumWidth(),
                    active_metrics.detail_width,
                )
            finally:
                self._close_window(window)


    def test_final_workbench_shell_has_left_nav_and_top_toolbar(self):
        """0.1.4 visual shell must expose the design-aligned nav and toolbar."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                self.assertTrue(window.workbench_nav.isVisible())
                self.assertEqual(window.workbench_nav.objectName(), "WorkbenchNav")
                self.assertIn(window.workbench_nav.minimumWidth(), (56, 180))

                self.assertTrue(window.workbench_top_toolbar.isVisible())
                self.assertEqual(window.workbench_top_toolbar.objectName(), "WorkbenchTopToolbar")
                self.assertEqual(window.txt_search.parentWidget(), window.workbench_top_toolbar)
                self.assertIn("Ctrl + F", window.txt_search.placeholderText())
                self.assertNotEqual(window.btn_import_local.property("emphasis"), "primary")
                self.assertFalse(window.btn_mobile_upload.isVisible())
                self.assertFalse(window.btn_scan_email.isVisible())
                self.assertFalse(window.btn_toolbar_export.isVisible())

                visible_nav_buttons = [
                    button for button in window.workbench_nav_buttons.values()
                    if button.isVisible()
                ]
                self.assertGreaterEqual(len(visible_nav_buttons), 1)
                self.assertFalse(window.workbench_nav_buttons["review"].icon().isNull())
                expected_nav_focus = Qt.TabFocus
                self.assertEqual(window.workbench_nav_buttons["overview"].focusPolicy(), expected_nav_focus)
                self.assertEqual(window.btn_scan_email.text(), "扫描邮箱")
                self.assertEqual(window.btn_toolbar_export.text(), "导出")
                self.assertFalse(window.btn_toolbar_help.isVisible())
                self.assertFalse(window.btn_toolbar_notify.isVisible())
                self.assertTrue(hasattr(window, "btn_toolbar_user"))
                self.assertEqual(window.btn_toolbar_user.text(), "本地模式 ▾")
                self.assertNotIn("张伟", window.btn_toolbar_user.text())
                self.assertTrue(window.btn_more.menu() is not None)
                self.assertIn(window.action_mobile_upload, window.btn_more.menu().actions())
                self.assertIn(window.action_scan_email, window.btn_more.menu().actions())
                self.assertIn(window.action_toolbar_export, window.btn_more.menu().actions())
                self.assertFalse(window.btn_collapse_nav.icon().isNull())
                self.assertTrue(window.btn_collapse_nav.toolTip())
            finally:
                self._close_window(window)


    def test_navigation_keeps_exactly_one_checked_page_after_mouse_switch(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                window.workbench_nav_buttons["overview"].click()
                QApplication.processEvents()
                selectable = ("overview", "review", "imports", "export", "settings")
                self.assertEqual(
                    [key for key in selectable if window.workbench_nav_buttons[key].isChecked()],
                    ["overview"],
                )
                if window.workbench_nav.width() <= 72:
                    self.assertTrue(
                        all(not window.workbench_nav_buttons[key].hasFocus() for key in selectable)
                    )

                window.workbench_nav_buttons["review"].click()
                QApplication.processEvents()
                self.assertEqual(
                    [key for key in selectable if window.workbench_nav_buttons[key].isChecked()],
                    ["review"],
                )

                window._nav_collapsed_manual = True
                window._apply_workbench_metrics(1920, 1080)
                window.workbench_nav_buttons["export"].click()
                QApplication.processEvents()
                self.assertEqual(window.workbench_nav.width(), 56)
                self.assertEqual(
                    [key for key in selectable if window.workbench_nav_buttons[key].isChecked()],
                    ["export"],
                )
                self.assertTrue(
                    all(window.workbench_nav_buttons[key].focusPolicy() == Qt.TabFocus for key in selectable)
                )
                self.assertTrue(
                    all(not window.workbench_nav_buttons[key].hasFocus() for key in selectable)
                )

                window._nav_collapsed_manual = False
                window._apply_workbench_metrics(1920, 1080)
                self.assertTrue(
                    all(window.workbench_nav_buttons[key].focusPolicy() == Qt.TabFocus for key in selectable)
                )
            finally:
                self._close_window(window)


    def test_invoice_table_default_columns_match_review_workbench_design(self):
        """The list is for fast switching, so default columns stay compact."""
        from scripts.invoice_fetch.gui.column_filters import VISIBLE_COLUMN_DEFINITIONS

        expected = (
            "review_status",
            "status",
            "expense_date",
            "total_amount",
            "seller_name",
            "invoice_number",
        )
        self.assertEqual(tuple(key for key, _label in VISIBLE_COLUMN_DEFINITIONS), expected)

    def test_invoice_table_uses_dense_row_height(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                self.assertLessEqual(window.table.verticalHeader().defaultSectionSize(), 40)
                self.assertLessEqual(window.table.font().pointSize(), 12)
            finally:
                self._close_window(window)


    def test_settings_has_single_full_surface_and_no_placeholder_pages(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window._switch_main_page("settings")
                labels = [window.settings_tabs.tabText(i) for i in range(window.settings_tabs.count())]
                self.assertEqual(
                    labels,
                    ["邮箱账户", "AI 配置", "运行状态", "安全与隐私", "数据与备份", "关于"],
                )
                window._open_settings_dialog(1)
                self.assertIs(window.center_stack.currentWidget(), window.settings_page)
                self.assertEqual(window.settings_tabs.currentIndex(), 0)
            finally:
                self._close_window(window)


    def test_export_page_uses_claims_invoices_and_integrity_three_columns(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window._switch_main_page("export")
                QApplication.processEvents()
                self.assertEqual(window.export_group_card.lbl_title.text(), "报销组")
                self.assertEqual(window.export_invoices_card.lbl_title.text(), "组内发票")
                self.assertEqual(window.export_integrity_card.lbl_title.text(), "完整性检查与导出")
                self.assertFalse(hasattr(window, "combo_export_claims"))
                self.assertLessEqual(len(self._visible_primary_buttons(window.export_page)), 1)
            finally:
                self._close_window(window)


    def test_workbench_version_follows_central_metadata(self):
        from scripts.invoice_fetch.version import APP_VERSION, VERSION

        self.assertEqual(APP_VERSION, f"v{VERSION}")


    def test_restored_splitter_sizes_are_clamped(self):
        """Sizes restored from QSettings must pass through clamp_vertical_split."""
        # Patch QSettings to return an out-of-bounds stored value
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                # Use a stable synthetic persisted total. The live Qt splitter
                # can report a transient platform-dependent height while the
                # window is being shown, which is not the preference contract
                # this test is intended to cover.
                total = 900
                # Capture the value handed to Qt instead of reading the live
                # splitter back after layout polish, which can normalize sizes
                # differently across Windows runners.
                captured = []
                with patch.object(
                    window.left_splitter,
                    "setSizes",
                    side_effect=lambda values: captured.append(list(values)),
                ):
                    window._restore_left_splitter_sizes([total - 10, 10])
                self.assertEqual(len(captured), 1)
                record, preview = captured[0]
                self.assertEqual(record + preview, total)
                self.assertGreaterEqual(record, 280)
                self.assertGreaterEqual(preview, 180)
            finally:
                self._close_window(window)


    def test_nav_collapse_toggle_works_at_large_size(self):
        settings = self._settings()
        settings.remove("nav_collapsed_manual")
        settings.sync()
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                # Default: expanded at the desktop token width.
                self.assertEqual(window.workbench_nav.maximumWidth(), 180)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "发票审核")
                self.assertTrue(window.btn_collapse_nav.isVisible())

                # Click collapse: should collapse to 52px
                window.btn_collapse_nav.click()
                QApplication.processEvents()
                settings.sync()
                self.assertEqual(window.workbench_nav.maximumWidth(), 56)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "")
                self.assertTrue(settings.value("nav_collapsed_manual", False, type=bool))

                # Click again: should expand back to 180px.
                window.btn_collapse_nav.click()
                QApplication.processEvents()
                settings.sync()
                self.assertEqual(window.workbench_nav.maximumWidth(), 180)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "发票审核")
                self.assertFalse(settings.value("nav_collapsed_manual", True, type=bool))
            finally:
                self._close_window(window)


if __name__ == "__main__":
    unittest.main()
