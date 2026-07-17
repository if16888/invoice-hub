# -*- coding: utf-8 -*-
"""SectionHeader component - section title bar."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from ..theme import Theme


class SectionHeader(QFrame):
    """Header bar with section title, optional subtitle/counter, and actions."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        actions: list[QWidget] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SectionHeader")
        self.setFixedHeight(Theme.SECTION_HEADER_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.lbl_title = QLabel(title)
        self.lbl_title.setProperty("role", "section-title")
        layout.addWidget(self.lbl_title)

        if subtitle:
            self.lbl_subtitle = QLabel(subtitle)
            self.lbl_subtitle.setProperty("role", "secondary")
            layout.addWidget(self.lbl_subtitle)

        layout.addStretch(1)

        if actions:
            for action in actions:
                layout.addWidget(action)

    def set_title(self, title: str) -> None:
        self.lbl_title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        if hasattr(self, "lbl_subtitle"):
            self.lbl_subtitle.setText(subtitle)
