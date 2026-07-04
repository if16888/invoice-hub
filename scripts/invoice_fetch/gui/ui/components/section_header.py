# -*- coding: utf-8 -*-
"""SectionHeader Component - Section Title Bar."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class SectionHeader(QFrame):
    """Header bar with section title, optional subtitle/counter, and right-aligned actions."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        actions: list[QWidget] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.lbl_title = QLabel(title)
        self.lbl_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_title.setStyleSheet("color: #172033;")
        layout.addWidget(self.lbl_title)

        if subtitle:
            self.lbl_subtitle = QLabel(subtitle)
            self.lbl_subtitle.setStyleSheet("color: #667085; font-size: 12px;")
            layout.addWidget(self.lbl_subtitle)

        layout.addStretch(1)

        if actions:
            for act in actions:
                layout.addWidget(act)

    def set_title(self, title: str) -> None:
        self.lbl_title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        if hasattr(self, "lbl_subtitle"):
            self.lbl_subtitle.setText(subtitle)
