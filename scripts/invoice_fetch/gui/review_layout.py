"""Responsive review workbench layout controller.

The physical Windows review found that collapsing the application sidebar made
more horizontal space available, but the detail pane stayed locked to the old
fixed width.  This module replaces that fixed-width resize hook with a bounded
splitter reflow that gives part of the reclaimed rail width to the detail pane
while preserving a useful invoice-table and preview area.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QHeaderView, QLayout, QSplitter, QSizePolicy, QWidget

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
    target = _base_detail_width(window, available)

    # A 1366-wide desktop is already space-constrained. Keep its historical
    # 352 px detail contract even when the rail defaults to icon-only; only use
    # reclaimed sidebar width on larger desktops.
    if window_width > COMPACT_DESKTOP_MAX_WIDTH and _nav_is_collapsed(window):
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
        if event.type() == QEvent.Resize:
            self.schedule()
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
        if applying:
            return
        applying = True
        try:
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
            applying = False

    # app.eventFilter and _on_header_section_resized resolve this hook at call
    # time, so the adaptive contract runs for viewport resizes and user drags
    # without installing another native event filter.
    window._adjust_column_4_width = fill_remainder
    fill_remainder()
    QTimer.singleShot(0, fill_remainder)

    table.setProperty("reviewRemainderFillApplied", True)
    table.setToolTip("点击列标题筛选；销售方可拖动调整，发票号自动利用剩余宽度")


def apply_review_workspace_closure(page: QWidget) -> None:
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
    "apply_review_workspace_closure",
    "_reflow_review_detail",
    "_target_detail_width",
]
