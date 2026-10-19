"""Editors for claim defaults and independent per-invoice reason overrides."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)


class ClaimReasonDialog(QDialog):
    def __init__(self, claim: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"报销信息 — {claim['name']}")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        hint = QLabel('组内发票默认继承此事由；已单独填写事由的发票保持不变。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.fields = {}
        for key, label in [('reason_category', '事由分类'), ('reason_detail', '事由说明'),
                           ('applicant_name', '报销人'), ('department', '部门')]:
            field = QLineEdit(str(claim.get(key) or ''))
            field.setMaxLength(1000 if key == 'reason_detail' else 100)
            self.fields[key] = field
            form.addRow(label, field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        return {key: field.text().strip() for key, field in self.fields.items()}


class InvoiceReasonDialog(QDialog):
    def __init__(self, invoice: dict, inherited_reason: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('当前发票报销事由')
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        default = QLabel('报销组事由：' + (inherited_reason or '未填写'))
        default.setWordWrap(True)
        layout.addWidget(default)
        self.inherit = QCheckBox('继承报销组事由')
        self.inherit.setChecked(invoice.get('custom_reason') is None)
        layout.addWidget(self.inherit)
        self.reason = QLineEdit(str(invoice.get('custom_reason') or ''))
        self.reason.setMaxLength(1000)
        self.reason.setPlaceholderText('单票事由；留空表示这张发票不填写事由')
        self.reason.setEnabled(not self.inherit.isChecked())
        self.inherit.toggled.connect(lambda checked: self.reason.setEnabled(not checked))
        layout.addWidget(self.reason)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> str | None:
        return None if self.inherit.isChecked() else self.reason.text().strip()
