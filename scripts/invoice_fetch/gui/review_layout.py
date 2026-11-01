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
from functools import wraps

from shiboken6 import isValid

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .company_tax_profile import apply_company_tax_profile
from .design_system_v11 import apply_design_system_v11
from .hci_v1 import apply_review_hci_closure, apply_review_hci_v1
from ..config import save_config
from .buyer_warning_controller import BuyerWarningController
from .column_filters import has_active_filters
from .icon_provider import IconProvider
from .invoice_detail_panel import install_invoice_detail_ownership
from .review_paging import install_review_paging
from .review_queue_semantics import apply_review_queue_semantics
from .ui_components import ElidedTextLabel, fit_button_to_content, make_button
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



# ── Review task ownership closure (merged from design_v1_review_task_closure) ──
_CROSS_WORKFLOW_BUTTONS = (
    "btn_import_local",
    "btn_scan_email",
    "btn_toolbar_export",
)


class _CommandCompatibility:
    """Non-widget compatibility surface for legacy callers."""

    def __init__(self, action, legacy_text=None):
        self._action = action
        self._legacy_text = legacy_text
        self._props = {
            "reviewCrossWorkflowActionRemoved": True,
            "reviewCompatibilityControl": None,
        }

    def property(self, name):
        return self._props.get(name, self._action.property(name))

    def setProperty(self, name, value):
        self._props[name] = value

    def text(self):
        return self._legacy_text or self._action.text()

    def setText(self, value):
        self._legacy_text = value

    def style(self):
        return _NullStyle()

    def isEnabled(self):
        return self._action.isEnabled()

    def setEnabled(self, value):
        self._action.setEnabled(value)

    def clearFocus(self):
        pass

    def setFocus(self, *_args):
        pass

    def isVisible(self):
        return False

    def isHidden(self):
        return True

    def menu(self):
        return None


class _NullStyle:
    def unpolish(self, *_args):
        pass

    def polish(self, *_args):
        pass


def _remove_cross_workflow_actions(window) -> None:
    """Remove Import/Scan/Export controls from the visible Review command bar."""
    toolbar = getattr(window, "workbench_top_toolbar", None)
    toolbar_layout = toolbar.layout() if toolbar is not None else None

    for attr in _CROSS_WORKFLOW_BUTTONS:
        button = getattr(window, attr, None)
        if button is None:
            continue
        _remove_widget_from_layout(toolbar_layout, button)
        parent = button.parentWidget()
        if parent is not None:
            _remove_widget_from_layout(parent.layout(), button)
        button.setProperty("reviewCrossWorkflowActionRemoved", True)
        action_name = {
            "btn_import_local": "action_import_local",
            "btn_scan_email": "action_scan_email",
            "btn_toolbar_export": "action_toolbar_export",
        }[attr]
        button.deleteLater()
        legacy_text = {
            "btn_import_local": "导入",
            "btn_scan_email": "扫描邮箱",
            "btn_toolbar_export": "导出",
        }[attr]
        setattr(
            window,
            attr,
            _CommandCompatibility(getattr(window, action_name), legacy_text),
        )

    more = getattr(window, "btn_more", None)
    if more is not None:
        more.setText("更多")
        more.setToolTip("更多审核操作")
        more.setAccessibleName("更多审核操作")
        fit_button_to_content(more, minimum=72, horizontal_padding=24)
        more.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    search = getattr(window, "txt_search", None)
    if search is not None:
        search.setPlaceholderText("搜索发票号 / 销售方 / 购买方 / 金额    Ctrl + F")
        search.setAccessibleName("搜索发票")

    if toolbar_layout is not None:
        toolbar_layout.setSpacing(8)
        toolbar_layout.invalidate()
    if toolbar is not None:
        toolbar.setToolTip("发票审核：搜索、筛选和处理当前记录")
        toolbar.adjustSize()


def _hide_redundant_review_header(window) -> None:
    """Keep Review as a dense workbench without a duplicate page title block."""
    header = getattr(window, "review_header", None)
    if header is None or not isValid(header):
        return
    parent = header.parentWidget()
    if parent is not None:
        _remove_widget_from_layout(parent.layout(), header)
    header.hide()
    header.setProperty("reviewDenseHeaderRemoved", True)


def _buyer_warning_summary(full_text: str) -> str:
    """Compatibility helper for callers that still need compact warning copy."""
    from ..reimbursement import compact_buyer_warning

    return compact_buyer_warning(full_text)


def _refresh_compact_buyer_warning(window) -> None:
    if window is None or not isValid(window):
        return
    BuyerWarningController.for_window(window).refresh()


def _refresh_from_ref(window_ref: weakref.ReferenceType) -> None:
    target = window_ref()
    if target is not None and isValid(target):
        _refresh_compact_buyer_warning(target)


def _schedule_refresh(window_ref: weakref.ReferenceType) -> None:
    QTimer.singleShot(0, lambda ref=window_ref: _refresh_from_ref(ref))


def _remove_company_action(window) -> None:
    """Keep company-profile editing on Settings, not inside the review banner."""
    detail = getattr(window, "_detail_panel", None)
    button = getattr(detail, "btn_edit_reimbursement_title", None) if detail else None
    if button is None or not isValid(button):
        return
    parent = button.parentWidget()
    if parent is not None:
        _remove_widget_from_layout(parent.layout(), button)
    button.hide()
    button.setFocusPolicy(Qt.NoFocus)
    button.setProperty("reviewCompanyActionRemoved", True)


