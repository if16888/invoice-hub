"""Authoritative visual tokens for Invoice Hub Design Baseline v1.0.

All product-wide color, typography and geometry contracts should originate here.
Legacy modules may expose compatibility dictionaries, but they must be populated
from these values rather than defining competing product tokens.
"""

from __future__ import annotations

from collections.abc import MutableMapping


DESIGN_TOKEN_VERSION = "design-v1.0"

DESIGN_V1_COLORS = {
    "page": "#F7F8FA",
    "surface": "#FFFFFF",
    "surface_secondary": "#F8FAFC",
    "selected": "#EFF6FF",
    "border": "#E5E7EB",
    "border_subtle": "#E4E7EC",
    "text": "#182230",
    "text_secondary": "#475467",
    "muted": "#667085",
    "accent": "#2563EB",
    "accent_hover": "#1D4ED8",
    "success": "#16803C",
    "warning": "#B54708",
    "danger": "#B42318",
    "info": "#2563EB",
}

DESIGN_V1_TYPE = {
    "page_title": 22,
    "section_title": 13,
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
