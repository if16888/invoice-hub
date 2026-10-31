"""Responsive review workbench layout controller.

The physical Windows review found that collapsing the application sidebar made
more horizontal space available, but the detail pane stayed locked to the old
fixed width.  This module replaces that fixed-width resize hook with a bounded
splitter reflow that gives part of the reclaimed rail width to the detail pane
while preserving a useful invoice-table and preview area.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable

from shiboken6 import isValid

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLayout,
    QSplitter,
    QSizePolicy,
    QWidget,
)

from .company_tax_profile import apply_company_tax_profile
from .design_system_v11 import apply_design_system_v11
from .design_v1_review_task_closure import apply_design_v1_review_task_closure
from .hci_v1 import apply_review_hci_v1
from .hci_v1_closure import apply_review_hci_closure
from .invoice_detail_panel import install_invoice_detail_ownership
from .review_feedback_fixes import apply_review_feedback_fixes, sync_review_feedback_state
from .review_paging import install_review_paging
from .review_queue_semantics import apply_review_queue_semantics
from .review_settings_issue_fixes import apply_review_attachment_action_fix
from .review_toolbar_filter_fixes import apply_review_toolbar_filter_fixes
from .workbench_layout import clamp_vertical_split


DETAIL_MIN_WIDTH = 352
DETAIL_MAX_WIDTH = 520
COLLAPSED_NAV_THRESHOLD = 96
COLLAPSED_DETAIL_BONUS = 48
MIN_WORKSPACE_WIDTH = 720
COMPACT_DESKTOP_MAX_WIDTH = 1366


def _nav_is_collapsed(window) -> bool:
    nav = getattr(window, "workbench_nav", None)
    return nav is not None and nav.width() <= COLLAPSED_NAV_THRESHOLD


def _base_detail_width(window, available: int) -> int:
    """Return the normal detail width before applying the collapsed-rail bonus."""
    window_width = max(0, int(window.width()))
    if window_width <= COMPACT_DESKTOP_MAX_WIDTH or available <= 1160:
        return 352
    if window_width <= 1440 or available <= 1280:
        return 380
    return 400


def _target_detail_width(window) -> int:
    splitter = getattr(window, "main_splitter", None)
    if splitter is None:
        return DETAIL_MIN_WIDTH

    available = max(0, int(splitter.width()))
    window_width = max(0, int(window.width()))
    restored_width = getattr(window, "_review_detail_restore_width", None)
    has_restored_width = restored_width is not None
    if restored_width is not None:
        try:
            target = int(restored_width)
        except (TypeError, ValueError):
            target = _base_detail_width(window, available)
    else:
        target = _base_detail_width(window, available)

    # A 1366-wide desktop is already space-constrained. Keep its historical
    # 352 px detail contract even when the rail defaults to icon-only; only use
    # reclaimed sidebar width on larger desktops.
    if (
        not has_restored_width
        and window_width > COMPACT_DESKTOP_MAX_WIDTH
        and _nav_is_collapsed(window)
    ):
        target += COLLAPSED_DETAIL_BONUS

    # Never let the detail pane crowd out the dense review workspace.
    if available > 0:
        target = min(target, max(DETAIL_MIN_WIDTH, available - MIN_WORKSPACE_WIDTH))
    return max(DETAIL_MIN_WIDTH, min(DETAIL_MAX_WIDTH, target))


def _reflow_review_detail(window) -> None:
    """Apply the responsive detail width and consume the splitter's full width."""
    detail = getattr(window, "_detail_panel", None)
    splitter = getattr(window, "main_splitter", None)
    if detail is None or splitter is None or splitter.count() < 2:
        return

    if getattr(window, "_review_detail_collapsed", False):
        detail.setMinimumWidth(0)
        detail.setMaximumWidth(0)
        available = max(0, int(splitter.width()) - splitter.handleWidth())
        splitter.setSizes([available, 0])
        return

    target = _target_detail_width(window)
    detail.setMinimumWidth(DETAIL_MIN_WIDTH)
    detail.setMaximumWidth(DETAIL_MAX_WIDTH)
    detail.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 1)
    available = max(0, int(splitter.width()) - splitter.handleWidth() * (splitter.count() - 1))
    if available <= 0:
        return
    target = min(target, max(DETAIL_MIN_WIDTH, available - MIN_WORKSPACE_WIDTH))
    splitter.setSizes([max(MIN_WORKSPACE_WIDTH, available - target), target])


