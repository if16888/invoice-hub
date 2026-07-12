"""Final Design Baseline v1.0 normalization for the review Workspace.

The review page is the dense archetype. This module does not change invoice
queries or review actions; it removes decorative Unicode, protects usable
geometry, and makes the empty/selection state visually truthful.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QSizePolicy, QWidget


FILTER_CARD_MIN_WIDTH = 108
FILTER_CARD_MAX_WIDTH = 156
DETAIL_MIN_WIDTH = 352
DETAIL_MAX_WIDTH = 520


def _normalize_filter_cards(window) -> None:
    for status, card in getattr(window, "filter_buttons", {}).items():
        icon = getattr(card, "_lbl_icon", None)
        if icon is not None:
            icon.clear()
            icon.hide()
        if hasattr(card, "_icon_text"):
            card._icon_text = ""
        card.setProperty("decorativeIconRemoved", True)
        card.setMinimumWidth(FILTER_CARD_MIN_WIDTH)
        card.setMaximumWidth(FILTER_CARD_MAX_WIDTH)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        title = getattr(card, "_lbl_title", None)
        value = getattr(card, "_lbl_value", None)
        if title is not None:
            title.setWordWrap(False)
        if value is not None:
            value.setWordWrap(False)
        accessible = card.text() if hasattr(card, "text") else str(status)
        card.setAccessibleName(accessible)
        card.setToolTip(f"筛选：{accessible}")


def _normalize_workspace_geometry(window) -> None:
    detail = getattr(window, "_detail_panel", None)
    if detail is not None:
        detail.setMinimumWidth(DETAIL_MIN_WIDTH)
        detail.setMaximumWidth(DETAIL_MAX_WIDTH)
        detail.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    table = getattr(window, "table", None)
    if table is not None:
        table.setTextElideMode(Qt.ElideRight)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setAlternatingRowColors(True)

    search = getattr(window, "txt_search", None)
    if search is not None:
        search.setMinimumWidth(260)
        search.setAccessibleName("搜索发票")

    advanced = getattr(window, "btn_advanced_filter", None)
    if advanced is not None:
        advanced.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


def _set_empty_copy(window, *, has_records: bool) -> None:
    title = getattr(window, "lbl_right_empty_title", None)
    desc = getattr(window, "lbl_right_empty_desc", None)
    if has_records:
        title_text = "未选择发票"
        desc_text = "选择一张发票后，可查看字段、原件、证明材料和报销信息。"
    else:
        title_text = "当前没有发票记录"
        desc_text = "导入发票后，可在这里审核字段、材料和报销信息。"
    if title is not None:
        title.setText(title_text)
    if desc is not None:
        desc.setText(desc_text)


def _sync_selection_contract(window) -> None:
    state = window._review_view_state()
    has_selection = state.has_current_invoice and state.selected_count == 1
    _set_empty_copy(window, has_records=state.visible_count > 0)

    detail = getattr(window, "_detail_panel", None)
    if detail is not None:
        if has_selection:
            detail.set_single_selection_state()
        elif state.selected_count > 1:
            detail.set_multi_selection_state(state.selected_count)
        else:
            detail.set_no_selection_state()

    if state.visible_count == 0 or (not state.has_current_invoice and state.selected_count <= 0):
        window._set_right_panel_state(False)


def _install_selection_refresh(window, page: QWidget) -> None:
    if page.property("reviewBaselineSelectionContractInstalled"):
        return
    page.setProperty("reviewBaselineSelectionContractInstalled", True)
    table = getattr(window, "table", None)
    if table is not None:
        table.itemSelectionChanged.connect(
            lambda: QTimer.singleShot(0, lambda: _sync_selection_contract(window))
        )


def apply_review_workspace_baseline(page: QWidget) -> None:
    """Apply the dense Workspace contract after all review controls exist."""
    if page is None or page.property("reviewWorkspaceBaselineApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    if not hasattr(window, "filter_buttons") or not hasattr(window, "_detail_panel"):
        return

    page.setProperty("reviewWorkspaceBaselineApplied", True)
    _normalize_filter_cards(window)
    _normalize_workspace_geometry(window)
    _install_selection_refresh(window, page)
    _sync_selection_contract(window)


__all__ = ["apply_review_workspace_baseline"]
