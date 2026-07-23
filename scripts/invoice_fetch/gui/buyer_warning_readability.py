"""Compatibility exports for the canonical BuyerWarning component.

BuyerWarning geometry is now owned by ``BuyerWarningController`` and the global
Design Token stylesheet. This module remains importable for older integrations,
but is no longer a separate Review pipeline stage.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from .buyer_warning_controller import (
    BUYER_WARNING_PADDING_X,
    BUYER_WARNING_PADDING_Y,
    BuyerWarningController,
)

BUYER_WARNING_HORIZONTAL_PADDING = BUYER_WARNING_PADDING_X
BUYER_WARNING_VERTICAL_PADDING = BUYER_WARNING_PADDING_Y


def apply_buyer_warning_readability(page: QWidget | None) -> None:
    """Compatibility adapter; apply the shared controller contract once."""
    if page is None:
        return
    window = page.window()
    if window is None:
        return
    BuyerWarningController.for_window(window)
    page.setProperty("buyerWarningReadabilityApplied", True)


__all__ = [
    "BUYER_WARNING_PADDING_X",
    "BUYER_WARNING_PADDING_Y",
    "BUYER_WARNING_HORIZONTAL_PADDING",
    "BUYER_WARNING_VERTICAL_PADDING",
    "apply_buyer_warning_readability",
]