class _ReviewDetailWidthController(QObject):
    """Coalesce window, splitter, and sidebar resize events into one safe reflow."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self._pending = False

    def schedule(self) -> None:
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self._apply)

    def _apply(self) -> None:
        self._pending = False
        try:
            _reflow_review_detail(self.window)
        except RuntimeError:
            # The window can be destroyed while a queued resize callback exists.
            return

    def eventFilter(self, watched, event):
        try:
            if not isValid(self.window):
                return False
            event_type = event.type()
            if event_type == QEvent.MouseButtonDblClick:
                splitter = getattr(self.window, "main_splitter", None)
                if (
                    splitter is not None
                    and isValid(splitter)
                    and watched is splitter.handle(1)
                    and event.button() == Qt.LeftButton
                ):
                    self.window._toggle_review_detail_panel()
                    event.accept()
                    return True
            if event_type == QEvent.Resize:
                self.schedule()
            return False
        except RuntimeError:
            # Qt can dispatch a final child event while tearing down the window.
            return False


def apply_review_detail_width_fix(page: QWidget) -> None:
    """Install the responsive width contract after the review page is complete."""
    if page is None or page.property("reviewDetailWidthFixApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    detail = getattr(window, "_detail_panel", None)
    splitter = getattr(window, "main_splitter", None)
    nav = getattr(window, "workbench_nav", None)
    if detail is None or splitter is None:
        return

    page.setProperty("reviewDetailWidthFixApplied", True)

    # The earlier physical-review module fixed the pane to 352/380/400 px on
    # every window resize. Remove that hook so the reclaimed sidebar width can
    # be distributed by this bounded splitter contract instead.
    old_filter = getattr(window, "_review_feedback_resize_filter", None)
    if old_filter is not None:
        window.removeEventFilter(old_filter)
        old_filter.deleteLater()
        delattr(window, "_review_feedback_resize_filter")

    controller = _ReviewDetailWidthController(window)
    window.installEventFilter(controller)
    splitter.installEventFilter(controller)
    detail_handle = splitter.handle(1)
    if detail_handle is not None:
        detail_handle.installEventFilter(controller)
    if nav is not None:
        nav.installEventFilter(controller)
    collapse_button = getattr(window, "btn_collapse_nav", None)
    if collapse_button is not None:
        collapse_button.clicked.connect(lambda _checked=False: controller.schedule())

    window._review_detail_width_controller = controller
    _reflow_review_detail(window)
    # A legacy single-shot resize callback may already have been queued before
    # its event filter was removed. Queue one final reflow so this contract wins.
    controller.schedule()


SELLER_COLUMN = 4
INVOICE_NUMBER_COLUMN = 5
SELLER_DEFAULT_WIDTH = 260
SELLER_MIN_WIDTH = 180
SELLER_MAX_WIDTH = 320
INVOICE_NUMBER_DEFAULT_WIDTH = 190
INVOICE_NUMBER_MIN_WIDTH = 178

RECORD_MIN_HEIGHT = 260
RECORD_MAX_HEIGHT = 480
PREVIEW_MIN_HEIGHT = 240


def apply_review_table_width_contract(page: QWidget) -> None:
    if page is None or page.property("reviewTableWidthContractApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    table = getattr(window, "table", None)
    if table is None or table.columnCount() <= INVOICE_NUMBER_COLUMN:
        return

    page.setProperty("reviewTableWidthContractApplied", True)
    min_widths = getattr(window, "_min_column_widths", None)
    if isinstance(min_widths, dict):
        min_widths[SELLER_COLUMN] = SELLER_MIN_WIDTH
        min_widths[INVOICE_NUMBER_COLUMN] = INVOICE_NUMBER_MIN_WIDTH

    table.setColumnWidth(SELLER_COLUMN, SELLER_DEFAULT_WIDTH)
    table.setColumnWidth(INVOICE_NUMBER_COLUMN, INVOICE_NUMBER_DEFAULT_WIDTH)

    def bounded_seller_adjustment() -> None:
        if not isValid(table) or getattr(window, "_shutdown_requested", False):
            return
        current = table.columnWidth(SELLER_COLUMN)
        if current < SELLER_MIN_WIDTH:
            table.setColumnWidth(SELLER_COLUMN, SELLER_MIN_WIDTH)
        elif current > SELLER_MAX_WIDTH:
            table.setColumnWidth(SELLER_COLUMN, SELLER_MAX_WIDTH)

    # app.eventFilter and _on_header_section_resized resolve this attribute at
    # call time, so replacing it here removes the old fill-all-spare-space rule.
    window._adjust_column_4_width = bounded_seller_adjustment
    bounded_seller_adjustment()


def _remove_widget_from_layout(layout: QLayout | None, widget: QWidget) -> bool:
    if layout is None:
        return False
    for index in range(layout.count() - 1, -1, -1):
        item = layout.itemAt(index)
        if item.widget() is widget:
            layout.removeWidget(widget)
            return True
        nested = item.layout()
        if nested is not None and _remove_widget_from_layout(nested, widget):
            return True
    return False


def _apply_initial_vertical_sizes(splitter: QSplitter, requested_sizes: list[int]) -> None:
    if not isValid(splitter):
        return
    total = max(
        splitter.height(),
        sum(requested_sizes) if len(requested_sizes) >= 2 else 0,
        RECORD_MIN_HEIGHT + PREVIEW_MIN_HEIGHT,
    )
    requested_record = requested_sizes[0] if requested_sizes else 320
    record, preview = clamp_vertical_split(
        total,
        requested_record,
        record_min=RECORD_MIN_HEIGHT,
        preview_min=PREVIEW_MIN_HEIGHT,
    )
    if record > RECORD_MAX_HEIGHT:
        record = RECORD_MAX_HEIGHT
        preview = total - record
    splitter.setSizes([record, max(PREVIEW_MIN_HEIGHT, preview)])


def _install_real_vertical_splitter(window) -> None:
    middle = getattr(window, "middle_workspace", None)
    upper = getattr(window, "left_upper_widget", None)
    preview = getattr(window, "preview_panel", None)
    old_splitter = getattr(window, "left_splitter", None)
    if middle is None or upper is None or preview is None:
        return

    if (
        isinstance(old_splitter, QSplitter)
        and old_splitter.objectName() == "ReviewVerticalSplitter"
        and old_splitter.count() == 2
    ):
        return

    requested_sizes = []
    if old_splitter is not None and hasattr(old_splitter, "sizes"):
        try:
            requested_sizes = [int(value) for value in old_splitter.sizes()]
        except (TypeError, ValueError, RuntimeError):
            requested_sizes = []

    layout = middle.layout()
    if layout is None:
        return
    layout.removeWidget(upper)
    layout.removeWidget(preview)

    splitter = QSplitter(Qt.Vertical, middle)
    splitter.setObjectName("ReviewVerticalSplitter")
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(6)
    splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # app.py historically fixed the list pane to 276 px. Restore the approved
    # 260-480 px adjustable range and preserve at least 240 px for preview.
    upper.setMinimumHeight(RECORD_MIN_HEIGHT)
    upper.setMaximumHeight(RECORD_MAX_HEIGHT)
    upper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    preview.setMinimumHeight(PREVIEW_MIN_HEIGHT)
    preview.setMaximumHeight(16777215)
    preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    splitter.addWidget(upper)
    splitter.addWidget(preview)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    layout.addWidget(splitter, 1)

    window.left_splitter = splitter
    window.review_vertical_splitter = splitter

    save_timer = getattr(window, "_splitter_save_timer", None)
    if save_timer is not None:
        splitter.splitterMoved.connect(lambda _pos, _index: save_timer.start())

    if old_splitter is not None and old_splitter is not splitter:
        old_splitter.deleteLater()

    _apply_initial_vertical_sizes(splitter, requested_sizes)
    QTimer.singleShot(
        0,
        lambda target=splitter, sizes=requested_sizes: _apply_initial_vertical_sizes(target, sizes),
    )


def _remove_load_all_from_product_surface(window) -> None:
    button = getattr(window, "btn_load_all", None)
    if button is None or button.property("designBaselineRemoved"):
        return

    parent = button.parentWidget()
    _remove_widget_from_layout(parent.layout() if parent is not None else None, button)
    button.setProperty("designBaselineRemoved", True)
    button.hide()
    button.setParent(None)
    button.deleteLater()
    window.btn_load_all = None


def _install_table_remainder_contract(window) -> None:
    """Fill the table viewport while retaining interactive minimum-width rules.

    ``QHeaderView.Stretch`` made the last column ignore the existing 178 px
    minimum-width regression contract: after a user drag to a narrow width Qt
    immediately stretched it again.  Keep every section Interactive instead and
    reuse the app's existing ``_adjust_column_4_width`` resize hook to allocate
    spare viewport width to the invoice-number column.  Seller width remains
    user-controlled within its established 180-320 px range.
    """
    table = getattr(window, "table", None)
    if table is None or table.columnCount() <= INVOICE_NUMBER_COLUMN:
        return

    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    for column in range(table.columnCount()):
        header.setSectionResizeMode(column, QHeaderView.Interactive)

    min_widths = getattr(window, "_min_column_widths", None)
    if isinstance(min_widths, dict):
        min_widths[SELLER_COLUMN] = SELLER_MIN_WIDTH
        min_widths[INVOICE_NUMBER_COLUMN] = INVOICE_NUMBER_MIN_WIDTH

    if table.columnWidth(SELLER_COLUMN) < SELLER_MIN_WIDTH:
        table.setColumnWidth(SELLER_COLUMN, SELLER_DEFAULT_WIDTH)
    if table.columnWidth(INVOICE_NUMBER_COLUMN) < INVOICE_NUMBER_MIN_WIDTH:
        table.setColumnWidth(INVOICE_NUMBER_COLUMN, INVOICE_NUMBER_DEFAULT_WIDTH)

    applying = False

    def fill_remainder() -> None:
        nonlocal applying
        if applying or not isValid(table) or getattr(window, "_shutdown_requested", False):
            return
        applying = True
        window._adjusting_review_columns = True
        try:
            viewport_width = max(0, table.viewport().width())
            compact = viewport_width < 720
            # Keep assignment confirmation before the long identifier when
            # native font minimums exceed the remaining compact width.
            claim_visual = header.visualIndex(6)
            number_visual = header.visualIndex(INVOICE_NUMBER_COLUMN)
            if compact and claim_visual > number_visual:
                header.moveSection(claim_visual, number_visual)
            elif not compact and claim_visual < number_visual:
                header.moveSection(claim_visual, number_visual)
            for column in (1, 2):
                table.setColumnHidden(column, compact)
            if compact:
                other_width = sum(table.columnWidth(index) for index in range(table.columnCount())
                                  if index != SELLER_COLUMN and not table.isColumnHidden(index))
                table.setColumnWidth(SELLER_COLUMN, max(120, viewport_width - other_width))
                return
            seller_width = max(
                SELLER_MIN_WIDTH,
                min(SELLER_MAX_WIDTH, table.columnWidth(SELLER_COLUMN)),
            )
            invoice_width = max(
                INVOICE_NUMBER_MIN_WIDTH,
                table.columnWidth(INVOICE_NUMBER_COLUMN),
            )
            if seller_width != table.columnWidth(SELLER_COLUMN):
                table.setColumnWidth(SELLER_COLUMN, seller_width)
            if invoice_width != table.columnWidth(INVOICE_NUMBER_COLUMN):
                table.setColumnWidth(INVOICE_NUMBER_COLUMN, invoice_width)

            viewport_width = max(0, table.viewport().width())
            total_width = sum(table.columnWidth(index) for index in range(table.columnCount()))
            delta = viewport_width - total_width

            if delta > 0:
                # When the invoice column has just been clamped to its minimum,
                # first spend the small remainder on the seller column. This
                # preserves the exact 178 px minimum-width contract used by the
                # column-resize tests and by narrow desktop layouts.
                if invoice_width <= INVOICE_NUMBER_MIN_WIDTH:
                    seller_growth = min(delta, SELLER_MAX_WIDTH - seller_width)
                    if seller_growth > 0:
                        table.setColumnWidth(SELLER_COLUMN, seller_width + seller_growth)
                        delta -= seller_growth
                if delta > 0:
                    table.setColumnWidth(
                        INVOICE_NUMBER_COLUMN,
                        table.columnWidth(INVOICE_NUMBER_COLUMN) + delta,
                    )
            elif delta < 0:
                excess = -delta
                shrink_invoice = min(
                    excess,
                    max(0, table.columnWidth(INVOICE_NUMBER_COLUMN) - INVOICE_NUMBER_MIN_WIDTH),
                )
                if shrink_invoice:
                    table.setColumnWidth(
                        INVOICE_NUMBER_COLUMN,
                        table.columnWidth(INVOICE_NUMBER_COLUMN) - shrink_invoice,
                    )
                    excess -= shrink_invoice
                if excess:
                    shrink_seller = min(
                        excess,
                        max(0, table.columnWidth(SELLER_COLUMN) - SELLER_MIN_WIDTH),
                    )
                    if shrink_seller:
                        table.setColumnWidth(
                            SELLER_COLUMN,
                            table.columnWidth(SELLER_COLUMN) - shrink_seller,
                        )
        finally:
            window._adjusting_review_columns = False
            applying = False

    # app.eventFilter and _on_header_section_resized resolve this hook at call
    # time, so the adaptive contract runs for viewport resizes and user drags
    # without installing another native event filter.
    window._adjust_column_4_width = fill_remainder
    fill_remainder()
    QTimer.singleShot(0, fill_remainder)

    table.setProperty("reviewRemainderFillApplied", True)
    table.setToolTip("点击列标题筛选；销售方可拖动调整，发票号自动利用剩余宽度")


def install_review_vertical_workspace(page: QWidget) -> None:
    """Apply the final Review workspace structure after legacy construction."""
    if page is None or page.property("reviewWorkspaceClosureApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    if not hasattr(window, "table") or not hasattr(window, "preview_panel"):
        return

    page.setProperty("reviewWorkspaceClosureApplied", True)
    _install_real_vertical_splitter(window)
    _remove_load_all_from_product_surface(window)
    _install_table_remainder_contract(window)


# ── Review workspace baseline (merged from review_workspace_baseline) ──
FILTER_CARD_MIN_WIDTH = 108
FILTER_CARD_MAX_WIDTH = 156
WORKSPACE_DETAIL_MIN_WIDTH = 352
WORKSPACE_DETAIL_MAX_WIDTH = 560
REVIEW_ROW_HEIGHT = 24


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
        detail.setMinimumWidth(WORKSPACE_DETAIL_MIN_WIDTH)
        detail.setMaximumWidth(WORKSPACE_DETAIL_MAX_WIDTH)
        detail.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    table = getattr(window, "table", None)
    if table is not None:
        table.setTextElideMode(Qt.ElideRight)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setMinimumSectionSize(REVIEW_ROW_HEIGHT)
        table.verticalHeader().setDefaultSectionSize(REVIEW_ROW_HEIGHT)

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

    sync_review_feedback_state(window)
    if detail is not None:
        detail.fixed_header_container.setMaximumHeight(360)


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
    apply_review_feedback_fixes(window)
    _install_selection_refresh(window, page)
    _sync_selection_contract(window)


# ── Review baseline/HCI pipeline (merged from review_baseline_pipeline) ──
ReviewStage = tuple[str, Callable[[QWidget], None]]


REVIEW_BASELINE_STAGES: tuple[ReviewStage, ...] = (
    ("workspace_baseline", apply_review_workspace_baseline),
    ("toolbar_and_filters", apply_review_toolbar_filter_fixes),
    ("company_tax_profile", apply_company_tax_profile),
    ("attachment_action_clarity", apply_review_attachment_action_fix),
    ("table_width", apply_review_table_width_contract),
    ("detail_width", apply_review_detail_width_fix),
    ("workspace_vertical_layout", install_review_vertical_workspace),
    ("invoice_detail_ownership", install_invoice_detail_ownership),
    # Paging owns the final count copy and reconnects the search debounce timer.
    ("list_paging", install_review_paging),
    # Task ownership runs late so no earlier compatibility stage can restore
    # cross-workflow buttons or expand the buyer warning again.
    ("task_ownership", apply_design_v1_review_task_closure),
    # Keep the established Design System contract: visual language is the final
    # Review baseline stage.
    ("visual_language_v11", apply_design_system_v11),
)


REVIEW_HCI_STAGES: tuple[ReviewStage, ...] = (
    ("hci_v1_task_flow", apply_review_hci_v1),
    ("hci_v1_closure", apply_review_hci_closure),
)


def _apply_stages(
    page: QWidget,
    stages: tuple[ReviewStage, ...],
    *,
    active_property: str,
    failed_property: str,
) -> tuple[str, ...]:
    completed: list[str] = []
    page.setProperty(failed_property, "")
    for name, stage in stages:
        page.setProperty(active_property, name)
        try:
            stage(page)
        except Exception:
            page.setProperty(failed_property, name)
            raise
        completed.append(name)
    page.setProperty(active_property, "")
    return tuple(completed)


def apply_review_baseline_pipeline(page: QWidget | None) -> None:
    """Apply the established Review visual/geometry baseline once."""
    if page is None or not isValid(page):
        return
    if page.property("reviewBaselinePipelineApplied"):
        return

    completed = _apply_stages(
        page,
        REVIEW_BASELINE_STAGES,
        active_property="reviewBaselinePipelineActiveStage",
        failed_property="reviewBaselinePipelineFailedStage",
    )
    page.setProperty("reviewBaselinePipelineStages", completed)
    page.setProperty("reviewBaselinePipelineApplied", True)


def apply_review_hci_pipeline(page: QWidget | None) -> None:
    """Apply HCI interaction stages only after the baseline has settled."""
    if page is None or not isValid(page):
        return
    if page.property("reviewHciPipelineApplied"):
        return
    if not page.property("reviewBaselinePipelineApplied"):
        apply_review_baseline_pipeline(page)

    completed = _apply_stages(
        page,
        REVIEW_HCI_STAGES,
        active_property="reviewHciPipelineActiveStage",
        failed_property="reviewHciPipelineFailedStage",
    )
    # Keep the established HCI stage identity stable. Queue semantics are a
    # post-HCI behavioral contract, not another migration/closure stage.
    apply_review_queue_semantics(page)
    page.setProperty("reviewHciPipelineStages", completed)
    page.setProperty("reviewHciPipelineApplied", True)


def schedule_review_baseline_pipeline(page: QWidget | None) -> None:
    """Queue one safe callback for baseline followed by post-baseline HCI."""
    if page is None or not isValid(page):
        return
    if (
        page.property("reviewBaselinePipelineApplied")
        and page.property("reviewHciPipelineApplied")
    ) or page.property("reviewBaselinePipelineScheduled"):
        return

    page.setProperty("reviewBaselinePipelineScheduled", True)
    page_ref = weakref.ref(page)

    def run_pipeline() -> None:
        target = page_ref()
        if target is None or not isValid(target):
            return
        try:
            apply_review_baseline_pipeline(target)
            apply_review_hci_pipeline(target)
        finally:
            if isValid(target):
                target.setProperty("reviewBaselinePipelineScheduled", False)

    QTimer.singleShot(0, run_pipeline)

__all__ = [
    "DETAIL_MAX_WIDTH",
    "DETAIL_MIN_WIDTH",
    "INVOICE_NUMBER_COLUMN",
    "INVOICE_NUMBER_MIN_WIDTH",
    "PREVIEW_MIN_HEIGHT",
    "RECORD_MAX_HEIGHT",
    "RECORD_MIN_HEIGHT",
    "SELLER_COLUMN",
    "SELLER_DEFAULT_WIDTH",
    "SELLER_MIN_WIDTH",
    "SELLER_MAX_WIDTH",
    "apply_review_detail_width_fix",
    "apply_review_table_width_contract",
    "install_review_vertical_workspace",
    "_reflow_review_detail",
    "_target_detail_width",
    "apply_review_workspace_baseline",
    "REVIEW_ROW_HEIGHT",
    "FILTER_CARD_MIN_WIDTH",
    "FILTER_CARD_MAX_WIDTH",
    "WORKSPACE_DETAIL_MIN_WIDTH",
    "WORKSPACE_DETAIL_MAX_WIDTH",
    "REVIEW_BASELINE_STAGES",
    "REVIEW_HCI_STAGES",
    "apply_review_baseline_pipeline",
    "apply_review_hci_pipeline",
    "schedule_review_baseline_pipeline",
]
