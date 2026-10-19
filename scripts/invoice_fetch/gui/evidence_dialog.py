"""Explicit material sharing across the selected, immutable invoice IDs."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .helpers import resolve_stored_path


class EvidenceDialog(QDialog):
    def __init__(self, invoice_ids, sources, associations, runtime_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("证明材料共享")
        self.resize(720, 460)
        self.invoice_ids = tuple(invoice_ids)
        self._sources = tuple(dict(source) for source in sources)
        self._runtime_dir = Path(runtime_dir)
        self._existing = {int(source): set(parents) & set(self.invoice_ids)
                          for source, parents in associations.items()}
        self._initial = {}
        layout = QVBoxLayout(self)
        hint = QLabel(f"将材料关联给已选择的 {len(self.invoice_ids)} 张发票。勾选关联到全部，取消勾选解除这些发票的关联。\n"
                      "横杠表示只关联了部分；保持横杠可保留原关系。解绑保留材料文件，其他发票的关联保持不变。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("查找材料文件、来源或邮件主题")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.table = QTableWidget(len(self._sources), 5)
        self.table.setHorizontalHeaderLabels(["关联", "材料文件", "来源 / 主题", "本次 / 全部引用", "状态"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for column in (0, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for row, source in enumerate(self._sources):
            source_id = int(source["id"])
            linked = self._existing.get(source_id, set())
            state = (Qt.Checked if len(linked) == len(self.invoice_ids) else
                     Qt.PartiallyChecked if linked else Qt.Unchecked)
            self._initial[source_id] = state
            item = QTableWidgetItem()
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(state)
            item.setData(Qt.UserRole, source_id)
            if source.get("is_deleted") and not linked:
                item.setFlags(Qt.NoItemFlags)
            self.table.setItem(row, 0, item)
            raw_path = str(source.get("attachment_path") or "")
            path = resolve_stored_path(raw_path, runtime_dir)
            deleted = bool(source.get("is_deleted"))
            status = "已删除，仅可解绑" if deleted else "可复用" if path.is_file() else "文件缺失，导出将阻断"
            values = (path.name or "（无文件路径）", source.get("mail_subject") or source.get("mailbox_key") or "本地材料",
                      f"{len(linked)} / {source.get('linked_count', 0)}", status)
            for column, value in enumerate(values, 1):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(raw_path if column == 1 else cell.text())
                self.table.setItem(row, column, cell)
        layout.addWidget(self.table)
        self.empty_hint = QLabel("暂无可复用材料。请先用发票详情中的“添加 / 补充”导入证明文件。")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setVisible(not sources)
        layout.addWidget(self.empty_hint)
        self.summary = QLabel("未修改关联")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.preview = self.buttons.addButton("打开所选材料", QDialogButtonBox.ActionRole)
        self.preview.setEnabled(False)
        self.preview.clicked.connect(self._open_selected)
        self.table.itemSelectionChanged.connect(lambda: self.preview.setEnabled(self.table.currentRow() >= 0))
        self.table.itemDoubleClicked.connect(lambda item: self._open_selected() if item.column() else None)
        self.save = self.buttons.button(QDialogButtonBox.Save)
        self.save.setText("保存关联")
        self.save.setEnabled(False)
        self.buttons.button(QDialogButtonBox.Cancel).setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.table.itemChanged.connect(self._changed)

    def association_changes(self):
        additions, removals = [], []
        for row, source in enumerate(self._sources):
            source_id = int(source["id"])
            state = self.table.item(row, 0).checkState()
            if state == self._initial[source_id] or state == Qt.PartiallyChecked:
                continue
            existing = self._existing.get(source_id, set())
            if state == Qt.Checked and not source.get("is_deleted"):
                additions.extend((parent, source_id) for parent in self.invoice_ids if parent not in existing)
            elif state == Qt.Unchecked:
                removals.extend((parent, source_id) for parent in self.invoice_ids if parent in existing)
        return tuple(additions), tuple(removals)

    def source_snapshots(self):
        return {row["id"]: (str(row.get("attachment_path") or ""), str(row.get("file_hash") or ""))
                for row in self._sources}

    def _open_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._sources):
            return
        path = resolve_stored_path(self._sources[row].get("attachment_path") or "", self._runtime_dir)
        if not path.is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "无法打开材料", "材料文件不存在或没有可用的打开程序，请先补齐文件。")

    def _changed(self, item):
        if item.column() != 0:
            return
        source = self._sources[item.row()]
        if source.get("is_deleted") and item.checkState() == Qt.Checked and self._initial[source["id"]] != Qt.Checked:
            self.table.blockSignals(True)
            item.setCheckState(Qt.Unchecked)
            self.table.blockSignals(False)
        added, removed = self.association_changes()
        self.summary.setText(f"新增 {len(added)} 条关联，解除 {len(removed)} 条关联" if added or removed else "未修改关联")
        self.save.setEnabled(bool(added or removed))

    def _filter(self, text):
        needle = text.strip().casefold()
        for row in range(self.table.rowCount()):
            content = " ".join(self.table.item(row, column).text() for column in range(1, 5)).casefold()
            self.table.setRowHidden(row, needle not in content)
