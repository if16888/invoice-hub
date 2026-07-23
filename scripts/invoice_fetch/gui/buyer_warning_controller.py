"""Single source of truth for the compact buyer-warning presentation."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy
from shiboken6 import isValid

from ..reimbursement import buyer_warning, compact_buyer_warning
from .design_tokens import DESIGN_V1_BUYER_WARNING


BUYER_WARNING_MIN_HEIGHT = DESIGN_V1_BUYER_WARNING["min_height"]
BUYER_WARNING_MAX_HEIGHT = DESIGN_V1_BUYER_WARNING["max_height"]
BUYER_WARNING_PADDING_Y = DESIGN_V1_BUYER_WARNING["padding_y"]
BUYER_WARNING_PADDING_X = DESIGN_V1_BUYER_WARNING["padding_x"]
BUYER_WARNING_MARGIN_Y = DESIGN_V1_BUYER_WARNING["margin_y"]


def selected_invoice(window) -> dict:
    """Return the invoice represented by the current table selection."""
    table = getattr(window, "table", None)
    invoices = getattr(window, "invoices_list", None) or []
    if table is not None and isValid(table):
        selection_model = table.selectionModel()
        if selection_model is not None:
            selected = selection_model.selectedRows()
            if len(selected) == 1:
                row = selected[0].row()
                if 0 <= row < len(invoices):
                    return invoices[row] or {}
            if len(selected) > 1:
                return {}
    return getattr(window, "current_invoice", None) or {}


class BuyerWarningController:
    """Own all BuyerWarning text, visibility, geometry and accessibility state."""

    def __init__(self, window):
        self.window = window
        self._label_layout_applied = False
        self._row_layout_applied = False

    @classmethod
    def for_window(cls, window) -> "BuyerWarningController":
        controller = getattr(window, "buyer_warning_controller", None)
        if not isinstance(controller, cls) or controller.window is not window:
            controller = cls(window)
            setattr(window, "buyer_warning_controller", controller)
        controller._apply_layout_contract()
        return controller

    def _widgets(self):
        detail = getattr(self.window, "_detail_panel", None)
        if detail is None and hasattr(self.window, "lbl_buyer_warning"):
            detail = self.window
        label = getattr(detail, "lbl_buyer_warning", None) if detail is not None else None
        row = getattr(detail, "buyer_warning_action_row", None) if detail is not None else None
        return detail, label, row

    def _apply_layout_contract(self) -> None:
        _detail, label, row = self._widgets()
        if label is None or not isValid(label):
            return

        if not self._label_layout_applied:
            label.setObjectName("CompactBuyerWarning")
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            label.setMinimumWidth(0)
            label.setMaximumWidth(16777215)
            label.setMinimumHeight(BUYER_WARNING_MIN_HEIGHT)
            label.setMaximumHeight(BUYER_WARNING_MAX_HEIGHT)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            label.setProperty("buyerWarningLayout", "tokenized")
            self._label_layout_applied = True

        if row is not None and isValid(row) and not self._row_layout_applied:
            row.setMinimumWidth(0)
            row.setMaximumWidth(16777215)
            row.setMinimumHeight(BUYER_WARNING_MIN_HEIGHT)
            row.setMaximumHeight(BUYER_WARNING_MAX_HEIGHT)
            row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            row_layout = row.layout()
            if row_layout is not None:
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.invalidate()
            self._row_layout_applied = True

    def refresh(self, full_text: str | None = None) -> None:
        """Refresh the warning from the selected invoice and current config."""
        if self.window is None or not isValid(self.window):
            return
        self._apply_layout_contract()
        _detail, label, row = self._widgets()
        if label is None or not isValid(label):
            return

        invoice = selected_invoice(self.window)
        resolved_text = full_text
        if resolved_text is None:
            resolved_text = (
                buyer_warning(invoice, getattr(self.window, "config", {}) or {})
                if invoice
                else ""
            )
        display_text = compact_buyer_warning(resolved_text)
        label.setText(f"⚠️ {display_text}" if display_text else "")
        label.setToolTip(display_text)
        label.setAccessibleDescription(display_text)
        label.setProperty("tone", "warning" if display_text else "muted")
        label.setVisible(bool(display_text))
        if row is not None and isValid(row):
            row.setVisible(bool(display_text))

        buyer_field = getattr(self.window, "txt_buyer", None)
        if buyer_field is None:
            detail = getattr(self.window, "_detail_panel", None)
            buyer_field = getattr(detail, "txt_buyer", None) if detail is not None else None
        if buyer_field is not None and isValid(buyer_field):
            actual_buyer = str(invoice.get("buyer_name") or "").strip() if invoice else ""
            buyer_field.setToolTip(resolved_text or actual_buyer)
            buyer_field.setAccessibleDescription(display_text or actual_buyer)


def refresh_buyer_warning(window) -> None:
    """Compatibility entry point for legacy callers."""
    BuyerWarningController.for_window(window).refresh()


__all__ = [
    "BUYER_WARNING_MARGIN_Y",
    "BUYER_WARNING_MAX_HEIGHT",
    "BUYER_WARNING_MIN_HEIGHT",
    "BUYER_WARNING_PADDING_X",
    "BUYER_WARNING_PADDING_Y",
    "BuyerWarningController",
    "refresh_buyer_warning",
    "selected_invoice",
]
