"""Regression tests for the UI P1 batch 1 (contrast, tables, dialogs, AI copy)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class BadgeContrastTests(unittest.TestCase):
    def test_status_badges_use_semantic_text_colors(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        expected = {
            'QLabel.StatusBadge[variant="review"]': "#B54708",
            'QLabel.StatusBadge[variant="approved"]': "#067647",
            'QLabel.StatusBadge[variant="ignored"]': "#475467",
            'QLabel.StatusBadge[variant="error"]': "#B91C1C",
        }
        for selector, color in expected.items():
            with self.subTest(selector=selector):
                start = APP_STYLESHEET.index(selector + " {")
                block = APP_STYLESHEET[start : APP_STYLESHEET.index("}", start)]
                self.assertIn(f"color: {color};", block)


class TableStateTests(unittest.TestCase):
    def test_table_uses_accent_selection_and_13px_type(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        start = APP_STYLESHEET.index("QTableWidget {")
        block = APP_STYLESHEET[start : APP_STYLESHEET.index("}", start)]
        self.assertIn("selection-background-color: #2563EB;", block)
        self.assertIn("selection-color: #FFFFFF;", block)
        self.assertIn("font-size: 13px;", block)

    def test_review_rows_are_28px(self):
        from scripts.invoice_fetch.gui.review_layout import REVIEW_ROW_HEIGHT

        self.assertEqual(REVIEW_ROW_HEIGHT, 28)


class DisabledTreatmentTests(unittest.TestCase):
    def test_disabled_variants_share_one_readable_pair(self):
        import re

        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        blocks = re.findall(r"([^\n{}]*:disabled[^\n{}]*)\{([^}]*)\}", APP_STYLESHEET)
        self.assertGreaterEqual(len(blocks), 10)
        checked = 0
        for selector, body in blocks:
            if "busy" in selector or ":read-only" in selector:
                continue
            checked += 1
            with self.subTest(selector=selector.strip()):
                self.assertIn("#667085", body)
                if "background-color" in body:
                    self.assertIn("#E4E7EC", body)
        self.assertGreaterEqual(checked, 12)


class DialogCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_claim_reason_dialogs_use_chinese_buttons_and_save_default(self):
        from PySide6.QtWidgets import QDialogButtonBox

        from scripts.invoice_fetch.gui.claim_reason_dialog import (
            ClaimReasonDialog,
            InvoiceReasonDialog,
        )

        for dialog in (
            ClaimReasonDialog({"name": "合成报销组"}),
            InvoiceReasonDialog({"custom_reason": None}, "合成事由"),
        ):
            with self.subTest(dialog=type(dialog).__name__):
                box = dialog.findChild(QDialogButtonBox)
                self.assertIsNotNone(box)
                self.assertEqual(box.button(QDialogButtonBox.Save).text(), "保存")
                self.assertEqual(box.button(QDialogButtonBox.Cancel).text(), "取消")
                self.assertTrue(box.button(QDialogButtonBox.Save).isDefault())
            dialog.deleteLater()
            self.app.processEvents()

    def test_exception_action_is_not_danger_variant(self):
        from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel

        panel = InvoiceDetailPanel()
        try:
            self.assertEqual(panel.btn_err.property("variant"), "secondary")
            self.assertEqual(panel.btn_err.property("tone"), "warning")
        finally:
            panel.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
