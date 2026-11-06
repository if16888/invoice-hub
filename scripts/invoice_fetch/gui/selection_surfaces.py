"""Selection surface styling and interaction behavior."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)
from shiboken6 import isValid

from .design_tokens import DESIGN_V1_COLORS, DESIGN_V1_METRICS

NAV_GROUP_ROLE = int(Qt.UserRole) + 67
INVOICE_ROW_ROLE = int(Qt.UserRole) + 68


def _paint_color(role: str) -> QColor:
    from .dark_mode import DARK_COLOR_MAP, prefers_dark

    value = DESIGN_V1_COLORS[role]
    return QColor(DARK_COLOR_MAP.get(value.upper(), value) if prefers_dark() else value)


class SelectionSurfaceDelegate(QStyledItemDelegate):
    """Preserve selection painting and draw an explicit keyboard focus ring."""

    @staticmethod
    def normalized_option(option: QStyleOptionViewItem) -> QStyleOptionViewItem:
        normalized = QStyleOptionViewItem(option)
        normalized.state &= ~QStyle.StateFlag.State_HasFocus
        return normalized

    def paint(self, painter, option, index) -> None:  # noqa: N802
        option = QStyleOptionViewItem(option)
        group = index.data(NAV_GROUP_ROLE)
        header = None
        if group:
            header = option.rect.adjusted(10, 0, -4, 0)
            header.setHeight(24)
            option.rect.adjust(0, 24, 0, 0)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        super().paint(painter, self.normalized_option(option), index)
        if header is not None:
            from .dark_mode import dark_stylesheet, prefers_dark

            painter.save()
            color = DESIGN_V1_COLORS["muted"]
            painter.setPen(QColor(dark_stylesheet(color) if prefers_dark() else color))
            font = painter.font()
            font.setPixelSize(12)
            font.setBold(False)
            painter.setFont(font)
            painter.drawText(header, Qt.AlignLeft | Qt.AlignVCenter, str(group))
            painter.restore()
        if not focused:
            return
        self.paint_focus(painter, option)

    @staticmethod
    def paint_focus(painter, option) -> None:
        painter.save()
        pen = QPen(_paint_color("focus_ring"))
        pen.setWidth(DESIGN_V1_METRICS["focus_border_width"])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(
            option.rect.adjusted(1, 1, -1, -1),
            DESIGN_V1_METRICS["radius_small"],
            DESIGN_V1_METRICS["radius_small"],
        )
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        hint = super().sizeHint(option, index)
        if index.data(NAV_GROUP_ROLE):
            hint.setHeight(hint.height() + 24)
        return hint


class InvoiceListDelegate(SelectionSurfaceDelegate):
    """Draw structured invoice rows without allocating child widgets per file."""

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(0, 64) if index.data(INVOICE_ROW_ROLE) else super().sizeHint(option, index)

    def paint(self, painter, option, index) -> None:  # noqa: N802
        row = index.data(INVOICE_ROW_ROLE)
        if not row:
            super().paint(painter, option, index)
            return
        base = QStyleOptionViewItem(option)
        self.initStyleOption(base, index)
        base.text = ""
        style = option.widget.style()
        style.drawControl(QStyle.CE_ItemViewItem, self.normalized_option(base), painter, option.widget)
        area = option.rect.adjusted(12, 8, -12, -8)
        amount = str(row["amount"])
        amount_width = min(max(64, base.fontMetrics.horizontalAdvance(amount) + 8), max(64, area.width() // 3))
        title_rect = area.adjusted(0, 0, -amount_width - 12, 0)
        title_rect.setHeight(20)
        amount_rect = area.adjusted(area.width() - amount_width, 0, 0, 0)
        amount_rect.setHeight(20)
        painter.save()
        painter.setFont(base.font)
        painter.setPen(_paint_color("text"))
        title = base.fontMetrics.elidedText(str(row["title"]), Qt.ElideRight, max(0, title_rect.width()))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title)
        font = base.font
        font.setBold(True)
        painter.setFont(font)
        amount = painter.fontMetrics().elidedText(amount, Qt.ElideMiddle, max(0, amount_rect.width()))
        painter.drawText(amount_rect, Qt.AlignRight | Qt.AlignVCenter, amount)
        font.setBold(False)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(_paint_color("warning_text" if row.get("attention") else "muted"))
        subtitle_rect = area.adjusted(0, 24, 0, 0)
        subtitle = painter.fontMetrics().elidedText(str(row["subtitle"]), Qt.ElideRight, max(0, subtitle_rect.width()))
        painter.drawText(subtitle_rect, Qt.AlignLeft | Qt.AlignVCenter, subtitle)
        painter.restore()
        if option.state & QStyle.StateFlag.State_HasFocus:
            self.paint_focus(painter, option)


def _set_dynamic_property(widget: QWidget, name: str, value: bool) -> None:
    normalized = "true" if value else "false"
    if widget.property(name) == normalized:
        return
    widget.setProperty(name, normalized)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _entity_list_stylesheet() -> str:
    colors = DESIGN_V1_COLORS
    metrics = DESIGN_V1_METRICS
    return f"""
