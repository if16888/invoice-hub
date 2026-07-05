# -*- coding: utf-8 -*-
"""StatusBadge Component - Unified Status Capsule."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget, QSizePolicy


class StatusBadge(QLabel):
    """Capsule status label driven by the 'badge' Qt semantic property (pending, passed, danger, muted)."""

    def __init__(
        self,
        text: str = "",
        badge: str = "muted",
        *,
        tooltip: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setProperty("class", "StatusBadge")
        self.setProperty("badge", badge)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedHeight(24)

        if tooltip:
            self.setToolTip(tooltip)

        self.refresh_style()

    def set_badge(self, badge: str, text: str | None = None) -> None:
        if text is not None:
            self.setText(text)
        self.setProperty("badge", badge)
        self.refresh_style()

    def refresh_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
