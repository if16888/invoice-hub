"""Design System v1.1 visual contracts for shared desktop interactions.

The existing product already has authoritative color and geometry tokens.  This
module gives those tokens semantic component roles so navigation controls and
review filters do not look like unrelated bordered buttons.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QPushButton, QSizePolicy, QWidget
from shiboken6 import isValid

from .design_tokens import DESIGN_V1_COLORS, DESIGN_V1_METRICS, DESIGN_V1_TYPE


_COLLAPSE_HINTS = ("收起侧边栏", "展开侧边栏", "收起导航", "展开导航")


def _repolish(widget: QWidget) -> None:
    if widget is None or not isValid(widget):
        return
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _sidebar_stylesheet() -> str:
    colors = DESIGN_V1_COLORS
    metrics = DESIGN_V1_METRICS
    return f"""
QFrame#WorkbenchNav {{
    background-color: {colors['surface']};
    border-right: 1px solid {colors['border']};
}}
QPushButton.WorkbenchNavButton {{
    background-color: transparent;
    color: {colors['text_secondary']};
    border: none;
    border-radius: {metrics['radius_medium']}px;
    padding: 0 12px;
    text-align: left;
}}
QPushButton.WorkbenchNavButton:hover {{
    background-color: {colors['surface_secondary']};
    color: {colors['text']};
}}
QPushButton.WorkbenchNavButton:focus {{
    background-color: {colors['surface_secondary']};
    color: {colors['accent_hover']};
    border: none;
    outline: 0;
}}
QPushButton.WorkbenchNavButton:checked,
QPushButton.WorkbenchNavButton:checked:focus {{
    background-color: {colors['selected']};
    color: {colors['accent_hover']};
    border: none;
    outline: 0;
    font-weight: 600;
}}
QPushButton[navigationControl="collapse"] {{
    min-height: {metrics['icon_button_size']}px;
    max-height: {metrics['icon_button_size']}px;
    background-color: transparent;
    color: {colors['text_secondary']};
    border: none;
    border-radius: {metrics['radius_medium']}px;
    padding: 0 10px;
    text-align: left;
    font-size: {DESIGN_V1_TYPE['secondary']}px;
    font-weight: 500;
}}
QPushButton[navigationControl="collapse"]:hover {{
    background-color: {colors['surface_secondary']};
    color: {colors['text']};
    border: none;
}}
QPushButton[navigationControl="collapse"]:focus {{
    background-color: {colors['selected']};
    color: {colors['accent_hover']};
    border: none;
    outline: 0;
}}
"""


def _filter_bar_stylesheet() -> str:
    colors = DESIGN_V1_COLORS
    metrics = DESIGN_V1_METRICS
    return f"""
QFrame#ReviewStatusSegmentedControl {{
    background-color: {colors['surface_secondary']};
    border: 1px solid {colors['border_subtle']};
    border-radius: {metrics['radius_large']}px;
}}
"""


def _status_segment_stylesheet() -> str:
    colors = DESIGN_V1_COLORS
    metrics = DESIGN_V1_METRICS
    return f"""
