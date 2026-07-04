# -*- coding: utf-8 -*-
"""InvoiceWorkbench - Main Review Workbench Layout Page."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QSizePolicy,
)
from ..theme import Theme


class InvoiceWorkbench(QWidget):
    """Main Invoice Hub review workbench layout container.

    Layout hierarchy:
      PageRoot (QHBoxLayout, margin=0, spacing=0)
      ├── SideNav (Fixed 208px width)
      └── ContentContainer (QVBoxLayout, margin=16, spacing=8)
          ├── TopToolbar (Fixed 56px height)
          └── BodyContainer (QHBoxLayout, margin=0, spacing=8)
              ├── WorkspaceContainer (QVBoxLayout, margin=0, spacing=8, stretch=1)
              │   ├── StatusFilterCard (Fixed 48px height)
              │   ├── InvoiceRecordCard (Fixed 230px height, max 240px)
              │   └── InvoicePreviewCard (Stretch=1, min-height 380px)
              └── ReviewPanel (Fixed 420px width)
    """

    def __init__(
        self,
        side_nav: QWidget,
        top_toolbar: QWidget,
        status_filter_card: QWidget,
        invoice_record_card: QWidget,
        invoice_preview_card: QWidget,
        review_panel: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PageRoot")

        # Root horizontal layout
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Left Side Navigation
        self.side_nav = side_nav
        self.side_nav.setMinimumWidth(Theme.SIDEBAR_WIDTH)
        self.side_nav.setMaximumWidth(Theme.SIDEBAR_WIDTH)
        root_layout.addWidget(self.side_nav)

        # 2. Right Main Content Area
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(8)

        # 2.1 Top Action Toolbar
        self.top_toolbar = top_toolbar
        self.top_toolbar.setFixedHeight(Theme.TOOLBAR_HEIGHT)
        content_layout.addWidget(self.top_toolbar)

        # 2.2 Body Container (Workspace + ReviewPanel)
        body_container = QWidget()
        body_layout = QHBoxLayout(body_container)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        # 2.2.1 Middle Workspace (3 Stable White Cards, NO Splitter)
        workspace_container = QWidget()
        workspace_layout = QVBoxLayout(workspace_container)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(8)  # Card gap = 8px (<= 12px)

        self.status_filter_card = status_filter_card
        self.status_filter_card.setFixedHeight(Theme.STAT_CARD_HEIGHT)
        workspace_layout.addWidget(self.status_filter_card, 0)

        self.invoice_record_card = invoice_record_card
        self.invoice_record_card.setFixedHeight(Theme.TABLE_CARD_HEIGHT)
        self.invoice_record_card.setMaximumHeight(240)
        workspace_layout.addWidget(self.invoice_record_card, 0)

        self.invoice_preview_card = invoice_preview_card
        self.invoice_preview_card.setMinimumHeight(Theme.PREVIEW_MIN_HEIGHT)
        self.invoice_preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        workspace_layout.addWidget(self.invoice_preview_card, 1)

        body_layout.addWidget(workspace_container, 1)

        # 2.2.2 Right Review Panel
        self.review_panel = review_panel
        self.review_panel.setMinimumWidth(Theme.REVIEW_WIDTH)
        self.review_panel.setMaximumWidth(Theme.REVIEW_WIDTH)
        body_layout.addWidget(self.review_panel, 0)

        content_layout.addWidget(body_container, 1)
        root_layout.addWidget(content_container, 1)
