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


if __name__ == "__main__":
    unittest.main()
