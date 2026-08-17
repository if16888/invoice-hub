"""Native date-range dialog used by the bounded history re-check flow."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from .ui_components import make_button


class DateRangeDialog(QDialog):
    """Collect a validated ISO date range without raw text entry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("重新检查指定时间范围")
        self.setModal(True)

        today = QDate.currentDate()
        self._today = today

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = QLabel("时间范围", self)
        title.setProperty("class", "SectionTitle")
        layout.addWidget(title)

        presets = QHBoxLayout()
        presets.setSpacing(8)
        for text, mode in (
            ("最近 7 天", "7d"),
            ("最近 30 天", "30d"),
            ("最近 3 个月", "3m"),
        ):
            button = make_button(text, variant="secondary")
            button.clicked.connect(lambda _checked=False, value=mode: self._apply_preset(value))
            presets.addWidget(button)
        presets.addStretch(1)
        layout.addLayout(presets)

        self.start_date_edit = self._make_date_edit(today.addDays(-30))
        self.end_date_edit = self._make_date_edit(today)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.addRow("开始日期", self.start_date_edit)
        form.addRow("结束日期", self.end_date_edit)
        layout.addLayout(form)

        help_text = QLabel(
            "重新检查已知邮件；不会清空扫描历史。\n"
            "已通过或已加入报销组的记录默认跳过；本次最多处理 200 封。",
            self,
        )
        help_text.setWordWrap(True)
        help_text.setProperty("class", "SectionHint")
        layout.addWidget(help_text)

        self.error_label = QLabel("", self)
        self.error_label.setWordWrap(True)
        self.error_label.setProperty("class", "ErrorText")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Cancel | QDialogButtonBox.Ok,
            parent=self,
        )
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.Ok).setText("开始重新检查")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.start_date_edit.dateChanged.connect(self._clear_error)
        self.end_date_edit.dateChanged.connect(self._clear_error)
        self.start_date_edit.setFocus()

    def _make_date_edit(self, value: QDate) -> QDateEdit:
        edit = QDateEdit(value, self)
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setMinimumDate(QDate(2000, 1, 1))
        edit.setMaximumDate(self._today)
        return edit

    def _clear_error(self, *_args) -> None:
        self.error_label.clear()
        self.error_label.hide()

    def _apply_preset(self, mode: str) -> None:
        if mode == "7d":
            start = self._today.addDays(-7)
        elif mode == "30d":
            start = self._today.addDays(-30)
        else:
            start = self._today.addMonths(-3)
        self.start_date_edit.setDate(start)
        self.end_date_edit.setDate(self._today)
        self._clear_error()

    def accept(self) -> None:
        if self.start_date_edit.date() > self.end_date_edit.date():
            self.error_label.setText("起始日期不能晚于结束日期。")
            self.error_label.show()
            return
        super().accept()

    def date_range(self) -> tuple[str, str]:
        return (
            self.start_date_edit.date().toString("yyyy-MM-dd"),
            self.end_date_edit.date().toString("yyyy-MM-dd"),
        )


__all__ = ["DateRangeDialog"]
