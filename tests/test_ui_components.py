# -*- coding: utf-8 -*-
"""
Tests for reusable compact workbench UI components.

Covers CompactStatCard and ShortcutDisclosure contracts as specified
in the 0.1.4 desktop workbench plan.  A QApplication is required for
widget construction; tests are skipped gracefully when PySide6 is not
installed.
"""

from __future__ import annotations

import sys
import unittest

try:
    from PySide6.QtWidgets import QApplication

    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False

_QAPP = None


def _get_app() -> "QApplication | None":
    global _QAPP
    if not _HAS_PYSIDE6:
        return None
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class TestSummaryStrip(unittest.TestCase):
    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        _get_app()

    def test_summary_strip_tracks_metrics_by_key(self):
        from scripts.invoice_fetch.gui.ui_components import SummaryStrip

        strip = SummaryStrip()
        strip.add_metric("all", "全部", "12", state="info")
        strip.add_metric("error", "异常", "3", state="danger")

        self.assertEqual(strip.card_for("all").text(), "全部 12")
        strip.set_metric("error", "4", title="异常票据")
        self.assertEqual(strip.card_for("error").text(), "异常票据 4")
        self.assertEqual(set(strip.metrics().keys()), {"all", "error"})


class TestIHDSReferenceComponents(unittest.TestCase):
    """Shared components introduced by the reference-led desktop surface."""

    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        _get_app()


    def test_danger_zone_is_a_separate_surface(self):
        from scripts.invoice_fetch.gui.ui_components import DangerZone

        zone = DangerZone()
        self.assertEqual(zone.objectName(), "DangerZone")
        self.assertIn("危险", zone.lbl_title.text())

    def test_reference_tokens_feed_generated_stylesheet(self):
        from scripts.invoice_fetch.gui.styles import COLOR_TOKENS, build_app_stylesheet

        stylesheet = build_app_stylesheet()
        self.assertIn(COLOR_TOKENS["app_background"], stylesheet)
        self.assertIn(COLOR_TOKENS["accent"], stylesheet)


if __name__ == "__main__":
    unittest.main()
