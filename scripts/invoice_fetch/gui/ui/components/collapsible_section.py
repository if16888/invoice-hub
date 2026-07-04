# -*- coding: utf-8 -*-
"""CollapsibleSection Component - Accordion Panel Wrapper."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from ..theme import Theme


class CollapsibleSection(QFrame):
    """Collapsible accordion container with title bar toggle."""

    def __init__(
        self,
        title: str,
        content_widget: QWidget,
        *,
        expanded: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._expanded = expanded

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(32)
        header.setCursor(Qt.PointingHandCursor)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(6)

        self.btn_toggle = QPushButton("▼" if expanded else "▶")
        self.btn_toggle.setProperty("variant", "ghost")
        self.btn_toggle.setFixedSize(24, 24)
        self.btn_toggle.clicked.connect(self.toggle)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(f"color: {Theme.TEXT_MAIN}; font-weight: 600; font-size: 12px;")

        header_layout.addWidget(self.btn_toggle)
        header_layout.addWidget(lbl_title)
        header_layout.addStretch(1)

        layout.addWidget(header)
        self.content_widget = content_widget
        self.content_widget.setVisible(expanded)
        layout.addWidget(self.content_widget)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.btn_toggle.setText("▼" if expanded else "▶")
        self.content_widget.setVisible(expanded)
