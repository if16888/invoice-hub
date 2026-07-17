"""Semantic status rendering for Settings labels.

Legacy Settings code still emits a few rich-text status strings. This contract
normalizes the rendered labels to plain text and Design-token-backed semantic
properties without changing the surrounding page structure.
"""

from __future__ import annotations

import re
import weakref

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QTextDocumentFragment
from PySide6.QtWidgets import QLabel, QWidget
from shiboken6 import isValid


_STATUS_ATTRS = (
    "lbl_cred_status",
    "lbl_ai_wizard_key_status",
    "lbl_ai_summary_key_status",
)

_SUCCESS_MARKERS = (
    "已安全保存",
    "当前配置专属",
    "已保存（当前配置专属",
    "已输入新 Key",
)
_WARNING_MARKERS = (
    "暂不支持",
    "状态已变更",
)
_DANGER_MARKERS = (
    "尚未配置",
    "未配置",
    "未设置",
    "需要输入",
)
_INFO_MARKERS = (
    "旧版 Provider",
    "环境变量",
    "授权状态",
    "API Key 状态",
    "已保存",
)


def plain_status_text(text: str) -> str:
    """Return readable plain text from legacy rich-text status content."""
    value = str(text or "")
    if "<" not in value and "&" not in value:
        return value.strip()
    try:
        plain = QTextDocumentFragment.fromHtml(value).toPlainText()
    except Exception:
        plain = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", plain).strip()


def infer_status_tone(text: str) -> str:
    """Map status language to the Design v1 semantic tone vocabulary."""
    value = plain_status_text(text)
    if any(marker in value for marker in _SUCCESS_MARKERS):
        return "success"
    if any(marker in value for marker in _DANGER_MARKERS):
        return "danger"
    if any(marker in value for marker in _WARNING_MARKERS):
        return "warning"
    if any(marker in value for marker in _INFO_MARKERS):
        return "info"
    return "muted"


def normalize_status_label(label: QLabel | None, *, tone: str | None = None) -> str | None:
    """Normalize one status label and return the applied tone."""
    if label is None or not isValid(label):
        return None

    plain = plain_status_text(label.text())
    applied_tone = tone or infer_status_tone(plain)
    changed = False

    if label.textFormat() != Qt.PlainText:
        label.setTextFormat(Qt.PlainText)
        changed = True
    if label.text() != plain:
        label.setText(plain)
        changed = True
    if label.property("semanticStatus") is not True:
        label.setProperty("semanticStatus", True)
        changed = True
    if label.property("status") != applied_tone:
        label.setProperty("status", applied_tone)
        changed = True
    if label.accessibleName() != plain:
        label.setAccessibleName(plain)

    if changed:
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()
    return applied_tone


class _SettingsStatusEventFilter(QObject):
    """Re-normalize a status label after legacy code changes its text."""

    _WATCHED_EVENTS = {
        QEvent.Show,
        QEvent.UpdateRequest,
        QEvent.LayoutRequest,
        QEvent.DynamicPropertyChange,
    }

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._queued: set[int] = set()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QLabel) and event.type() in self._WATCHED_EVENTS:
            key = id(watched)
            if key not in self._queued:
                self._queued.add(key)
                label_ref = weakref.ref(watched)

                def sync() -> None:
                    self._queued.discard(key)
                    label = label_ref()
                    if label is not None and isValid(label):
                        normalize_status_label(label)

                QTimer.singleShot(0, sync)
        return False


def _status_labels(window: QWidget) -> list[QLabel]:
    labels: list[QLabel] = []
    seen: set[int] = set()

    for attr in _STATUS_ATTRS:
        label = getattr(window, attr, None)
        if isinstance(label, QLabel) and id(label) not in seen:
            labels.append(label)
            seen.add(id(label))

    for label in window.findChildren(QLabel):
        if id(label) in seen:
            continue
        if label.property("class") == "StatusHint" or label.property("semanticStatus") is True:
            labels.append(label)
            seen.add(id(label))
    return labels


def install_settings_semantic_status_contract(page: QWidget | None) -> None:
    """Install semantic status rendering on the active Settings surface."""
    if page is None or not isValid(page):
        return
    if page.property("settingsSemanticStatusContractApplied"):
        return

    window = page.window()
    if window is None or not isValid(window):
        return

    event_filter = _SettingsStatusEventFilter(window)
    labels = _status_labels(window)
    for label in labels:
        normalize_status_label(label)
        label.installEventFilter(event_filter)

    # Keep the QObject alive for the lifetime of the window.
    window._settings_semantic_status_filter = event_filter
    page.setProperty("settingsSemanticStatusContractApplied", True)
    page.setProperty("settingsSemanticStatusLabelCount", len(labels))


__all__ = [
    "infer_status_tone",
    "install_settings_semantic_status_contract",
    "normalize_status_label",
    "plain_status_text",
]
