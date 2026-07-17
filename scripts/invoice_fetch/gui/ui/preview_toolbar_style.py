"""Design-token-backed QSS for the document preview toolbar."""

from __future__ import annotations

from .theme import Theme


def build_preview_toolbar_qss() -> str:
    """Return the complete PreviewToolbar stylesheet from Design v1 aliases."""
    return f"""
QFrame#PreviewFloatingToolbar {{
    background: {Theme.BG_CARD};
    border: 1px solid {Theme.BORDER_STRONG};
    border-radius: {Theme.RADIUS_CARD}px;
}}
QToolButton.PreviewToolBtn {{
    min-height: 28px;
    max-height: 28px;
    padding: 0 8px;
    border-radius: {Theme.RADIUS_SM}px;
    border: {Theme.FOCUS_BORDER_WIDTH}px solid transparent;
    color: {Theme.TEXT_SUB};
    background: transparent;
    font-size: {Theme.TYPE_SECONDARY}px;
    font-weight: 500;
}}
QToolButton.PreviewToolBtn:hover {{
    background: {Theme.BLUE_BG};
    color: {Theme.BLUE};
}}
QToolButton.PreviewToolBtn:focus {{
    background: {Theme.BLUE_BG};
    border-color: {Theme.FOCUS_RING};
    color: {Theme.BLUE_HOVER};
}}
QToolButton.PreviewToolBtn:pressed {{
    background: {Theme.BG_CANVAS};
    border-color: {Theme.BLUE};
    color: {Theme.BLUE_HOVER};
}}
QToolButton.PreviewToolBtn[iconOnly="true"] {{
    min-width: 30px;
    max-width: 30px;
    padding: 0;
    font-size: {Theme.TYPE_SURFACE_TITLE}px;
    font-weight: 600;
}}
QToolButton.PreviewToolBtn:disabled {{
    color: {Theme.TEXT_MUTED};
    background: transparent;
    border-color: transparent;
}}
QToolButton.PreviewToolBtn::menu-indicator {{
    image: none;
    width: 0px;
}}
QLabel.ToolbarSep {{
    color: {Theme.BORDER_STRONG};
    font-size: {Theme.TYPE_SECONDARY}px;
    margin: 0 4px;
}}
"""


__all__ = ["build_preview_toolbar_qss"]
