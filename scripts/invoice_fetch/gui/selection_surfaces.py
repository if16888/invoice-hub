"""Selection surface styling and interaction behavior."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, Qt
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


class SelectionSurfaceDelegate(QStyledItemDelegate):
    """Preserve selection painting but remove the native focus rectangle."""

    @staticmethod
    def normalized_option(option: QStyleOptionViewItem) -> QStyleOptionViewItem:
        normalized = QStyleOptionViewItem(option)
        normalized.state &= ~QStyle.StateFlag.State_HasFocus
        return normalized

    def paint(self, painter, option, index) -> None:  # noqa: N802
        super().paint(painter, self.normalized_option(option), index)


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
    view_ref = weakref.ref(view)

    def run() -> None:
        target = view_ref()
        if target is not None and isValid(target):
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
    view.setItemDelegate(SelectionSurfaceDelegate(view))
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
