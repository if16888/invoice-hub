"""Formal paging state for the Review workspace.

The controller owns paging metadata; the window remains responsible for the
existing renderer and database query implementation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReviewPagingController:
    window: object
    page_size: int = 50
    scope_signature: tuple | None = None
    loading: bool = False
    pending_row: int = -1

    @property
    def loaded_count(self) -> int:
        return len(getattr(self.window, "invoices_list", []) or [])

    @property
    def total_count(self) -> int:
        return int(getattr(self.window, "_record_total_matching", self.loaded_count) or 0)

    def reset_scope(self, signature: tuple) -> None:
        if signature != self.scope_signature:
            self.scope_signature = signature
            self.pending_row = -1
            self.window._is_first_load = True

    def load_first_page(self) -> None:
        self.window._is_first_load = True
        self.window._load_invoices()

    def has_more(self) -> bool:
        return self.loaded_count < self.total_count

    def load_next_page(self) -> None:
        if self.loading or not self.has_more():
            return
        self.loading = True
        try:
            self.window._append_next_invoice_batch()
        finally:
            self.loading = False

    def move_selection(self, delta: int) -> None:
        table = getattr(self.window, "table", None)
        row = table.currentRow() if table is not None else -1
        if delta > 0 and row >= self.loaded_count - 1 and self.has_more():
            self.pending_row = self.loaded_count
            self.load_next_page()
            if self.pending_row < self.loaded_count:
                self.window._select_invoice_by_id(self.window.invoices_list[self.pending_row].get("id"))
                self.pending_row = -1
            return
        self.window._move_invoice_selection(delta)


__all__ = ["ReviewPagingController"]
