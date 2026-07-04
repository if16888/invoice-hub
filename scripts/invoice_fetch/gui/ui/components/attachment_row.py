# -*- coding: utf-8 -*-
"""AttachmentRow Component - Supporting Document Row Widget."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget
from ..theme import Theme


class AttachmentRow(QFrame):
    """Row widget representing an attached supporting material/file."""

    def __init__(
        self,
        label: str,
        filename: str = "",
        *,
        status: str = "",
        status_tone: str = "muted",
        on_open=None,
        on_locate=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setStyleSheet(f"border-bottom: 1px solid {Theme.BORDER};")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(8)

        self.lbl_label = QLabel(label)
        self.lbl_label.setStyleSheet(f"color: {Theme.TEXT_SUB}; font-weight: 600; font-size: 12px;")
        layout.addWidget(self.lbl_label)

        if filename:
            self.lbl_filename = QLabel(filename)
            self.lbl_filename.setStyleSheet(f"color: {Theme.TEXT_MAIN}; font-size: 12px;")
            layout.addWidget(self.lbl_filename)

        if status:
            self.lbl_status = QLabel(status)
            color = Theme.ORANGE_TEXT if status_tone == "warning" else Theme.TEXT_MUTED
            self.lbl_status.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 500;")
            layout.addWidget(self.lbl_status)

        layout.addStretch(1)

        if on_open:
            btn_open = QPushButton("打开")
            btn_open.setProperty("variant", "toolbar")
            btn_open.clicked.connect(on_open)
            layout.addWidget(btn_open)

        if on_locate:
            btn_locate = QPushButton("定位")
            btn_locate.setProperty("variant", "toolbar")
            btn_locate.clicked.connect(on_locate)
            layout.addWidget(btn_locate)
