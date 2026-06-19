"""Lightweight invoice table column filtering helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


ValueGetter = Callable[[dict], str]

COLUMN_DEFINITIONS = (
    ("status", "资料", "values"),
    ("expense_date", "费用日期", "date"),
    ("total_amount", "金额", "amount"),
    ("invoice_number", "发票号码", "values"),
    ("seller_name", "销售方", "values"),
    ("category", "消费类型", "values"),
    ("source", "来源", "values"),
    ("claim_name", "报销组", "values"),
)

COLUMN_KEYS = tuple(item[0] for item in COLUMN_DEFINITIONS)
COLUMN_LABELS = {key: label for key, label, _kind in COLUMN_DEFINITIONS}
COLUMN_KINDS = {key: kind for key, _label, kind in COLUMN_DEFINITIONS}
CLAIM_GROUP_FIELD_KEYS = ("claim_name", "claim_group_name", "claim_group")


def column_value(row: dict, key: str, value_getters: dict[str, ValueGetter] | None = None) -> str:
    getter = (value_getters or {}).get(key)
    if getter is not None:
        getter_value = str(getter(row) or "").strip()
        if getter_value or key != "claim_name":
            return getter_value
    if key == "claim_name":
        for claim_key in CLAIM_GROUP_FIELD_KEYS:
            value = str(row.get(claim_key) or "").strip()
            if value:
                return value
        return ""
    if key == "expense_date":
        return str(row.get("expense_date") or row.get("invoice_date") or "").strip()
    return str(row.get(key) or "").strip()


def is_filter_active(spec: dict | None) -> bool:
    spec = spec or {}
    return bool("values" in spec or spec.get("quick") or spec.get("min") or spec.get("max"))


def has_active_filters(filters: dict[str, dict] | None) -> bool:
    return any(is_filter_active(spec) for spec in (filters or {}).values())


def unique_column_values(
    rows: list[dict],
    key: str,
    value_getters: dict[str, ValueGetter] | None = None,
) -> list[str]:
    values = {column_value(row, key, value_getters) or "(空白)" for row in rows}
    return sorted(values, key=lambda value: value.casefold())


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _matches_quick_date(value: str, quick: str, today: date) -> bool:
    current = _parse_date(value)
    if current is None:
        return False
    if quick == "today":
        return current == today
    if quick == "week":
        start = today - timedelta(days=today.weekday())
        return start <= current <= today
    if quick == "month":
        return current.year == today.year and current.month == today.month
    if quick == "last_30_days":
        return today - timedelta(days=29) <= current <= today
    return True


def _parse_decimal(value: object) -> Decimal | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def apply_column_filters(
    rows: list[dict],
    filters: dict[str, dict] | None,
    value_getters: dict[str, ValueGetter] | None = None,
    today: date | None = None,
) -> list[dict]:
    active = {key: spec for key, spec in (filters or {}).items() if is_filter_active(spec)}
    if not active:
        return list(rows)

    today = today or date.today()
    matched: list[dict] = []
    for row in rows:
        keep = True
        for key, spec in active.items():
            value = column_value(row, key, value_getters)
            selected = set(spec.get("values") or ())
            if "values" in spec and (value or "(空白)") not in selected:
                keep = False
                break
            quick = str(spec.get("quick") or "")
            if quick and not _matches_quick_date(value, quick, today):
                keep = False
                break
            if key == "total_amount":
                amount = _parse_decimal(value)
                minimum = _parse_decimal(spec.get("min"))
                maximum = _parse_decimal(spec.get("max"))
                if amount is None:
                    keep = False
                    break
                if minimum is not None and amount < minimum:
                    keep = False
                    break
                if maximum is not None and amount > maximum:
                    keep = False
                    break
        if keep:
            matched.append(row)
    return matched


class ColumnFilterPopup(QDialog):
    """Compact popup editor for one invoice table column filter."""

    def __init__(
        self,
        key: str,
        values: list[str],
        current: dict | None,
        apply_callback: Callable[[str, dict], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent, Qt.Popup)
        self.key = key
        self.values = list(values)
        self.current = dict(current or {})
        self.apply_callback = apply_callback
        self.setObjectName("columnFilterPopup")
        self.setMinimumWidth(250)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)
        title = QLabel(f"筛选：{COLUMN_LABELS[key]}")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        self.value_list = None
        self.search_edit = None
        self.select_all = None
        self.quick_combo = None
        self.min_edit = None
        self.max_edit = None
        kind = COLUMN_KINDS[key]
        if kind == "amount":
            amount_row = QHBoxLayout()
            self.min_edit = QLineEdit(str(self.current.get("min") or ""))
            self.min_edit.setPlaceholderText("最小金额")
            self.max_edit = QLineEdit(str(self.current.get("max") or ""))
            self.max_edit.setPlaceholderText("最大金额")
            amount_row.addWidget(self.min_edit)
            amount_row.addWidget(QLabel("至"))
            amount_row.addWidget(self.max_edit)
            layout.addLayout(amount_row)
        else:
            if kind == "date":
                self.quick_combo = QComboBox()
                self.quick_combo.addItem("自定义日期", "")
                self.quick_combo.addItem("今天", "today")
                self.quick_combo.addItem("本周", "week")
                self.quick_combo.addItem("本月", "month")
                self.quick_combo.addItem("最近 30 天", "last_30_days")
                quick_index = self.quick_combo.findData(str(self.current.get("quick") or ""))
                self.quick_combo.setCurrentIndex(max(0, quick_index))
                layout.addWidget(self.quick_combo)

            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText("搜索值")
            layout.addWidget(self.search_edit)
            self.select_all = QCheckBox("全选")
            layout.addWidget(self.select_all)
            self.value_list = QListWidget()
            self.value_list.setMaximumHeight(220)
            selected = set(self.current.get("values") or ())
            has_value_filter = "values" in self.current
            for value in self.values:
                item = QListWidgetItem(value)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if not has_value_filter or value in selected else Qt.Unchecked)
                self.value_list.addItem(item)
            self.select_all.setChecked(not has_value_filter or len(selected) == len(self.values))
            self.search_edit.textChanged.connect(self._filter_visible_values)
            self.select_all.toggled.connect(self._toggle_all_values)
            layout.addWidget(self.value_list)

        buttons = QHBoxLayout()
        clear_button = QPushButton("清除此列")
        clear_button.clicked.connect(self._clear)
        apply_button = QPushButton("应用")
        apply_button.setDefault(True)
        apply_button.clicked.connect(self._apply)
        buttons.addWidget(clear_button)
        buttons.addStretch()
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

    def _filter_visible_values(self, text: str):
        needle = str(text or "").strip().casefold()
        for index in range(self.value_list.count()):
            item = self.value_list.item(index)
            item.setHidden(bool(needle and needle not in item.text().casefold()))

    def _toggle_all_values(self, checked: bool):
        for index in range(self.value_list.count()):
            self.value_list.item(index).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _clear(self):
        self.apply_callback(self.key, {})
        self.close()

    def _apply(self):
        kind = COLUMN_KINDS[self.key]
        if kind == "amount":
            spec = {
                "min": self.min_edit.text().strip(),
                "max": self.max_edit.text().strip(),
            }
        else:
            selected = {
                self.value_list.item(index).text()
                for index in range(self.value_list.count())
                if self.value_list.item(index).checkState() == Qt.Checked
            }
            spec = {}
            if selected != set(self.values):
                spec["values"] = selected
            if kind == "date":
                quick = str(self.quick_combo.currentData() or "")
                if quick:
                    spec = {"quick": quick}
        self.apply_callback(self.key, spec)
        self.close()
