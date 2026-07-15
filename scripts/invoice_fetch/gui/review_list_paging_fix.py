"""Review paging UI wiring.

Paging behavior lives in :class:`ReviewPagingController` and the formal
InvoiceReviewApp methods. This module only updates copy and connects signals;
it never replaces window methods or database methods at runtime.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from .review_paging import ReviewPagingController


def apply_review_list_paging_fix(page: QWidget | None) -> None:
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


__all__ = ["apply_review_list_paging_fix"]
