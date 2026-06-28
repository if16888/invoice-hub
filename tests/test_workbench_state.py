"""Unit tests for workbench state engine (IncrementalWindow and is_keyboard_input_target)."""

from __future__ import annotations
import unittest
from PySide6.QtWidgets import QApplication, QWidget, QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QPushButton
from scripts.invoice_fetch.gui.workbench_state import IncrementalWindow, is_keyboard_input_target

class TestWorkbenchState(unittest.TestCase):
    """Tests the IncrementalWindow paging logic and the keyboard input target detector."""

    @classmethod
    def setUpClass(cls):
        # Create QApplication instance if it doesn't exist
        cls.app = QApplication.instance() or QApplication([])

    def test_incremental_window_initialization(self):
        win = IncrementalWindow(limit=25)
        self.assertEqual(win.limit, 25)
        self.assertEqual(win.offset, 0)
        self.assertTrue(win.has_more)
        self.assertEqual(win.invoices, [])

    def test_incremental_window_reset(self):
        win = IncrementalWindow(limit=50)
        win.invoices = [{"id": 1}]
        win.offset = 50
        win.has_more = False
        
        win.reset(status_filter="to_review", search_text="test", column_filters={"amount": "100"})
        self.assertEqual(win.offset, 0)
        self.assertTrue(win.has_more)
        self.assertEqual(win.invoices, [])
        self.assertEqual(win.status_filter, "to_review")
        self.assertEqual(win.search_text, "test")
        self.assertEqual(win.column_filters, {"amount": "100"})

    def test_incremental_window_advance(self):
        win = IncrementalWindow(limit=10)
        
        # Advance with full page
        win.advance(10)
        self.assertEqual(win.offset, 10)
        self.assertTrue(win.has_more)
        
        # Advance with partial page
        win.advance(5)
        self.assertEqual(win.offset, 15)
        self.assertFalse(win.has_more)

    def test_incremental_window_append(self):
        win = IncrementalWindow(limit=10)
        win.append_invoices([{"id": 1}, {"id": 2}])
        self.assertEqual(win.invoices, [{"id": 1}, {"id": 2}])
        
        win.append_invoices([{"id": 3}])
        self.assertEqual(win.invoices, [{"id": 1}, {"id": 2}, {"id": 3}])

    def test_is_keyboard_input_target(self):
        # None widget should return False
        self.assertFalse(is_keyboard_input_target(None))

        # Push button should return False
        btn = QPushButton("Click me")
        self.assertFalse(is_keyboard_input_target(btn))

        # Check line edit, text edit, spinbox, combobox (should return True)
        line_edit = QLineEdit()
        self.assertTrue(is_keyboard_input_target(line_edit))

        text_edit = QTextEdit()
        self.assertTrue(is_keyboard_input_target(text_edit))

        plain_text_edit = QPlainTextEdit()
        self.assertTrue(is_keyboard_input_target(plain_text_edit))

        spin_box = QSpinBox()
        self.assertTrue(is_keyboard_input_target(spin_box))

        combo_box = QComboBox()
        self.assertTrue(is_keyboard_input_target(combo_box))

        # Simple widget should return False
        widget = QWidget()
        self.assertFalse(is_keyboard_input_target(widget))
