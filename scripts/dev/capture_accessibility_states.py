"""Capture native Qt accessibility interaction states with Design v1 widgets.

The gallery uses only synthetic labels and UI Kit components. Run each scale in a
separate process so Qt reads ``QT_SCALE_FACTOR`` before QApplication starts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scripts.invoice_fetch.gui.ui import build_qss
from scripts.invoice_fetch.gui.ui.components import AppButton, StatCard


STATES = (
    "button-focus",
    "nav-focus",
    "stat-focus",
    "input-focus",
    "tab-focus",
    "table-selected-hover",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--scale", type=float, required=True)
    parser.add_argument("--state", choices=STATES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    label = QLabel(title)
    label.setProperty("role", "section-title")
    layout.addWidget(label)
    return card, layout


def _build_gallery() -> tuple[QWidget, dict[str, QWidget]]:
    root = QWidget()
    root.setObjectName("PageRoot")
    root.setWindowTitle("Invoice Hub Accessibility State Gallery")
    root_layout = QVBoxLayout(root)
    root_layout.setContentsMargins(24, 24, 24, 24)
    root_layout.setSpacing(16)

    title = QLabel("Design v1.2 Accessibility States")
    title.setProperty("role", "section-title")
    subtitle = QLabel("Synthetic UI gallery — keyboard focus, selected hover, and tab semantics")
    subtitle.setProperty("role", "hint")
    root_layout.addWidget(title)
    root_layout.addWidget(subtitle)

    controls: dict[str, QWidget] = {}

    button_card, button_layout = _card("Buttons and input")
    button_row = QHBoxLayout()
    primary = AppButton("保存并继续", variant="primary")
    secondary = AppButton("取消", variant="default")
    ghost = AppButton("更多", variant="ghost")
    danger = AppButton("删除", variant="danger")
    for widget in (primary, secondary, ghost, danger):
        button_row.addWidget(widget)
    button_row.addStretch(1)
    button_layout.addLayout(button_row)
    field = QLineEdit()
    field.setPlaceholderText("键盘焦点输入框")
    button_layout.addWidget(field)
    controls.update(primary=primary, input=field)

    nav_card, nav_layout = _card("Navigation and status filter")
    nav = QFrame()
    nav.setObjectName("WorkbenchNav")
    nav_row = QHBoxLayout(nav)
    nav_row.setContentsMargins(12, 12, 12, 12)
    nav_row.setSpacing(8)
    for index, text in enumerate(("今日工作台", "发票审核", "导入中心")):
        button = QPushButton(text)
        button.setProperty("class", "WorkbenchNavButton")
        button.setCheckable(True)
        button.setChecked(index == 1)
        nav_row.addWidget(button)
        if index == 1:
            controls["nav"] = button
    nav_row.addStretch(1)
    nav_layout.addWidget(nav)
    stat = StatCard("待审核", "42", selected=True)
    nav_layout.addWidget(stat)
    controls["stat"] = stat

    tab_card, tab_layout = _card("Tabs")
    tabs = QTabWidget()
    tabs.addTab(QLabel("邮箱账户内容"), "邮箱账户")
    tabs.addTab(QLabel("开票信息内容"), "开票信息")
    tabs.setCurrentIndex(1)
    tab_layout.addWidget(tabs)
    controls["tab"] = tabs.tabBar()

    table_card, table_layout = _card("Selected row hover")
    table = QTableWidget(4, 3)
    table.setHorizontalHeaderLabels(("状态", "销售方", "金额"))
    rows = (
        ("待审核", "Synthetic Supplier A", "128.50"),
        ("已通过", "Synthetic Supplier B", "86.00"),
        ("待补全", "Synthetic Supplier C", "42.30"),
        ("缺原件", "Synthetic Supplier D", "19.90"),
    )
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(value))
    table.selectRow(1)
    table_layout.addWidget(table)
    controls["table"] = table

    root_layout.addWidget(button_card)
    root_layout.addWidget(nav_card)
    root_layout.addWidget(tab_card)
    root_layout.addWidget(table_card, 1)
    return root, controls


def _apply_state(state: str, controls: dict[str, QWidget], app: QApplication) -> QWidget:
    target = controls[state.split("-", 1)[0]] if state != "table-selected-hover" else controls["table"]
    if state == "table-selected-hover":
        table = controls["table"]
        item = table.item(1, 1)
        table.setFocus(Qt.OtherFocusReason)
        QTest.mouseMove(table.viewport(), table.visualItemRect(item).center())
    else:
        target.setFocus(Qt.TabFocusReason)
    app.processEvents()
    QTest.qWait(160)
    app.processEvents()
    return target


def _visible_geometry_failures(root: QWidget) -> list[str]:
    failures: list[str] = []
    for widget in root.findChildren(QWidget):
        parent = widget.parentWidget()
        if not widget.isVisible() or parent is None or not parent.isVisible():
            continue
        if not parent.rect().intersects(widget.geometry()):
            failures.append(f"{type(widget).__name__}:{widget.objectName()} outside parent")
    return failures


def main() -> int:
    args = _args()
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in {"offscreen", "minimal"}:
        raise SystemExit("native accessibility capture refuses offscreen/minimal Qt platforms")
    if str(args.scale) != os.environ.get("QT_SCALE_FACTOR", str(args.scale)):
        raise SystemExit("QT_SCALE_FACTOR must be set before process start and match --scale")

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(build_qss())
    root, controls = _build_gallery()
    root.resize(args.width, args.height)
    root.show()
    root.raise_()
    root.activateWindow()
    app.processEvents()
    QTest.qWait(220)

    target = _apply_state(args.state, controls, app)
    focused = app.focusWidget()
    failures = _visible_geometry_failures(root)
    if args.state != "table-selected-hover" and focused is not target:
        failures.append(
            f"focus mismatch: expected {type(target).__name__}, got {type(focused).__name__ if focused else 'None'}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image = root.grab()
    if image.isNull() or not image.save(str(args.output)) or args.output.stat().st_size == 0:
        failures.append("screenshot is empty")

    record = {
        "state": args.state,
        "width": args.width,
        "height": args.height,
        "scale": args.scale,
        "device_pixel_ratio": root.devicePixelRatioF(),
        "focused_widget": type(focused).__name__ if focused else None,
        "focused_object_name": focused.objectName() if focused else None,
        "screenshot": str(args.output),
        "failures": failures,
        "result": "FAIL" if failures else "PASS",
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        existing = {"runs": []}
        if args.report.exists():
            existing = json.loads(args.report.read_text(encoding="utf-8"))
        key = f"{args.state}:{args.width}x{args.height}@{args.scale}"
        record["case_key"] = key
        runs = [run for run in existing.get("runs", []) if run.get("case_key") != key]
        runs.append(record)
        existing["runs"] = runs
        args.report.write_text(json.dumps(existing, ensure_ascii=True, indent=2), encoding="utf-8")

    print(json.dumps(record, ensure_ascii=True))
    root.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