QFrame#CompactStatCard {{
    min-height: {metrics['segmented_item_height']}px;
    max-height: {metrics['segmented_item_height']}px;
    background-color: transparent;
    border: none;
    border-radius: {metrics['radius_medium']}px;
}}
QFrame#CompactStatCard:hover {{
    background-color: {colors['surface']};
    border: none;
}}
QFrame#CompactStatCard:focus {{
    background-color: {colors['surface']};
    border: none;
    outline: 0;
}}
QFrame#CompactStatCard[selected="true"],
QFrame#CompactStatCard[selected="true"]:focus {{
    background-color: {colors['selected']};
    border: none;
    outline: 0;
}}
QFrame#CompactStatCard QLabel[class="CompactStatCardTitle"] {{
    color: {colors['text_secondary']};
    font-size: {DESIGN_V1_TYPE['secondary']}px;
    font-weight: 500;
}}
QFrame#CompactStatCard QLabel[class="CompactStatCardValue"] {{
    color: {colors['text']};
    font-size: {DESIGN_V1_TYPE['body']}px;
    font-weight: 600;
}}
QFrame#CompactStatCard[selected="true"] QLabel[class="CompactStatCardTitle"],
QFrame#CompactStatCard[selected="true"] QLabel[class="CompactStatCardValue"] {{
    color: {colors['accent_hover']};
    font-weight: 700;
}}
"""


def _find_sidebar_collapse_button(window) -> QPushButton | None:
    for attr in (
        "btn_nav_collapse",
        "btn_sidebar_collapse",
        "btn_toggle_nav",
        "btn_nav_toggle",
        "nav_toggle_button",
    ):
        candidate = getattr(window, attr, None)
        if isinstance(candidate, QPushButton) and isValid(candidate):
            return candidate

    nav = getattr(window, "workbench_nav", None)
    if nav is None or not isValid(nav):
        return None
    for button in nav.findChildren(QPushButton):
        text = str(button.text() or "")
        accessible = str(button.accessibleName() or "")
        tooltip = str(button.toolTip() or "")
        haystack = " ".join((text, accessible, tooltip))
        if any(hint in haystack for hint in _COLLAPSE_HINTS):
            return button
    return None


def apply_sidebar_visual_language(window) -> None:
    """Render navigation state with fills instead of decorative outlines."""
    nav = getattr(window, "workbench_nav", None)
    if not isinstance(nav, QFrame) or not isValid(nav):
        return

    nav.setProperty("visualLanguage", "design-v1.1")
    if nav.property("designV11SidebarStyled") is not True:
        nav.setProperty("designV11SidebarStyled", True)
        nav.setStyleSheet(_sidebar_stylesheet())

    collapse = _find_sidebar_collapse_button(window)
    if collapse is not None:
        collapse.setProperty("navigationControl", "collapse")
        collapse.setProperty("variant", "ghost")
        collapse.setFlat(True)
        collapse.setAutoDefault(False)
        collapse.setDefault(False)
        collapse.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        collapse.setAccessibleName(
            collapse.accessibleName()
            or ("收起侧边栏" if "收起" in collapse.text() else "展开侧边栏")
        )
        _repolish(collapse)
    _repolish(nav)


def apply_review_status_segmented_control(window) -> None:
    """Turn the five review statuses into one neutral segmented filter."""
    bar = getattr(window, "filter_bar_widget", None)
    cards = getattr(window, "filter_buttons", None)
    if not isinstance(bar, QFrame) or not isValid(bar) or not isinstance(cards, dict):
        return

    metrics = DESIGN_V1_METRICS
    bar.setObjectName("ReviewStatusSegmentedControl")
    bar.setProperty("visualRole", "segmented-filter")
    bar.setFixedHeight(metrics["segmented_control_height"])
    bar.setStyleSheet(_filter_bar_stylesheet())
    layout = bar.layout()
    if layout is not None:
        inset = max(0, (metrics["segmented_control_height"] - metrics["segmented_item_height"]) // 2)
        layout.setContentsMargins(inset, inset, inset, inset)
        layout.setSpacing(metrics["segmented_item_gap"])

    segment_qss = _status_segment_stylesheet()
    for status, card in cards.items():
        if card is None or not isValid(card):
            continue
        card.setProperty("visualRole", "status-segment")
        card.setProperty("statusKey", str(status))
        card.setFixedHeight(metrics["segmented_item_height"])
        card.setStyleSheet(segment_qss)
        card_layout = card.layout()
        if card_layout is not None:
            card_layout.setContentsMargins(10, 0, 10, 0)
            card_layout.setSpacing(5)
        title = getattr(card, "_lbl_title", None)
        value = getattr(card, "_lbl_value", None)
        if title is not None:
            title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if value is not None:
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        _repolish(card)
    _repolish(bar)


def apply_design_system_v11(root: QWidget) -> None:
    """Apply the shared visual language without changing business behaviour."""
    if root is None or not isValid(root):
        return
    window = root.window()
    if window is None or not isValid(window):
        return
    apply_sidebar_visual_language(window)
    apply_review_status_segmented_control(window)


__all__ = [
    "apply_design_system_v11",
    "apply_review_status_segmented_control",
    "apply_sidebar_visual_language",
]
