# -*- coding: utf-8 -*-
"""Card Component - Unified White Container Card."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QWidget, QVBoxLayout


class Card(QFrame):
    """Reusable white card container widget matching Theme.RADIUS_CARD and Theme.BORDER."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("class", "WorkbenchCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
