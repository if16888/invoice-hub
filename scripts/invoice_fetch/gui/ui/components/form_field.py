# -*- coding: utf-8 -*-
"""FormField Component - Top-Label Form Field Wrapper."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from ..theme import Theme


class FormField(QWidget):
    """Clean top-label form field wrapper to prevent field misalignment."""

    def __init__(
        self,
        label: str,
        widget: QWidget,
        *,
        required: bool = False,
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        lbl_text = f"{label} *" if required else label
        self.lbl_field = QLabel(lbl_text)
        self.lbl_field.setStyleSheet(f"color: {Theme.TEXT_SUB}; font-size: 12px; font-weight: 500;")
        layout.addWidget(self.lbl_field)

        self.widget = widget
        layout.addWidget(self.widget)

        if hint:
            self.lbl_hint = QLabel(hint)
            self.lbl_hint.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 11px;")
            layout.addWidget(self.lbl_hint)
