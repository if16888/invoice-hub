"""Authoritative visual tokens for Invoice Hub Design Baseline v1.0.

All product-wide color, typography and geometry contracts originate here.
Compatibility modules may expose aliases, but they must derive them from these
values rather than maintaining competing product tokens.
"""

from __future__ import annotations

from collections.abc import MutableMapping


DESIGN_TOKEN_VERSION = "design-v1.2-focus-closure"

DESIGN_V1_COLORS = {
    "page": "#F7F8FA",
    "surface": "#FFFFFF",
    "surface_secondary": "#F8FAFC",
    "canvas": "#F1F5F9",
    "selected": "#EFF6FF",
    "border": "#E5E7EB",
    "border_subtle": "#E4E7EC",
    "border_strong": "#D0D5DD",
    "text": "#182230",
    "text_secondary": "#475467",
    "muted": "#667085",
    "placeholder": "#98A2B3",
    "accent": "#2563EB",
    "accent_hover": "#1D4ED8",
    "accent_border": "#BFDBFE",
    # Focus indicators must remain visible on white, page, and selected surfaces.
    "focus_ring": "#2563EB",
    # Filled accent controls use an inverse inner border for the focused state.
    "focus_ring_inverse": "#FFFFFF",
    "success": "#16803C",
    "success_hover": "#15803D",
    "success_surface": "#ECFDF3",
    "success_border": "#ABEFC6",
    "success_text": "#067647",
    "warning": "#B54708",
    "warning_hover": "#D97706",
    "warning_surface": "#FFFAEB",
    "warning_border": "#FED7AA",
    "warning_text": "#B54708",
    "danger": "#B42318",
    "danger_hover": "#DC2626",
    "danger_surface": "#FEF3F2",
    "danger_border": "#FCA5A5",
    "danger_text": "#B91C1C",
    "muted_surface": "#F2F4F7",
    "muted_border": "#E2E8F0",
    "muted_text": "#475467",
    "info": "#2563EB",
}

DESIGN_V1_TYPE = {
    "page_title": 22,
    "surface_title": 16,
    "subpage_title": 15,
    "section_title": 14,
    "body": 13,
    "secondary": 12,
    "caption": 11,
    "metric": 18,
    "badge": 12,
}

DESIGN_V1_METRICS = {
    "page_margin": 24,
    "workspace_horizontal_margin": 12,
    "section_gap": 16,
    "workspace_gap": 8,
    "control_height": 34,
    "toolbar_control_height": 32,
    "toolbar_height": 56,
    "sidebar_width": 208,
    "review_width": 420,
    "stat_card_height": 48,
    "table_card_height": 230,
    "preview_min_height": 380,
    "section_header_height": 28,
    "nav_item_height": 40,
    "table_header_height": 34,
    "scrollbar_width": 8,
    "focus_border_width": 2,
    "radius_small": 6,
    "radius_medium": 8,
    "radius_large": 10,
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
    "DESIGN_V1_METRICS",
    "DESIGN_V1_TYPE",
    "LEGACY_COLOR_TOKEN_MAP",
    "apply_legacy_color_tokens",
    "canonical_legacy_color_tokens",
]