def _refresh_visible_review_from_refs(
    window_ref: weakref.ReferenceType,
    page_ref: weakref.ReferenceType,
    stack_ref: weakref.ReferenceType,
) -> None:
    target = window_ref()
    review_page = page_ref()
    stack = stack_ref()
    if (
        target is None
        or review_page is None
        or stack is None
        or not isValid(target)
        or not isValid(review_page)
        or not isValid(stack)
    ):
        return
    if stack.currentWidget() is review_page:
        _refresh_compact_buyer_warning(target)


def _install_warning_refresh(window, page: QWidget) -> None:
    if page.property("designV1BuyerWarningRefreshInstalled"):
        _refresh_compact_buyer_warning(window)
        return
    page.setProperty("designV1BuyerWarningRefreshInstalled", True)

    window_ref = weakref.ref(window)
    page_ref = weakref.ref(page)

    table = getattr(window, "table", None)
    if table is not None:
        table.itemSelectionChanged.connect(
            lambda ref=window_ref: _schedule_refresh(ref)
        )
        model = table.model()
        if model is not None:
            # Queue reloads block table signals and then call the selection
            # handler directly. Model changes provide a reliable final refresh
            # after the rebuilt selection and current invoice are synchronized.
            model.modelReset.connect(lambda ref=window_ref: _schedule_refresh(ref))
            model.layoutChanged.connect(lambda ref=window_ref: _schedule_refresh(ref))
            model.rowsInserted.connect(
                lambda *_args, ref=window_ref: _schedule_refresh(ref)
            )

    segment = getattr(window, "status_segment_control", None)
    if segment is not None and hasattr(segment, "changed"):
        segment.changed.connect(
            lambda _key, ref=window_ref: _schedule_refresh(ref)
        )

    center_stack = getattr(window, "center_stack", None)
    if center_stack is not None:
        stack_ref = weakref.ref(center_stack)
        center_stack.currentChanged.connect(
            lambda _index, wref=window_ref, pref=page_ref, sref=stack_ref: QTimer.singleShot(
                0,
                lambda: _refresh_visible_review_from_refs(wref, pref, sref),
            )
        )

    _refresh_compact_buyer_warning(window)
    _schedule_refresh(window_ref)


def apply_design_v1_review_task_closure(page: QWidget | None) -> None:
    """Enforce final Review task ownership and synchronized warning disclosure."""
    if page is None or not isValid(page) or page.property("designV1ReviewTaskClosureApplied"):
        return
    window = page.window()
    if window is None or not isValid(window):
        return
    if page is not getattr(window, "review_page", None):
        return
    if not hasattr(window, "table"):
        return

    page.setProperty("designV1ReviewTaskClosureApplied", True)
    _hide_redundant_review_header(window)
    _remove_cross_workflow_actions(window)
    _remove_company_action(window)
    _install_warning_refresh(window, page)



# ── Review feedback normalization (merged from review_feedback_fixes) ──
PARTY_LABEL_WIDTH = 48


def _find_layout_containing(layout: QLayout | None, widget: QWidget):
    if layout is None:
        return None
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget:
            return layout
        nested = item.layout()
        if nested is not None:
            found = _find_layout_containing(nested, widget)
            if found is not None:
                return found
    return None


def _clear_layout(layout: QLayout, preserve: set[QWidget] | None = None) -> None:
    preserve = preserve or set()
    while layout.count():
        item = layout.takeAt(0)
        nested = item.layout()
        widget = item.widget()
        if nested is not None:
            _clear_layout(nested, preserve)
            nested.deleteLater()
        elif widget is not None:
            if widget in preserve:
                widget.setParent(None)
            else:
                widget.deleteLater()


