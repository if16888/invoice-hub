from __future__ import annotations

from dataclasses import dataclass


def is_keyboard_input_target(widget) -> bool:
    """Return whether focused widget ancestry owns editing/navigation keys."""
    if widget is None:
        return False
    from PySide6.QtWidgets import (
        QAbstractSpinBox,
        QComboBox,
        QLineEdit,
        QPlainTextEdit,
        QTextEdit,
    )

    current = widget
    while current is not None:
        if isinstance(current, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return True
        if isinstance(current, QComboBox) and current.isEditable():
            return True
        current = current.parentWidget()
    return False


@dataclass
class IncrementalWindow:
    batch_size: int = 100
    offset: int = 0
    total: int = 0
    loading: bool = False
    has_more: bool = True
    generation: int = 0

    def __post_init__(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")

    def reset(self) -> None:
        self.offset = 0
        self.total = 0
        self.loading = False
        self.has_more = True
        self.generation += 1

    def next_query(self) -> tuple[int, int]:
        if self.loading:
            raise RuntimeError("batch query already in progress")
        if not self.has_more and self.offset > 0:
            raise RuntimeError("no more batches available")
        self.loading = True
        return self.batch_size, self.offset

    def accept_batch(self, count: int, total: int, generation: int) -> None:
        if generation != self.generation:
            return
        self.loading = False
        self.total = max(0, int(total))
        self.offset = max(0, self.offset + max(0, int(count)))
        self.has_more = self.offset < self.total

    def fail_batch(self, generation: int) -> None:
        if generation != self.generation:
            return
        self.loading = False
