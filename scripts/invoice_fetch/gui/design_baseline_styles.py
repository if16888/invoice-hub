"""Global stylesheet assembly for Invoice Hub Design Baseline v1.0."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from .design_tokens import (
    DESIGN_TOKEN_VERSION,
    DESIGN_V1_COLORS,
    DESIGN_V1_METRICS,
    DESIGN_V1_TYPE,
    apply_legacy_color_tokens,
)


# Compatibility export retained for existing imports. The mapping itself is the
# authoritative Design v1 dictionary, not a second independently maintained set.
BASELINE_COLORS = DESIGN_V1_COLORS

BASELINE_QSS = f"""
QMainWindow {{ background-color: {BASELINE_COLORS['page']}; }}
QLabel[class="PageTitle"] {{
    color: {BASELINE_COLORS['text']};
    font-size: {DESIGN_V1_TYPE['page_title']}px;
    font-weight: 600;
}}
QLabel[class="PageHint"] {{
    color: {BASELINE_COLORS['muted']};
    font-size: {DESIGN_V1_TYPE['body']}px;
    font-weight: 400;
}}
QFrame#SectionCard,
QFrame#SummaryStrip,
QFrame#CommandBar,
QFrame#ReadOnlyDetailPanel,
QFrame#SecondaryNavStack {{
    background: {BASELINE_COLORS['surface']};
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: {DESIGN_V1_METRICS['radius_medium']}px;
}}
QFrame#EmptyStateCard,
QFrame#LoadingCard,
QFrame#InlineErrorCard {{
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: {DESIGN_V1_METRICS['radius_medium']}px;
}}
QFrame#SelectableSourceCard {{
    background: {BASELINE_COLORS['surface']};
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: {DESIGN_V1_METRICS['radius_medium']}px;
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
    border-radius: {DESIGN_V1_METRICS['radius_small']}px;
    min-height: {DESIGN_V1_METRICS['control_height']}px;
    padding: 0 14px;
    font-size: {DESIGN_V1_TYPE['body']}px;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover,
QPushButton[emphasis="primary"]:hover {{
    background: {BASELINE_COLORS['accent_hover']};
    border-color: {BASELINE_COLORS['accent_hover']};
}}
QPushButton[variant="secondary"],
QPushButton[emphasis="secondary"] {{
    background: {BASELINE_COLORS['surface']};
    color: {BASELINE_COLORS['text']};
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: {DESIGN_V1_METRICS['radius_small']}px;
    min-height: {DESIGN_V1_METRICS['control_height']}px;
    padding: 0 12px;
    font-size: {DESIGN_V1_TYPE['body']}px;
    font-weight: 500;
}}
QLabel[class="StatusBadge"] {{
    border-radius: 999px;
    padding: 2px 8px;
    font-size: {DESIGN_V1_TYPE['badge']}px;
    font-weight: 600;
}}
QListWidget#SecondaryNavList::item:selected {{
    background: {BASELINE_COLORS['selected']};
    color: {BASELINE_COLORS['accent']};
}}
QTableWidget {{
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: {DESIGN_V1_METRICS['radius_medium']}px;
    selection-background-color: {BASELINE_COLORS['selected']};
    selection-color: {BASELINE_COLORS['accent']};
}}
"""


def build_canonical_application_stylesheet() -> str:
    """Build the full application QSS from the Design v1 token authority."""
    from . import styles as legacy_styles

    apply_legacy_color_tokens(legacy_styles.COLOR_TOKENS)
    core_qss = legacy_styles.build_app_stylesheet()
    try:
        from .ui import build_qss

        core_qss += "\n" + build_qss()
    except ImportError:
        pass

    # Keep late imports of styles.APP_STYLESHEET aligned with the same authority.
    legacy_styles.APP_STYLESHEET = core_qss
    return core_qss + "\n" + BASELINE_QSS


def apply_global_design_baseline(page: QWidget) -> None:
    """Install the canonical product stylesheet once on the main window."""
    if page is None:
        return
    window = page.window()
    if window.property("designBaselineV1Applied"):
        return

    window.setStyleSheet(build_canonical_application_stylesheet())
    window.setProperty("designBaselineTokenVersion", DESIGN_TOKEN_VERSION)
    window.setProperty("designBaselineV1Applied", True)


__all__ = [
    "BASELINE_COLORS",
    "BASELINE_QSS",
    "apply_global_design_baseline",
    "build_canonical_application_stylesheet",
]
