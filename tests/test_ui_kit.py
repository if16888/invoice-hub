# -*- coding: utf-8 -*-
"""Unit tests for Invoice Hub UI Kit (ui/ module)."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_COLORS, DESIGN_V1_METRICS
from scripts.invoice_fetch.gui.ui import Theme, build_qss
from scripts.invoice_fetch.gui.ui.components import (
    AlertBanner,
    AppButton,
    Card,
    FormField,
    SectionHeader,
    StatCard,
    StatusBadge,
)
from scripts.invoice_fetch.gui.ui.pages import InvoiceWorkbench


class TestUIKit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_invoice_workbench_layout(self):
        side_nav = QWidget()
        top_toolbar = QWidget()
        status_card = QWidget()
        record_card = QWidget()
        preview_card = QWidget()
        review_panel = QWidget()

        workbench = InvoiceWorkbench(
            side_nav=side_nav,
            top_toolbar=top_toolbar,
            status_filter_card=status_card,
            invoice_record_card=record_card,
            invoice_preview_card=preview_card,
            review_panel=review_panel,
        )
        self.assertEqual(workbench.objectName(), "PageRoot")
        self.assertEqual(workbench.side_nav.maximumWidth(), DESIGN_V1_METRICS["sidebar_width"])
        self.assertEqual(workbench.top_toolbar.height(), DESIGN_V1_METRICS["toolbar_height"])
        self.assertEqual(workbench.status_filter_card.height(), DESIGN_V1_METRICS["stat_card_height"])
        self.assertEqual(workbench.invoice_record_card.height(), DESIGN_V1_METRICS["table_card_height"])
        self.assertEqual(workbench.invoice_preview_card.minimumHeight(), DESIGN_V1_METRICS["preview_min_height"])
        self.assertEqual(workbench.review_panel.maximumWidth(), DESIGN_V1_METRICS["review_width"])

    def test_theme_tokens_derive_from_design_v1(self):
        self.assertEqual(Theme.BG_PAGE, DESIGN_V1_COLORS["page"])
        self.assertEqual(Theme.BG_CARD, DESIGN_V1_COLORS["surface"])
        self.assertEqual(Theme.TEXT_MAIN, DESIGN_V1_COLORS["text"])
        self.assertEqual(Theme.TEXT_HINT, DESIGN_V1_COLORS["muted"])
        self.assertEqual(Theme.CONTROL_HEIGHT, DESIGN_V1_METRICS["control_height"])
        self.assertEqual(Theme.RADIUS_CARD, DESIGN_V1_METRICS["radius_large"])

    def test_build_qss_contains_accessibility_contracts(self):
        qss = build_qss()
        self.assertIn("QMainWindow", qss)
        self.assertIn(DESIGN_V1_COLORS["page"], qss)
        self.assertIn('QLabel[role="hint"]', qss)
        self.assertIn("QPushButton:focus", qss)
        self.assertIn("QFrame#CompactStatCard:focus", qss)
        self.assertIn("QTableWidget::item:hover", qss)
        self.assertIn(f"width: {DESIGN_V1_METRICS['scrollbar_width']}px", qss)

    def test_card_instantiation(self):
        card = Card()
        self.assertEqual(card.objectName(), "Card")
        self.assertEqual(card.property("class"), "WorkbenchCard")

    def test_app_button_variants(self):
        button = AppButton("Save", variant="primary", shortcut_text="Ctrl+S")
        self.assertEqual(button.text(), "Save (Ctrl+S)")
        self.assertEqual(button.property("variant"), "primary")
        button.set_variant("danger")
        self.assertEqual(button.property("variant"), "danger")

    def test_status_badge(self):
        badge = StatusBadge("Pending", badge="pending")
        self.assertEqual(badge.text(), "Pending")
        self.assertEqual(badge.property("badge"), "pending")
        badge.set_badge("passed", "Passed")
        self.assertEqual(badge.text(), "Passed")
        self.assertEqual(badge.property("badge"), "passed")

    def test_stat_card_is_keyboard_focusable(self):
        card = StatCard("待审核", "42", state="warning")
        self.assertEqual(card.focusPolicy(), Qt.StrongFocus)
        self.assertEqual(card.value(), "42")
        card.set_value("43")
        self.assertEqual(card.accessibleName(), "待审核 43")
        card.set_selected(True)
        self.assertTrue(card.property("selected"))

    def test_semantic_component_roles_have_no_inline_qss(self):
        header = SectionHeader("基本信息", "只读摘要")
        field = FormField("销售方", QWidget(), hint="以发票原文为准")

        self.assertEqual(header.lbl_title.property("role"), "section-title")
        self.assertEqual(header.lbl_subtitle.property("role"), "secondary")
        self.assertEqual(header.lbl_title.styleSheet(), "")
        self.assertEqual(field.lbl_field.property("role"), "field-label")
        self.assertEqual(field.lbl_hint.property("role"), "hint")
        self.assertEqual(field.lbl_hint.styleSheet(), "")

    def test_alert_banner(self):
        alert = AlertBanner("Risk warning", tone="warning")
        self.assertEqual(alert.lbl_text.text(), "Risk warning")
        self.assertEqual(alert.property("tone"), "warning")


if __name__ == "__main__":
    unittest.main()
