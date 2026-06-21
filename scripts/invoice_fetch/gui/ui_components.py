# -*- coding: utf-8 -*-
"""
Invoice Hub Reusable UI Helper Components.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shortcut tables (no Qt dependency — always importable)
# ---------------------------------------------------------------------------

#: Core shortcuts always visible in the collapsed disclosure summary.
CORE_SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Enter", "通过"),
    ("Del", "忽略"),
    ("Ctrl+E", "异常"),
)

#: Secondary shortcuts shown only when disclosure is expanded.
SECONDARY_SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("↑ / ↓", "切换发票"),
    ("Ctrl+F", "搜索"),
    ("F11", "预览全屏"),
    ("Ctrl+I", "导入"),
    ("Ctrl+U", "扫码上传"),
    ("Ctrl+M", "邮箱同步"),
    ("Ctrl+R", "刷新"),
)


try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtWidgets import (
        QPushButton,
        QLabel,
        QFrame,
        QHBoxLayout,
        QVBoxLayout,
        QSizePolicy,
        QLayout,
        QWidget,
    )

    _HAS_QT = True
except ImportError:
    _HAS_QT = False


if _HAS_QT:

    def make_button(
        text: str,
        variant: str = "secondary",
        min_width: int = None,
        tooltip: str = None,
    ) -> QPushButton:
        """
        Create a styled QPushButton using global QSS properties.
        """
        btn = QPushButton(text)
        btn.setProperty("variant", variant)
        btn.setAutoDefault(False)
        btn.setDefault(False)
        btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        # Apply height constraints
        if variant == "toolbar":
            btn.setFixedHeight(30)
        elif variant == "chip":
            pass
        else:
            btn.setFixedHeight(28)

        btn.ensurePolished()
        text_width = btn.fontMetrics().horizontalAdvance(btn.text())
        size_hint_width = btn.sizeHint().width()
        requested_min_width = int(min_width or 0)
        actual_min_width = max(text_width + 24, size_hint_width, requested_min_width)
        btn.setMinimumWidth(actual_min_width)

        if tooltip:
            btn.setToolTip(tooltip)

        return btn

    def make_badge(
        text: str,
        variant: str = "muted",
        min_width: int = None,
        tooltip: str = None,
    ) -> QLabel:
        """
        Create a QLabel styled as a StatusBadge using QSS.
        """
        lbl = QLabel(text)
        lbl.setProperty("class", "StatusBadge")
        lbl.setProperty("variant", variant)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        default_w = min_width or 0
        lbl.setMinimumWidth(max(default_w, lbl.sizeHint().width() + 12))

        if tooltip:
            lbl.setToolTip(tooltip)

        return lbl

    def make_filter_chip(text: str, tooltip: str = None) -> QPushButton:
        """
        Create a QPushButton styled as a filter chip (variant="chip") with a close mark.
        """
        display_text = text if text.endswith(" ×") else f"{text} ×"
        btn = make_button(display_text, variant="chip", tooltip=tooltip)
        btn.setMaximumWidth(120)
        return btn

    def build_action_cluster(widgets: list, min_width: int = None) -> QFrame:
        """
        Group multiple widgets horizontally in a right-aligned action cluster.
        """
        frame = QFrame()
        frame.setProperty("class", "ActionCluster")
        frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.setSizeConstraint(QLayout.SetFixedSize)

        for w in widgets:
            w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            layout.addWidget(w)

        if min_width is not None:
            frame.setMinimumWidth(min_width)

        return frame

    # ---------------------------------------------------------------------------
    # CompactStatCard
    # ---------------------------------------------------------------------------

    class CompactStatCard(QFrame):
        """Compact status summary card for the workbench filter bar.

        Displays a short *title* (e.g. "待审核") and a numeric *value*.  The
        *state* property drives QSS appearance (``warning``, ``success``,
        ``muted``, ``danger``, ``info``).  When *selected* is ``True`` the card
        uses the ``selected=true`` QSS property.

        The component emits intent only — it never queries the database.
        Callers connect :attr:`clicked` to trigger a filter change.
        """

        #: Emitted when the card is clicked.
        clicked = Signal()

        def __init__(
            self,
            title: str,
            value: str,
            *,
            state: str = "muted",
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self.setObjectName("CompactStatCard")
            self.setProperty("state", state)
            self.setProperty("selected", False)
            self.setCursor(Qt.PointingHandCursor)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(2)

            self._lbl_title = QLabel(title)
            self._lbl_title.setProperty("class", "CompactStatCardTitle")
            self._lbl_title.setAlignment(Qt.AlignCenter)

            self._lbl_value = QLabel(value)
            self._lbl_value.setProperty("class", "CompactStatCardValue")
            self._lbl_value.setAlignment(Qt.AlignCenter)

            layout.addWidget(self._lbl_title)
            layout.addWidget(self._lbl_value)

            # Store raw value for programmatic access
            self._value = value

        # ------------------------------------------------------------------
        # Public API
        # ------------------------------------------------------------------

        def set_value(self, value: str) -> None:
            """Update the displayed numeric value."""
            self._value = value
            self._lbl_value.setText(value)

        def value(self) -> str:
            """Return the current displayed value string."""
            return self._value

        def set_selected(self, selected: bool) -> None:
            """Toggle the *selected* semantic property and refresh QSS."""
            self.setProperty("selected", selected)
            # Force Qt to re-evaluate QSS rules for property changes
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

        # ------------------------------------------------------------------
        # Mouse events
        # ------------------------------------------------------------------

        def mousePressEvent(self, event) -> None:  # noqa: N802
            if event.button() == Qt.LeftButton:
                self.clicked.emit()
            super().mousePressEvent(event)

    # ---------------------------------------------------------------------------
    # ShortcutDisclosure
    # ---------------------------------------------------------------------------

    class ShortcutDisclosure(QFrame):
        """Collapsible shortcut-help panel for the workbench sidebar footer.

        Collapsed (default): shows only the three core shortcuts (Enter, Del,
        Ctrl+E) that represent the primary review actions.

        Expanded: also shows the full secondary shortcut set including
        navigation, search, focus mode, import, upload, mail sync, and refresh.

        The *expanded* property is a semantic Qt property so QSS selectors can
        adjust the panel appearance.  No inline stylesheet is used.
        """

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("ShortcutDisclosure")
            self._expanded: bool = False
            self.setProperty("expanded", False)

        # ------------------------------------------------------------------
        # Public API
        # ------------------------------------------------------------------

        def is_expanded(self) -> bool:
            """Return ``True`` when the panel is in its expanded state."""
            return self._expanded

        def set_expanded(self, expanded: bool) -> None:
            """Expand or collapse the shortcut panel."""
            self._expanded = expanded
            self.setProperty("expanded", expanded)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

        def visible_shortcuts(self) -> tuple[str, ...]:
            """Return the tuple of shortcut *key* strings currently visible.

            When collapsed, only the three core keys are returned.  When
            expanded, the core keys are followed by all secondary keys in the
            order they appear in :data:`SECONDARY_SHORTCUTS`.
            """
            core_keys = tuple(key for key, _label in CORE_SHORTCUTS)
            if not self._expanded:
                return core_keys
            secondary_keys = tuple(key for key, _label in SECONDARY_SHORTCUTS)
            return core_keys + secondary_keys
