"""Shared first-level page header for the Design System v1.1 surfaces."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget


class PageHeader(QFrame):
    """A consistent 22px page title with a muted 13px subtitle."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.lbl_title = QLabel(title, self)
        self.lbl_title.setProperty("class", "PageTitle")
        layout.addWidget(self.lbl_title)
        self.lbl_subtitle = QLabel(subtitle, self)
        self.lbl_subtitle.setProperty("class", "PageSubtitle")
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setVisible(bool(subtitle))
        layout.addWidget(self.lbl_subtitle)

    def set_title(self, title: str) -> None:
        self.lbl_title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.lbl_subtitle.setText(subtitle)
        self.lbl_subtitle.setVisible(bool(subtitle))
