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

# Canonical stylesheet assembly is the migration boundary for older literals
# embedded in the legacy QSS. Keep this map deliberately narrow and semantic:
# brand and status colors are safe to normalize globally, while page-specific
# geometry remains owned by the page archetype migrations.
_OBSOLETE_LITERAL_MAP = {
    "#1599BD": DESIGN_V1_COLORS["accent"],
    "#1599bd": DESIGN_V1_COLORS["accent"],
    "#059669": DESIGN_V1_COLORS["success"],
    "#12b76a": DESIGN_V1_COLORS["success"],
    "#12B76A": DESIGN_V1_COLORS["success"],
    "#DC2626": DESIGN_V1_COLORS["danger"],
    "#dc2626": DESIGN_V1_COLORS["danger"],
    "#f04438": DESIGN_V1_COLORS["danger"],
    "#F04438": DESIGN_V1_COLORS["danger"],
}

BASELINE_QSS = f"""
QWidget {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    font-size: {DESIGN_V1_TYPE['body']}px;
}}
QMainWindow {{ background-color: {BASELINE_COLORS['page']}; }}
QDialog {{ background-color: {BASELINE_COLORS['surface']}; }}
QDialog QLabel {{ font-size: 12px; font-weight: 400; }}
QDialog QPushButton {{ min-height: 30px; padding: 0 12px; font-size: 12px; font-weight: 400; }}
QDialog QLineEdit, QDialog QComboBox, QDialog QSpinBox, QDialog QDateEdit {{
    background: {BASELINE_COLORS['surface']};
    border: 1px solid {BASELINE_COLORS['border']};
    border-radius: 5px; min-height: 28px; padding: 1px 9px;
    font-size: 12px; font-weight: 400;
}}
QDialog QLineEdit:focus, QDialog QComboBox:focus, QDialog QDateEdit:focus {{
    border: 1px solid {BASELINE_COLORS['accent']};
}}
QDialog QSpinBox {{ padding-right: 30px; }}
QDialog QSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 24px; border-left: 1px solid {BASELINE_COLORS['border']};
    border-bottom: 1px solid {BASELINE_COLORS['border']};
    border-top-right-radius: 5px; background: {BASELINE_COLORS['surface_secondary']};
}}
QDialog QSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 24px; border-left: 1px solid {BASELINE_COLORS['border']};
    border-bottom-right-radius: 5px; background: {BASELINE_COLORS['surface_secondary']};
}}
QDialog QSpinBox::up-button:hover, QDialog QSpinBox::down-button:hover {{
    background: {BASELINE_COLORS['navigation_selected']};
}}
QDialog[inputDialog="true"] {{ background: {BASELINE_COLORS['surface']}; }}
QWidget#DialogFormBody {{ background: {BASELINE_COLORS['surface']}; }}
QDialog[inputDialog="true"] QScrollArea {{ background: {BASELINE_COLORS['surface']}; border: none; }}
QLabel[class="DialogTitle"] {{
    font-size: 17px;
    font-weight: 600;
    color: {BASELINE_COLORS['text']};
}}
QLabel[class="DialogHint"] {{ color: {BASELINE_COLORS['muted']}; }}
QLabel[class="DialogError"] {{ color: {BASELINE_COLORS['danger']}; }}
QLabel[class="EmailSuffix"] {{
    background: {BASELINE_COLORS['surface_secondary']};
    color: {BASELINE_COLORS['text_secondary']};
    padding: 4px 8px;
    border-radius: 6px;
}}
QDialog[inputDialog="true"] QLineEdit,
QDialog[inputDialog="true"] QComboBox,
QDialog[inputDialog="true"] QSpinBox {{
    background: {BASELINE_COLORS['surface']};
    border: 1px solid {BASELINE_COLORS['navigation_border']};
    border-radius: 6px;
    min-height: 28px;
    padding: 1px 9px;
    font-size: 12px;
    font-weight: 400;
}}
QDialog[inputDialog="true"] QLineEdit:focus,
QDialog[inputDialog="true"] QComboBox:focus,
QDialog[inputDialog="true"] QSpinBox:focus {{ border: 1px solid {BASELINE_COLORS['accent']}; }}
QDialog[inputDialog="true"] QSpinBox {{ padding-right: 30px; }}
QFrame#WorkbenchNav {{
    background: {BASELINE_COLORS['navigation']};
    border-right: 1px solid {BASELINE_COLORS['navigation_border']};
}}
QPushButton.WorkbenchNavButton {{
    font-size: {DESIGN_V1_TYPE['section_title']}px;
    font-weight: 600;
}}
QPushButton.WorkbenchNavButton:checked {{
    background: {BASELINE_COLORS['navigation_selected']};
    border: 1px solid {BASELINE_COLORS['accent_border']};
    color: {BASELINE_COLORS['accent_hover']};
    font-weight: 700;
}}
QFrame#WorkbenchTopToolbar {{
    background: {BASELINE_COLORS['surface']};
    border: 1px solid {BASELINE_COLORS['navigation_border']};
    border-radius: {DESIGN_V1_METRICS['radius_medium']}px;
}}
QLabel[class="PageTitle"] {{
    color: {BASELINE_COLORS['text']};
    font-size: {DESIGN_V1_TYPE['page_title']}px;
    font-weight: 700;
}}
QLabel[class="PageHint"] {{
    color: {BASELINE_COLORS['muted']};
    font-size: {DESIGN_V1_TYPE['body']}px;
    font-weight: 400;
}}
QLabel[class="SectionTitle"] {{
    color: {BASELINE_COLORS['text']};
    font-size: {DESIGN_V1_TYPE['section_title']}px;
    font-weight: 600;
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
QFrame[class="ChecklistRow"] QLabel[class="ChecklistValue"][state="success"] {{
    color: {BASELINE_COLORS['success']};
}}
QFrame[class="ChecklistRow"] QLabel[class="ChecklistValue"][state="warning"] {{
    color: {BASELINE_COLORS['warning']};
}}
QFrame[class="ChecklistRow"] QLabel[class="ChecklistValue"][state="danger"] {{
    color: {BASELINE_COLORS['danger']};
}}
QFrame[class="ChecklistRow"] QLabel[class="ChecklistValue"][state="muted"] {{
    color: {BASELINE_COLORS['muted']};
}}
"""


def _purge_obsolete_literals(stylesheet: str) -> str:
    """Replace known pre-Baseline brand and status literals."""
    for literal, canonical in _OBSOLETE_LITERAL_MAP.items():
        stylesheet = stylesheet.replace(literal, canonical)
    return stylesheet


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

    core_qss = _purge_obsolete_literals(core_qss)

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
