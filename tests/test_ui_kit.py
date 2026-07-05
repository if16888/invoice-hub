# -*- coding: utf-8 -*-
"""Unit tests for Invoice Hub UI Kit (ui/ module)."""

import unittest
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication
from scripts.invoice_fetch.gui.ui import Theme, build_qss
from scripts.invoice_fetch.gui.ui.components import (
    Card,
    AppButton,
    StatusBadge,
    StatCard,
    SectionHeader,
    FormField,
    AlertBanner,
    AttachmentRow,
    PreviewToolbar,
    ShortcutHelp,
    CollapsibleSection,
)


from scripts.invoice_fetch.gui.ui.pages import InvoiceWorkbench
from PySide6.QtWidgets import QWidget


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
        self.assertEqual(workbench.side_nav.maximumWidth(), 208)
        self.assertEqual(workbench.top_toolbar.height(), 56)
        self.assertEqual(workbench.status_filter_card.height(), 48)
        self.assertEqual(workbench.invoice_record_card.height(), 230)
        self.assertEqual(workbench.invoice_preview_card.minimumHeight(), 380)
        self.assertEqual(workbench.review_panel.maximumWidth(), 420)

    def test_theme_tokens(self):
        self.assertEqual(Theme.BG_PAGE, "#F6F8FB")
        self.assertEqual(Theme.BG_CARD, "#FFFFFF")
        self.assertEqual(Theme.SIDEBAR_WIDTH, 208)
        self.assertEqual(Theme.REVIEW_WIDTH, 420)

    def test_build_qss(self):
        qss = build_qss()
        self.assertIn("QMainWindow", qss)
        self.assertIn("#F6F8FB", qss)
        self.assertIn("#FFFFFF", qss)
        self.assertIn("StatusBadge", qss)

    def test_card_instantiation(self):
        card = Card()
        self.assertEqual(card.objectName(), "Card")
        self.assertEqual(card.property("class"), "WorkbenchCard")

    def test_app_button_variants(self):
        btn = AppButton("Save", variant="primary", shortcut_text="Ctrl+S")
        self.assertEqual(btn.text(), "Save (Ctrl+S)")
        self.assertEqual(btn.property("variant"), "primary")
        btn.set_variant("danger")
        self.assertEqual(btn.property("variant"), "danger")

    def test_status_badge(self):
        badge = StatusBadge("Pending", badge="pending")
        self.assertEqual(badge.text(), "Pending")
        self.assertEqual(badge.property("badge"), "pending")
        badge.set_badge("passed", "Passed")
        self.assertEqual(badge.text(), "Passed")
        self.assertEqual(badge.property("badge"), "passed")

    def test_stat_card(self):
        card = StatCard("待审核", "42", state="warning")
        self.assertEqual(card.value(), "42")
        card.set_value("43")
        self.assertEqual(card.value(), "43")
        card.set_selected(True)
        self.assertTrue(card.property("selected"))

    def test_alert_banner(self):
        alert = AlertBanner("Risk warning", tone="warning")
        self.assertEqual(alert.lbl_text.text(), "Risk warning")
        self.assertEqual(alert.property("tone"), "warning")

    def test_preview_toolbar(self):
        toolbar = PreviewToolbar()
        self.assertEqual(toolbar.height(), 40)
        self.assertIsNotNone(toolbar.btn_fit_width)
        self.assertIsNotNone(toolbar.btn_fullscreen)


if __name__ == "__main__":
    unittest.main()
