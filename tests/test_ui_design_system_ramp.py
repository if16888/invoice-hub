"""Regression tests for P1-23/P1-25: type ramp, font stacks and radii."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DesignSystemRampTests(unittest.TestCase):
    def test_type_ramp_has_no_off_ramp_sizes(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        for size in (10, 14, 16, 18, 20):
            with self.subTest(size=size):
                self.assertNotIn(f"font-size: {size}px;", APP_STYLESHEET)
        for size in (11, 12, 13, 15, 17, 22):
            with self.subTest(size=size):
                self.assertIn(f"font-size: {size}px;", APP_STYLESHEET)

    def test_weight_ramp_drops_extra_bold(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        self.assertNotIn("font-weight: 800;", APP_STYLESHEET)

    def test_radius_ramp_is_6_8_10_or_capsule(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        for radius in (4, 5, 7, 12, 9999):
            with self.subTest(radius=radius):
                self.assertNotIn(f"border-radius: {radius}px;", APP_STYLESHEET)
        self.assertIn("border-radius: 999px;", APP_STYLESHEET)

    def test_font_stacks_are_unified(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        self.assertIn("PingFang SC", APP_STYLESHEET)
        self.assertIn("Microsoft YaHei UI", APP_STYLESHEET)
        self.assertIn("Consolas", APP_STYLESHEET)
        self.assertNotIn('"Segoe UI", monospace', APP_STYLESHEET)


if __name__ == "__main__":
    unittest.main()
