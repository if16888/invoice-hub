# -*- coding: utf-8 -*-
"""
Tests for QSS style architecture compliance.

Verifies that:
- CompactStatCard and ShortcutDisclosure rely only on semantic Qt properties
  (``state``, ``selected``, ``expanded``) rather than per-widget inline
  stylesheets.
- APP_STYLESHEET contains the CompactStatCard and ShortcutDisclosure QSS
  selectors needed to drive those properties.
- No inline ``setStyleSheet`` call exists on CompactStatCard or
  ShortcutDisclosure instances.

These tests run without a QApplication (pure static analysis) in
environments that lack PySide6, and as live widget checks when PySide6
is available.
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
import unittest

# ---------------------------------------------------------------------------
# PySide6 availability guard
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Static analysis helpers
# ---------------------------------------------------------------------------

def _source_of(obj) -> str:
    """Return dedented source of *obj* (class or function)."""
    try:
        return textwrap.dedent(inspect.getsource(obj))
    except (OSError, TypeError):
        return ""


def _calls_set_style_sheet(source: str) -> list[str]:
    """Return lines in *source* that call setStyleSheet directly."""
    hits = []
    for line in source.splitlines():
        stripped = line.strip()
        if "setStyleSheet" in stripped and not stripped.startswith("#"):
            hits.append(line)
    return hits


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStyleArchitectureStatic(unittest.TestCase):
    """Static source-level checks that do NOT require PySide6."""

    def _get_ui_components_source(self) -> str:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ui_components_src",
            "scripts/invoice_fetch/gui/ui_components.py",
        )
        if spec is None:
            self.fail("Could not locate ui_components.py")
        with open(spec.origin, encoding="utf-8") as fh:
            return fh.read()

    def test_compact_stat_card_no_inline_set_style_sheet(self):
        """CompactStatCard must not call setStyleSheet on itself."""
        src = self._get_ui_components_source()
        # Parse AST and check CompactStatCard class body
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "CompactStatCard":
                class_src = ast.get_source_segment(src, node) or ""
                inline = _calls_set_style_sheet(class_src)
                self.assertEqual(
                    inline,
                    [],
                    f"CompactStatCard uses inline setStyleSheet:\n" + "\n".join(inline),
                )
                return
        # Class not yet defined → harmless at this stage (will fail component tests)

    def test_shortcut_disclosure_no_inline_set_style_sheet(self):
        """ShortcutDisclosure must not call setStyleSheet on itself."""
        src = self._get_ui_components_source()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "ShortcutDisclosure":
                class_src = ast.get_source_segment(src, node) or ""
                inline = _calls_set_style_sheet(class_src)
                self.assertEqual(
                    inline,
                    [],
                    f"ShortcutDisclosure uses inline setStyleSheet:\n"
                    + "\n".join(inline),
                )
                return

    def test_app_stylesheet_contains_compact_stat_card_selector(self):
        """APP_STYLESHEET must define at least one CompactStatCard QSS rule."""
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        self.assertIn(
            "CompactStatCard",
            APP_STYLESHEET,
            "APP_STYLESHEET missing CompactStatCard QSS selector",
        )

    def test_app_stylesheet_contains_state_selectors(self):
        """APP_STYLESHEET must include state-driven selectors for CompactStatCard."""
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        self.assertIn(
            '[state="warning"]',
            APP_STYLESHEET,
            "APP_STYLESHEET missing state=warning selector for CompactStatCard",
        )

    def test_app_stylesheet_contains_selected_selector(self):
        """APP_STYLESHEET must include a selected=true selector."""
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        self.assertIn(
            '[selected="true"]',
            APP_STYLESHEET,
            "APP_STYLESHEET missing selected=true selector",
        )

    def test_app_stylesheet_contains_shortcut_disclosure_selector(self):
        """APP_STYLESHEET must define at least one ShortcutDisclosure QSS rule."""
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        self.assertIn(
            "ShortcutDisclosure",
            APP_STYLESHEET,
            "APP_STYLESHEET missing ShortcutDisclosure QSS selector",
        )

    def test_core_shortcuts_tuple_is_exported(self):
        """CORE_SHORTCUTS must be importable from ui_components and non-empty."""
        from scripts.invoice_fetch.gui.ui_components import CORE_SHORTCUTS

        self.assertIsInstance(CORE_SHORTCUTS, tuple)
        self.assertGreater(len(CORE_SHORTCUTS), 0)

    def test_secondary_shortcuts_tuple_is_exported(self):
        """SECONDARY_SHORTCUTS must be importable from ui_components and non-empty."""
        from scripts.invoice_fetch.gui.ui_components import SECONDARY_SHORTCUTS

        self.assertIsInstance(SECONDARY_SHORTCUTS, tuple)
        self.assertGreater(len(SECONDARY_SHORTCUTS), 0)

    def test_detail_caption_uses_readable_information_color(self):
        """Informative 11px detail text must not use the decorative light gray."""
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        selector = APP_STYLESHEET.split("QLabel.DetailCaption {", 1)[1].split("}", 1)[0]
        self.assertIn("#667085", selector)
        self.assertNotIn("#94A3B8", selector)


class TestStyleArchitectureLive(unittest.TestCase):
    """Live widget checks that require PySide6."""

    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        _get_app()

    def test_compact_stat_card_has_no_inline_stylesheet(self):
        """CompactStatCard instance must have an empty styleSheet()."""
        from scripts.invoice_fetch.gui.ui_components import CompactStatCard

        card = CompactStatCard("待审核", "10", state="warning")
        self.assertEqual(
            card.styleSheet(),
            "",
            "CompactStatCard must not set an inline stylesheet; use QSS properties",
        )

    def test_shortcut_disclosure_has_no_inline_stylesheet(self):
        """ShortcutDisclosure instance must have an empty styleSheet()."""
        from scripts.invoice_fetch.gui.ui_components import ShortcutDisclosure

        panel = ShortcutDisclosure()
        self.assertEqual(
            panel.styleSheet(),
            "",
            "ShortcutDisclosure must not set an inline stylesheet; use QSS properties",
        )

    def test_more_menu_button_has_accessible_name(self):
        from scripts.invoice_fetch.gui.ui_components import MoreMenuButton

        button = MoreMenuButton()
        self.assertEqual(button.accessibleName(), "更多操作")


if __name__ == "__main__":
    unittest.main()