def _field_key(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setProperty("class", "DetailFieldKey")
    label.setFixedWidth(PARTY_LABEL_WIDTH)
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return label


def _replace_summary_parties(window) -> None:
    detail = window._detail_panel
    if detail.property("summaryPartiesConsolidated"):
        return
    detail.setProperty("summaryPartiesConsolidated", True)

    summary_layout = detail.summary_card.layout()
    old_seller = detail.lbl_sum_seller
    seller_layout = _find_layout_containing(summary_layout, old_seller)
    if seller_layout is None:
        return

    seller_value = ElidedTextLabel("—", detail.summary_card)
    seller_value.setProperty("class", "DetailSeller")
    seller_value.setAccessibleName("销售方")
    seller_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    seller_layout.replaceWidget(old_seller, seller_value)
    old_seller.hide()
    old_seller.deleteLater()
    seller_layout.insertWidget(0, _field_key("销售方", detail.summary_card))
    detail.lbl_sum_seller = seller_value
    window.lbl_sum_seller = seller_value

    buyer_row = QHBoxLayout()
    buyer_row.setContentsMargins(0, 0, 0, 0)
    buyer_row.setSpacing(8)
    buyer_row.addWidget(_field_key("购买方", detail.summary_card))
    buyer_value = ElidedTextLabel("—", detail.summary_card)
    buyer_value.setProperty("class", "DetailParty")
    buyer_value.setAccessibleName("购买方")
    buyer_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    buyer_row.addWidget(buyer_value, 1)

    seller_row_index = 2
    for index in range(summary_layout.count()):
        if summary_layout.itemAt(index).layout() is seller_layout:
            seller_row_index = index
            break
    summary_layout.insertLayout(seller_row_index + 1, buyer_row)
    detail.lbl_sum_buyer = buyer_value
    window.lbl_sum_buyer = buyer_value

    date_layout = _find_layout_containing(summary_layout, detail.lbl_sum_date)
    if date_layout is not None:
        date_index = date_layout.indexOf(detail.lbl_sum_date)
        date_layout.insertWidget(max(0, date_index), _field_key("费用日期", detail.summary_card))
        detail.lbl_sum_date.setAccessibleName("费用日期")

    # The number already belongs to the complete field grid below. Keeping it in
    # the summary duplicates information and consumes the narrow header height.
    detail.lbl_sum_number.hide()
    detail.lbl_sum_number.setProperty("summaryDuplicateHidden", True)

    detail.summary_card.layout().setSpacing(6)
    detail.fixed_header_container.setMaximumHeight(360)


def _rebuild_review_actions(window) -> None:
    detail = window._detail_panel
    if detail.property("reviewActionsReflowed"):
        return
    detail.setProperty("reviewActionsReflowed", True)

    old_layout = detail.inline_review_layout
    while old_layout.count():
        item = old_layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(detail.summary_card)

    row = QFrame(detail.summary_card)
    row.setObjectName("ReviewActionRow")
    row.setProperty("class", "ReviewActionRow")
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)

    # Decisions must be visible together. A stacked primary action wastes a
    # full row and separates the three mutually-exclusive choices.
    detail.btn_app.setMinimumWidth(0)
    detail.btn_app.setMaximumWidth(16777215)
    detail.btn_app.setFixedHeight(36)
    detail.btn_app.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    font = detail.btn_app.font()
    font.setBold(True)
    detail.btn_app.setFont(font)
    row_layout.addWidget(detail.btn_app, 4)

    for button in (detail.btn_ign, detail.btn_err):
        button.setMinimumWidth(0)
        button.setMaximumWidth(16777215)
        button.setFixedHeight(36)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row_layout.addWidget(button, 3)
    detail.btn_inline_more.setFixedSize(40, 36)
    row_layout.addWidget(detail.btn_inline_more, 0)

    old_layout.addWidget(row, 1)
    detail.review_action_row = row
    window.review_action_row = row


def _show_complete_core_fields(window) -> None:
    detail = window._detail_panel
    for label in (
        detail.lbl_core_number,
        detail.lbl_core_date,
        detail.lbl_core_amount,
        detail.lbl_core_category,
        detail.lbl_core_buyer,
        detail.lbl_core_seller,
    ):
        label.show()
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    detail.invoice_core_grid.setColumnStretch(0, 0)
    detail.invoice_core_grid.setColumnStretch(1, 1)
    detail.detail_core_section.setProperty("completeCoreFields", True)


def _rebuild_claim_section(window) -> None:
    detail = window._detail_panel
    section = detail.claim_setup_section
    if section.property("claimLayoutReflowed"):
        return
    section.setProperty("claimLayoutReflowed", True)

    preserve = {
        detail.lbl_claim_assignment,
        detail.btn_claim_assignment,
        detail.combo_claims,
        detail.claim_actions_widget,
        detail.new_claim_widget,
        detail.btn_refresh_claims,
        detail.lbl_claim_total,
        detail.lbl_export_summary,
        detail.btn_new_claim_toggle,
    }
    inline_reason = getattr(window, "txt_invoice_reason_inline", None)
    edit_reason = getattr(window, "btn_edit_invoice_reason", None)
    edit_financial = getattr(window, "btn_edit_financial_fields", None)
    preserve.update(
        widget for widget in (inline_reason, edit_reason, edit_financial)
        if isinstance(widget, QWidget)
    )
    layout = section.layout()
    _clear_layout(layout, preserve)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    title = QLabel("当前报销组", section)
    title.setProperty("class", "SectionTitle")
    layout.addWidget(title)

    assignment_row = QHBoxLayout()
    assignment_row.setContentsMargins(0, 0, 0, 0)
    assignment_row.setSpacing(8)
    detail.lbl_claim_assignment.setParent(section)
    detail.lbl_claim_assignment.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    assignment_row.addWidget(detail.lbl_claim_assignment, 1)
    detail.btn_claim_assignment.setParent(section)
    detail.btn_claim_assignment.setMinimumWidth(64)
    detail.btn_claim_assignment.setMaximumWidth(88)
    assignment_row.addWidget(detail.btn_claim_assignment, 0)
    layout.addLayout(assignment_row)

    if isinstance(inline_reason, QWidget):
        inline_reason.setParent(section)
        layout.addWidget(inline_reason)

    reason_actions = [widget for widget in (edit_reason, edit_financial) if isinstance(widget, QWidget)]
    if reason_actions:
        reason_action_row = QHBoxLayout()
        reason_action_row.setContentsMargins(0, 0, 0, 0)
        reason_action_row.setSpacing(8)
        for widget in reason_actions:
            widget.setParent(section)
            reason_action_row.addWidget(widget)
        layout.addLayout(reason_action_row)

    detail.lbl_claim_total.setParent(section)
    detail.lbl_claim_total.setWordWrap(False)
    detail.lbl_claim_total.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    layout.addWidget(detail.lbl_claim_total)

    actions_widget = detail.claim_actions_widget
    actions_widget.setParent(section)
    actions_widget.setObjectName("ClaimActionRow")
    actions_widget.setProperty("class", "ClaimActionRow")
    actions_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    actions = actions_widget.layout()
    while actions.count():
        item = actions.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(actions_widget)
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(8)
    for button, minimum in (
        (detail.btn_add_to_claim, 84),
        (detail.btn_export, 64),
        (detail.btn_delete_claim, 82),
    ):
        button.setParent(actions_widget)
        button.setMinimumWidth(minimum)
        button.setMaximumWidth(120)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        actions.addWidget(button, 1)
    layout.addWidget(actions_widget)

    detail.new_claim_widget.setParent(section)
    layout.addWidget(detail.new_claim_widget)

    detail.combo_claims.setParent(section)
    detail.combo_claims.hide()
    detail.btn_refresh_claims.setParent(section)
    detail.btn_refresh_claims.hide()
    detail.lbl_export_summary.setParent(section)
    detail.lbl_export_summary.hide()
    detail.btn_new_claim_toggle.setParent(section)
    detail.btn_new_claim_toggle.hide()

    section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    detail.claim_section_title = title
    detail.claim_action_row = actions

    content = detail.reimbursement_scroll.widget()
    if content is not None and content.layout() is not None:
        content.layout().setContentsMargins(12, 12, 12, 12)
        content.layout().setSpacing(12)