QListWidget#EntityList {{
    background-color: {colors['surface']};
    border: 1px solid {colors['border']};
    border-radius: {metrics['radius_large']}px;
    padding: 4px;
    outline: 0;
}}
QListWidget#EntityList::item {{
    background: transparent;
    border: none;
    padding: 0;
    margin: 2px 0;
    outline: 0;
}}
QListWidget#EntityList::item:selected,
QListWidget#EntityList::item:selected:active,
QListWidget#EntityList::item:selected:!active {{
    background: transparent;
    color: {colors['text']};
    border: none;
    outline: 0;
}}
QListWidget#EntityList[listRole="invoices"]::item:hover {{ background: {colors['surface_secondary']}; }}
QListWidget#EntityList[listRole="invoices"]::item:selected {{ background: {colors['selected']}; }}
QWidget[selectionSurfaceRow="true"] {{
    background-color: {colors['surface']};
    border: 1px solid transparent;
    border-radius: {metrics['radius_medium']}px;
}}
QWidget[selectionSurfaceRow="true"]:hover {{
    background-color: {colors['surface_secondary']};
    border-color: {colors['border_subtle']};
}}
QWidget[selectionSurfaceRow="true"][selected="true"] {{
    background-color: {colors['selected']};
    border-color: {colors['accent_border']};
}}
QWidget[selectionSurfaceRow="true"][selected="true"] QLabel[class="EntityListTitle"] {{
    color: {colors['accent_hover']};
}}
QWidget[selectionSurfaceRow="true"][selected="true"] QLabel[class="EntityListSubtitle"],
QWidget[selectionSurfaceRow="true"][selected="true"] QLabel[class="EntityListMeta"] {{
    color: {colors['text_secondary']};
}}
"""


def _secondary_nav_stylesheet() -> str:
    colors = DESIGN_V1_COLORS
    metrics = DESIGN_V1_METRICS
    return f"""
QListWidget#SecondaryNavList {{
    outline: 0;
}}
QListWidget#SecondaryNavList::item {{
    border: 1px solid transparent;
    border-radius: {metrics['radius_medium']}px;
    outline: 0;
}}
QListWidget#SecondaryNavList::item:selected,
QListWidget#SecondaryNavList::item:selected:active,
QListWidget#SecondaryNavList::item:selected:!active {{
    background-color: {colors['selected']};
    border-color: {colors['accent_border']};
    color: {colors['accent_hover']};
    outline: 0;
}}
"""


def _filter_value_stylesheet() -> str:
    colors = DESIGN_V1_COLORS
    metrics = DESIGN_V1_METRICS
    return f"""
