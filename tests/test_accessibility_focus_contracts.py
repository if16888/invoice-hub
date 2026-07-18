from __future__ import annotations

import unittest

from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_COLORS, DESIGN_V1_METRICS
from scripts.invoice_fetch.gui.ui import build_qss


def _channel(value: int) -> float:
    normalized = value / 255.0
    return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    color = color.lstrip("#")
    red, green, blue = (int(color[index:index + 2], 16) for index in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def _contrast(left: str, right: str) -> float:
    lighter, darker = sorted((_luminance(left), _luminance(right)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _rule(qss: str, selector: str) -> str:
    marker = f"{selector} {{"
    if marker not in qss:
        raise AssertionError(f"missing selector: {selector}")
    return qss.split(marker, 1)[1].split("}", 1)[0]


class AccessibilityFocusContractTests(unittest.TestCase):
    def test_focus_ring_meets_non_text_contrast_threshold(self):
        focus = DESIGN_V1_COLORS["focus_ring"]
        self.assertGreaterEqual(_contrast(focus, DESIGN_V1_COLORS["surface"]), 3.0)
        self.assertGreaterEqual(_contrast(focus, DESIGN_V1_COLORS["page"]), 3.0)
        self.assertGreaterEqual(
            _contrast(DESIGN_V1_COLORS["focus_ring_inverse"], DESIGN_V1_COLORS["accent"]),
            3.0,
        )

    def test_button_focus_changes_color_not_border_width(self):
        qss = build_qss()
        base = _rule(qss, "QPushButton")
        focus = _rule(qss, "QPushButton:focus")
        self.assertIn(f"border: {DESIGN_V1_METRICS['focus_border_width']}px", base)
        self.assertIn("border-color:", focus)
        self.assertNotIn("border:", focus)

    def test_navigation_focus_preserves_reserved_geometry(self):
        qss = build_qss()
        base = _rule(qss, "QPushButton.WorkbenchNavButton")
        focus = _rule(qss, "QPushButton.WorkbenchNavButton:focus")
        checked = _rule(qss, "QPushButton.WorkbenchNavButton:checked")
        self.assertIn(f"border: {DESIGN_V1_METRICS['focus_border_width']}px", base)
        self.assertIn("border-color:", focus)
        self.assertNotIn("padding-left:", focus)
        self.assertIn("background-color:", checked)
        self.assertIn("border-color:", checked)
        self.assertNotIn("border-left:", checked)
        self.assertNotIn("padding-left:", checked)

    def test_selected_hover_keeps_selection_semantics(self):
        qss = build_qss()
        selected_hover = _rule(qss, "QTableView::item:selected:hover, QTableWidget::item:selected:hover")
        self.assertIn(DESIGN_V1_COLORS["selected"], selected_hover)
        self.assertIn(DESIGN_V1_COLORS["accent"], selected_hover)

    def test_selected_tab_focus_keeps_bottom_indicator(self):
        qss = build_qss()
        selected_focus = _rule(qss, "QTabBar::tab:selected:focus")
        self.assertIn("border-color:", selected_focus)
        self.assertIn("border-bottom-color:", selected_focus)
        self.assertIn(DESIGN_V1_COLORS["accent"], selected_focus)


if __name__ == "__main__":
    unittest.main()
