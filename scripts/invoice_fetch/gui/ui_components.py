# -*- coding: utf-8 -*-
"""Invoice Hub Reusable UI Helper Components."""

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
    from PySide6.QtGui import QKeyEvent, QPainter
    from PySide6.QtWidgets import (
        QFrame,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QToolButton,
        QSizePolicy,
        QLayout,
        QWidget,
        QVBoxLayout,
        QListWidget,
        QListWidgetItem,
        QStackedWidget,
    )

    _HAS_QT = True
except ImportError:
    _HAS_QT = False


if _HAS_QT:

    def is_visual_primary(button) -> bool:
        """Single primary-action contract shared by product code and tests."""
        return bool(
            button is not None
            and (
                button.property("variant") == "primary"
                or button.property("emphasis") == "primary"
            )
        )

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
        if variant == "chip":
            btn.setFixedHeight(26)
        elif variant == "toolbar":
            btn.setFixedHeight(34)
        else:
            btn.setFixedHeight(34)

        btn.ensurePolished()
        text_width = btn.fontMetrics().horizontalAdvance(btn.text())
        size_hint_width = btn.sizeHint().width()
        requested_min_width = int(min_width or 0)
        actual_min_width = max(text_width + 24, size_hint_width, requested_min_width)
        btn.setMinimumWidth(actual_min_width)
        if variant == "primary":
            btn.setMaximumWidth(max(actual_min_width, 220))

        if tooltip:
            btn.setToolTip(tooltip)

        return btn

    class AdaptiveButton(QPushButton):
        """Text button whose minimum width follows font metrics at any DPI."""

        def __init__(self, text: str, variant: str = "secondary", parent=None):
            super().__init__(text, parent)
            self.setProperty("variant", variant)
            self.setFixedHeight(34)
            self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            self.refresh_adaptive_width()

        def refresh_adaptive_width(self):
            self.setMinimumWidth(max(self.fontMetrics().horizontalAdvance(self.text()) + 28, self.sizeHint().width()))

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

    class SummaryStrip(QFrame):
        """Lightweight horizontal metrics strip shared by workbench pages."""

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("SummaryStrip")
            self.setProperty("class", "WorkbenchCard")
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            self._layout = QHBoxLayout(self)
            self._layout.setContentsMargins(12, 8, 12, 8)
            self._layout.setSpacing(8)
            self._items: dict[str, CompactStatCard] = {}

        def add_metric(
            self,
            key: str,
            title: str,
            value: str = "0",
            *,
            state: str = "muted",
            icon_text: str = "",
        ) -> CompactStatCard:
            card = CompactStatCard(title, value, state=state, icon_text=icon_text, parent=self)
            card.setObjectName("SummaryStripCard")
            card.setFixedHeight(40)
            card.setMinimumWidth(120)
            self._layout.addWidget(card, 1)
            self._items[key] = card
            return card

        def set_metric(self, key: str, value: str, title: str | None = None) -> None:
            card = self._items.get(key)
            if not card:
                return
            if title is not None:
                card.set_title(title)
            card.set_value(value)

        def card_for(self, key: str) -> CompactStatCard | None:
            return self._items.get(key)

        def metrics(self) -> dict[str, CompactStatCard]:
            return dict(self._items)

    class ElidedValueLabel(QLabel):
        """Single-line value label that paints a DPI-safe ellipsis."""

        def __init__(self, text: str = "", parent: QWidget | None = None):
            super().__init__(parent)
            self.setProperty("class", "ElidedValue")
            self.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self.set_value(text)

        def set_value(self, text: str = "") -> None:
            value = str(text or "—")
            self.setText(value)
            self.setToolTip("" if value == "—" else value)

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setFont(self.font())
            painter.setPen(self.palette().color(self.foregroundRole()))
            text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, max(0, self.width()))
            painter.drawText(self.rect(), self.alignment() or (Qt.AlignLeft | Qt.AlignVCenter), text)

    class ElidedTextLabel(ElidedValueLabel):
        """Semantic alias for long product text such as paths, names and IDs."""

    class CredentialValueLabel(ElidedValueLabel):
        """Never displays a secret; only a credential presence/status value."""

    class StatusLine(QFrame):
        """Compact task row: label, status and one relevant primary action."""

        def __init__(self, label: str, status: str = "—", parent: QWidget | None = None):
            super().__init__(parent)
            self.setProperty("class", "StatusLine")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(8)
            self.lbl_label = QLabel(label)
            self.lbl_label.setProperty("class", "DetailFieldKey")
            self.lbl_status = QLabel(status)
            self.lbl_status.setProperty("class", "StatusLineValue")
            self.lbl_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self._action_widget = None
            layout.addWidget(self.lbl_label)
            layout.addWidget(self.lbl_status, 1)

        def set_status(self, status: str, state: str = "muted") -> None:
            self.lbl_status.setText(status)
            self.lbl_status.setProperty("variant", state)
            self.lbl_status.style().unpolish(self.lbl_status)
            self.lbl_status.style().polish(self.lbl_status)

        def set_action(self, button: QPushButton | None) -> None:
            if button is self._action_widget:
                if button is not None:
                    button.show()
                return
            self.clear_action()
            if button is not None:
                self._action_widget = button
                button.setParent(self)
                button.show()
                self.layout().addWidget(button)

        def replace_action(self, button: QPushButton | None) -> None:
            self.set_action(button)

        def clear_action(self) -> None:
            if self._action_widget is None:
                return
            self.layout().removeWidget(self._action_widget)
            self._action_widget.hide()
            self._action_widget.setParent(self)
            self._action_widget = None

    class ChecklistRow(QFrame):
        """Single preflight checklist row: icon + label + value.

        Used on the export page to show the status of each prerequisite
        (e.g. approved invoices, missing attachments, export directory).

        Parameters
        ----------
        label:
            Human-readable requirement description, e.g. ``"已通过发票"``.
        value:
            Initial display value, e.g. ``"—"``.
        ok:
            ``True`` → green check, ``False`` → red warning, ``None`` → neutral.
        """

        def __init__(
            self,
            label: str,
            value: str = "—",
            ok: bool | None = None,
            parent: QWidget | None = None,
        ):
            super().__init__(parent)
            self.setProperty("class", "ChecklistRow")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(8, 5, 8, 5)
            layout.setSpacing(8)

            self.lbl_icon = QLabel("·")
            self.lbl_icon.setFixedWidth(16)
            self.lbl_icon.setAlignment(Qt.AlignCenter)
            self.lbl_icon.setProperty("class", "ChecklistIcon")

            self.lbl_label = QLabel(label)
            self.lbl_label.setProperty("class", "ChecklistLabel")
            self.lbl_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            self.lbl_value = QLabel(value)
            self.lbl_value.setProperty("class", "ChecklistValue")
            self.lbl_value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.lbl_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            layout.addWidget(self.lbl_icon)
            layout.addWidget(self.lbl_label)
            layout.addWidget(self.lbl_value, 1)

            self.set_value(value, ok)

        def set_value(self, value: str, ok: bool | None = None) -> None:
            """Update the displayed value and status icon."""
            self.lbl_value.setText(str(value))
            if ok is True:
                self.lbl_icon.setText("✓")
                self.lbl_icon.setStyleSheet("color: #12b76a; font-weight: bold;")
                self.lbl_value.setStyleSheet("color: #12b76a;")
            elif ok is False:
                self.lbl_icon.setText("✗")
                self.lbl_icon.setStyleSheet("color: #f04438; font-weight: bold;")
                self.lbl_value.setStyleSheet("color: #f04438;")
            else:
                self.lbl_icon.setText("·")
                self.lbl_icon.setStyleSheet("color: #98a2b3;")
                self.lbl_value.setStyleSheet("color: #667085;")

    class SelectableSourceCard(QFrame):
        """Selectable import source card without page-specific styling logic."""

        clicked = Signal(str)

        def __init__(self, key: str, title: str, description: str, parent=None):
            super().__init__(parent)
            self.key = key
            self.setObjectName("SelectableSourceCard")
            self.setProperty("selected", False)
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.StrongFocus)
            self.setAccessibleName(title)
            self.setAccessibleDescription(description)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(3)
            self.lbl_title = QLabel(title, self)
            self.lbl_title.setProperty("class", "SourceCardTitle")
            self.lbl_description = QLabel(description, self)
            self.lbl_description.setProperty("class", "SourceCardDescription")
            self.lbl_description.setWordWrap(True)
            layout.addWidget(self.lbl_title)
            layout.addWidget(self.lbl_description)

        def set_selected(self, selected: bool) -> None:
            self.setProperty("selected", bool(selected))
            self.style().unpolish(self)
            self.style().polish(self)

        def mousePressEvent(self, event) -> None:
            if event.button() == Qt.LeftButton:
                self.clicked.emit(self.key)
            super().mousePressEvent(event)

        def keyPressEvent(self, event) -> None:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.clicked.emit(self.key)
                event.accept()
                return
            super().keyPressEvent(event)

    class CompactFieldRow(QFrame):
        """One compact read-only label/value/action row for settings surfaces."""

        def __init__(self, label: str, value: str = "—", action: QWidget | None = None, parent=None):
            super().__init__(parent)
            self.setObjectName("CompactFieldRow")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 6, 0, 6)
            layout.setSpacing(12)
            self.lbl_label = QLabel(label, self)
            self.lbl_label.setProperty("class", "DetailFieldKey")
            self.lbl_label.setMinimumWidth(92)
            self.lbl_value = ElidedValueLabel(value, self)
            layout.addWidget(self.lbl_label)
            layout.addWidget(self.lbl_value, 1)
            if action is not None:
                action.setParent(self)
                layout.addWidget(action)

        def set_value(self, value: str) -> None:
            self.lbl_value.set_value(value)

    class ActivityTimeline(QFrame):
        """Product-facing activity list; entries are summaries, never raw logs."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("ActivityTimeline")
            self._layout = QVBoxLayout(self)
            self._layout.setContentsMargins(0, 0, 0, 0)
            self._layout.setSpacing(0)

        def clear(self) -> None:
            while self._layout.count():
                item = self._layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        def add_entry(self, when: str, title: str, summary: str, state: str = "muted") -> QWidget:
            row = QFrame(self)
            row.setProperty("class", "ActivityTimelineRow")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 8, 0, 8)
            layout.setSpacing(12)
            lbl_when = QLabel(when, row)
            lbl_when.setProperty("class", "ActivityTimelineWhen")
            lbl_when.setMinimumWidth(72)
            lbl_title = QLabel(title, row)
            lbl_title.setProperty("class", "ActivityTimelineTitle")
            lbl_summary = QLabel(summary, row)
            lbl_summary.setProperty("class", "ActivityTimelineSummary")
            lbl_summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(lbl_when)
            layout.addWidget(lbl_title, 1)
            layout.addWidget(lbl_summary, 1)
            self._layout.addWidget(row)
            return row

    class DangerZone(QFrame):
        """Explicitly separated container for destructive settings actions."""

        def __init__(self, title: str = "危险操作", hint: str = "这些操作可能影响本地数据。", parent=None):
            super().__init__(parent)
            self.setObjectName("DangerZone")
            self.body_layout = QVBoxLayout(self)
            self.body_layout.setContentsMargins(12, 10, 12, 10)
            self.body_layout.setSpacing(8)
            self.lbl_title = QLabel(title, self)
            self.lbl_title.setProperty("class", "SectionTitle")
            self.lbl_hint = QLabel(hint, self)
            self.lbl_hint.setProperty("class", "SectionHint")
            self.lbl_hint.setWordWrap(True)
            self.body_layout.addWidget(self.lbl_title)
            self.body_layout.addWidget(self.lbl_hint)

    class EmptyStateCard(QFrame):
        """Consistent empty state with one optional next action."""

        def __init__(self, title: str, description: str = "", action: QPushButton | None = None, parent=None):
            super().__init__(parent)
            self.setObjectName("EmptyStateCard")
            layout = QVBoxLayout(self)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(8)
            self.lbl_icon = QLabel("○")
            self.lbl_icon.setObjectName("EmptyStateIcon")
            self.lbl_icon.setAlignment(Qt.AlignCenter)
            self.lbl_title = QLabel(title)
            self.lbl_title.setObjectName("EmptyStateTitle")
            self.lbl_title.setAlignment(Qt.AlignCenter)
            self.lbl_description = QLabel(description)
            self.lbl_description.setObjectName("EmptyStateDescription")
            self.lbl_description.setWordWrap(True)
            self.lbl_description.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.lbl_icon)
            layout.addWidget(self.lbl_title)
            layout.addWidget(self.lbl_description)
            if action is not None:
                layout.addWidget(action, 0, Qt.AlignCenter)

        def set_content(self, title, description="", icon=None):
            self.lbl_title.setText(title)
            self.lbl_description.setText(description)
            self.lbl_description.setVisible(bool(description))
            self.lbl_icon.setText(str(icon) if icon else "")
            self.lbl_icon.setVisible(bool(icon))

        def set_action(self, button=None):
            if hasattr(self, "_action") and self._action is not None:
                self._action.hide()
                self._action.setParent(self)
            self._action = button
            if button is not None:
                button.setParent(self)
                self.layout().addWidget(button, 0, Qt.AlignCenter)
                button.show()

    class LoadingCard(QFrame):
        """Consistent in-page loading state without technical log copy."""

        def __init__(self, text: str = "正在加载…", parent=None):
            super().__init__(parent)
            self.setObjectName("LoadingCard")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(14, 12, 14, 12)
            self.lbl_text = QLabel(text)
            self.lbl_text.setAlignment(Qt.AlignCenter)
            layout.addStretch(1)
            layout.addWidget(self.lbl_text)
            layout.addStretch(1)

        def set_text(self, text): self.lbl_text.setText(text)
        def start(self): self.show()
        def stop(self): self.hide()

    class InlineErrorCard(QFrame):
        """Consistent inline error with retry and optional secondary action."""

        def __init__(self, text: str = "暂时无法加载", retry: QPushButton | None = None, parent=None):
            super().__init__(parent)
            self.setObjectName("InlineErrorCard")
            layout = QHBoxLayout(self)
            layout.setContentsMargins(10, 8, 10, 8)
            self.lbl_text = QLabel(text)
            self.lbl_text.setWordWrap(True)
            layout.addWidget(self.lbl_text, 1)
            if retry is not None:
                layout.addWidget(retry)

        def set_error(self, text): self.lbl_text.setText(text)
        def set_retry_action(self, button=None):
            if hasattr(self, "_retry") and self._retry is not None:
                self.layout().removeWidget(self._retry)
                self._retry.hide()
                self._retry.setParent(self)
            self._retry = button
            if button is not None:
                button.setParent(self)
                self.layout().addWidget(button)
                button.show()
        def clear(self): self.set_error(""); self.set_retry_action(None)

    class PageStateStack(QFrame):
        """Keep content, empty, loading, and error mutually exclusive."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("PageStateStack")
            self.stack = QStackedWidget(self)
            self.content = QWidget()
            self.empty = EmptyStateCard("暂无内容")
            self.loading = LoadingCard()
            self.error = InlineErrorCard()
            for widget in (self.content, self.empty, self.loading, self.error):
                self.stack.addWidget(widget)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.stack)

        def set_content(self, widget: QWidget):
            old_layout = self.content.layout()
            if old_layout is not None:
                while old_layout.count():
                    item = old_layout.takeAt(0)
                    child = item.widget()
                    if child is not None:
                        child.setParent(None)
            layout = QVBoxLayout(self.content)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(widget)
            self.show_content()

        def show_content(self): self.stack.setCurrentWidget(self.content)
        def set_empty_object_name(self, object_name: str):
            self.empty.setObjectName(object_name)
        def show_empty(self, title, description="", action=None, icon=None):
            self.empty.set_content(title, description, icon)
            self.empty.set_action(action)
            self.stack.setCurrentWidget(self.empty)
        def show_loading(self, text="正在加载…"):
            self.loading.set_text(text)
            self.loading.start()
            self.stack.setCurrentWidget(self.loading)
        def show_error(self, text, retry=None, details=None):
            self.error.set_error(text)
            self.error.set_retry_action(retry)
            self.stack.setCurrentWidget(self.error)

    class SectionCard(QFrame):
        """Simple titled card for page sections."""

        def __init__(
            self,
            title: str = "",
            *,
            eyebrow: str = "",
            hint: str = "",
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self.setProperty("class", "WorkbenchCard")
            self.setObjectName("SectionCard")
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

            self._layout = QVBoxLayout(self)
            self._layout.setContentsMargins(14, 12, 14, 12)
            self._layout.setSpacing(10)

            self.lbl_eyebrow = QLabel(eyebrow, self)
            self.lbl_eyebrow.setProperty("class", "SectionEyebrow")
            self.lbl_eyebrow.setVisible(bool(eyebrow))
            self._layout.addWidget(self.lbl_eyebrow)

            self.lbl_title = QLabel(title, self)
            self.lbl_title.setProperty("class", "SectionTitle")
            self.lbl_title.setVisible(bool(title))
            self._layout.addWidget(self.lbl_title)

            self.lbl_hint = QLabel(hint, self)
            self.lbl_hint.setProperty("class", "SectionHint")
            self.lbl_hint.setWordWrap(True)
            self.lbl_hint.setVisible(bool(hint))
            self._layout.addWidget(self.lbl_hint)

            self.body = QWidget(self)
            self.body_layout = QVBoxLayout(self.body)
            self.body_layout.setContentsMargins(0, 0, 0, 0)
            self.body_layout.setSpacing(8)
            self._layout.addWidget(self.body)

        def set_title(self, title: str) -> None:
            self.lbl_title.setText(title)
            self.lbl_title.setVisible(bool(title))

        def set_hint(self, hint: str) -> None:
            self.lbl_hint.setText(hint)
            self.lbl_hint.setVisible(bool(hint))

    class PageHeader(QFrame):
        """Shared page title row with optional title and hint."""

        def __init__(self, title: str, hint: str = "", parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("PageHeader")
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)

            self.lbl_title = QLabel(title, self)
            self.lbl_title.setProperty("class", "PageTitle")
            layout.addWidget(self.lbl_title)

            self.lbl_hint = QLabel(hint, self)
            self.lbl_hint.setProperty("class", "PageHint")
            self.lbl_hint.setWordWrap(True)
            self.lbl_hint.setVisible(bool(hint))
            layout.addWidget(self.lbl_hint)

    class CommandBar(QFrame):
        """Horizontal action bar wrapper used inside workbench pages."""

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setProperty("class", "WorkbenchCard")
            self.setObjectName("CommandBar")
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.layout = QHBoxLayout(self)
            self.layout.setContentsMargins(12, 10, 12, 10)
            self.layout.setSpacing(8)
            self.primary_action = None
            self.secondary_actions: list[QWidget] = []
            self.more_menu = None

        def set_actions(
            self,
            primary_action: QWidget | None = None,
            secondary_actions: list[QWidget] | None = None,
            more_menu: QWidget | None = None,
        ) -> None:
            self.primary_action = primary_action
            self.secondary_actions = list(secondary_actions or [])
            self.more_menu = more_menu

            while self.layout.count():
                item = self.layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)

            if self.primary_action is not None:
                self.layout.addWidget(self.primary_action)
            for action in self.secondary_actions:
                self.layout.addWidget(action)
            self.layout.addStretch(1)
            if self.more_menu is not None:
                self.layout.addWidget(self.more_menu)

    class EntityList(QListWidget):
        """Styled list surface for accounts, groups, and queue items."""

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("EntityList")
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.setAlternatingRowColors(True)

        def add_entity_row(
            self,
            title: str,
            subtitle: str = "",
            status_badge: str = "",
            meta: str = "",
            user_data=None,
        ) -> QListWidgetItem:
            item = QListWidgetItem(self)
            item.setData(Qt.UserRole, user_data)
            row = QWidget(self)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(8)

            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(2)

            lbl_title = QLabel(title, row)
            lbl_title.setProperty("class", "EntityListTitle")
            lbl_title.setWordWrap(True)
            text_col.addWidget(lbl_title)

            if subtitle:
                lbl_subtitle = QLabel(subtitle, row)
                lbl_subtitle.setProperty("class", "EntityListSubtitle")
                lbl_subtitle.setWordWrap(True)
                text_col.addWidget(lbl_subtitle)

            layout.addLayout(text_col, 1)

            if meta:
                lbl_meta = QLabel(meta, row)
                lbl_meta.setProperty("class", "EntityListMeta")
                lbl_meta.setWordWrap(True)
                lbl_meta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                layout.addWidget(lbl_meta, 0, Qt.AlignRight | Qt.AlignVCenter)

            if status_badge:
                badge = make_badge(status_badge)
                layout.addWidget(badge, 0, Qt.AlignRight | Qt.AlignVCenter)

            item.setSizeHint(row.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, row)
            return item

    class ReadOnlyDetailPanel(SectionCard):
        """SectionCard variant for stacked read-only details."""

        def __init__(self, title: str = "", hint: str = "", parent: QWidget | None = None) -> None:
            super().__init__(title=title, hint=hint, parent=parent)
            self.setObjectName("ReadOnlyDetailPanel")
            self.rows_layout = QFormLayout()
            self.rows_layout.setContentsMargins(0, 0, 0, 0)
            self.rows_layout.setSpacing(8)
            self.body_layout.addLayout(self.rows_layout)

        def add_row(self, key: str, value: str | QWidget) -> QWidget:
            if isinstance(value, QWidget):
                widget = value
            else:
                widget = QLabel(str(value))
                widget.setWordWrap(True)
                widget.setProperty("class", "DetailValue")
            self.rows_layout.addRow(key, widget)
            return widget

    class MoreMenuButton(QToolButton):
        """Small 34x34 menu trigger reused across pages."""

        def __init__(self, text: str = "⋯", parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("WorkbenchTopIconButton")
            self.setText(text)
            self.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self.setPopupMode(QToolButton.InstantPopup)
            self.setFixedSize(34, 34)

    class LogDrawer(QFrame):
        """Simple host surface for the collapsible bottom log drawer."""

        def __init__(self, title: str = "运行日志", parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setProperty("class", "WorkbenchCard")
            self.setObjectName("LogDrawer")
            layout = QVBoxLayout(self)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(6)
            self.lbl_title = QLabel(title, self)
            self.lbl_title.setProperty("class", "SectionTitle")
            layout.addWidget(self.lbl_title)
            self.host = QWidget(self)
            self.host_layout = QVBoxLayout(self.host)
            self.host_layout.setContentsMargins(0, 0, 0, 0)
            self.host_layout.setSpacing(0)
            layout.addWidget(self.host)

    class SecondaryNavStack(QFrame):
        """Two-column secondary navigation with a compatibility tab-like API."""

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("SecondaryNavStack")
            self.setProperty("class", "WorkbenchCard")
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self.nav_list = QListWidget(self)
            self.nav_list.setObjectName("SecondaryNavList")
            self.nav_list.setFixedWidth(164)
            self.nav_list.currentRowChanged.connect(self._on_nav_changed)
            layout.addWidget(self.nav_list, 0)

            self.stack = QStackedWidget(self)
            layout.addWidget(self.stack, 1)

        def addTab(self, widget: QWidget, label: str) -> None:  # noqa: N802
            self.stack.addWidget(widget)
            self.nav_list.addItem(QListWidgetItem(label))
            if self.stack.count() == 1:
                self.nav_list.setCurrentRow(0)

        def setCurrentIndex(self, index: int) -> None:  # noqa: N802
            if 0 <= index < self.stack.count():
                self.nav_list.setCurrentRow(index)

        def currentIndex(self) -> int:  # noqa: N802
            return self.stack.currentIndex()

        def currentWidget(self) -> QWidget | None:  # noqa: N802
            return self.stack.currentWidget()

        def count(self) -> int:
            return self.stack.count()

        def tabText(self, index: int) -> str:  # noqa: N802
            item = self.nav_list.item(index)
            return item.text() if item is not None else ""

        def widget(self, index: int) -> QWidget | None:
            return self.stack.widget(index)

        def _on_nav_changed(self, row: int) -> None:
            if 0 <= row < self.stack.count() and self.stack.currentIndex() != row:
                self.stack.setCurrentIndex(row)

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
            icon_text: str = "",
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self.setObjectName("CompactStatCard")
            self.setProperty("state", state)
            self.setProperty("selected", False)
            self.setCursor(Qt.PointingHandCursor)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 6, 12, 6)
            layout.setSpacing(6)

            self._lbl_icon = QLabel(icon_text, self)
            self._lbl_icon.setProperty("class", "CompactStatCardIcon")
            self._lbl_icon.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self._lbl_icon.setVisible(bool(icon_text))

            self._lbl_title = QLabel(title, self)
            self._lbl_title.setProperty("class", "CompactStatCardTitle")
            self._lbl_title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

            self._lbl_value = QLabel(value, self)
            self._lbl_value.setProperty("class", "CompactStatCardValue")
            self._lbl_value.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

            layout.addWidget(self._lbl_icon)
            layout.addWidget(self._lbl_title)
            layout.addStretch(1)
            layout.addWidget(self._lbl_value)
            self.setFixedHeight(40)
            self.setMinimumWidth(124)

            # Store raw value for programmatic access
            self._value = value
            self._icon_text = icon_text

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

        def icon_text(self) -> str:
            """Return the current decorative icon string."""
            return self._icon_text

        def set_title(self, title: str) -> None:
            self._lbl_title.setText(title)

        def text(self) -> str:
            """Return the title followed by the value for compatibility."""
            return f"{self._lbl_title.text()} {self.value()}"

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

        def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.clicked.emit()
                event.accept()
                return
            super().keyPressEvent(event)

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
            layout = QVBoxLayout(self)
            layout.setContentsMargins(10, 8, 10, 8)
            layout.setSpacing(5)
            self._rows: list[QWidget] = []
            for key, label in CORE_SHORTCUTS + SECONDARY_SHORTCUTS:
                row = QWidget(self)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(8)
                key_label = QLabel(key)
                key_label.setProperty("class", "ShortcutKey")
                action_label = QLabel(label)
                action_label.setProperty("class", "ShortcutAction")
                row_layout.addWidget(key_label)
                row_layout.addStretch(1)
                row_layout.addWidget(action_label)
                layout.addWidget(row)
                self._rows.append(row)
            self._apply_row_visibility()

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
            self._apply_row_visibility()
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

        def _apply_row_visibility(self) -> None:
            core_count = len(CORE_SHORTCUTS)
            for index, row in enumerate(self._rows):
                row.setVisible(index < core_count or self._expanded)

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
