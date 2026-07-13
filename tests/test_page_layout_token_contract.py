import unittest

from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_METRICS
from scripts.invoice_fetch.gui.page_layouts import (
    BASELINE_PAGE_MARGIN,
    BASELINE_SECTION_GAP,
    WORKSPACE_HORIZONTAL_MARGIN,
    WORKSPACE_SECTION_GAP,
)


class PageLayoutTokenContractTests(unittest.TestCase):
    def test_page_layout_metrics_come_from_design_v1(self):
        self.assertEqual(BASELINE_PAGE_MARGIN, DESIGN_V1_METRICS["page_margin"])
        self.assertEqual(BASELINE_SECTION_GAP, DESIGN_V1_METRICS["section_gap"])
        self.assertEqual(
            WORKSPACE_HORIZONTAL_MARGIN,
            DESIGN_V1_METRICS["workspace_horizontal_margin"],
        )
        self.assertEqual(WORKSPACE_SECTION_GAP, DESIGN_V1_METRICS["workspace_gap"])


if __name__ == "__main__":
    unittest.main()
