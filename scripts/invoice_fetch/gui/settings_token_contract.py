"""Design-token override for migrated Settings surfaces."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from .design_tokens import (
    DESIGN_TOKEN_VERSION,
    DESIGN_V1_COLORS,
    DESIGN_V1_METRICS,
    DESIGN_V1_TYPE,
)


def _settings_token_qss() -> str:
    colors = DESIGN_V1_COLORS
    metrics = DESIGN_V1_METRICS
    type_scale = DESIGN_V1_TYPE
    return f"""
QFrame#SettingsSubpageHeader {{ background: transparent; border: none; }}
QLabel[class="SettingsSubpageTitle"] {{
    color: {colors['text']};
    font-size: {type_scale['subpage_title']}px;
    font-weight: 600;
}}
QLabel[class="SettingsSubpageHint"] {{
    color: {colors['muted']};
    font-size: {type_scale['secondary']}px;
}}
QFrame[class="SettingsDetailSurface"] {{
    background: {colors['surface']};
    border: 1px solid {colors['border']};
    border-radius: {metrics['radius_medium']}px;
}}
QLabel[class="SettingsSurfaceTitle"] {{
    color: {colors['text']};
    font-size: {type_scale['surface_title']}px;
    font-weight: 600;
}}
QLabel[class="SettingsSurfaceHint"] {{
    color: {colors['muted']};
    font-size: {type_scale['secondary']}px;
}}
QLabel[class="SettingsSectionTitle"] {{
    color: {colors['text']};
    font-size: {type_scale['section_title']}px;
    font-weight: 600;
}}
QLabel[class="SettingsFieldKey"] {{
    color: {colors['muted']};
    font-size: {type_scale['secondary']}px;
    font-weight: 500;
}}
QLabel[class="SettingsFieldValue"] {{
    color: {colors['text']};
    font-size: {type_scale['body']}px;
}}
QFrame[class="SettingsSectionDivider"] {{
    background: {colors['border']};
    border: none;
}}
QFrame#SettingsActionFooter {{ background: transparent; border: none; }}
QLabel[class="SettingsInlineStatus"] {{
    color: {colors['muted']};
    background: {colors['surface_secondary']};
    border-radius: {metrics['radius_small']}px;
    padding: 8px 10px;
}}
QLabel#AISettingsStatusBadge {{
    border-radius: 999px;
    padding: 2px 8px;
    font-size: {type_scale['badge']}px;
    font-weight: 600;
}}
QLabel#AISettingsStatusBadge[tone="success"] {{
    color: {colors['success']};
    background: {colors['success_surface']};
}}
QLabel#AISettingsStatusBadge[tone="warning"] {{
    color: {colors['warning']};
    background: {colors['warning_surface']};
}}
QLabel#AISettingsStatusBadge[tone="muted"] {{
    color: {colors['muted']};
    background: {colors['muted_surface']};
}}
QLabel[semanticStatus="true"] {{
    color: {colors['muted']};
    background: {colors['surface_secondary']};
    border: 1px solid {colors['border']};
    border-radius: {metrics['radius_small']}px;
    padding: 5px 8px;
    font-size: {type_scale['secondary']}px;
}}
QLabel[semanticStatus="true"][status="success"] {{
    color: {colors['success_text']};
    background: {colors['success_surface']};
    border-color: {colors['success_border']};
}}
QLabel[semanticStatus="true"][status="warning"] {{
    color: {colors['warning_text']};
    background: {colors['warning_surface']};
    border-color: {colors['warning_border']};
}}
QLabel[semanticStatus="true"][status="danger"] {{
    color: {colors['danger_text']};
    background: {colors['danger_surface']};
    border-color: {colors['danger_border']};
}}
QLabel[semanticStatus="true"][status="info"] {{
    color: {colors['accent']};
    background: {colors['selected']};
    border-color: {colors['accent_border']};
}}
"""


def apply_settings_token_contract(page: QWidget | None) -> None:
    if page is None or not isValid(page):
        return
    if page.property("settingsTokenContractApplied"):
        return

    window = page.window()
    tabs = getattr(window, "settings_tabs", None)
    if tabs is None or not isValid(tabs):
        return

    tabs.setStyleSheet(tabs.styleSheet() + "\n" + _settings_token_qss())
    page.setProperty("settingsTokenContractVersion", DESIGN_TOKEN_VERSION)
    page.setProperty("settingsTokenContractApplied", True)


__all__ = ["apply_settings_token_contract"]
