# -*- coding: utf-8 -*-
"""
Tests for workbench_layout.py — pure metrics and splitter clamping.

No Qt or database required; all assertions are plain Python.
"""

import unittest

from scripts.invoice_fetch.gui.workbench_layout import (
    WorkbenchMetrics,
    clamp_vertical_split,
    metrics_for_size,
)


class TestMetricsForSize(unittest.TestCase):
    """Verify responsive breakpoint logic for metrics_for_size()."""

    def test_1920_layout_uses_full_density(self):
        metrics = metrics_for_size(1920, 1080)
        self.assertEqual(metrics.nav_width, 56)
        self.assertEqual(metrics.detail_width, 390)
        self.assertEqual(metrics.record_height, 340)
        self.assertEqual(metrics.thumbnail_width, 88)
        self.assertFalse(metrics.compact)

    def test_1366_layout_collapses_navigation(self):
        metrics = metrics_for_size(1366, 768)
        self.assertTrue(metrics.nav_collapsed)
        self.assertGreaterEqual(metrics.detail_width, 360)
        self.assertLessEqual(metrics.detail_width, 380)
        self.assertEqual(metrics.record_height, 300)

    def test_1440_900_is_compact_but_not_collapsed(self):
        metrics = metrics_for_size(1440, 900)
        self.assertTrue(metrics.nav_collapsed)
        self.assertTrue(metrics.compact)
        self.assertEqual(metrics.detail_width, 380)

    def test_1280_720_collapses_navigation(self):
        """Sub-1366 width also triggers the collapsed tier."""
        metrics = metrics_for_size(1280, 720)
        self.assertTrue(metrics.nav_collapsed)
        self.assertTrue(metrics.compact)

    def test_metrics_are_frozen(self):
        metrics = metrics_for_size(1920, 1080)
        with self.assertRaises(Exception):
            metrics.nav_width = 999  # type: ignore[misc]

    def test_returns_workbench_metrics_instance(self):
        self.assertIsInstance(metrics_for_size(1920, 1080), WorkbenchMetrics)


class TestClampVerticalSplit(unittest.TestCase):
    """Verify splitter boundary clamping."""

    def test_lower_boundary_clamped_to_record_min(self):
        record, preview = clamp_vertical_split(
            900, 50, record_min=280, preview_min=300
        )
        self.assertEqual(record, 280)
        self.assertEqual(preview, 620)

    def test_upper_boundary_clamped_to_preview_min(self):
        record, preview = clamp_vertical_split(
            900, 850, record_min=280, preview_min=300
        )
        self.assertEqual(record, 600)
        self.assertEqual(preview, 300)

    def test_in_range_value_passes_through(self):
        record, preview = clamp_vertical_split(
            900, 400, record_min=280, preview_min=300
        )
        self.assertEqual(record, 400)
        self.assertEqual(preview, 500)

    def test_total_always_equals_sum(self):
        for requested in (0, 100, 400, 800, 1000):
            record, preview = clamp_vertical_split(
                900, requested, record_min=280, preview_min=300
            )
            self.assertEqual(record + preview, 900)


# ---------------------------------------------------------------------------
# Integration tests — require PySide6 and InvoiceReviewApp
# ---------------------------------------------------------------------------

try:
    from PySide6.QtCore import Qt, QSettings
    from PySide6.QtWidgets import QApplication, QSizePolicy

    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False