def _sync_seller_tooltips(window) -> None:
    table = getattr(window, "table", None)
    if table is None or table.columnCount() <= 4:
        return
    for row in range(table.rowCount()):
        item = table.item(row, 4)
        if item is not None:
            full_text = item.text()
            if item.toolTip() != full_text:
                item.setToolTip(full_text)


def _install_seller_tooltip_sync(window) -> None:
    table = window.table
    if table.property("sellerTooltipSyncInstalled"):
        return
    table.setProperty("sellerTooltipSyncInstalled", True)
    model = table.model()
    refresh = lambda *_args: QTimer.singleShot(0, lambda: _sync_seller_tooltips(window))
    model.rowsInserted.connect(refresh)
    model.modelReset.connect(refresh)
    model.dataChanged.connect(refresh)
    _sync_seller_tooltips(window)


def _show_shortcut_popup(window) -> None:
    popup = window.shortcut_disclosure
    button = window.btn_shortcut_help
    if popup.isVisible():
        popup.hide()
        return

    popup.set_expanded(False)
    popup.adjustSize()
    anchor = button.mapToGlobal(QPoint(0, 0))
    popup_size = popup.sizeHint()
    x = anchor.x()
    y = anchor.y() - popup_size.height() - 8
    screen = QGuiApplication.screenAt(anchor)
    if screen is not None:
        available = screen.availableGeometry()
        x = max(available.left() + 8, min(x, available.right() - popup_size.width() - 8))
        y = max(available.top() + 8, min(y, available.bottom() - popup_size.height() - 8))
    popup.move(x, y)
    popup.show()
    popup.raise_()


def _normalize_help_entry(window) -> None:
    button = getattr(window, "btn_shortcut_help", None)
    popup = getattr(window, "shortcut_disclosure", None)
    if button is None or popup is None or button.property("unifiedHelpEntry"):
        return
    button.setProperty("unifiedHelpEntry", True)
    button.setText("帮助")
    button.setAccessibleName("帮助")
    button.setToolTip("查看审核快捷键")
    button.setIconSize(QSize(16, 16))
    button.setFlat(False)
    button.setStyleSheet("")
    button.setCursor(Qt.PointingHandCursor)
    button.setMinimumHeight(36)
    try:
        button.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    button.clicked.connect(lambda _checked=False: _show_shortcut_popup(window))
    window._show_shortcut_help_popup = lambda: _show_shortcut_popup(window)


def _feedback_detail_width(window) -> int:
    width = max(0, window.width())
    if width <= 1366:
        return 352
    if width <= 1440:
        return 380
    return 400


def _apply_responsive_detail_width(window) -> None:
    detail = getattr(window, "_detail_panel", None)
    if detail is None:
        return
    target = _feedback_detail_width(window)
    detail.setMinimumWidth(target)
    detail.setMaximumWidth(target)


