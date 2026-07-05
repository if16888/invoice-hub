# -*- coding: utf-8 -*-
"""AppButton and IconButton Components."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QToolButton, QWidget, QSizePolicy
from ..theme import Theme


class AppButton(QPushButton):
    """Unified application button with variants: primary, default, danger, ghost, toolbar."""

    def __init__(
        self,
        text: str = "",
        variant: str = "default",
        *,
        shortcut_text: str | None = None,
        tooltip: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        if shortcut_text:
            display_text = f"{text} ({shortcut_text})" if text else f"({shortcut_text})"
        else:
            display_text = text

        super().__init__(display_text, parent)
        self.setProperty("variant", variant)
        self.setAutoDefault(False)
        self.setDefault(False)

        if tooltip:
            self.setToolTip(tooltip)

        self.refresh_style()

    def set_variant(self, variant: str) -> None:
        self.setProperty("variant", variant)
        self.refresh_style()

    def refresh_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class IconButton(QToolButton):
    """Icon-only button with hover states and custom tooltip."""

    def __init__(
        self,
        icon=None,
        tooltip: str = "",
        *,
        size: int = 32,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("WorkbenchTopIconButton")
        if icon:
            self.setIcon(icon)
        if tooltip:
            self.setToolTip(tooltip)
        self.setFixedSize(size, size)
