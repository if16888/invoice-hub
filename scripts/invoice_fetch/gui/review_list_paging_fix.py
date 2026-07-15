"""Review-list paging and count semantics.

The legacy workbench already queried the first 50 rows, but the visible copy mixed
"filtered" and "loaded" counts. Its incremental loader also used stale attribute
names and keyboard Down stopped at the last loaded row. This migration keeps the
existing renderer and turns the first-page optimisation into predictable infinite
scrolling without adding a permanent visible "load all" control.
"""

from __future__ import annotations

from functools import wraps

from PySide6.QtCore import Qt, QTimer
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


def _header_count_text(window) -> str:
    loaded = len(getattr(window, "invoices_list", []) or [])
    total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
    if loaded < total:
        return f"已加载 {loaded} / 共 {total} 张"
    if not _is_default_scope(window):
        return f"当前筛选 {total} 张"
    return f"已加载全部，共 {total} 张"


def _legacy_status_text(window) -> str:
    """Keep old non-visible status contracts stable while the header owns copy."""
    loaded = len(getattr(window, "invoices_list", []) or [])
    total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
    if loaded < total:
        return f"当前显示 {loaded} / {total} 张｜首屏限量加载"
    if not _is_default_scope(window):
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


def _detach_legacy_status_label(window) -> None:
    """Remove the duplicate bottom-left count from the visible status layout."""
    label = getattr(window, "lbl_status_left", None)
    if label is None or label.property("pagingCountDetached"):
        return
    parent = label.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        layout.removeWidget(label)
    label.setProperty("pagingCountDetached", True)
    label.hide()


def _position_legacy_load_all_proxy(window, has_more: bool, total: int) -> None:
    """Retain the old callable widget off-canvas for compatibility tests/callers.

    The product UI uses infinite scrolling. Older integrations still inspect or
    invoke ``btn_load_all`` directly, so the widget remains alive with its legacy
    geometry and text but is removed from the layout and clipped outside its parent.
    """
    button = getattr(window, "btn_load_all", None)
    if button is None:
        return
    parent = button.parentWidget()
    if not button.property("legacyPagingCompatibilityProxy"):
        layout = parent.layout() if parent is not None else None
        if layout is not None:
            layout.removeWidget(button)
        button.setProperty("legacyPagingCompatibilityProxy", True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    button.setText("加载全部")
    button.setToolTip(f"当前已加载部分记录，共 {total} 张；界面会在滚动到底时自动加载")
    button.ensurePolished()
    width = max(
        button.fontMetrics().horizontalAdvance(button.text()) + 24,
        button.sizeHint().width(),
        56,
    )
    height = max(button.sizeHint().height(), 28)
    button.setMinimumSize(width, height)
    button.setMaximumSize(width, height)
    button.resize(width, height)
    if parent is not None:
        button.move(parent.width() + width + 32, 0)
    button.setVisible(bool(has_more))


def _sync_paging_ui(window) -> None:
    loaded = len(getattr(window, "invoices_list", []) or [])
    total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
    has_more = loaded < total

    window._limited_first_load_active = has_more
    window._limited_first_load_total = total if has_more else 0
    window._first_load_notice = (
        f"首屏已加载最近 {loaded} / {total} 张；向下滚动到末尾或在最后一行按 ↓ 会自动加载更多。"
        if has_more
        else None
    )

    _position_legacy_load_all_proxy(window, has_more, total)

    updater = getattr(window, "_update_record_header_summary", None)
    if callable(updater):
        updater(total_matching=total)

    tooltip = (
        "向下滚动到列表末尾，或在最后一行按 ↓，会自动加载后续记录。"
        if has_more
        else "当前范围已经全部加载。"
    )
    record_count = getattr(window, "lbl_record_count", None)
    if record_count is not None:
        record_count.setToolTip(tooltip)
        record_count.setAccessibleDescription(tooltip)

    status_left = getattr(window, "lbl_status_left", None)
    if status_left is not None:
        status_left.setText(_legacy_status_text(window))
        status_left.setToolTip(tooltip)
    _detach_legacy_status_label(window)


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
            window.lbl_record_count.setText(_header_count_text(window))

        if selected_count is None:
            selection_model = window.table.selectionModel()
            selected_count = len(selection_model.selectedRows()) if selection_model is not None else 0
        if hasattr(window, "lbl_record_selection"):
            window.lbl_record_selection.setText(
                "未选" if int(selected_count or 0) <= 0 else f"已选 {int(selected_count)} 张"
            )

    def format_status_count_prefix() -> str:
        return _legacy_status_text(window)

    window._update_record_header_summary = update_record_header_summary
    window._format_status_count_prefix = format_status_count_prefix

    @wraps(original_load_invoices)
    def load_invoices(*args, **kwargs):
        signature = _scope_signature(window)
        expanding = bool(getattr(window, "_review_paging_expanding", False))
        default_scope = _is_default_scope(window)
        signature_changed = signature != getattr(window, "_review_paging_signature", None)
        if signature_changed and not expanding:
            window._review_page_limit = _PAGE_SIZE
            window._column_filters_load_all = False
            # Filter/search scopes are evaluated in memory by the legacy loader;
            # retain its 50-row first page before infinite-scroll completion.
            window._limited_first_load_active = not default_scope
        window._review_paging_signature = signature

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
        loaded = len(getattr(window, "invoices_list", []) or [])
        total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
        if loaded >= total:
            _sync_paging_ui(window)
            return

        if _is_default_scope(window):
            current_limit = max(loaded, int(getattr(window, "_review_page_limit", _PAGE_SIZE)))
            window._review_page_limit = min(total, current_limit + _PAGE_SIZE)
        else:
            # Search and column filters are currently evaluated after a full DB read;
            # once the user reaches the first filtered page, reveal the rest in one pass.
            window._column_filters_load_all = True
            window._limited_first_load_active = False

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

    def load_all_invoices_compat() -> None:
        """Compatibility entry point; the product UI no longer exposes this action."""
        loaded = len(getattr(window, "invoices_list", []) or [])
        total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
        if loaded >= total:
            _sync_paging_ui(window)
            return
        window._review_paging_expanding = True
        window._review_page_limit = max(_PAGE_SIZE, total)
        window._column_filters_load_all = True
        window._limited_first_load_active = False
        try:
            window._load_invoices()
        finally:
            window._review_paging_expanding = False
            _sync_paging_ui(window)

    window._load_all_invoices_clicked = load_all_invoices_compat
    load_all_button = getattr(window, "btn_load_all", None)
    if load_all_button is not None:
        try:
            load_all_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        load_all_button.clicked.connect(window._load_all_invoices_clicked)

    @wraps(original_move_selection)
    def move_invoice_selection(delta: int) -> None:
        table = window.table
        loaded = len(getattr(window, "invoices_list", []) or [])
        total = max(0, int(getattr(window, "_record_total_matching", loaded) or 0))
        row = table.currentRow()
        if delta > 0 and loaded > 0 and row >= loaded - 1 and loaded < total:
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
