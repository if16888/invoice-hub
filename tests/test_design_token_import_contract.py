import unittest

from scripts.invoice_fetch.gui.design_baseline_styles import BASELINE_COLORS
from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_COLORS


class DesignTokenImportContractTests(unittest.TestCase):
    def test_baseline_colors_is_the_authoritative_mapping(self):
        self.assertIs(BASELINE_COLORS, DESIGN_V1_COLORS)


if __name__ == "__main__":
    unittest.main()
