"""Centered, token-driven shell for non-workbench product pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ...design_tokens import DESIGN_V1_METRICS


class StandardPage(QWidget):
    """A full-height page with one centered, consistently sized content rail."""

    MAX_CONTENT_WIDTH = 1280

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("pageArchetype", "standard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            DESIGN_V1_METRICS["page_margin"],
            DESIGN_V1_METRICS["page_margin"],
            DESIGN_V1_METRICS["page_margin"],
            DESIGN_V1_METRICS["page_margin"],
        )
        outer.setSpacing(0)

        self.content = QWidget(self)
        self.content.setObjectName("StandardPageContent")
        self.content.setMaximumWidth(self.MAX_CONTENT_WIDTH)
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(DESIGN_V1_METRICS["section_gap"])
        self._content_layout.setAlignment(Qt.AlignTop)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self.content, 1)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout
