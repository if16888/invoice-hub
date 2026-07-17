# -*- coding: utf-8 -*-
"""FormField component - top-label form field wrapper."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class FormField(QWidget):
    """Top-label form field wrapper with semantic label and hint roles."""

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
        self.setObjectName("FormField")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label_text = f"{label} *" if required else label
        self.lbl_field = QLabel(label_text)
        self.lbl_field.setProperty("role", "field-label")
        self.lbl_field.setProperty("required", required)
        layout.addWidget(self.lbl_field)

        self.widget = widget
        layout.addWidget(self.widget)

        if hint:
            self.lbl_hint = QLabel(hint)
            self.lbl_hint.setProperty("role", "hint")
            self.lbl_hint.setWordWrap(True)
            layout.addWidget(self.lbl_hint)
