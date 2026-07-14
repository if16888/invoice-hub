"""Runtime semantic state contract for ChecklistRow.

The legacy component used Unicode glyphs and inline colors.  Invoice Hub loads
this contract before constructing its pages, so every ChecklistRow instance uses
the Design v1 icon provider and QSS-driven state properties.
"""

from __future__ import annotations

from typing import Type

from PySide6.QtCore import QSize

from .icon_provider import IconProvider


VALID_CHECKLIST_STATES = frozenset({"success", "warning", "danger", "muted"})
_STATE_ICON = {
    "success": "success",
    "warning": "warning",
    "danger": "danger",
    "muted": "info",
}
_STATE_TOOLTIP = {
    "success": "检查通过",
    "warning": "提醒项，不阻塞当前操作",
    "danger": "检查未通过",
    "muted": "等待检查",
}


def _resolve_state(row, ok: bool | None, state: str | None) -> str:
    if state in VALID_CHECKLIST_STATES:
        return str(state)
    if ok is True:
        return "success"
    if ok is False:
        false_state = str(row.property("falseState") or "danger")
        return false_state if false_state in VALID_CHECKLIST_STATES else "danger"
    return "muted"


def _semantic_set_value(
    self,
    value: str,
    ok: bool | None = None,
    *,
    state: str | None = None,
) -> None:
    resolved = _resolve_state(self, ok, state)
    text = str(value)

    self.lbl_value.setText(text)
    self.lbl_value.setProperty("state", resolved)
    self.setProperty("state", resolved)

    # Remove compatibility-only per-widget styling before QSS repolish.
    self.lbl_icon.setText("")
    self.lbl_icon.setStyleSheet("")
    self.lbl_value.setStyleSheet("")
    self.lbl_icon.setPixmap(
        IconProvider.icon(_STATE_ICON[resolved]).pixmap(QSize(14, 14))
    )
    self.lbl_icon.setToolTip(_STATE_TOOLTIP[resolved])
    self.lbl_icon.setAccessibleName(_STATE_TOOLTIP[resolved])

    for widget in (self, self.lbl_icon, self.lbl_value):
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def _semantic_set_state(self, value: str, state: str) -> None:
    self.set_value(value, state=state)


def install_semantic_checklist_contract(checklist_type: Type) -> None:
    """Install the semantic contract once on the shared ChecklistRow class."""
    if bool(getattr(checklist_type, "_semantic_contract_installed", False)):
        return
    checklist_type.set_value = _semantic_set_value
    checklist_type.set_state = _semantic_set_state
    checklist_type._semantic_contract_installed = True


__all__ = [
    "VALID_CHECKLIST_STATES",
    "install_semantic_checklist_contract",
]