class _ReviewResizeFilter(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Resize:
            # InvoiceReviewApp applies its legacy metrics in resizeEvent. Run
            # once more afterwards so the physical-review width wins.
            QTimer.singleShot(0, lambda: _apply_responsive_detail_width(self.window))
        return False


def _install_responsive_detail_width(window) -> None:
    if hasattr(window, "_review_feedback_resize_filter"):
        _apply_responsive_detail_width(window)
        return
    resize_filter = _ReviewResizeFilter(window)
    window.installEventFilter(resize_filter)
    window._review_feedback_resize_filter = resize_filter
    _apply_responsive_detail_width(window)


def sync_review_feedback_state(window) -> None:
    """Refresh visual values after the app has populated the selected invoice."""
    detail = getattr(window, "_detail_panel", None)
    if detail is None:
        return
    invoice = getattr(window, "current_invoice", None) or {}
    seller = str(invoice.get("seller_name") or "").strip()
    buyer = str(invoice.get("buyer_name") or "").strip()
    expense_date = str(invoice.get("expense_date") or invoice.get("invoice_date") or "").strip()
    amount = str(invoice.get("total_amount") or "").strip()
    category = str(invoice.get("category") or "未分类").strip()

    if hasattr(detail, "lbl_sum_seller"):
        detail.lbl_sum_seller.set_value(seller or "—")
    if hasattr(detail, "lbl_sum_buyer"):
        detail.lbl_sum_buyer.set_value(buyer or "—")
    detail.lbl_sum_category.setText(category or "未分类")
    detail.lbl_sum_category.setToolTip(category)
    detail.lbl_sum_date.setText(expense_date or "—")
    detail.lbl_sum_date.setToolTip(expense_date)

    detail.lbl_core_date.set_value(expense_date or "—")
    detail.lbl_core_amount.set_value(detail._format_amount_display(amount))
    detail.lbl_core_seller.set_value(seller or "—")
    detail.lbl_core_buyer.set_value(buyer or "—")

    claim_text = detail.lbl_claim_total.text().strip()
    detail.lbl_claim_total.setToolTip(claim_text)
    # Keep the full group context supplied by the app; the compact label only
    # describes the action and no longer repeats a potentially long name.
    valid_claims = any(
        isinstance(detail.combo_claims.itemData(index), int)
        and detail.combo_claims.itemData(index) > 0
        for index in range(detail.combo_claims.count())
    )
    detail.claim_empty_hint.setVisible(not valid_claims)
    _sync_seller_tooltips(window)


def apply_review_feedback_fixes(window) -> None:
    """Apply all physical-review corrections once to the review page."""
    page = getattr(window, "review_page", None)
    if page is None or page.property("reviewFeedbackFixesApplied"):
        return
    page.setProperty("reviewFeedbackFixesApplied", True)
    _replace_summary_parties(window)
    _rebuild_review_actions(window)
    _show_complete_core_fields(window)
    _rebuild_claim_section(window)
    _install_seller_tooltip_sync(window)
    _normalize_help_entry(window)
    _install_responsive_detail_width(window)
    window._detail_panel.combo_claims.currentIndexChanged.connect(
        lambda _index: QTimer.singleShot(0, lambda: sync_review_feedback_state(window))
    )
    sync_review_feedback_state(window)

# ── Review toolbar and filters (merged from review_toolbar_filter_fixes) ──
COLUMN_WIDTHS = {
    0: 68,
    1: 62,
    2: 86,
    3: 84,
    SELLER_COLUMN: 260,
    INVOICE_NUMBER_COLUMN: 190,
}
STATUS_FILTER_WIDTHS = {
    "all": 86,
    "to_review": 92,
    "approved": 92,
    "ignored": 86,
    "error": 86,
}


class ReimbursementTitleDialog(QDialog):
    """Edit the expected reimbursement buyer title without exposing config.json."""

    def __init__(self, reimbursement_cfg: dict | None = None, parent=None):
        super().__init__(parent)
        cfg = dict(reimbursement_cfg or {})
        self.setWindowTitle("报销抬头设置")
        self.setModal(True)
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel("报销抬头")
        title.setProperty("class", "DialogTitle")
        root.addWidget(title)
        hint = QLabel("用于核对发票购买方是否与实际报销单位一致。此设置只保存在本地。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #667085; font-size: 12px;")
        root.addWidget(hint)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.txt_buyer_name = QLineEdit(str(cfg.get("buyer_name") or ""))
        self.txt_buyer_name.setPlaceholderText("例如：示例科技有限公司")
        self.txt_buyer_name.setClearButtonEnabled(True)
        self.txt_tax_id = QLineEdit(str(cfg.get("buyer_tax_id") or ""))
        self.txt_tax_id.setPlaceholderText("选填，用于后续核对或导出")
        self.txt_tax_id.setClearButtonEnabled(True)
        self.chk_strict = QCheckBox("发现购买方不一致时在审核页提醒")
        self.chk_strict.setChecked(bool(cfg.get("strict_buyer_check", False)))
        form.addRow("单位名称", self.txt_buyer_name)
        form.addRow("纳税人识别号", self.txt_tax_id)
        form.addRow("", self.chk_strict)
        root.addLayout(form)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = make_button("取消", variant="secondary", min_width=80)
        save = make_button("保存", variant="primary", min_width=96)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept_if_valid)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

    def _accept_if_valid(self) -> None:
        if self.chk_strict.isChecked() and not self.txt_buyer_name.text().strip():
            QMessageBox.warning(self, "缺少单位名称", "启用抬头核对前，请填写报销单位名称。")
            self.txt_buyer_name.setFocus()
            return
        self.accept()

    def values(self) -> tuple[str, str, bool]:
        return (
            self.txt_buyer_name.text().strip(),
            self.txt_tax_id.text().strip(),
            self.chk_strict.isChecked(),
        )


def _set_compact_button(button: QWidget | None, minimum: int, maximum: int) -> None:
    if button is None:
        return
    button.setMinimumWidth(minimum)
    button.setMaximumWidth(maximum)
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


def _fit_material_action(button: QWidget | None, maximum: int = 96) -> None:
    if button is None:
        return
    button.ensurePolished()
    text = str(getattr(button, "text", lambda: "")() or "")
    required = button.fontMetrics().horizontalAdvance(text) + 24
    width = max(56, min(maximum, required))
    button.setMinimumWidth(width)
    button.setMaximumWidth(width)
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


def _normalize_material_status_line(status_line, *, action_maximum: int = 96) -> None:
    if status_line is None:
        return
    status_line.setMinimumWidth(0)
    status_line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    layout = status_line.layout()
    if layout is not None:
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

    label = getattr(status_line, "lbl_label", None)
    if label is not None:
        label.setMinimumWidth(40)
        label.setMaximumWidth(40)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    value = getattr(status_line, "lbl_status", None)
    if value is not None:
        value.setMinimumWidth(32)
        value.setMaximumWidth(16777215)
        value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        value.setToolTip(value.text())

    action = getattr(status_line, "_action_widget", None)
    _fit_material_action(action, action_maximum)
    if action is not None:
        action.show()
    if layout is not None:
        layout.setStretch(0, 0)
        layout.setStretch(1, 1)
        if action is not None:
            action_index = layout.indexOf(action)
            if action_index >= 0:
                layout.setStretch(action_index, 0)


