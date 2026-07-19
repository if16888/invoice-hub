"""Readability contract for the compact buyer-mismatch warning.

The Review summary keeps this warning intentionally compact, but the global
``InlineWarning`` stylesheet contributes vertical padding and margins that leave
just enough room for two lines.  Long company names can wrap to three lines in a
narrow detail panel, causing the first and last glyph rows to be clipped.

This contract removes only the redundant vertical chrome.  It keeps the
existing 72px cap, warning colors, border, tooltip and synchronization logic.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from shiboken6 import isValid


BUYER_WARNING_VERTICAL_PADDING = 2
BUYER_WARNING_HORIZONTAL_PADDING = 9


def _warning_stylesheet() -> str:
    return f"""
QLabel#CompactBuyerWarning {{
    padding: {BUYER_WARNING_VERTICAL_PADDING}px {BUYER_WARNING_HORIZONTAL_PADDING}px;
    margin-top: 0px;
    margin-bottom: 0px;
}}
"""


def apply_buyer_warning_readability(page: QWidget | None) -> None:
    """Keep wrapped buyer-warning text fully visible in the Review summary."""
    if page is None or not isValid(page):
        return
    if page.property("buyerWarningReadabilityApplied"):
        return

    window = page.window()
    if window is None or not isValid(window):
        return
    detail = getattr(window, "_detail_panel", None)
    if detail is None or not isValid(detail):
        return
    label = getattr(detail, "lbl_buyer_warning", None)
    if label is None or not isValid(label):
        return

    label.setProperty("buyerWarningLayout", "readable")
    label.setMargin(0)
    label.setContentsMargins(0, 0, 0, 0)
    label.setStyleSheet(_warning_stylesheet())
    label.updateGeometry()

    row = getattr(detail, "buyer_warning_action_row", None)
    if row is not None and isValid(row):
        row_layout = row.layout()
        if row_layout is not None:
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.invalidate()
        row.updateGeometry()

    page.setProperty("buyerWarningReadabilityApplied", True)


__all__ = [
    "BUYER_WARNING_HORIZONTAL_PADDING",
    "BUYER_WARNING_VERTICAL_PADDING",
    "apply_buyer_warning_readability",
]