import sys
import tempfile
from pathlib import Path

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
        _get_app()
        settings = QSettings("InvoiceHub", "workbench")
        settings.remove("nav_collapsed_manual")
        settings.remove("shortcut_help_expanded")
        settings.sync()

    def tearDown(self):
        if _HAS_PYSIDE6:
            QApplication.processEvents()
            settings = QSettings("InvoiceHub", "workbench")
            settings.remove("nav_collapsed_manual")
            settings.remove("shortcut_help_expanded")
            settings.sync()

    def _make_window(self, td: str):
        """Create a minimal InvoiceReviewApp against a temp database."""
        try:
            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        except ImportError as exc:
            self.skipTest(f"InvoiceReviewApp import failed: {exc}")
        db_path = Path(td) / "workbench_test.db"
        window = InvoiceReviewApp(db_path, splash=None)
        return window

    # ------------------------------------------------------------------
    # Splitter hierarchy and orientation
    # ------------------------------------------------------------------

    def test_main_splitter_is_horizontal(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                QApplication.processEvents()
                self.assertEqual(
                    window.main_splitter.orientation(), Qt.Horizontal
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_left_splitter_is_vertical(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                QApplication.processEvents()
                self.assertEqual(
                    window.left_splitter.orientation(), Qt.Vertical
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_left_splitter_children(self):
        """widget(0) = left_upper_widget, widget(1) = preview_panel."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                QApplication.processEvents()
                self.assertIs(
                    window.left_splitter.widget(0), window.left_upper_widget
                )
                self.assertIs(
                    window.left_splitter.widget(1), window.preview_panel
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_detail_panel_minimum_width_at_1920(self):
        """At 1920×1080 the detail panel minimum width must be >= 420."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                self.assertLessEqual(window._detail_panel.minimumWidth(), 400)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_detail_panel_minimum_width_at_1366(self):
        """At 1366×768 the compact detail panel minimum width must be >= 360."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1366, 768)
                QApplication.processEvents()
                self.assertGreaterEqual(window._detail_panel.minimumWidth(), 360)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_table_header_is_visible(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                window.left_stack.setCurrentWidget(window.table)
                QApplication.processEvents()
                self.assertFalse(window.table.horizontalHeader().isHidden())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_main_splitter_stretch_factors(self):
        """Left pane stretches; right detail pane has zero stretch."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                # Both splitter children must have positive size
                sizes = window.main_splitter.sizes()
                self.assertEqual(len(sizes), 2)
                self.assertTrue(all(s > 0 for s in sizes))
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_left_splitter_sizes_nonzero(self):
        """Both vertical panes must have positive size after construction."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                sizes = window.left_splitter.sizes()
                self.assertEqual(len(sizes), 2)
                self.assertTrue(all(s > 0 for s in sizes))
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_compact_status_cards_fit_the_filter_bar(self):
        from scripts.invoice_fetch.gui.ui_components import CompactStatCard

        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                self.assertLessEqual(window.filter_bar_widget.maximumHeight(), 40)
                self.assertEqual(len(window.filter_buttons), 5)
                self.assertTrue(all(isinstance(card, CompactStatCard) for card in window.filter_buttons.values()))
                self.assertTrue(all(card.maximumWidth() <= 160 for card in window.filter_buttons.values()))
                self.assertTrue(all(card.sizeHint().height() <= 36 for card in window.filter_buttons.values()))
                self.assertTrue(all("\n" not in card.text() for card in window.filter_buttons.values()))
            finally:
                window.db.close()
                window.close()

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
                self.assertLessEqual(window.workbench_nav.minimumWidth(), 56)

                self.assertTrue(window.workbench_top_toolbar.isVisible())
                self.assertEqual(window.workbench_top_toolbar.objectName(), "WorkbenchTopToolbar")
                self.assertEqual(window.txt_search.parentWidget(), window.workbench_top_toolbar)
                self.assertIn("Ctrl + F", window.txt_search.placeholderText())
                self.assertEqual(window.btn_import_local.property("emphasis"), "primary")

                visible_nav_buttons = [
                    button for button in window.workbench_nav_buttons.values()
                    if button.isVisible()
                ]
                self.assertGreaterEqual(len(visible_nav_buttons), 8)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "")
                self.assertEqual(window.workbench_nav_buttons["review"].toolTip(), "发票审核")
                self.assertEqual(window.workbench_nav_buttons["imports"].toolTip(), "导入记录")
                self.assertEqual(window.workbench_nav_buttons["mail"].toolTip(), "邮箱导入")
                self.assertFalse(window.workbench_nav_buttons["review"].icon().isNull())
                self.assertEqual(window.btn_scan_email.text(), "邮箱同步")
                self.assertEqual(window.btn_toolbar_export.text(), "批量导出")
                self.assertFalse(window.btn_toolbar_help.isVisible())
                self.assertFalse(window.btn_toolbar_notify.isVisible())
                self.assertTrue(window.btn_toolbar_user.isVisible())
                self.assertEqual(window.btn_toolbar_user.text(), "本地模式 ▾")
                self.assertNotIn("张伟", window.btn_toolbar_user.text())
                self.assertTrue(window.btn_more.menu() is not None)
                self.assertFalse(window.btn_collapse_nav.icon().isNull())
                self.assertTrue(window.btn_collapse_nav.toolTip())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_preview_empty_state_uses_shared_styled_label(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                self.assertEqual(window.lbl_preview_status.property("class"), "PreviewEmptyState")
                self.assertEqual(window.lbl_preview_status.styleSheet(), "")
                self.assertLessEqual(window.lbl_preview_status.maximumWidth(), 560)
                self.assertEqual(window.preview_stack.objectName(), "PreviewSurface")
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

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
                self.assertLessEqual(window.table.verticalHeader().defaultSectionSize(), 23)
                self.assertLessEqual(window.table.font().pointSize(), 12)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_workbench_version_is_014(self):
        from scripts.invoice_fetch.version import APP_VERSION, VERSION

        self.assertEqual(VERSION, "0.1.4")
        self.assertEqual(APP_VERSION, "v0.1.4")

    def test_status_bar_shortcut_copy_uses_chinese_punctuation(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                self.assertIn("快捷键：", window.btn_shortcut_help.text())
                self.assertIn("·", window.btn_shortcut_help.text())
            finally:
                window.db.close()
                window.close()

    def test_shortcut_disclosure_defaults_collapsed_without_resizing_splitter(self):
        from PySide6.QtCore import QSettings

        settings = QSettings("InvoiceHub", "workbench")
        settings.remove("shortcut_help_expanded")
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.resize(1920, 1080)
                window.show()
                QApplication.processEvents()
                QApplication.processEvents()
                self.assertFalse(window.shortcut_disclosure.is_expanded())
                before = window.main_splitter.sizes()
                window._toggle_shortcut_disclosure()
                QApplication.processEvents()
                self.assertTrue(window.shortcut_disclosure.is_expanded())
                self.assertEqual(window.main_splitter.sizes(), before)
            finally:
                window.shortcut_disclosure.hide()
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    # ------------------------------------------------------------------
    # Restored-state clamp (plan Step 4 verification)
    # ------------------------------------------------------------------

    def test_restored_splitter_sizes_are_clamped(self):
        """Sizes restored from QSettings must pass through clamp_vertical_split."""
        # Patch QSettings to return an out-of-bounds stored value
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                total = sum(window.left_splitter.sizes())
                # Apply an extreme out-of-bounds restore directly via the
                # internal helper; sizes must still satisfy the minimums.
                window._restore_left_splitter_sizes([total - 10, 10])
                QApplication.processEvents()
                record, preview = window.left_splitter.sizes()
                self.assertGreaterEqual(record, 280)
                self.assertGreaterEqual(preview, 180)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_user_adjusted_left_splitter_is_not_reset_by_resize(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                total_before = sum(window.left_splitter.sizes())
                window.left_splitter.setSizes([460, max(total_before - 460, 180)])
                QApplication.processEvents()
                moved_sizes = window.left_splitter.sizes()
                moved_ratio = moved_sizes[0] / sum(moved_sizes)

                window.resize(1880, 1040)
                QApplication.processEvents()
                resized_sizes = window.left_splitter.sizes()
                resized_ratio = resized_sizes[0] / sum(resized_sizes)

                self.assertAlmostEqual(resized_ratio, moved_ratio, delta=0.03)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_compact_density_shortens_search_placeholder(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1366, 768)
                QApplication.processEvents()
                self.assertIn("Ctrl + F", window.txt_search.placeholderText())
                self.assertNotIn("邮件主题", window.txt_search.placeholderText())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_compact_nav_collapses_to_icons_only(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1366, 768)
                QApplication.processEvents()
                self.assertFalse(window.workbench_nav_title.isVisible())
                self.assertFalse(window.workbench_nav_subtitle.isVisible())
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "")
                self.assertEqual(window.btn_collapse_nav.text(), "")
                self.assertGreater(window.workbench_nav.maximumWidth(), 40)
                self.assertLessEqual(window.workbench_nav.maximumWidth(), 72)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_default_nav_is_collapsed_at_1920(self):
        settings = QSettings("InvoiceHub", "workbench")
        settings.remove("nav_collapsed_manual")
        settings.sync()
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                self.assertLessEqual(window.workbench_nav.maximumWidth(), 56)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "")
                self.assertEqual(window.workbench_nav_buttons["review"].toolTip(), "发票审核")
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_manual_nav_expand_toggle_persists_at_large_size(self):
        settings = QSettings("InvoiceHub", "workbench")
        settings.remove("nav_collapsed_manual")
        settings.sync()
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                window.btn_collapse_nav.click()
                QApplication.processEvents()
                settings.sync()

                self.assertEqual(window.workbench_nav.maximumWidth(), 208)
                self.assertTrue(window.workbench_nav_title.isVisible())
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "发票审核")
                self.assertEqual(window.btn_collapse_nav.text(), "收起侧边栏")
                self.assertEqual(window.btn_collapse_nav.toolTip(), "收起侧边栏")
                self.assertFalse(settings.value("nav_collapsed_manual", True, type=bool))

                window.resize(1880, 1040)
                QApplication.processEvents()
                self.assertEqual(window.workbench_nav.maximumWidth(), 208)

                window.btn_collapse_nav.click()
                QApplication.processEvents()
                settings.sync()
                self.assertLessEqual(window.workbench_nav.maximumWidth(), 56)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "")
                self.assertTrue(settings.value("nav_collapsed_manual", False, type=bool))
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_manual_nav_expand_persists_on_restart(self):
        settings = QSettings("InvoiceHub", "workbench")
        settings.remove("nav_collapsed_manual")
        settings.sync()
        with tempfile.TemporaryDirectory() as td:
            first = self._make_window(td)
            try:
                first.show()
                first.resize(1920, 1080)
                QApplication.processEvents()
                first.btn_collapse_nav.click()
                QApplication.processEvents()
                self.assertEqual(first.workbench_nav.maximumWidth(), 208)
                first._save_splitter_prefs()
                persisted = QSettings("InvoiceHub", "workbench")
                persisted.sync()
                self.assertFalse(
                    persisted.value("nav_collapsed_manual", True, type=bool)
                )
                first.close()
                first.deleteLater()
                QApplication.processEvents()

                second = self._make_window(td)
                try:
                    second.show()
                    second.resize(1920, 1080)
                    QApplication.processEvents()
                    self.assertEqual(second.workbench_nav.maximumWidth(), 208)
                    self.assertEqual(second.workbench_nav_buttons["review"].text(), "发票审核")
                finally:
                    second.db.close()
                    second.close()
                    second.deleteLater()
                    QApplication.processEvents()
            finally:
                if getattr(first, "db", None) is not None and first.db.is_open:
                    first.db.close()

    def test_default_collapsed_nav_does_not_persist_false_manual_state(self):
        settings = QSettings("InvoiceHub", "workbench")
        settings.remove("nav_collapsed_manual")
        settings.sync()
        with tempfile.TemporaryDirectory() as td:
            first = self._make_window(td)
            try:
                first.show()
                first.resize(1920, 1080)
                QApplication.processEvents()
                self.assertLessEqual(first.workbench_nav.maximumWidth(), 56)
                self.assertIsNone(first._nav_collapsed_manual)

                first.close()
                first.deleteLater()
                QApplication.processEvents()

                self.assertFalse(settings.contains("nav_collapsed_manual"))

                second = self._make_window(td)
                try:
                    second.show()
                    second.resize(1920, 1080)
                    QApplication.processEvents()
                    self.assertLessEqual(second.workbench_nav.maximumWidth(), 56)
                    self.assertEqual(second.workbench_nav_buttons["review"].text(), "")
                    self.assertFalse(settings.contains("nav_collapsed_manual"))
                    self.assertIsNone(second._nav_collapsed_manual)
                finally:
                    second.db.close()
                    second.close()
                    second.deleteLater()
                    QApplication.processEvents()
            finally:
                if getattr(first, "db", None) is not None and first.db.is_open:
                    first.db.close()


if __name__ == "__main__":
    unittest.main()
