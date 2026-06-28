"""Workbench state engine: incremental loading and keyboard routing classifier."""

from __future__ import annotations
from typing import Any
from PySide6.QtWidgets import QWidget, QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox

class IncrementalWindow:
    """Tracks state and offset pagination for incremental database loading."""

    def __init__(self, limit: int = 50):
        self.limit = limit
        self.offset = 0
        self.has_more = True
        self.invoices: list[dict[str, Any]] = []
        self.status_filter: str | None = None
        self.search_text: str = ""
        self.column_filters: dict[str, Any] = {}

    def reset(self, status_filter: str | None = None, search_text: str = "", column_filters: dict[str, Any] | None = None) -> None:
        """Reset pagination state to first page."""
        self.offset = 0
        self.has_more = True
        self.invoices = []
        self.status_filter = status_filter
        self.search_text = search_text
        self.column_filters = dict(column_filters) if column_filters is not None else {}

    def advance(self, count_loaded: int) -> None:
        """Advance offset and determine if there are more records to load."""
        if count_loaded < self.limit:
            self.has_more = False
        self.offset += count_loaded

    def append_invoices(self, new_invoices: list[dict[str, Any]]) -> None:
        """Append newly loaded invoices to the cache."""
        self.invoices.extend(new_invoices)


def is_keyboard_input_target(widget: QWidget | None) -> bool:
    """Return True if the focused widget is a text/number editor or combo box that should consume keyboard inputs."""
    if widget is None:
        return False
    # Check common input widgets
    if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox)):
        return True
    # Also check if class name contains common editor identifiers to be robust
    class_name = widget.metaObject().className() if hasattr(widget, "metaObject") else ""
    if any(term in class_name for term in ["LineEdit", "TextEdit", "SpinBox", "ComboBox"]):
        return True
    return False
