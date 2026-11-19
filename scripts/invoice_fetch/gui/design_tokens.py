"""Authoritative visual tokens for Invoice Hub Design Baseline v1.0.

All product-wide color, typography and geometry contracts originate here.
Compatibility modules may expose aliases, but they must derive them from these
values rather than maintaining competing product tokens.
"""

from __future__ import annotations

from collections.abc import MutableMapping


DESIGN_TOKEN_VERSION = "design-v1.4-desktop"

DESIGN_V1_COLORS = {
    "page": "#F3F5F8",
    "surface": "#FFFFFF",
    "surface_secondary": "#F7F8FA",
    "canvas": "#E8EDF3",
    "navigation": "#ECEFF3",
    "navigation_border": "#DDE3EB",
    "navigation_selected": "#DFECFC",
    "selected": "#DFECFC",
    "border": "#DDE3EB",
    "border_subtle": "#E8ECF1",
    "border_strong": "#7C8DA4",
    "text": "#202A37",
    "text_secondary": "#4C5A6C",
    "muted": "#56657A",
    "placeholder": "#5E6B7E",
    "accent": "#0963CB",
    "accent_hover": "#0757B5",
    "accent_border": "#B8D2EF",
    "focus_ring": "#0963CB",
    "focus_ring_inverse": "#FFFFFF",
    "success": "#146247",
    "success_hover": "#104F3A",
    "success_surface": "#E9F5ED",
    "success_border": "#C5E5D3",
    "success_text": "#146247",
    "warning": "#804807",
    "warning_hover": "#6C3C05",
    "warning_surface": "#FFF1D8",
    "warning_border": "#F0D5A7",
    "warning_text": "#804807",
    "danger": "#A5253D",
    "danger_hover": "#8C1E32",
    "danger_surface": "#FCEEF1",
    "danger_border": "#F0C6D1",
    "danger_text": "#9E2239",
    "muted_surface": "#E8ECF1",
    "muted_border": "#DDE3EB",
    "muted_text": "#4C5A6C",
    "info": "#0963CB",
    "link": "#005BB6",
    "selected_text": "#164D8C",
    "accent_surface": "#EAF3FF",
    "hover_surface": "#EDF2F7",
}

DESKTOP_DARK_COLORS = {
    "#F3F5F8": "#1C2027",
    "#FFFFFF": "#272D36",
    "#F7F8FA": "#303743",
    "#E8EDF3": "#171B21",
    "#ECEFF3": "#232831",
    "#DDE3EB": "#3E4858",
    "#DFECFC": "#293F5C",
    "#E8ECF1": "#353E4B",
    "#7C8DA4": "#6F819A",
    "#202A37": "#F3F5F9",
    "#4C5A6C": "#C0CADA",
    "#56657A": "#A3B0C4",
    "#5E6B7E": "#A0ADBF",
    "#0963CB": "#9CC6FF",
    "#0757B5": "#B3D3FF",
    "#B8D2EF": "#41648F",
    "#146247": "#9DDCBC",
    "#104F3A": "#B3E9CB",
    "#E9F5ED": "#203A33",
    "#C5E5D3": "#305043",
    "#804807": "#FFD187",
    "#6C3C05": "#FFE0AB",
    "#FFF1D8": "#43351F",
    "#F0D5A7": "#604A2A",
    "#A5253D": "#FFACB7",
    "#8C1E32": "#FFBDC6",
    "#FCEEF1": "#482831",
    "#F0C6D1": "#63414E",
    "#9E2239": "#FFB8C2",
    "#005BB6": "#A6CCFF",
    "#164D8C": "#C8E0FF",
    "#EAF3FF": "#253A56",
    "#EDF2F7": "#363F4E",
}

DESIGN_V1_TYPE = {
    "page_title": 24,
    "surface_title": 15,
    "subpage_title": 20,
    "section_title": 15,
    "body": 13,
    "secondary": 12,
    "caption": 12,
    "metric": 16,
    "dashboard_metric": 30,
    "badge": 12,
}

DESIGN_V1_METRICS = {
    "page_margin": 24,
    "workspace_horizontal_margin": 12,
    "section_gap": 16,
    "workspace_gap": 12,
    "control_height": 32,
    "toolbar_control_height": 28,
    "toolbar_height": 64,
    "sidebar_width": 208,
    "sidebar_compact_width": 64,
    "review_row_height": 40,
    "review_detail_width": 324,
    "review_detail_compact_width": 294,
    "review_width": 420,
    "stat_card_height": 48,
    "table_card_height": 230,
    "preview_min_height": 380,
    "section_header_height": 28,
    "nav_item_height": 36,
    "table_header_height": 28,
    "scrollbar_width": 8,
    "focus_border_width": 2,
    "icon_button_size": 32,
    "segmented_control_height": 36,
    "segmented_item_height": 30,
    "segmented_item_gap": 4,
    "radius_small": 6,
    "radius_medium": 8,
    "radius_large": 12,
}

# P1-22: the only spacing scale used by layout code. Values are multiples of
# 4px; the 8pt grid is the default rhythm.
DESIGN_V1_SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
}

DESIGN_V1_BUYER_WARNING = {
    "min_height": 44,
    "max_height": 76,
    "padding_y": 2,
    "padding_x": 9,
    "margin_y": 0,
}

# Compatibility keys consumed by styles.py. Values are always sourced from the
# Design v1 authority above; no product-facing module should redefine them.
LEGACY_COLOR_TOKEN_MAP = {
    "app_background": "page",
    "surface_primary": "surface",
    "surface_secondary": "surface_secondary",
    "text_primary": "text",
    "text_secondary": "text_secondary",
    "text_muted": "muted",
    "border_subtle": "border_subtle",
    "accent": "accent",
    "success": "success",
    "warning": "warning",
    "danger": "danger",
    "info": "info",
}


def canonical_legacy_color_tokens() -> dict[str, str]:
    """Return the compatibility token dictionary derived from Design v1."""
    return {
        legacy_key: DESIGN_V1_COLORS[canonical_key]
        for legacy_key, canonical_key in LEGACY_COLOR_TOKEN_MAP.items()
    }


def apply_legacy_color_tokens(target: MutableMapping[str, str]) -> None:
    """Overwrite a legacy token mapping with the authoritative Design v1 values."""
    target.update(canonical_legacy_color_tokens())


__all__ = [
    "DESIGN_TOKEN_VERSION",
    "DESIGN_V1_COLORS",
    "DESIGN_V1_BUYER_WARNING",
    "DESIGN_V1_METRICS",
    "DESIGN_V1_SPACING",
    "DESIGN_V1_TYPE",
    "LEGACY_COLOR_TOKEN_MAP",
    "apply_legacy_color_tokens",
    "canonical_legacy_color_tokens",
]