QListWidget#FilterValueList {{
    background-color: {colors['surface']};
    border: 1px solid {colors['border']};
    border-radius: {metrics['radius_medium']}px;
    padding: 4px;
    outline: 0;
}}
QListWidget#FilterValueList::item {{
    min-height: 28px;
    padding: 4px 8px;
    border: 1px solid transparent;
    border-radius: {metrics['radius_small']}px;
    outline: 0;
}}
QListWidget#FilterValueList::item:hover {{
    background-color: {colors['surface_secondary']};
    border-color: {colors['border_subtle']};
}}
QListWidget#FilterValueList::item:selected,
QListWidget#FilterValueList::item:selected:active,
QListWidget#FilterValueList::item:selected:!active {{
    background-color: {colors['selected']};
    border-color: {colors['accent_border']};
    color: {colors['text']};
    outline: 0;
}}
"""


class _EntityRowMouseBridge(QObject):
    """Route clicks on row children back through QListWidget selection."""

    def __init__(self, view: QListWidget) -> None:
        super().__init__(view)
        self._view_ref = weakref.ref(view)
        self._watched: weakref.WeakSet[QWidget] = weakref.WeakSet()

    def attach_row(self, row: QWidget) -> None:
        widgets = [row]
        widgets.extend(row.findChildren(QWidget))
        for widget in widgets:
            if widget in self._watched or not isValid(widget):
                continue
            self._watched.add(widget)
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            view = self._view_ref()
            if view is not None and isValid(view) and isinstance(watched, QWidget):
                point = watched.mapTo(view.viewport(), event.position().toPoint())
                item = view.itemAt(point)
                if item is not None:
                    view.setCurrentItem(item)
                    view.setFocus(Qt.MouseFocusReason)
                    # Keep the original child event alive so labels can
                    # still support text selection and future row actions.
                    return False
        return super().eventFilter(watched, event)


def _decorate_entity_rows(view: QListWidget) -> None:
    if not isValid(view):
        return
    current = view.currentItem()
    for index in range(view.count()):
        item = view.item(index)
        row = view.itemWidget(item)
        if row is None or not isValid(row):
            continue
        # Do not overwrite semantic object names such as MailboxAccountRow.
        # The reusable selection surface is identified by a dynamic property.
        _set_dynamic_property(row, "selectionSurfaceRow", True)
        row.setAttribute(Qt.WA_StyledBackground, True)
        bridge = getattr(view, "_entity_row_mouse_bridge", None)
        if bridge is None or not isValid(bridge):
            bridge = _EntityRowMouseBridge(view)
            view._entity_row_mouse_bridge = bridge
        bridge.attach_row(row)
        row.setFocusPolicy(Qt.NoFocus)
        row.setMinimumHeight(68)
        layout = row.layout()
        if layout is not None:
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(8)
        row.ensurePolished()
        height = max(68, row.sizeHint().height() + 4)
        if item.sizeHint().height() != height:
            item.setSizeHint(QSize(0, height))
        _set_dynamic_property(row, "selected", item.isSelected() or item is current)


def _schedule_entity_sync(view: QListWidget) -> None:
    if view is None or not isValid(view):
        return
    if view.property("entitySyncPending"):
        return
    view.setProperty("entitySyncPending", True)
    view_ref = weakref.ref(view)

    def run() -> None:
        target = view_ref()
        if target is not None and isValid(target):
            target.setProperty("entitySyncPending", False)
            _decorate_entity_rows(target)

    QTimer.singleShot(0, run)


def _install_entity_list(view: QListWidget) -> None:
    if view.property("selectionSurfaceContract") == "entity":
        _schedule_entity_sync(view)
        return
    view.setProperty("selectionSurfaceContract", "entity")
    view.setAlternatingRowColors(False)
    view.setSelectionMode(QAbstractItemView.SingleSelection)
    view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    delegate = InvoiceListDelegate if view.property("listRole") == "invoices" else SelectionSurfaceDelegate
    view.setItemDelegate(delegate(view))
    view.setStyleSheet(view.styleSheet() + _entity_list_stylesheet())
    view.currentItemChanged.connect(lambda *_args, target=view: _schedule_entity_sync(target))
    view.itemSelectionChanged.connect(lambda target=view: _schedule_entity_sync(target))
    model = view.model()
    model.rowsInserted.connect(lambda *_args, target=view: _schedule_entity_sync(target))
    model.modelReset.connect(lambda target=view: _schedule_entity_sync(target))
    _schedule_entity_sync(view)


def _install_secondary_nav(view: QListWidget) -> None:
    if view.property("selectionSurfaceContract") == "secondary-nav":
        return
    view.setProperty("selectionSurfaceContract", "secondary-nav")
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    view.setItemDelegate(SelectionSurfaceDelegate(view))
    view.setStyleSheet(view.styleSheet() + _secondary_nav_stylesheet())


def _install_filter_values(view: QListWidget) -> None:
    if view.property("selectionSurfaceContract") == "filter-values":
        return
    view.setProperty("selectionSurfaceContract", "filter-values")
    view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    view.setItemDelegate(SelectionSurfaceDelegate(view))
    view.setStyleSheet(view.styleSheet() + _filter_value_stylesheet())


def install_selection_surface_contracts(root: QWidget) -> None:
    """Install deterministic selection styling on list views below *root*."""
    if root is None or not isValid(root):
        return
    views = [root] if isinstance(root, QListWidget) else []
    views.extend(root.findChildren(QListWidget))
    for view in views:
        if not isValid(view):
            continue
        object_name = view.objectName()
        has_custom_rows = any(view.itemWidget(view.item(i)) is not None for i in range(view.count()))
        if object_name == "EntityList" or has_custom_rows:
            _install_entity_list(view)
        elif object_name == "SecondaryNavList":
            _install_secondary_nav(view)
        elif object_name == "FilterValueList":
            _install_filter_values(view)


def _ancestor_list(widget: QWidget | None) -> QListWidget | None:
    parent = widget.parentWidget() if widget is not None else None
    while parent is not None:
        if isinstance(parent, QListWidget):
            return parent
        parent = parent.parentWidget()
    return None


class _SelectionSurfaceWatcher(QObject):
    """Observe deferred widget construction without adding page-layout timers."""

    def __init__(self, root: QWidget) -> None:
        super().__init__(root)
        self._watched: set[int] = set()
        self.watch_tree(root)

    def watch_tree(self, root: QWidget) -> None:
        if root is None or not isValid(root):
            return
        widgets = [root]
        widgets.extend(root.findChildren(QWidget))
        for widget in widgets:
            key = id(widget)
            if key in self._watched or not isValid(widget):
                continue
            self._watched.add(key)
            widget.installEventFilter(self)
            widget.objectNameChanged.connect(self._on_object_name_changed)
        install_selection_surface_contracts(root)

    def _on_object_name_changed(self, _name: str) -> None:
        widget = self.sender()
        if isinstance(widget, QWidget) and isValid(widget):
            install_selection_surface_contracts(widget)
            ancestor = _ancestor_list(widget)
            if ancestor is not None:
                install_selection_surface_contracts(ancestor)

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget) and isValid(child):
                self.watch_tree(child)
                ancestor = _ancestor_list(child)
                if ancestor is not None:
                    install_selection_surface_contracts(ancestor)
        return super().eventFilter(watched, event)


def schedule_selection_surface_contracts(root: QWidget) -> None:
    """Install now and watch later child construction without timer coupling."""
    if root is None or not isValid(root):
        return
    watcher = getattr(root, "_selection_surface_watcher", None)
    if watcher is None or not isValid(watcher):
        watcher = _SelectionSurfaceWatcher(root)
        root._selection_surface_watcher = watcher
    else:
        watcher.watch_tree(root)


__all__ = [
    "SelectionSurfaceDelegate",
    "install_selection_surface_contracts",
    "schedule_selection_surface_contracts",
]
