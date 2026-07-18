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
    def test_theme_compatibility_aliases_match_authority(self):
        self.assertEqual(Theme.BG_PAGE, DESIGN_V1_COLORS["page"])
        self.assertEqual(Theme.BG_CARD, DESIGN_V1_COLORS["surface"])
        self.assertEqual(Theme.BORDER, DESIGN_V1_COLORS["border"])
        self.assertEqual(Theme.BLUE, DESIGN_V1_COLORS["accent"])
        self.assertEqual(Theme.TEXT_HINT, DESIGN_V1_COLORS["muted"])
        self.assertEqual(Theme.CONTROL_HEIGHT, DESIGN_V1_METRICS["control_height"])
        self.assertEqual(Theme.RADIUS_CARD, DESIGN_V1_METRICS["radius_large"])

    def test_semantic_components_do_not_embed_visual_literals(self):
        for component in (SectionHeader, FormField):
            source = inspect.getsource(component)
            self.assertNotIn("setStyleSheet", source, component.__name__)
            self.assertNotIn("QFont(", source, component.__name__)
            self.assertEqual(_HEX_COLOR.findall(source), [], component.__name__)

    def test_hint_copy_uses_readable_muted_token(self):
        qss = build_qss()
        selector = 'QLabel[role="hint"]'
        self.assertIn(selector, qss)
        hint_rule = qss.split(selector, 1)[1].split("}", 1)[0]
        self.assertIn(DESIGN_V1_COLORS["muted"], hint_rule)
        self.assertNotIn(DESIGN_V1_COLORS["placeholder"], hint_rule)

    def test_focus_hover_and_scrollbar_contracts_are_present(self):
        qss = build_qss()
        self.assertIn("QPushButton:focus", qss)
        self.assertIn("QPushButton.WorkbenchNavButton:checked:focus", qss)
        self.assertIn("QFrame#CompactStatCard:focus", qss)
        self.assertIn("QTableView::item:hover", qss)
        self.assertIn(f"width: {DESIGN_V1_METRICS['scrollbar_width']}px", qss)

    def test_checked_navigation_uses_a_shallow_block_without_geometry_shift(self):
        qss = build_qss()
        checked_rule = qss.split("QPushButton.WorkbenchNavButton:checked {", 1)[1].split("}", 1)[0]
        self.assertIn("background-color:", checked_rule)
        self.assertIn("border-color:", checked_rule)
        self.assertNotIn("border-left:", checked_rule)
        self.assertNotIn("padding-left:", checked_rule)

    def test_application_status_badges_derive_from_design_tokens(self):
        self.assertEqual(app_module.REVIEW_STATUS_BADGES["approved"]["fill"], DESIGN_V1_COLORS["success_surface"])
        self.assertEqual(app_module.REVIEW_STATUS_BADGES["error"]["text"], DESIGN_V1_COLORS["danger_text"])
        self.assertEqual(app_module.DATA_STATUS_BADGES["正常"]["fill"], DESIGN_V1_COLORS["success_surface"])

    def test_application_semantic_roles_are_present(self):
        source = inspect.getsource(app_module.InvoiceReviewApp)
        self.assertIn('setObjectName("LogView")', source)
        self.assertIn('setProperty("role", "guide")', source)

    def test_qss_contains_application_semantic_roles(self):
        qss = build_qss()
        for role in ("status", "caption", "emphasis", "strong", "guide", "guidePlain"):
            self.assertIn(f'QLabel[role="{role}"]', qss)
        for status in ("success", "warning", "danger", "info"):
            self.assertIn(f'QLabel[status="{status}"]', qss)
        self.assertIn("QTextEdit#LogView", qss)

    def test_review_actions_are_compact_and_auto_advance(self):
        from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel
        source = inspect.getsource(InvoiceDetailPanel)
        self.assertIn('make_button("通过", variant="primary"', source)
        self.assertIn("通过后自动进入下一张", source)
        self.assertIn("self.inline_review_layout.setStretch(0, 1)", source)
        self.assertNotIn('make_button("通过并下一张"', source)


if __name__ == "__main__":
    unittest.main()
