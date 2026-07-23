# -*- coding: utf-8 -*-
"""Invoice Hub UI Kit component exports."""

from .card import Card
from .button import AppButton, IconButton
from .status_badge import StatusBadge
from .stat_card import StatCard, CompactStatCard
from .section_header import SectionHeader
from .form_field import FormField
from .alert_banner import AlertBanner
from .attachment_row import AttachmentRow
from .preview_toolbar import PreviewToolbar
from .shortcut_help import ShortcutHelp
from .collapsible_section import CollapsibleSection

__all__ = [
    "Card",
    "AppButton",
    "IconButton",
    "StatusBadge",
    "StatCard",
    "CompactStatCard",
    "SectionHeader",
    "FormField",
    "AlertBanner",
    "AttachmentRow",
    "PreviewToolbar",
    "ShortcutHelp",
    "CollapsibleSection",
    "PageHeader",
    "SegmentControl",
]


def __getattr__(name: str):
    """Load Design v1.1 components lazily to avoid compatibility cycles."""
    if name == "PageHeader":
        from .page_header import PageHeader
        return PageHeader
    if name == "SegmentControl":
        from .segment_control import SegmentControl
        return SegmentControl
    raise AttributeError(name)