def _repair_material_rows(window) -> None:
    """Keep material labels, states and actions visible in the narrow detail pane."""
    detail = getattr(window, "_detail_panel", None)
    if detail is None:
        return

    for attr in ("original_card", "evidence_card", "combo_supporting_docs"):
        widget = getattr(detail, attr, None)
        if widget is not None:
            widget.hide()

    for attr, maximum in (
        ("btn_open_file", 72),
        ("btn_locate_file", 72),
        ("btn_add_attachment", 72),
        ("btn_retry_download", 72),
        ("btn_open_extra_files", 72),
        ("btn_add_evidence", 96),
    ):
        _fit_material_action(getattr(detail, attr, None), maximum)

    _normalize_material_status_line(
        getattr(detail, "original_status_line", None),
        action_maximum=72,
    )
    _normalize_material_status_line(
        getattr(detail, "evidence_status_line", None),
        action_maximum=96,
    )


def _clarify_review_toolbar(window) -> None:
    import_button = getattr(window, "btn_import_local", None)
    scan_button = getattr(window, "btn_scan_email", None)
    if import_button is not None:
        import_button.setText("导入")
        import_button.setToolTip("导入发票：本地文件、手机上传或邮箱扫描")
        import_button.setAccessibleName("导入发票")
        _set_compact_button(import_button, 76, 92)

    for attr, text, tooltip in (
        ("action_import_local", "本地文件", "选择 PDF、OFD、图片或压缩包导入"),
        ("action_import_mobile", "手机上传", "打开手机扫码上传"),
        ("action_import_mail", "邮箱扫描", "进入导入中心查看邮箱账号和扫描结果"),
    ):
        action = getattr(window, attr, None)
        if action is not None:
            action.setText(text)
            action.setToolTip(tooltip)

    if scan_button is not None:
        scan_button.setText("扫描邮箱")
        scan_button.setToolTip("扫描已配置邮箱中的新发票")
        scan_button.setAccessibleName("扫描邮箱")
        scan_button.show()
        _set_compact_button(scan_button, 88, 108)
    scan_action = getattr(window, "action_scan_email", None)
    if scan_action is not None:
        scan_action.setText("扫描邮箱")
        scan_action.setToolTip("扫描已配置邮箱中的新发票")

    export_button = getattr(window, "btn_toolbar_export", None)
    more_button = getattr(window, "btn_more", None)
    _set_compact_button(export_button, 72, 88)
    if more_button is not None:
        more_button.setText("更多")
        more_button.setToolTip("更多审核与诊断操作")
        _set_compact_button(more_button, 72, 88)

    toolbar = getattr(window, "workbench_top_toolbar", None)
    if toolbar is not None and toolbar.layout() is not None:
        toolbar.layout().setSpacing(6)


def _compact_status_filters(window) -> None:
    bar = getattr(window, "filter_bar_widget", None)
    if bar is None:
        return
    bar.setFixedHeight(40)
    bar.setToolTip("快速按审核状态筛选；字段筛选可直接点击表格列标题")
    layout = bar.layout()
    if layout is not None:
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

    for status, card in getattr(window, "filter_buttons", {}).items():
        width = STATUS_FILTER_WIDTHS.get(status, 86)
        card.setFixedHeight(30)
        card.setMinimumWidth(width)
        card.setMaximumWidth(width)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        title = getattr(card, "_lbl_title", None)
        card.setToolTip(f"快速筛选：{title.text() if title is not None else status}")
        card_layout = card.layout()
        if card_layout is not None:
            card_layout.setContentsMargins(9, 3, 9, 3)
            card_layout.setSpacing(4)

    advanced = getattr(window, "btn_advanced_filter", None)
    if advanced is not None:
        advanced.hide()
        advanced.setToolTip("字段筛选已移到表格列标题")

    reset = getattr(window, "btn_reset_filters", None)
    if reset is not None:
        reset.setText("清除筛选")
        reset.setToolTip("清除状态、列和搜索筛选")
        _set_compact_button(reset, 78, 92)

    sort_hint = getattr(window, "lbl_record_sort", None)
    if sort_hint is not None:
        sort_hint.setText("点击列标题可筛选")
        sort_hint.setToolTip("点击任意列标题筛选；拖动列边界调整宽度")


def _decorate_column_headers(window) -> None:
    """Add a visible filter affordance without replacing established header copy."""
    table = getattr(window, "table", None)
    if table is None:
        return
    header = table.horizontalHeader()
    header.setSectionsClickable(True)
    header.setIconSize(QSize(12, 12))
    header.setToolTip("点击任意列标题筛选；拖动列边界调整宽度")
    filter_icon = IconProvider.icon("filter")
    for column in range(table.columnCount()):
        item = table.horizontalHeaderItem(column)
        if item is not None:
            item.setIcon(filter_icon)


def _sync_reset_visibility(window) -> None:
    reset = getattr(window, "btn_reset_filters", None)
    if reset is None:
        return
    active = (
        getattr(window, "current_filter", "all") != "all"
        or has_active_filters(getattr(window, "column_filters", {}) or {})
        or bool(getattr(window, "txt_search", None) and window.txt_search.text().strip())
    )
    reset.setVisible(active)


