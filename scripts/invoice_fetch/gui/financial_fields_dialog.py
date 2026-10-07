"""Financial editor preserving collected-empty versus unknown values."""
from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget,
)

from ..financial_validation import check_tax_balance, normalize_tax_rate
from ..tax_id_validation import TAX_ID_TYPES, check_tax_id


class FinancialFieldsDialog(QDialog):
    def __init__(self, invoice: dict, parent=None):
        super().__init__(parent)
        self.invoice = invoice
        self.setWindowTitle('当前发票财税字段')
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        hint = QLabel('以票面为准填写；未采集的数据保持未知。税率使用百分数，如 13%。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.fields, self.unknown = {}, {}
        for key, label in [('buyer_tax_id', '购买方税号'), ('amount', '税前金额'),
                           ('tax_amount', '税额'), ('tax_rate', '税率')]:
            field = QLineEdit(str(invoice.get(key) or ''))
            unknown = QCheckBox('未采集')
            unknown.setChecked(invoice.get(key) is None)
            field.setEnabled(not unknown.isChecked())
            unknown.toggled.connect(lambda checked, target=field: target.setEnabled(not checked))
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(field, 1)
            row_layout.addWidget(unknown)
            form.addRow(label, row)
            self.fields[key], self.unknown[key] = field, unknown
        self.tax_id_type = QComboBox()
        for key, label in TAX_ID_TYPES.items():
            self.tax_id_type.addItem(label, key)
        index = self.tax_id_type.findData(invoice.get('buyer_tax_id_type', 'unknown'))
        if index >= 0:
            self.tax_id_type.setCurrentIndex(index)
        else:
            self.tax_id_type.addItem('类型无效，请重新选择', invoice.get('buyer_tax_id_type'))
            self.tax_id_type.setCurrentIndex(self.tax_id_type.count() - 1)
        form.addRow('税号类型', self.tax_id_type)
        self.invoice_code = QLineEdit(str(invoice.get('invoice_code') or ''))
        form.addRow('发票代码', self.invoice_code)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        values = {key: None if self.unknown[key].isChecked() else field.text().strip()
                  for key, field in self.fields.items()}
        for key in ('amount', 'tax_amount'):
            if values[key]:
                try:
                    value = Decimal(values[key].replace(',', ''))
                    if (not value.is_finite() or abs(value.adjusted()) > 128
                            or len(value.as_tuple().digits) > 128):
                        raise ValueError('non-finite')
                except (ValueError, InvalidOperation):
                    raise ValueError('税前金额与税额必须是有限数值。') from None
                values[key] = format(value, 'f')
        values['tax_rate'] = normalize_tax_rate(values['tax_rate'])
        values['invoice_code'] = self.invoice_code.text().strip()
        values['buyer_tax_id_type'] = self.tax_id_type.currentData()
        return values

    def _save(self):
        try:
            values = self.values()
        except ValueError as exc:
            QMessageBox.warning(self, '字段校验', str(exc))
            return
        id_check = check_tax_id(values['buyer_tax_id'], values['buyer_tax_id_type'])
        if id_check.blocking:
            QMessageBox.warning(self, '税号待核对', id_check.message + '；已允许保存，导出前须修正。')
        balance = check_tax_balance({**self.invoice, **values})
        if balance.blocking:
            QMessageBox.warning(self, '价税待核对', balance.message + '；已允许保存，导出前须修正。')
        self.accept()
