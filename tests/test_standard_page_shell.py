from __future__ import annotations

import inspect
import unittest

from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_METRICS
from scripts.invoice_fetch.gui.ui.layouts import StandardPage
from scripts.invoice_fetch.gui import app as app_module


class StandardPageShellTests(unittest.TestCase):
    def test_standard_page_uses_shared_token_contract(self):
        self.assertEqual(StandardPage.MAX_CONTENT_WIDTH, 1280)
        source = inspect.getsource(StandardPage)
        self.assertIn('DESIGN_V1_METRICS["page_margin"]', source)
        self.assertIn('DESIGN_V1_METRICS["section_gap"]', source)

    def test_four_standard_pages_use_standard_page(self):
        source = inspect.getsource(app_module.InvoiceReviewApp)
        for name in (
            "_build_overview_page_view",
            "_build_imports_page_view",
            "_build_export_page_view",
            "_build_settings_page_view",
        ):
            method = getattr(app_module.InvoiceReviewApp, name)
            self.assertIn("StandardPage()", inspect.getsource(method), name)

    def test_review_workspace_is_not_wrapped_in_standard_page(self):
        source = inspect.getsource(app_module.InvoiceReviewApp)
        self.assertIn("WorkspacePageLayout.apply(self.workbench_content", source)

    def test_standard_metrics_match_authority(self):
        self.assertEqual(DESIGN_V1_METRICS["page_margin"], 24)
        self.assertEqual(DESIGN_V1_METRICS["section_gap"], 16)


if __name__ == "__main__":
    unittest.main()
