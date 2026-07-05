# -*- coding: utf-8 -*-
"""AlertBanner Component - Risk and System Alert Banner."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget, QSizePolicy
from ..theme import Theme


class AlertBanner(QFrame):
    """Multiline alert banner driven by 'tone' property (warning, danger, info, success)."""

    def __init__(
        self,
        text: str = "",
        tone: str = "warning",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AlertBanner")
        self.setProperty("tone", tone)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self.lbl_text = QLabel(text)
        self.lbl_text.setObjectName("AlertBannerText")
        self.lbl_text.setProperty("tone", tone)
        self.lbl_text.setWordWrap(True)
        layout.addWidget(self.lbl_text)

        self.refresh_style()

    def set_text(self, text: str, tone: str | None = None) -> None:
        self.lbl_text.setText(text)
        if tone:
            self.setProperty("tone", tone)
            self.lbl_text.setProperty("tone", tone)
            self.refresh_style()

    def refresh_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.lbl_text.style().unpolish(self.lbl_text)
        self.lbl_text.style().polish(self.lbl_text)
        self.update()
