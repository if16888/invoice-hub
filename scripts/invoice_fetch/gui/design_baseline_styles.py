"""Global visual tokens and QSS overrides for Design Baseline v1.0."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


BASELINE_COLORS = {
    "page": "#F7F8FA",
    "surface": "#FFFFFF",
    "selected": "#EFF6FF",
    "border": "#E5E7EB",
    "text": "#182230",
    "muted": "#667085",
    "accent": "#2563EB",
    "success": "#16803C",
    "warning": "#B54708",
    "danger": "#B42318",
}


BASELINE_QSS = f"""
QMainWindow {{ background-color: {BASELINE_COLORS['page']}; }}
QLabel[class="PageTitle"] {{
    color: {BASELINE_COLORS['text']};
    font-size: 22px;
    font-weight: 600;
}}
QLabel[class="PageHint"] {{
    color: {BASELINE_COLORS['muted']};
    font-size: 13px;
    font-weight: 400;
}}
QFrame#SectionCard,
QFrame#SummaryStrip,
QFrame#CommandBar,
QFrame#ReadOnlyDetailPanel,
QFrame#SecondaryNavStack {{
    background: {BASELINE_COLORS['surface']};
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: 8px;
}}
QFrame#EmptyStateCard,
QFrame#LoadingCard,
QFrame#InlineErrorCard {{
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: 8px;
}}
QFrame#SelectableSourceCard {{
    background: {BASELINE_COLORS['surface']};
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: 8px;
}}
QFrame#SelectableSourceCard[selected="true"] {{
    background: {BASELINE_COLORS['selected']};
    border: 1px solid {BASELINE_COLORS['accent']};
}}
QPushButton[variant="primary"],
QPushButton[emphasis="primary"] {{
    background: {BASELINE_COLORS['accent']};
    color: #FFFFFF;
    border: 1px solid {BASELINE_COLORS['accent']};
    border-radius: 6px;
    min-height: 34px;
    padding: 0 14px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover,
QPushButton[emphasis="primary"]:hover {{
    background: #1D4ED8;
    border-color: #1D4ED8;
}}
QPushButton[variant="secondary"],
QPushButton[emphasis="secondary"] {{
    background: {BASELINE_COLORS['surface']};
    color: {BASELINE_COLORS['text']};
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: 6px;
    min-height: 34px;
    padding: 0 12px;
    font-size: 13px;
    font-weight: 500;
}}
QLabel[class="StatusBadge"] {{
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QListWidget#SecondaryNavList::item:selected {{
    background: {BASELINE_COLORS['selected']};
    color: {BASELINE_COLORS['accent']};
}}
QTableWidget {{
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: 8px;
    selection-background-color: {BASELINE_COLORS['selected']};
    selection-color: {BASELINE_COLORS['accent']};
}}
"""


def apply_global_design_baseline(page: QWidget) -> None:
    """Install the shared visual contract once on the main window."""
    if page is None:
        return
    window = page.window()
    if window.property("designBaselineV1Applied"):
        return
    window.setProperty("designBaselineV1Applied", True)
    window.setStyleSheet((window.styleSheet() or "") + "\n" + BASELINE_QSS)


__all__ = ["BASELINE_COLORS", "BASELINE_QSS", "apply_global_design_baseline"]
