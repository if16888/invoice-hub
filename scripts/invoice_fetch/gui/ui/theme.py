# -*- coding: utf-8 -*-
"""Invoice Hub UI Kit compatibility aliases for Design Baseline v1."""

from __future__ import annotations

from ..design_tokens import DESIGN_V1_COLORS, DESIGN_V1_METRICS, DESIGN_V1_TYPE


class Theme:
    """UI Kit aliases derived exclusively from the authoritative Design v1 tokens."""

    # Page and surface colors
    BG_PAGE = DESIGN_V1_COLORS["page"]
    BG_CARD = DESIGN_V1_COLORS["surface"]
    BG_SUBTLE = DESIGN_V1_COLORS["surface_secondary"]
    BG_CANVAS = DESIGN_V1_COLORS["canvas"]

    # Borders and focus
    BORDER = DESIGN_V1_COLORS["border"]
    BORDER_STRONG = DESIGN_V1_COLORS["border_strong"]
    BORDER_FOCUS = DESIGN_V1_COLORS["accent"]
    FOCUS_RING = DESIGN_V1_COLORS["focus_ring"]
    FOCUS_RING_INVERSE = DESIGN_V1_COLORS["focus_ring_inverse"]

    # Typography and text colors
    TEXT_MAIN = DESIGN_V1_COLORS["text"]
    TEXT_SUB = DESIGN_V1_COLORS["text_secondary"]
    TEXT_HINT = DESIGN_V1_COLORS["muted"]
    TEXT_MUTED = DESIGN_V1_COLORS["placeholder"]
    TEXT_ON_ACCENT = DESIGN_V1_COLORS["surface"]

    # Brand and semantic status colors
    BLUE = DESIGN_V1_COLORS["accent"]
    BLUE_HOVER = DESIGN_V1_COLORS["accent_hover"]
    BLUE_BG = DESIGN_V1_COLORS["selected"]
    BLUE_BORDER = DESIGN_V1_COLORS["accent_border"]

    GREEN = DESIGN_V1_COLORS["success"]
    GREEN_HOVER = DESIGN_V1_COLORS["success_hover"]
    GREEN_BG = DESIGN_V1_COLORS["success_surface"]
    GREEN_BORDER = DESIGN_V1_COLORS["success_border"]
    GREEN_TEXT = DESIGN_V1_COLORS["success_text"]

    ORANGE = DESIGN_V1_COLORS["warning"]
    ORANGE_HOVER = DESIGN_V1_COLORS["warning_hover"]
    ORANGE_BG = DESIGN_V1_COLORS["warning_surface"]
    ORANGE_BORDER = DESIGN_V1_COLORS["warning_border"]
    ORANGE_TEXT = DESIGN_V1_COLORS["warning_text"]

    RED = DESIGN_V1_COLORS["danger"]
    RED_HOVER = DESIGN_V1_COLORS["danger_hover"]
    RED_BG = DESIGN_V1_COLORS["danger_surface"]
    RED_BORDER = DESIGN_V1_COLORS["danger_border"]
    RED_TEXT = DESIGN_V1_COLORS["danger_text"]

    GRAY_BG = DESIGN_V1_COLORS["muted_surface"]
    GRAY_BORDER = DESIGN_V1_COLORS["muted_border"]
    GRAY_TEXT = DESIGN_V1_COLORS["muted_text"]

    # Typography scale
    TYPE_PAGE_TITLE = DESIGN_V1_TYPE["page_title"]
    TYPE_SURFACE_TITLE = DESIGN_V1_TYPE["surface_title"]
    TYPE_SUBPAGE_TITLE = DESIGN_V1_TYPE["subpage_title"]
    TYPE_SECTION_TITLE = DESIGN_V1_TYPE["section_title"]
    TYPE_BODY = DESIGN_V1_TYPE["body"]
    TYPE_SECONDARY = DESIGN_V1_TYPE["secondary"]
    TYPE_CAPTION = DESIGN_V1_TYPE["caption"]
    TYPE_METRIC = DESIGN_V1_TYPE["metric"]
    TYPE_BADGE = DESIGN_V1_TYPE["badge"]

    # Border radii
    RADIUS_CARD = DESIGN_V1_METRICS["radius_large"]
    RADIUS_CONTROL = DESIGN_V1_METRICS["radius_medium"]
    RADIUS_BADGE = DESIGN_V1_METRICS["radius_large"]
    RADIUS_SM = DESIGN_V1_METRICS["radius_small"]

    # Layout metrics and dimensions. These remain compatibility aliases for the
    # UI Kit page classes; the values are owned by design_tokens.py.
    CONTROL_HEIGHT = DESIGN_V1_METRICS["control_height"]
    TOOLBAR_CONTROL_HEIGHT = DESIGN_V1_METRICS["toolbar_control_height"]
    TOOLBAR_HEIGHT = DESIGN_V1_METRICS["toolbar_height"]
    SIDEBAR_WIDTH = DESIGN_V1_METRICS["sidebar_width"]
    REVIEW_WIDTH = DESIGN_V1_METRICS["review_width"]
    STAT_CARD_HEIGHT = DESIGN_V1_METRICS["stat_card_height"]
    TABLE_CARD_HEIGHT = DESIGN_V1_METRICS["table_card_height"]
    PREVIEW_MIN_HEIGHT = DESIGN_V1_METRICS["preview_min_height"]
    SECTION_HEADER_HEIGHT = DESIGN_V1_METRICS["section_header_height"]
    NAV_ITEM_HEIGHT = DESIGN_V1_METRICS["nav_item_height"]
    TABLE_HEADER_HEIGHT = DESIGN_V1_METRICS["table_header_height"]
    SCROLLBAR_WIDTH = DESIGN_V1_METRICS["scrollbar_width"]
    FOCUS_BORDER_WIDTH = DESIGN_V1_METRICS["focus_border_width"]
