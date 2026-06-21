# -*- coding: utf-8 -*-
"""
Tests for reusable compact workbench UI components.

Covers CompactStatCard and ShortcutDisclosure contracts as specified
in the 0.1.4 desktop workbench plan.  A QApplication is required for
widget construction; tests are skipped gracefully when PySide6 is not
installed.
"""

from __future__ import annotations

import sys
import unittest

try:
    from PySide6.QtWidgets import QApplication

    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False

_QAPP = None


def _get_app() -> "QApplication | None":
    global _QAPP
    if not _HAS_PYSIDE6:
        return None
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class TestCompactStatCard(unittest.TestCase):
    """Contract tests for CompactStatCard."""

    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        _get_app()

    def _make_card(self, title="待审核", value="117", state="warning"):
        from scripts.invoice_fetch.gui.ui_components import CompactStatCard

        return CompactStatCard(title, value, state=state)

    # --- object identity -------------------------------------------------------

    def test_object_name_is_compact_stat_card(self):
        card = self._make_card()
        self.assertEqual(card.objectName(), "CompactStatCard")

    # --- selected property ------------------------------------------------------

    def test_set_selected_true_reflects_property(self):
        card = self._make_card()
        card.set_selected(True)
        self.assertIs(card.property("selected"), True)

    def test_set_selected_false_reflects_property(self):
        card = self._make_card()
        card.set_selected(True)
        card.set_selected(False)
        self.assertIs(card.property("selected"), False)

    def test_default_not_selected(self):
        card = self._make_card()
        # property may be None (not set) or False — neither is True
        self.assertIsNot(card.property("selected"), True)

    # --- state property ---------------------------------------------------------

    def test_state_property_set(self):
        card = self._make_card(state="warning")
        self.assertEqual(card.property("state"), "warning")

    def test_state_values(self):
        for state in ("warning", "success", "muted", "danger", "info"):
            card = self._make_card(state=state)
            self.assertEqual(card.property("state"), state)

    # --- set_value --------------------------------------------------------------

    def test_set_value_updates_display(self):
        from scripts.invoice_fetch.gui.ui_components import CompactStatCard

        card = CompactStatCard("待审核", "0")
        card.set_value("99")
        self.assertEqual(card.value(), "99")

    # --- clicked signal ---------------------------------------------------------

    def test_clicked_signal_exists(self):
        from scripts.invoice_fetch.gui.ui_components import CompactStatCard

        card = CompactStatCard("全部", "0")
        _ = card.clicked  # must not raise AttributeError


class TestShortcutDisclosure(unittest.TestCase):
    """Contract tests for ShortcutDisclosure."""

    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        _get_app()

    def _make_panel(self):
        from scripts.invoice_fetch.gui.ui_components import ShortcutDisclosure

        return ShortcutDisclosure()

    # --- default state ----------------------------------------------------------

    def test_defaults_to_collapsed(self):
        panel = self._make_panel()
        self.assertFalse(panel.is_expanded())

    def test_visible_shortcuts_defaults_to_core_actions(self):
        panel = self._make_panel()
        self.assertEqual(panel.visible_shortcuts(), ("Enter", "Del", "Ctrl+E"))

    # --- expansion --------------------------------------------------------------

    def test_set_expanded_true(self):
        panel = self._make_panel()
        panel.set_expanded(True)
        self.assertTrue(panel.is_expanded())

    def test_set_expanded_false(self):
        panel = self._make_panel()
        panel.set_expanded(True)
        panel.set_expanded(False)
        self.assertFalse(panel.is_expanded())

    def test_visible_shortcuts_collapsed_always_core(self):
        panel = self._make_panel()
        panel.set_expanded(False)
        self.assertEqual(panel.visible_shortcuts(), ("Enter", "Del", "Ctrl+E"))

    def test_expanded_shortcuts_include_secondary_keys(self):
        """Expanded state must expose at least the secondary shortcut keys."""
        from scripts.invoice_fetch.gui.ui_components import SECONDARY_SHORTCUTS

        panel = self._make_panel()
        panel.set_expanded(True)
        expanded = panel.visible_shortcuts()
        secondary_keys = {key for key, _label in SECONDARY_SHORTCUTS}
        visible_keys = set(expanded)
        self.assertTrue(
            secondary_keys.issubset(visible_keys),
            f"Missing secondary keys: {secondary_keys - visible_keys}",
        )

    def test_core_shortcuts_always_present_when_expanded(self):
        panel = self._make_panel()
        panel.set_expanded(True)
        expanded = panel.visible_shortcuts()
        for key in ("Enter", "Del", "Ctrl+E"):
            self.assertIn(key, expanded)

    # --- semantic constants -----------------------------------------------------

    def test_core_shortcuts_constant_structure(self):
        from scripts.invoice_fetch.gui.ui_components import CORE_SHORTCUTS

        self.assertEqual(len(CORE_SHORTCUTS), 3)
        keys = [k for k, _label in CORE_SHORTCUTS]
        self.assertIn("Enter", keys)
        self.assertIn("Del", keys)
        self.assertIn("Ctrl+E", keys)

    def test_secondary_shortcuts_constant_has_all_keys(self):
        from scripts.invoice_fetch.gui.ui_components import SECONDARY_SHORTCUTS

        keys = {k for k, _label in SECONDARY_SHORTCUTS}
        expected = {
            "↑ / ↓",
            "Ctrl+F",
            "F11",
            "Ctrl+I",
            "Ctrl+U",
            "Ctrl+M",
            "Ctrl+R",
        }
        self.assertEqual(keys, expected)


if __name__ == "__main__":
    unittest.main()
