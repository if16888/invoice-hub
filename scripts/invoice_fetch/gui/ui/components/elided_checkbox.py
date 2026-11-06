"""Native checkbox behavior with a label that can shrink inside account rows."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QStyle, QStyleOptionButton, QStylePainter


class ElidedCheckBox(QCheckBox):
    """Keep the full accessible label while painting a bounded, elided label."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAccessibleName(text)
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def minimumSizeHint(self):  # noqa: N802
        hint = super().minimumSizeHint()
        hint.setWidth(48)
        return hint

    def paintEvent(self, event):  # noqa: N802
        option = QStyleOptionButton()
        self.initStyleOption(option)
        text_rect = self.style().subElementRect(QStyle.SE_CheckBoxContents, option, self)
        option.text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, max(0, text_rect.width()))
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_CheckBox, option)
