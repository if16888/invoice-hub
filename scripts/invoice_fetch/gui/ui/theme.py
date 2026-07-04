# -*- coding: utf-8 -*-
"""Invoice Hub UI Kit - Design Tokens."""

from __future__ import annotations


class Theme:
    """Centralized Theme design tokens for colors, sizes, and styling constants."""

    # Page and Surface Colors
    BG_PAGE = "#F6F8FB"       # Global application page background
    BG_CARD = "#FFFFFF"       # White card container background
    BG_SUBTLE = "#F8FAFC"     # Table headers & subtle control backgrounds
    BG_CANVAS = "#F1F5F9"     # PDF/Image preview canvas background

    # Borders
    BORDER = "#E5EAF2"        # Standard card and container border
    BORDER_STRONG = "#D0D5DD" # Form field and control hover border
    BORDER_FOCUS = "#2563EB"  # Active control focus border

    # Typography / Text Colors
    TEXT_MAIN = "#172033"     # Primary text
    TEXT_SUB = "#667085"      # Secondary text / labels / hints
    TEXT_MUTED = "#98A2B3"    # Disabled text / placeholders

    # Brand & Semantic Status Colors
    BLUE = "#2563EB"
    BLUE_HOVER = "#1D4ED8"
    BLUE_BG = "#EFF6FF"
    BLUE_BORDER = "#BFDBFE"

    GREEN = "#16A34A"
    GREEN_HOVER = "#15803D"
    GREEN_BG = "#ECFDF3"
    GREEN_BORDER = "#ABEFC6"
    GREEN_TEXT = "#067647"

    ORANGE = "#F59E0B"
    ORANGE_HOVER = "#D97706"
    ORANGE_BG = "#FFF7ED"
    ORANGE_BORDER = "#FED7AA"
    ORANGE_TEXT = "#C2410C"

    RED = "#EF4444"
    RED_HOVER = "#DC2626"
    RED_BG = "#FEF2F2"
    RED_BORDER = "#FCA5A5"
    RED_TEXT = "#B91C1C"

    GRAY_BG = "#F1F5F9"
    GRAY_BORDER = "#E2E8F0"
    GRAY_TEXT = "#475569"

    # Border Radii
    RADIUS_CARD = 12
    RADIUS_CONTROL = 8
    RADIUS_BADGE = 12
    RADIUS_SM = 6

    # Layout Metrics & Dimensions
    CONTROL_HEIGHT = 36
    TOOLBAR_HEIGHT = 56
    SIDEBAR_WIDTH = 208
    REVIEW_WIDTH = 420
    STAT_CARD_HEIGHT = 48
    TABLE_CARD_HEIGHT = 230
    PREVIEW_MIN_HEIGHT = 380
