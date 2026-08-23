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

    def test_icon_text_is_exposed_when_provided(self):
        from scripts.invoice_fetch.gui.ui_components import CompactStatCard

        card = CompactStatCard("全部", "303", state="info", icon_text="◎")
        self.assertEqual(card.icon_text(), "◎")

    # --- clicked signal ---------------------------------------------------------

    def test_clicked_signal_exists(self):
        from scripts.invoice_fetch.gui.ui_components import CompactStatCard

        card = CompactStatCard("全部", "0")
        self.assertTrue(hasattr(card, "clicked"))
        received = []
        card.clicked.connect(lambda: received.append(True))
        card.clicked.emit()
        self.assertEqual(len(received), 1)


class TestSummaryStrip(unittest.TestCase):
    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        _get_app()

    def test_summary_strip_tracks_metrics_by_key(self):
        from scripts.invoice_fetch.gui.ui_components import SummaryStrip

        strip = SummaryStrip()
        strip.add_metric("all", "全部", "12", state="info")
        strip.add_metric("error", "异常", "3", state="danger")

        self.assertEqual(strip.card_for("all").text(), "全部 12")
        strip.set_metric("error", "4", title="异常票据")
        self.assertEqual(strip.card_for("error").text(), "异常票据 4")
        self.assertEqual(set(strip.metrics().keys()), {"all", "error"})


class TestIHDSReferenceComponents(unittest.TestCase):
    """Shared components introduced by the reference-led desktop surface."""

    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        _get_app()

    def test_selectable_source_has_one_explicit_selection_state(self):
        from scripts.invoice_fetch.gui.ui_components import SelectableSourceCard

        source = SelectableSourceCard("mail", "邮箱", "扫描已配置的发票邮箱。")
        self.assertIs(source.property("selected"), False)
        source.set_selected(True)
        self.assertIs(source.property("selected"), True)
        self.assertEqual(source.key, "mail")

    def test_compact_field_row_elides_and_keeps_full_tooltip(self):
        from scripts.invoice_fetch.gui.ui_components import CompactFieldRow

        value = "D:/very/long/runtime/path/that/must/not/force/the/settings/layout/to/grow/invoices.db"
        row = CompactFieldRow("数据库路径", value)
        self.assertEqual(row.lbl_value.toolTip(), value)
        self.assertEqual(row.lbl_label.text(), "数据库路径")

    def test_activity_timeline_contains_product_facing_entries(self):
        from scripts.invoice_fetch.gui.ui_components import ActivityTimeline

        timeline = ActivityTimeline()
        timeline.add_entry("今天 17:30", "邮箱扫描", "扫描 12 封 · 新增 10 · 失败 0")
        self.assertEqual(timeline.layout().count(), 1)
        timeline.clear()
        self.assertEqual(timeline.layout().count(), 0)

    def test_danger_zone_is_a_separate_surface(self):
        from scripts.invoice_fetch.gui.ui_components import DangerZone

        zone = DangerZone()
        self.assertEqual(zone.objectName(), "DangerZone")
        self.assertIn("危险", zone.lbl_title.text())

    def test_reference_tokens_feed_generated_stylesheet(self):
        from scripts.invoice_fetch.gui.styles import COLOR_TOKENS, build_app_stylesheet

        stylesheet = build_app_stylesheet()
        self.assertIn(COLOR_TOKENS["app_background"], stylesheet)
        self.assertIn(COLOR_TOKENS["accent"], stylesheet)


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
