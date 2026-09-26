from __future__ import annotations

import inspect
import re
import unittest

from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_COLORS, DESIGN_V1_METRICS
from scripts.invoice_fetch.gui.ui import Theme, build_qss
from scripts.invoice_fetch.gui.ui.components.form_field import FormField
from scripts.invoice_fetch.gui.ui.components.section_header import SectionHeader
from scripts.invoice_fetch.gui import app as app_module


_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


class DesignV1UIConvergenceTests(unittest.TestCase):


    def test_hint_copy_uses_readable_muted_token(self):
        qss = build_qss()
        selector = 'QLabel[role="hint"]'
        self.assertIn(selector, qss)
        hint_rule = qss.split(selector, 1)[1].split("}", 1)[0]
        self.assertIn(DESIGN_V1_COLORS["muted"], hint_rule)
        self.assertNotIn(DESIGN_V1_COLORS["placeholder"], hint_rule)


    def test_application_status_badges_derive_from_design_tokens(self):
        self.assertEqual(app_module.REVIEW_STATUS_BADGES["approved"]["fill"], DESIGN_V1_COLORS["success_surface"])
        self.assertEqual(app_module.REVIEW_STATUS_BADGES["error"]["text"], DESIGN_V1_COLORS["danger_text"])
        self.assertEqual(app_module.DATA_STATUS_BADGES["正常"]["fill"], DESIGN_V1_COLORS["success_surface"])


if __name__ == "__main__":
    unittest.main()
