"""Formal paging state for the Review workspace.

The controller owns paging metadata; the window remains responsible for the
existing renderer and database query implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget


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
            append = getattr(self.window, "_append_next_invoice_batch_impl", None)
            (append or self.window._append_next_invoice_batch)()
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
        self._move_local(delta)

    def _move_local(self, delta: int) -> None:
        if not getattr(self.window, "invoices_list", None):
            return
        row = self.window.table.currentRow()
        if row < 0:
            row = 0 if delta >= 0 else len(self.window.invoices_list) - 1
        row = max(0, min(len(self.window.invoices_list) - 1, row + delta))
        self.window._select_invoice_by_id(self.window.invoices_list[row].get("id"))

    def append_next_batch(self) -> None:
        self.load_next_page()


def install_review_paging(page: QWidget | None) -> None:
    """Install the established Review paging controller and UI wiring."""
    if page is None or page.property("reviewListPagingFixApplied"):
        return
    window = page.window()
    page.setProperty("reviewListPagingFixApplied", True)
    window.review_paging = ReviewPagingController(window)
    window._review_page_limit = window.review_paging.page_size
    window._review_paging_signature = None
    legacy_status = getattr(window, "lbl_status_left", None)
    if legacy_status is not None:
        legacy_status.hide()
        legacy_status.setProperty("pagingCountDetached", True)

    def refresh_copy() -> None:
        loaded = len(getattr(window, "invoices_list", []) or [])
        total = int(getattr(window, "_record_total_matching", loaded) or loaded)
        if hasattr(window, "lbl_record_count"):
            if loaded < total:
                window.lbl_record_count.setText(f"已加载 {loaded} / 共 {total} 张")
            else:
                window.lbl_record_count.setText(f"已加载全部，共 {total} 张")

    window._refresh_review_paging_copy = refresh_copy
    timer = getattr(window, "search_reload_timer", None)
    if timer is not None:
        try:
            timer.timeout.disconnect()
        except (RuntimeError, TypeError):
            pass
        timer.timeout.connect(window._load_invoices)
    refresh_copy()


__all__ = ["ReviewPagingController", "install_review_paging"]
