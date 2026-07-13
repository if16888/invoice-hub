import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from scripts.invoice_fetch.gui import styles
from scripts.invoice_fetch.gui.design_baseline_styles import (
    BASELINE_COLORS,
    apply_global_design_baseline,
    build_canonical_application_stylesheet,
)
from scripts.invoice_fetch.gui.design_tokens import (
    DESIGN_TOKEN_VERSION,
    DESIGN_V1_COLORS,
    DESIGN_V1_METRICS,
    DESIGN_V1_TYPE,
    apply_legacy_color_tokens,
    canonical_legacy_color_tokens,
)


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class DesignTokenAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_design_v1_exports_the_approved_product_tokens(self):
        self.assertIs(BASELINE_COLORS, DESIGN_V1_COLORS)
        self.assertEqual(DESIGN_V1_COLORS["page"], "#F7F8FA")
        self.assertEqual(DESIGN_V1_COLORS["accent"], "#2563EB")
        self.assertEqual(DESIGN_V1_COLORS["success"], "#16803C")
        self.assertEqual(DESIGN_V1_COLORS["danger"], "#B42318")
        self.assertEqual(DESIGN_V1_TYPE["page_title"], 22)
        self.assertEqual(DESIGN_V1_METRICS["control_height"], 34)

    def test_legacy_mapping_is_derived_from_the_authority(self):
        target = {
            "accent": "#1599BD",
            "success": "#059669",
            "danger": "#DC2626",
            "unrelated": "preserved",
        }
        apply_legacy_color_tokens(target)

        self.assertEqual(target["accent"], DESIGN_V1_COLORS["accent"])
        self.assertEqual(target["success"], DESIGN_V1_COLORS["success"])
        self.assertEqual(target["danger"], DESIGN_V1_COLORS["danger"])
        self.assertEqual(target["unrelated"], "preserved")
        self.assertEqual(
            {key: target[key] for key in canonical_legacy_color_tokens()},
            canonical_legacy_color_tokens(),
        )

    def test_canonical_stylesheet_rebuilds_legacy_tokens_before_rendering(self):
        styles.COLOR_TOKENS["accent"] = "#1599BD"
        stylesheet = build_canonical_application_stylesheet()

        self.assertEqual(styles.COLOR_TOKENS["accent"], "#2563EB")
        self.assertEqual(styles.COLOR_TOKENS["success"], "#16803C")
        self.assertEqual(styles.COLOR_TOKENS["danger"], "#B42318")
        self.assertIn("#2563EB", stylesheet)
        self.assertNotIn("#1599BD", stylesheet)
        self.assertEqual(styles.APP_STYLESHEET + "\n" + stylesheet.split("\n", 1)[-1] != "", True)

    def test_global_baseline_replaces_stale_window_qss_once(self):
        page = QWidget()
        page.setStyleSheet("QWidget { color: #1599BD; }")
        try:
            apply_global_design_baseline(page)
            first = page.styleSheet()
            apply_global_design_baseline(page)

            self.assertTrue(page.property("designBaselineV1Applied"))
            self.assertEqual(page.property("designBaselineTokenVersion"), DESIGN_TOKEN_VERSION)
            self.assertIn(DESIGN_V1_COLORS["accent"], first)
            self.assertNotIn("#1599BD", first)
            self.assertEqual(page.styleSheet(), first)
        finally:
            page.close()
            page.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
