# -*- coding: utf-8 -*-
"""ShortcutHelp Component - Footer Shortcut Disclosure."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from ..theme import Theme

CORE_SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Enter", "通过"),
    ("Del", "忽略"),
    ("Ctrl+E", "异常"),
)

SECONDARY_SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("↑ / ↓", "切换发票"),
    ("Ctrl+F", "搜索"),
    ("F11", "预览全屏"),
    ("Ctrl+I", "导入"),
    ("Ctrl+U", "扫码上传"),
    ("Ctrl+M", "邮箱同步"),
    ("Ctrl+R", "刷新"),
)


class ShortcutHelp(QFrame):
    """Collapsible shortcut-help disclosure panel."""

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

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
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