def _open_filter_from_header_click(window, section: int) -> None:
    """Open the existing popup for a full-cell header click.

    QHeaderView emits sectionClicked only for a click, not for a resize drag, so
    this keeps column resizing intact without installing a native event filter.
    """
    if section < 0:
        return
    popup = getattr(window, "_column_filter_popup", None)
    try:
        if popup is not None and popup.isVisible():
            return
    except RuntimeError:
        pass

    header = window.table.horizontalHeader()
    marker_x = header.sectionViewportPosition(section) + header.sectionSize(section) - 8
    window._column_filter_header_press_pos = QPoint(marker_x, max(0, header.height() // 2))
    window._show_column_filter_popup(section)


def _install_header_filter_decoration(window) -> None:
    if getattr(window, "_column_header_decoration_installed", False):
        _decorate_column_headers(window)
        _sync_reset_visibility(window)
        return
    window._column_header_decoration_installed = True

    original = window._refresh_column_filter_headers

    @wraps(original)
    def refresh_headers(*args, **kwargs):
        result = original(*args, **kwargs)
        _decorate_column_headers(window)
        _sync_reset_visibility(window)
        return result

    window._refresh_column_filter_headers = refresh_headers
    for card in getattr(window, "filter_buttons", {}).values():
        card.clicked.connect(lambda: QTimer.singleShot(0, lambda: _sync_reset_visibility(window)))
    window.txt_search.textChanged.connect(lambda _text: _sync_reset_visibility(window))

    header = window.table.horizontalHeader()
    header.sectionClicked.connect(
        lambda section, target=window: _open_filter_from_header_click(target, section)
    )

    _decorate_column_headers(window)
    _sync_reset_visibility(window)


def _apply_table_column_widths(window) -> None:
    table = getattr(window, "table", None)
    if table is None:
        return
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    for column, width in COLUMN_WIDTHS.items():
        header.setSectionResizeMode(column, QHeaderView.Interactive)
        table.setColumnWidth(column, width)
    if hasattr(window, "_min_column_widths"):
        window._min_column_widths.update(COLUMN_WIDTHS)
        window._min_column_widths[SELLER_COLUMN] = 180
        window._min_column_widths[INVOICE_NUMBER_COLUMN] = 178
    table.setToolTip("点击列标题筛选；销售方等长文本可悬停查看完整内容")


def _install_column_width_contract(window) -> None:
    _apply_table_column_widths(window)


def _save_reimbursement_title(window, buyer_name: str, buyer_tax_id: str, strict: bool) -> None:
    cfg = dict(getattr(window, "config", {}) or {})
    reimbursement_cfg = dict(cfg.get("reimbursement") or {})
    reimbursement_cfg.update(
        {
            "buyer_name": buyer_name.strip(),
            "buyer_tax_id": buyer_tax_id.strip(),
            "strict_buyer_check": bool(strict),
        }
    )
    cfg["reimbursement"] = reimbursement_cfg
    save_config(cfg)
    window.config = cfg
    if hasattr(window, "_desktop_settings_cfg"):
        window._desktop_settings_cfg = dict(cfg)


def _refresh_buyer_warning(window) -> None:
    BuyerWarningController.for_window(window).refresh()


def _open_reimbursement_title_dialog(window) -> None:
    cfg = (getattr(window, "config", {}) or {}).get("reimbursement", {})
    dialog = ReimbursementTitleDialog(cfg, window)
    if dialog.exec() != QDialog.Accepted:
        return
    buyer_name, buyer_tax_id, strict = dialog.values()
    try:
        _save_reimbursement_title(window, buyer_name, buyer_tax_id, strict)
    except OSError as exc:
        QMessageBox.critical(window, "保存失败", f"无法保存报销抬头设置：{exc}")
        return
    _refresh_buyer_warning(window)
    QMessageBox.information(window, "已保存", "报销抬头设置已保存到本地。")


def _install_buyer_title_entry(window) -> None:
    detail = getattr(window, "_detail_panel", None)
    if detail is None or not hasattr(detail, "lbl_buyer_warning"):
        return
    if detail.property("buyerTitleEntryInstalled"):
        _refresh_buyer_warning(window)
        return
    detail.setProperty("buyerTitleEntryInstalled", True)

    warning = detail.lbl_buyer_warning
    parent_layout = _find_layout_containing(detail.summary_card.layout(), warning)
    if parent_layout is not None:
        row = QFrame(detail.summary_card)
        row.setObjectName("BuyerWarningActionRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        parent_layout.replaceWidget(warning, row)
        warning_scroll = QScrollArea(row)
        warning_scroll.setObjectName("BuyerWarningScrollArea")
        warning_scroll.setWidgetResizable(True)
        warning_scroll.setFrameShape(QFrame.NoFrame)
        warning_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        warning_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        warning_scroll.setMinimumWidth(0)
        warning_scroll.setMinimumHeight(44)
        warning_scroll.setMaximumHeight(76)
        warning_scroll.setWidget(warning)
        row_layout.addWidget(warning_scroll, 1)
        edit_button = make_button("设置抬头", variant="secondary", min_width=76)
        edit_button.setMaximumWidth(92)
        edit_button.setFixedHeight(30)
        edit_button.clicked.connect(lambda _checked=False: _open_reimbursement_title_dialog(window))
        row_layout.addWidget(edit_button, 0, Qt.AlignTop)
        row.setMinimumHeight(44)
        row.setMaximumHeight(76)
        detail.buyer_warning_action_row = row
        detail.buyer_warning_scroll = warning_scroll
        detail.btn_edit_reimbursement_title = edit_button
        window.btn_edit_reimbursement_title = edit_button

    BuyerWarningController.for_window(window).refresh()


def apply_review_toolbar_filter_fixes(page: QWidget) -> None:
    """Apply the physical-review fixes once after the review tree is complete."""
    if page is None or page.property("reviewToolbarFilterFixesApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    if not hasattr(window, "table") or not hasattr(window, "filter_buttons"):
        return
    page.setProperty("reviewToolbarFilterFixesApplied", True)
    _clarify_review_toolbar(window)
    _compact_status_filters(window)
    _install_header_filter_decoration(window)
    _install_column_width_contract(window)
    _repair_material_rows(window)
    _install_buyer_title_entry(window)

# ── Review baseline/HCI pipeline (merged from review_baseline_pipeline) ──

# ── Review attachment/company action closure (merged from review_settings_issue_fixes) ──
def _remove_from_layout(widget: QWidget) -> None:
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        layout.removeWidget(widget)


def _remove_status_bar_version(window) -> None:
    """Remove the clipped version chip from the review footer."""
    label = getattr(window, "lbl_version", None)
    if label is not None:
        _remove_from_layout(label)
        label.hide()
        label.setParent(window)
        label.setProperty("reviewFooterVersionRemoved", True)

    container = getattr(window, "status_actions_container", None)
    if container is not None:
        container.setMinimumWidth(0)
        container.setStyleSheet("background: transparent; border: none;")
        container.adjustSize()


def _place_secondary_action(status_line, button: QWidget) -> None:
    """Place a non-primary action in the final material row without floating."""
    _remove_from_layout(button)
    button.setParent(status_line)
    if status_line.layout().indexOf(button) < 0:
        status_line.layout().addWidget(button)
    button.show()


def _hide_non_primary_action(status_line, button: QWidget) -> None:
    if status_line._action_widget is button:
        return
    _remove_from_layout(button)
    button.hide()
    button.setParent(status_line)


def _stabilize_original_file_actions(detail, *, has_file: bool) -> None:
    """Keep original-file controls inside the Materials / Original row."""
    status_line = detail.original_status_line
    primary = status_line._action_widget

    detail.btn_open_file.setText("打开")
    detail.btn_open_file.setToolTip("打开当前发票原件")
    detail.btn_add_attachment.setText("替换原件" if has_file else "补充原件")
    detail.btn_add_attachment.setToolTip(
        "选择本地文件替换当前发票原件" if has_file else "选择本地文件补充发票原件"
    )
    detail.btn_add_attachment.setMinimumWidth(84)
    detail.btn_retry_download.setText("重新下载")
    detail.btn_retry_download.setToolTip("重新从原始来源下载发票原件")
    detail.btn_retry_download.setMinimumWidth(80)

    _hide_non_primary_action(status_line, detail.btn_locate_file)

    if primary in (detail.btn_open_file, detail.btn_retry_download):
        _place_secondary_action(status_line, detail.btn_add_attachment)
    else:
        _hide_non_primary_action(status_line, detail.btn_open_file)
        _hide_non_primary_action(status_line, detail.btn_retry_download)

    if primary is not detail.btn_open_file:
        _hide_non_primary_action(status_line, detail.btn_open_file)
    if primary is not detail.btn_retry_download:
        _hide_non_primary_action(status_line, detail.btn_retry_download)


def _remove_review_company_action(detail) -> None:
    """Keep buyer mismatch information but remove the Settings shortcut button."""
    button = getattr(detail, "btn_edit_reimbursement_title", None)
    if button is None:
        return
    # The control is removed from the layout and hidden below.  Disconnecting
    # all slots without knowing the original callable makes PySide emit a
    # RuntimeWarning when another compatibility pass already detached it.
    # A hidden, disabled control cannot be activated by the user and remains
    # owned by the detail panel for safe Qt lifetime management.
    button.setEnabled(False)
    _remove_from_layout(button)
    button.hide()
    button.setParent(detail)
    button.setProperty("reviewCompanyActionRemoved", True)


def apply_review_attachment_action_fix(page: QWidget | None) -> None:
    """Fix escaped attachment controls and remove the company Settings shortcut."""
    if page is None or page.property("reviewAttachmentActionFixApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    detail = getattr(window, "_detail_panel", None)
    if detail is None or not hasattr(detail, "original_status_line"):
        return

    page.setProperty("reviewAttachmentActionFixApplied", True)
    original_set_attachment_state = detail.set_attachment_state

    @wraps(original_set_attachment_state)
    def set_attachment_state(
        *,
        has_file: bool = False,
        has_url: bool = False,
        file_name: str = "",
        file_path: str = "",
        can_download: bool = False,
    ):
        result = original_set_attachment_state(
            has_file=has_file,
            has_url=has_url,
            file_name=file_name,
            file_path=file_path,
            can_download=can_download,
        )
        _stabilize_original_file_actions(detail, has_file=bool(has_file))
        return result

    detail.set_attachment_state = set_attachment_state
    _remove_review_company_action(detail)
    _remove_status_bar_version(window)




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
    "apply_design_v1_review_task_closure",
    "_refresh_compact_buyer_warning",
    "_buyer_warning_summary",
    "apply_review_feedback_fixes",
    "sync_review_feedback_state",
    "apply_review_toolbar_filter_fixes",
    "ReimbursementTitleDialog",
    "_repair_material_rows",
    "_save_reimbursement_title",
    "_sync_seller_tooltips",
    "apply_review_attachment_action_fix",
]
