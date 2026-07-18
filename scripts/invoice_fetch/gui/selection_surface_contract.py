"""Shared selection/focus contract for list-based desktop surfaces.

Qt's native item-view delegate may paint a platform focus rectangle even when
QSS already provides a product selection state. With transparent custom row
widgets this appears as a dark box around the selected item on Windows. This
module keeps keyboard navigation intact while replacing that native rectangle
with Design v1 selection surfaces.
"""

from __future__ import annotations

import weakref

from PySide6.QtCore import QSize, QTimer, Qt
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
QWidget#EntityListRow {{
    background-color: {colors['surface']};
    border: 1px solid transparent;
    border-radius: {metrics['radius_medium']}px;
}}
QWidget#EntityListRow:hover {{
    background-color: {colors['surface_secondary']};
    border-color: {colors['border_subtle']};
}}
QWidget#EntityListRow[selected="true"] {{
    background-color: {colors['selected']};
    border-color: {colors['accent_border']};
}}
QWidget#EntityListRow[selected="true"] QLabel[class="EntityListTitle"] {{
    color: {colors['accent_hover']};
}}
QWidget#EntityListRow[selected="true"] QLabel[class="EntityListSubtitle"],
QWidget#EntityListRow[selected="true"] QLabel[class="EntityListMeta"] {{
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


def _decorate_entity_rows(view: QListWidget) -> None:
    if not isValid(view):
        return
    current = view.currentItem()
    for index in range(view.count()):
        item = view.item(index)
        row = view.itemWidget(item)
        if row is None or not isValid(row):
            continue
        row.setObjectName("EntityListRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
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


def schedule_selection_surface_contracts(root: QWidget) -> None:
    """Apply after page construction and once more after deferred population."""
    root_ref = weakref.ref(root)

    def run() -> None:
        target = root_ref()
        if target is not None and isValid(target):
            install_selection_surface_contracts(target)

    QTimer.singleShot(0, run)
    QTimer.singleShot(120, run)


__all__ = [
    "SelectionSurfaceDelegate",
    "install_selection_surface_contracts",
    "schedule_selection_surface_contracts",
]
