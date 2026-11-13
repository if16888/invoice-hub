"""Token-backed segmented status filter control.

The visual container is a single segmented filter, while each item keeps the
existing ``CompactStatCard`` compatibility API used by Review paging, keyboard
navigation, accessibility checks and regression tests.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from ...ui_components import CompactStatCard


_STATE_BY_KEY = {
    "all": "info",
    "to_review": "warning",
    "approved": "success",
    "ignored": "muted",
    "error": "danger",
}


def _repolish_widget_tree(widget: QWidget) -> None:
    """Re-evaluate QSS for a widget and all descendants.

    The segment text colors are selected through a parent dynamic-property
    selector such as ``CompactStatCard[selected=true] QLabel``. Qt reliably
    repolishes the card itself when that property changes, but on Windows it
    may retain the previous palette on the child labels. Refreshing the whole
    small segment subtree keeps background and text state synchronized.
    """
    widgets = (widget, *widget.findChildren(QWidget))
    for item in widgets:
        style = item.style()
        style.unpolish(item)
        style.polish(item)
        item.update()


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
            card.setFocusPolicy(Qt.StrongFocus)
            card.setAccessibleName(card.text())
            card.installEventFilter(self)
            card.clicked.connect(lambda value=key: self._activate(value))
            self.buttons[key] = card
            layout.addWidget(card, 1)

        if selected in self.buttons:
            self.set_selected(selected)

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress) and event.modifiers() == Qt.NoModifier:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_Left, Qt.Key_Right):
                # A focused filter owns activation; Enter must not approve an invoice.
                if event.type() == QEvent.ShortcutOverride:
                    event.accept()
                    return True
                if key in (Qt.Key_Left, Qt.Key_Right):
                    keys = list(self.buttons)
                    current = str(watched.property("segmentKey"))
                    index = (keys.index(current) + (1 if key == Qt.Key_Right else -1)) % len(keys)
                    self.buttons[keys[index]].setFocus(Qt.TabFocusReason)
                    self._activate(keys[index])
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _activate(self, key: str) -> None:
        if key not in self.buttons:
            return
        self.set_selected(key)
        self.changed.emit(key)

    def refresh_geometry(self) -> None:
        """The segmented container owns width, including the first layout."""
        for card in self.buttons.values():
            card.setMinimumWidth(0)
            card.setMaximumWidth(16777215)
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            card.updateGeometry()
        self.layout().invalidate()
        self.updateGeometry()

    def set_selected(self, key: str) -> None:
        if key not in self.buttons:
            return
        self._selected = key
        for item_key, card in self.buttons.items():
            card.set_selected(item_key == key)
            _repolish_widget_tree(card)

    def selected(self) -> str:
        return self._selected

    def set_label(self, key: str, label: str) -> None:
        card = self.buttons.get(key)
        if card is not None:
            card.set_title(label)
            card.setAccessibleName(card.text())

    def set_value(self, key: str, value: str | int) -> None:
        card = self.buttons.get(key)
        if card is not None:
            card.set_value(str(value))
            card.setAccessibleName(card.text())

    def label(self, key: str) -> str:
        card = self.buttons[key]
        return card.text()
