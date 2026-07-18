"""Token-backed segmented status filter control."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QWidget


class SegmentControl(QWidget):
    """Exclusive, compact control for mutually exclusive page filters."""

    changed = Signal(str)

    def __init__(self, items: dict[str, str], selected: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SegmentControl")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(36)
        self.buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        for key, label in items.items():
            button = QPushButton(label, self)
            button.setObjectName(f"Segment_{key}")
            button.setProperty("class", "SegmentItem")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.TabFocus)
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
            button.clicked.connect(lambda _checked=False, value=key: self.changed.emit(value))
            self._group.addButton(button)
            self.buttons[key] = button
            layout.addWidget(button)
        if selected in self.buttons:
            self.set_selected(selected)

    def set_selected(self, key: str) -> None:
        if key not in self.buttons:
            return
        self.buttons[key].setChecked(True)
        for button in self.buttons.values():
            button.style().unpolish(button)
            button.style().polish(button)

    def set_label(self, key: str, label: str) -> None:
        if key in self.buttons:
            self.buttons[key].setText(label)

    def label(self, key: str) -> str:
        return self.buttons[key].text()
