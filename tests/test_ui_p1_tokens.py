"""Regression tests for P1-21 (single token authority) and P1-22 (spacing grid)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TokenAuthorityTests(unittest.TestCase):
    def test_style_constants_are_derived_from_design_tokens(self):
        from scripts.invoice_fetch.gui import styles
        from scripts.invoice_fetch.gui.design_tokens import (
            DESIGN_V1_METRICS,
            DESIGN_V1_SPACING,
            DESIGN_V1_TYPE,
        )

        self.assertEqual(styles.SIDEBAR_EXPANDED_WIDTH, DESIGN_V1_METRICS["sidebar_width"])
        self.assertEqual(styles.PAGE_MARGIN, DESIGN_V1_METRICS["page_margin"])
        self.assertEqual(styles.SECTION_GAP, DESIGN_V1_METRICS["section_gap"])
        self.assertEqual(styles.CARD_GAP, DESIGN_V1_SPACING["md"])
        self.assertEqual(styles.CARD_PADDING, DESIGN_V1_SPACING["md"])
        self.assertEqual(styles.TYPE_METRIC, DESIGN_V1_TYPE["metric"])
        self.assertEqual(styles.TYPE_PAGE_TITLE, DESIGN_V1_TYPE["page_title"])
        self.assertEqual(styles.RADIUS_LG, DESIGN_V1_METRICS["radius_large"])

    def test_spacing_scale_is_the_8pt_grid(self):
        from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_SPACING

        self.assertEqual(
            DESIGN_V1_SPACING,
            {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32},
        )
        for name, value in DESIGN_V1_SPACING.items():
            with self.subTest(name=name):
                self.assertEqual(value % 4, 0)

    def test_settings_common_page_uses_the_token_margin(self):
        from scripts.invoice_fetch.gui import settings_common
        from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_METRICS

        self.assertEqual(settings_common._PAGE_MARGIN, DESIGN_V1_METRICS["page_margin"])


if __name__ == "__main__":
    unittest.main()
