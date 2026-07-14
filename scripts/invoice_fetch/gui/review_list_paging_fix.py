"""Review-list paging and count semantics.

The legacy workbench already queried the first 50 rows, but the visible copy mixed
"filtered" and "loaded" counts. Its incremental loader also used stale attribute
names and keyboard Down stopped at the last loaded row. This migration keeps the
existing renderer and turns the first-page optimisation into predictable infinite
scrolling without adding a permanent "load all" control.
"""

from __future__ import annotations

from functools import wraps

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QAbstractItemView, QWidget

from .column_filters import has_active_filters


_PAGE_SIZE = 50


def _freeze_filter_value(value):
    if isinstance(value, dict):
        return tuple(
            sorted((str(key), _freeze_filter_value(item)) for key, item in value.items())
        )
    if isinstance(value, (set, frozenset, list, tuple)):
        frozen = [_freeze_filter_value(item) for item in value]
        return tuple(sorted(frozen, key=repr))
    return value


def _scope_signature(window) -> tuple:
    search_text = ""
    if hasattr(window, "txt_search"):
        search_text = window.txt_search.text().strip()
    show_deleted = False
    if hasattr(window, "chk_show_deleted"):
        show_deleted = bool(window.chk_show_deleted.isChecked())
    return (
        search_text,
        getattr(window, "current_filter_status", None),
        _freeze_filter_value(getattr(window, "column_filters", {}) or {}),
        show_deleted,
    )


def _is_default_scope(window) -> bool:
    search_text = window.txt_search.text().strip() if hasattr(window, "txt_search") else ""
    column_filters = getattr(window, "column_filters", {}) or {}
    return (
        not search_text
        and not has_active_filters(column_filters)
        and getattr(window, "current_filter_status", None) is None
    )


def _is_filtered_scope(window) -> bool:
    return not _is_default_scope(window)


def _count_text(window) -> str:
    loaded = len(getattr(window, "invoices_list", []) or [])
    total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
    if loaded < total:
        return f"已加载 {loaded} / 共 {total} 张"
    if _is_filtered_scope(window):
        return f"当前筛选 {total} 张"
    return f"共 {total} 张"


def _select_loaded_row(window, row: int) -> None:
    table = getattr(window, "table", None)
    invoices = getattr(window, "invoices_list", []) or []
    if table is None or not (0 <= row < len(invoices)):
        return
    table.blockSignals(True)
    try:
        window._apply_single_row_selection(row)
    finally:
        table.blockSignals(False)
    item = table.item(row, 0)
    if item is not None:
        table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
    table.setFocus()
    window._on_table_selection_changed()


def _sync_paging_ui(window) -> None:
    loaded = len(getattr(window, "invoices_list", []) or [])
    total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
    has_more = _is_default_scope(window) and loaded < total

    window._limited_first_load_active = has_more
    window._limited_first_load_total = total if has_more else 0
    window._first_load_notice = (
        f"首屏已加载最近 {loaded} / {total} 张；向下滚动到末尾或在最后一行按 ↓ 会自动加载更多。"
        if has_more
        else None
    )

    load_all = getattr(window, "btn_load_all", None)
    if load_all is not None:
        load_all.hide()
        load_all.setEnabled(False)

    updater = getattr(window, "_update_record_header_summary", None)
    if callable(updater):
        updater(total_matching=total)

    tooltip = (
        "向下滚动到列表末尾，或在最后一行按 ↓，会自动加载后续 50 张。"
        if has_more
        else "当前范围已经全部加载。"
    )
    record_count = getattr(window, "lbl_record_count", None)
    if record_count is not None:
        record_count.setToolTip(tooltip)
        record_count.setAccessibleDescription(tooltip)

    status_left = getattr(window, "lbl_status_left", None)
    if status_left is not None:
        text = _count_text(window)
        status_left.setText(text)
        status_left.setToolTip(tooltip)


