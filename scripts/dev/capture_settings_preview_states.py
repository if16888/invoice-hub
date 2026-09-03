"""Capture native Settings semantic-status and PreviewToolbar interaction states.

All content is synthetic. Run each scale factor in a separate process so Qt
reads ``QT_SCALE_FACTOR`` before QApplication starts.
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

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from scripts.invoice_fetch.gui.settings_status import normalize_status_label
from scripts.invoice_fetch.gui.settings_theme import _settings_token_qss
from scripts.invoice_fetch.gui.ui import build_qss
from scripts.invoice_fetch.gui.ui.components.preview_toolbar import PreviewToolbar


STATES = (
    "settings-success",
    "settings-warning",
    "settings-danger",
    "settings-info",
    "preview-normal",
    "preview-hover",
    "preview-focus",
    "preview-disabled",
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
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    heading = QLabel(title)
    heading.setProperty("role", "section-title")
    layout.addWidget(heading)
    return card, layout


def _build_gallery() -> tuple[QWidget, dict[str, QWidget]]:
    root = QWidget()
    root.setObjectName("PageRoot")
    root.setWindowTitle("Invoice Hub Settings and Preview State Gallery")
    layout = QVBoxLayout(root)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(16)

    title = QLabel("Design v1.2 Settings / Preview semantic states")
    title.setProperty("role", "section-title")
    subtitle = QLabel("Synthetic validation surface — no user data, credentials, or documents")
    subtitle.setProperty("role", "hint")
    layout.addWidget(title)
    layout.addWidget(subtitle)

    settings_card, settings_layout = _card("Settings status labels")
    status_row = QHBoxLayout()
    status_row.setSpacing(10)
    status_texts = {
        "settings-success": "授权状态：<font color='#10B981'><b>已安全保存到系统凭据管理器</b></font>",
        "settings-warning": "授权状态：<font color='#D97706'><b>Outlook 当前版本暂不支持配置/测试</b></font>",
        "settings-danger": "API Key 状态：<font color='#B42318'><b>尚未配置</b></font>",
        "settings-info": "API Key 状态：<font color='#3B82F6'><b>已保存（旧版 Provider Key）</b></font>",
    }
    controls: dict[str, QWidget] = {}
    for state, text in status_texts.items():
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMinimumWidth(220)
        normalize_status_label(label)
        status_row.addWidget(label)
        controls[state] = label
    status_row.addStretch(1)
    settings_layout.addLayout(status_row)
    layout.addWidget(settings_card)

    preview_card, preview_layout = _card("Actual PreviewToolbar component")
    toolbar = PreviewToolbar()
    preview_layout.addWidget(toolbar, 0, Qt.AlignLeft)
    layout.addWidget(preview_card)
    layout.addStretch(1)

    controls.update(
        toolbar=toolbar,
        preview_normal=toolbar,
        preview_hover=toolbar.btn_download,
        preview_focus=toolbar.btn_fit_width,
        preview_disabled=toolbar.btn_print,
    )
    return root, controls


def _apply_state(state: str, controls: dict[str, QWidget], app: QApplication) -> QWidget:
    key = state.replace("-", "_")
    target = controls.get(key, controls.get(state))
    if target is None:
        raise RuntimeError(f"missing synthetic control for state: {state}")

    if state == "preview-hover":
        button = controls["preview_hover"]
        QTest.mouseMove(button, button.rect().center())
    elif state == "preview-focus":
        target.setFocus(Qt.TabFocusReason)
    elif state == "preview-disabled":
        target.setEnabled(False)
    elif state.startswith("settings-"):
        target.setFocus(Qt.OtherFocusReason)

    app.processEvents()
    QTest.qWait(180)
    app.processEvents()
    return target


def _geometry_failures(root: QWidget) -> list[str]:
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
    platform = os.environ.get("QT_QPA_PLATFORM", "").lower()
    if platform in {"offscreen", "minimal"}:
        raise SystemExit("native capture refuses offscreen/minimal Qt platforms")
    if str(args.scale) != os.environ.get("QT_SCALE_FACTOR", str(args.scale)):
        raise SystemExit("QT_SCALE_FACTOR must match --scale before QApplication starts")

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(build_qss() + "\n" + _settings_token_qss())
    root, controls = _build_gallery()
    root.resize(args.width, args.height)
    root.show()
    root.raise_()
    root.activateWindow()
    app.processEvents()
    QTest.qWait(220)

    target = _apply_state(args.state, controls, app)
    failures = _geometry_failures(root)
    if args.state == "preview-focus" and app.focusWidget() is not target:
        failures.append("preview focus target did not receive keyboard focus")
    if args.state.startswith("settings-"):
        if "<font" in target.text().lower():
            failures.append("settings status still contains rich-text color markup")
        if target.property("semanticStatus") is not True:
            failures.append("settings status lacks semanticStatus property")

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
        "target_class": type(target).__name__,
        "target_object_name": target.objectName(),
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
