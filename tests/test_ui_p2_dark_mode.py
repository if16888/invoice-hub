"""Regression tests for the opt-in dark palette (P2-17)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DarkModeTests(unittest.TestCase):
    def test_dark_stylesheet_maps_light_surfaces(self):
        from scripts.invoice_fetch.gui.dark_mode import dark_stylesheet

        light = "background-color: #FFFFFF; color: #111827; border: 1px solid #E4E7EC;"
        dark = dark_stylesheet(light)
        self.assertIn("#161A20", dark)
        self.assertIn("#E6E8EB", dark)
        self.assertIn("#2A3038", dark)
        self.assertNotIn("#FFFFFF", dark)

    def test_theme_is_opt_in_via_environment(self):
        from scripts.invoice_fetch.gui import dark_mode

        original = os.environ.get("INVOICE_HUB_THEME")
        try:
            os.environ["INVOICE_HUB_THEME"] = "dark"
            self.assertTrue(dark_mode.prefers_dark())
            os.environ["INVOICE_HUB_THEME"] = "light"
            self.assertFalse(dark_mode.prefers_dark())
            os.environ.pop("INVOICE_HUB_THEME", None)
            self.assertFalse(dark_mode.prefers_dark())
        finally:
            if original is None:
                os.environ.pop("INVOICE_HUB_THEME", None)
            else:
                os.environ["INVOICE_HUB_THEME"] = original

    def test_dark_palette_is_complete(self):
        from PySide6.QtGui import QPalette

        from scripts.invoice_fetch.gui.dark_mode import dark_palette

        palette = dark_palette()
        self.assertEqual(palette.color(QPalette.Window).name(), "#0f1115")
        self.assertEqual(palette.color(QPalette.Text).name(), "#e6e8eb")


if __name__ == "__main__":
    unittest.main()
