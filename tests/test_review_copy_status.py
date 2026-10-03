"""Synthetic tests for selectable review details and full-width status text."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from scripts.invoice_fetch.gui.ui_components import ElidedValueLabel, MiddleElidedValueLabel, ReadOnlyDetailPanel
from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel


class ReviewCopyStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_elided_value_supports_selected_text_and_full_context_copy(self):
        for label_type in (ElidedValueLabel, MiddleElidedValueLabel):
            with self.subTest(label=label_type.__name__):
                text = "SYNTHETIC-INVOICE-IDENTIFIER-001"
                label = label_type(text)
                try:
                    label.resize(80, 28)
                    self.assertEqual(label.focusPolicy(), Qt.ClickFocus)
                    label.show()
                    label.setFocus()
                    label.setSelection(0, 9)
                    self.app.processEvents()
                    QTest.keyClick(label, Qt.Key_C, Qt.ControlModifier)
                    self.assertEqual(self.app.clipboard().text(), "SYNTHETIC")
                    with patch("scripts.invoice_fetch.gui.ui_components.QMenu") as constructor:
                        menu = constructor.return_value
                        def execute(_position):
                            callback = menu.addAction.return_value.triggered.connect.call_args_list[0].args[0]
                            label.set_value("SYNTHETIC-CHANGED-DURING-MENU")
                            callback()
                        menu.exec.side_effect = execute
                        label.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(), QPoint()))
                    self.assertEqual(self.app.clipboard().text(), text)
                    menu.deleteLater.assert_called_once()
                finally:
                    label.close()
                    label.deleteLater()
        self.app.clipboard().clear()

    def test_read_only_detail_values_are_selectable(self):
        panel = ReadOnlyDetailPanel("Synthetic")
        try:
            value = panel.add_row("Number", "SYNTHETIC-001")
            self.assertTrue(value.textInteractionFlags() & Qt.TextSelectableByMouse)
            self.assertTrue(value.textInteractionFlags() & Qt.TextSelectableByKeyboard)
        finally:
            panel.close()
            panel.deleteLater()

    def test_error_status_uses_full_row_without_character_wrapping(self):
        panel = InvoiceDetailPanel()
        try:
            panel.set_closing_status(is_error=True)
            self.assertFalse(panel.lbl_closing_desc.wordWrap())
            layout = panel.closing_card.layout()
            self.assertEqual(layout.stretch(layout.indexOf(panel.lbl_closing_desc)), 1)
            self.assertEqual(layout.count(), 1)
            self.assertTrue(panel.lbl_sum_seller.textInteractionFlags() & Qt.TextSelectableByMouse)
            self.assertEqual(panel.lbl_sum_seller.focusPolicy(), Qt.ClickFocus)
            panel.set_closing_status(missing_fields=True)
            self.assertTrue(panel.lbl_closing_desc.wordWrap())
            self.assertTrue(panel.lbl_closing_desc.sizePolicy().hasHeightForWidth())
            panel.set_closing_status(is_error=True)
            self.assertFalse(panel.lbl_closing_desc.wordWrap())
        finally:
            panel.close()
            panel.deleteLater()
