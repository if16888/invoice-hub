# -*- coding: utf-8 -*-
"""StatCard Component - Filter Bar Status Summary Card."""

from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget, QSizePolicy
from ..theme import Theme


class StatCard(QFrame):
    """Compact status summary card for the workbench filter bar."""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        value: str = "0",
        *,
        state: str = "muted",
        icon_text: str = "",
        selected: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CompactStatCard")
        self.setProperty("state", state)
        self.setProperty("selected", selected)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(Theme.STAT_CARD_HEIGHT)
        self.setMinimumWidth(140)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(6)

        self._lbl_icon = QLabel(icon_text)
        self._lbl_icon.setProperty("class", "CompactStatCardIcon")
        self._lbl_icon.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._lbl_icon.setVisible(bool(icon_text))

        self._lbl_title = QLabel(title)
        self._lbl_title.setProperty("class", "CompactStatCardTitle")
        self._lbl_title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self._lbl_value = QLabel(str(value))
        self._lbl_value.setProperty("class", "CompactStatCardValue")
        self._lbl_value.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        layout.addWidget(self._lbl_icon)
        layout.addWidget(self._lbl_title)
        layout.addStretch(1)
        layout.addWidget(self._lbl_value)

        self._value = str(value)
        self._icon_text = icon_text

    def set_value(self, value: str | int) -> None:
        self._value = str(value)
        self._lbl_value.setText(self._value)

    def value(self) -> str:
        return self._value

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


# Alias for compatibility with legacy code
CompactStatCard = StatCard
