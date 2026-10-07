"""Explicit review of weak matches; resolving a candidate never deletes an invoice."""
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QAbstractItemView,
)


class DuplicateReviewDialog(QDialog):
    def __init__(self, db, parent, open_invoice, allowed):
        super().__init__(parent)
        self.db, self.open_invoice, self.allowed = db, open_invoice, allowed
        self.setWindowTitle('无票号疑似重复复核')
        self.resize(780, 440)
        layout = QVBoxLayout(self)
        hint = QLabel('销售方、费用日期、金额及币种相同，仅表示疑似重复。请查看两张原件后确认。'
                      '确认重复仅作标记；可回到审核页将该票忽略，或在此重置复核结论。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.filter = QComboBox()
        for label, decision in [('待复核', 'pending'), ('已确认不同票据', 'distinct'), ('已确认重复', 'duplicate')]:
            self.filter.addItem(label, decision)
        self.filter.currentIndexChanged.connect(self._reload)
        layout.addWidget(self.filter)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['当前记录', '对照记录', '销售方', '费用日期', '金额'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        self.resolve_buttons = []
        self.reset_button = None
        for label, callback in [('查看当前原件', lambda: self._open('invoice_id')),
                                ('查看对照原件', lambda: self._open('reference_id')),
                                ('确认不同票据', lambda: self._resolve('distinct')),
                                ('确认重复', lambda: self._resolve('duplicate')),
                                ('重置复核结论', self._reset)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            if label in {'确认不同票据', '确认重复'}:
                self.resolve_buttons.append(button)
            if label == '重置复核结论':
                self.reset_button = button
            actions.addWidget(button)
        layout.addLayout(actions)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self._reload()

    def _reload(self):
        self.candidates = self.db.list_duplicate_candidates(self.filter.currentData())
        self.table.setRowCount(len(self.candidates))
        for index, row in enumerate(self.candidates):
            values = [row['invoice_id'], row['reference_id'], row.get('seller_name') or '',
                      row.get('expense_date') or row.get('invoice_date') or '',
                      str(row.get('total_amount') or '') + ' ' + str(row.get('currency') or '')]
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        for button in self.resolve_buttons:
            button.setEnabled(bool(self.candidates) and self.filter.currentData() == 'pending')
        self.reset_button.setEnabled(bool(self.candidates) and self.filter.currentData() != 'pending')
        if self.candidates:
            self.table.selectRow(0)
        else:
            self.result_label.setText('当前分类没有无票号疑似重复记录。')

    def _selected(self):
        row = self.table.currentRow()
        return self.candidates[row] if 0 <= row < len(self.candidates) else None

    def _open(self, key):
        candidate = self._selected()
        if candidate:
            self.open_invoice(candidate[key])

    def _resolve(self, decision):
        candidate = self._selected()
        if not candidate or not self.allowed():
            return
        if not self.db.resolve_duplicate_candidate(candidate['id'], decision):
            self.result_label.setText('票据已变更，已刷新复核队列，请重新核对。')
            self._reload()
            return
        self._reload()
        self.result_label.setText('已确认不同票据，保留两张记录。' if decision == 'distinct'
                                  else '已标记重复；记录和审核状态未改变，导出前请将重复票据忽略。')

    def _reset(self):
        candidate = self._selected()
        if candidate and self.allowed():
            if self.db.reset_duplicate_candidate(candidate['id']):
                self._reload()
                self.result_label.setText('已重置为待复核，记录与审核状态保持不变。')
