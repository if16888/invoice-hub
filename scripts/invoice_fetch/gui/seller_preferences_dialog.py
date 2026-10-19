"""Manage local seller category memories without changing existing invoices."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class SellerPreferencesDialog(QDialog):
    def __init__(self, preferences: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("商户分类记忆")
        self.resize(640, 420)
        self._preferences = tuple(dict(row) for row in preferences)
        layout = QVBoxLayout(self)
        hint = QLabel("手动纠正分类时可记住销售方。删除记忆只影响以后的自动分类，已有发票保持不变。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(len(preferences), 3)
        self.table.setHorizontalHeaderLabels(["销售方", "记忆分类", "更新时间"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for index, row in enumerate(self._preferences):
            for column, key in enumerate(("seller_name", "preferred_category", "updated_at")):
                item = QTableWidgetItem(str(row[key]))
                item.setToolTip(item.text())
                item.setData(Qt.UserRole, row["seller_name"])
                self.table.setItem(index, column, item)
        layout.addWidget(self.table)
        self.empty_hint = QLabel("暂无分类记忆。编辑发票并纠正分类后，可在这里查看。")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setVisible(not preferences)
        layout.addWidget(self.empty_hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.forget_button = buttons.addButton("删除选中记忆", QDialogButtonBox.AcceptRole)
        self.forget_button.setEnabled(False)
        self.table.itemSelectionChanged.connect(
            lambda: self.forget_button.setEnabled(bool(self.selected_sellers()))
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_sellers(self) -> tuple[str, ...]:
        return tuple(self._preferences[index.row()]["seller_name"]
                     for index in sorted(self.table.selectionModel().selectedRows(), key=lambda value: value.row()))