def apply_review_list_paging_fix(page: QWidget | None) -> None:
    """Install clear count copy and reliable mouse/keyboard incremental loading."""
    if page is None or page.property("reviewListPagingFixApplied"):
        return
    window = page.window()
    required = ("_load_invoices", "_move_invoice_selection", "table")
    if any(not hasattr(window, name) for name in required):
        return

    page.setProperty("reviewListPagingFixApplied", True)
    window._review_page_limit = _PAGE_SIZE
    window._review_paging_signature = None
    window._review_paging_expanding = False
    window._review_paging_pending_row = -1

    original_load_invoices = window._load_invoices
    original_move_selection = window._move_invoice_selection

    def update_record_header_summary(
        total_matching: int | None = None,
        selected_count: int | None = None,
    ) -> None:
        if total_matching is not None:
            window._record_total_matching = max(0, int(total_matching))
        elif not hasattr(window, "_record_total_matching"):
            window._record_total_matching = len(getattr(window, "invoices_list", []) or [])

        if hasattr(window, "lbl_record_count"):
            window.lbl_record_count.setText(_count_text(window))

        if selected_count is None:
            selection_model = window.table.selectionModel()
            selected_count = len(selection_model.selectedRows()) if selection_model is not None else 0
        if hasattr(window, "lbl_record_selection"):
            window.lbl_record_selection.setText(
                "未选" if int(selected_count or 0) <= 0 else f"已选 {int(selected_count)} 张"
            )

    def format_status_count_prefix() -> str:
        return _count_text(window)

    window._update_record_header_summary = update_record_header_summary
    window._format_status_count_prefix = format_status_count_prefix

    @wraps(original_load_invoices)
    def load_invoices(*args, **kwargs):
        signature = _scope_signature(window)
        expanding = bool(getattr(window, "_review_paging_expanding", False))
        if signature != getattr(window, "_review_paging_signature", None) and not expanding:
            window._review_page_limit = _PAGE_SIZE
        window._review_paging_signature = signature

        default_scope = _is_default_scope(window)
        result = None
        if default_scope:
            target_limit = max(_PAGE_SIZE, int(getattr(window, "_review_page_limit", _PAGE_SIZE)))
            db = getattr(window, "db", None)
            original_list_invoices = getattr(db, "list_invoices", None)
            patched_db_method = False

            if callable(original_list_invoices):
                def list_invoices_with_page_limit(*db_args, **db_kwargs):
                    if db_kwargs.get("limit") == _PAGE_SIZE:
                        db_kwargs["limit"] = target_limit
                    return original_list_invoices(*db_args, **db_kwargs)

                try:
                    db.list_invoices = list_invoices_with_page_limit
                    patched_db_method = True
                except (AttributeError, TypeError):
                    patched_db_method = False

            window._limited_first_load_active = False
            window._is_first_load = True
            try:
                if not patched_db_method and target_limit > _PAGE_SIZE:
                    # Conservative fallback: load the complete default range rather than
                    # leaving keyboard navigation stuck at row 50.
                    window._is_first_load = False
                result = original_load_invoices(*args, **kwargs)
            finally:
                if patched_db_method:
                    db.list_invoices = original_list_invoices
                window._is_first_load = False
        else:
            result = original_load_invoices(*args, **kwargs)

        _sync_paging_ui(window)

        pending_row = int(getattr(window, "_review_paging_pending_row", -1))
        window._review_paging_pending_row = -1
        if 0 <= pending_row < len(getattr(window, "invoices_list", []) or []):
            QTimer.singleShot(0, lambda row=pending_row: _select_loaded_row(window, row))
        return result

    window._load_invoices = load_invoices

    def load_next_invoice_page() -> None:
        if getattr(window, "_is_loading_more_invoices", False):
            return
        if not _is_default_scope(window):
            return
        loaded = len(getattr(window, "invoices_list", []) or [])
        total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
        if loaded >= total:
            _sync_paging_ui(window)
            return

        current_limit = max(loaded, int(getattr(window, "_review_page_limit", _PAGE_SIZE)))
        window._review_page_limit = min(total, current_limit + _PAGE_SIZE)
        window._is_loading_more_invoices = True
        window._review_paging_expanding = True
        if hasattr(window, "lbl_record_count"):
            window.lbl_record_count.setText(f"已加载 {loaded} / 共 {total} 张，正在加载更多…")

        def perform_load() -> None:
            try:
                window._load_invoices()
            finally:
                window._review_paging_expanding = False
                window._is_loading_more_invoices = False
                _sync_paging_ui(window)

        QTimer.singleShot(0, perform_load)

    window._load_next_invoice_page = load_next_invoice_page
    # The legacy append implementation used stale filter/deletion attributes.
    # Keep any old queued callback safe by routing it through the same pager.
    window._append_next_invoice_batch = load_next_invoice_page

    @wraps(original_move_selection)
    def move_invoice_selection(delta: int) -> None:
        table = window.table
        loaded = len(getattr(window, "invoices_list", []) or [])
        total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
        row = table.currentRow()
        if (
            delta > 0
            and loaded > 0
            and row >= loaded - 1
            and loaded < total
            and _is_default_scope(window)
        ):
            window._review_paging_pending_row = loaded
            window._load_next_invoice_page()
            return
        original_move_selection(delta)

    window._move_invoice_selection = move_invoice_selection

    timer = getattr(window, "search_reload_timer", None)
    if timer is not None:
        try:
            timer.timeout.disconnect()
        except (RuntimeError, TypeError):
            pass
        timer.timeout.connect(window._load_invoices)

    _sync_paging_ui(window)


__all__ = ["apply_review_list_paging_fix"]
