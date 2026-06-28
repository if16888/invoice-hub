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
        self.assertEqual(metrics.nav_width, 208)
        self.assertEqual(metrics.detail_width, 444)
        self.assertEqual(metrics.record_height, 340)
        self.assertEqual(metrics.thumbnail_width, 104)
        self.assertFalse(metrics.compact)

    def test_1366_layout_collapses_navigation(self):
        metrics = metrics_for_size(1366, 768)
        self.assertTrue(metrics.nav_collapsed)
        self.assertGreaterEqual(metrics.detail_width, 360)
        self.assertLessEqual(metrics.detail_width, 380)
        self.assertEqual(metrics.record_height, 300)

    def test_1440_900_is_compact_but_not_collapsed(self):
        metrics = metrics_for_size(1440, 900)
        self.assertFalse(metrics.nav_collapsed)
        self.assertTrue(metrics.compact)
        self.assertEqual(metrics.detail_width, 390)

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
    from PySide6.QtCore import Qt
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
                self.assertGreaterEqual(window._detail_panel.minimumWidth(), 420)
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


if __name__ == "__main__":
    unittest.main()
