"""Token-backed segmented status filter control.

The visual container is a single segmented filter, while each item keeps the
existing ``CompactStatCard`` compatibility API used by Review paging, keyboard
navigation, accessibility checks and regression tests.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from ...ui_components import CompactStatCard


_STATE_BY_KEY = {
    "all": "info",
    "to_review": "warning",
    "approved": "success",
    "ignored": "muted",
    "error": "danger",
}


class SegmentControl(QWidget):
    """Exclusive, compact control for mutually exclusive page filters."""

    # Keep a lightweight Qt-compatible signal surface without replacing the
    # established item widgets with generic QPushButtons.
    from PySide6.QtCore import Signal

    changed = Signal(str)

    def __init__(
        self,
        items: dict[str, str],
        selected: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("SegmentControl")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(36)
        self.buttons: dict[str, CompactStatCard] = {}
        self._selected = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)

        for key, label in items.items():
            card = CompactStatCard(
                label,
                "0",
                state=_STATE_BY_KEY.get(key, "muted"),
                icon_text="",
                parent=self,
            )
            card.setProperty("segmentKey", key)
            card.setProperty("visualRole", "status-segment")
            card.clicked.connect(lambda value=key: self._activate(value))
            self.buttons[key] = card
            layout.addWidget(card)

        if selected in self.buttons:
            self.set_selected(selected)

    def _activate(self, key: str) -> None:
        if key not in self.buttons:
            return
        self.set_selected(key)
        self.changed.emit(key)

    def set_selected(self, key: str) -> None:
        if key not in self.buttons:
            return
        self._selected = key
        for item_key, card in self.buttons.items():
            card.set_selected(item_key == key)

    def selected(self) -> str:
        return self._selected

    def set_label(self, key: str, label: str) -> None:
        card = self.buttons.get(key)
        if card is not None:
            card.set_title(label)

    def set_value(self, key: str, value: str | int) -> None:
        card = self.buttons.get(key)
        if card is not None:
            card.set_value(str(value))

    def label(self, key: str) -> str:
        card = self.buttons[key]
        return card.text()
