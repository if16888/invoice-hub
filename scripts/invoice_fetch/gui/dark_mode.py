"""Opt-in dark palette for the Qt shell.

P2-17: the product keeps one QSS source (styles.build_canonical_application_stylesheet)
and derives a dark rendering from the same literals. Opt in with
INVOICE_HUB_THEME=dark (or let the platform color scheme decide once that is
validated on real devices); the light path is unchanged.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

DARK_COLOR_MAP = {
    "#F6F8FB": "#0F1115",
    "#F7F8FA": "#0F1115",
    "#FFFFFF": "#161A20",
    "#F8FAFC": "#1B2027",
    "#F2F4F7": "#1F252E",
    "#EFF6FF": "#1E293B",
    "#EEF2F6": "#1B2027",
    "#E5E5EA": "#2A3038",
    "#E5EAF2": "#2A3038",
    "#E4E7EC": "#2A3038",
    "#E5E7EB": "#2A3038",
    "#D0D5DD": "#3A4250",
    "#98A2B3": "#6B7687",
    "#667085": "#98A2B3",
    "#475467": "#B4BDCB",
    "#344054": "#CBD5E1",
    "#172033": "#E6E8EB",
    "#111827": "#E6E8EB",
    "#2563EB": "#5B9BFF",
    "#1D4ED8": "#7BB0FF",
    "#BFDBFE": "#2B4C7E",
    "#FEF3F2": "#3B1D1D",
    "#FFFAEB": "#3A2E12",
    "#ECFDF3": "#123527",
}


def theme_override() -> str:
    return os.environ.get("INVOICE_HUB_THEME", "").strip().lower()


def prefers_dark() -> bool:
    """Dark theme is currently opt-in; system detection is behind the same env."""
    override = theme_override()
    if override in {"dark", "light"}:
        return override == "dark"
    return False


def dark_stylesheet(base: str) -> str:
    """Map the canonical light stylesheet literals onto dark surfaces."""
    stylesheet = base
    for light, dark in DARK_COLOR_MAP.items():
        stylesheet = stylesheet.replace(light, dark)
    return stylesheet


def dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#0F1115"))
    palette.setColor(QPalette.WindowText, QColor("#E6E8EB"))
    palette.setColor(QPalette.Base, QColor("#161A20"))
    palette.setColor(QPalette.AlternateBase, QColor("#1B2027"))
    palette.setColor(QPalette.Text, QColor("#E6E8EB"))
    palette.setColor(QPalette.Button, QColor("#1F252E"))
    palette.setColor(QPalette.ButtonText, QColor("#E6E8EB"))
    palette.setColor(QPalette.Highlight, QColor("#5B9BFF"))
    palette.setColor(QPalette.HighlightedText, QColor("#0F1115"))
    palette.setColor(QPalette.ToolTipBase, QColor("#1B2027"))
    palette.setColor(QPalette.ToolTipText, QColor("#E6E8EB"))
    palette.setColor(QPalette.PlaceholderText, QColor("#98A2B3"))
    return palette


def apply_app_theme(app) -> bool:
    """Apply the dark palette when opted in; returns True when dark is active."""
    if app is None or not prefers_dark():
        return False
    base = app.styleSheet()
    if base:
        app.setStyleSheet(dark_stylesheet(base))
    app.setPalette(dark_palette())
    return True


__all__ = [
    "DARK_COLOR_MAP",
    "apply_app_theme",
    "dark_palette",
    "dark_stylesheet",
    "prefers_dark",
    "theme_override",
]
