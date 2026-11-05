"""Opt-in dark palette for the Qt shell.

P2-17: the product keeps one QSS source (styles.build_canonical_application_stylesheet)
and derives a dark rendering from the same literals. Opt in with
INVOICE_HUB_THEME=dark (or let the platform color scheme decide once that is
validated on real devices); the light path is unchanged.
"""

from __future__ import annotations

import os
import re

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPalette

DARK_COLOR_MAP = {
    "#F6F8FB": "#0F1115",
    "#F1F5F9": "#0F1115",
    "#EDF2F8": "#131923",
    "#D7E5FB": "#263D60",
    "#CBD5E1": "#3A4250",
    "#E2E8F0": "#2A3038",
    "#182230": "#E6E8EB",
    "#101828": "#E6E8EB",
    "#16803C": "#53CE83",
    "#15803D": "#72DC9A",
    "#067647": "#53CE83",
    "#ABEFC6": "#245C3C",
    "#B54708": "#FFC078",
    "#D97706": "#FFD29C",
    "#FED7AA": "#71501D",
    "#B42318": "#FF9186",
    "#DC2626": "#FFA49B",
    "#B91C1C": "#FF9186",
    "#FCA5A5": "#743833",
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
    # One pass also handles lowercase local QSS without remapping a replacement.
    return re.sub(r"#[0-9a-fA-F]{6}\b", lambda match: DARK_COLOR_MAP.get(
        match.group().upper(), match.group()), base)


class _DarkStyleFilter(QObject):
    """Theme local and lazily constructed QSS, including baseline reapplications."""

    def eventFilter(self, widget, event):
        if event.type() in (QEvent.Polish, QEvent.StyleChange) and prefers_dark():
            self.apply(widget)
        return False

    def apply(self, widget):
        from PySide6.QtWidgets import QWidget

        if not isinstance(widget, QWidget) or getattr(widget, "_dark_style_busy", False):
            return
        source = widget.styleSheet()
        if not source or source == getattr(widget, "_dark_applied_qss", None):
            return
        themed = dark_stylesheet(source)
        widget._dark_applied_qss = themed
        if themed != source:
            widget._dark_style_busy = True
            try:
                widget.setStyleSheet(themed)
            finally:
                widget._dark_style_busy = False



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
    from PySide6.QtWidgets import QWidget

    style_filter = getattr(app, "_invoice_hub_dark_style_filter", None)
    if style_filter is None:
        style_filter = _DarkStyleFilter(app)
        app._invoice_hub_dark_style_filter = style_filter
        app.installEventFilter(style_filter)
    base = app.styleSheet()
    if base and base != getattr(app, "_dark_applied_qss", None):
        themed = dark_stylesheet(base)
        app._dark_applied_qss = themed
        app.setStyleSheet(themed)
    app.setPalette(dark_palette())
    for window in app.topLevelWidgets():
        style_filter.apply(window)
        for child in window.findChildren(QWidget):
            style_filter.apply(child)
    return True


__all__ = [
    "DARK_COLOR_MAP",
    "apply_app_theme",
    "dark_palette",
    "dark_stylesheet",
    "prefers_dark",
    "theme_override",
]
