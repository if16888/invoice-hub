"""Design Baseline v1.0 closure for the dense Review workspace.

This module resolves three remaining structural gaps without changing invoice
business logic:

* replace the compatibility-only vertical splitter with a real user-resizable
  splitter between the invoice list and document preview;
* remove the legacy ``Load all`` control from the visible product surface while
  preserving the existing incremental-loading callbacks;
* make the final invoice-number column consume otherwise-unused table width so
  the record surface does not end in a large blank band.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHeaderView, QLayout, QSizePolicy, QSplitter, QWidget

from .workbench_layout import clamp_vertical_split


RECORD_MIN_HEIGHT = 260
RECORD_MAX_HEIGHT = 480
PREVIEW_MIN_HEIGHT = 240
SELLER_COLUMN = 4
INVOICE_NUMBER_COLUMN = 5


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
    # Keep the compatibility object alive because legacy loading code and tests
    # still update its text/visibility. WA_DontShowOnScreen prevents that object
    # from becoming a product-surface control after it has been removed from the
    # status-bar layout.
    button.setAttribute(Qt.WA_DontShowOnScreen, True)


def _fill_table_remainder(window) -> None:
    table = getattr(window, "table", None)
    if table is None or table.columnCount() <= INVOICE_NUMBER_COLUMN:
        return

    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    for column in range(INVOICE_NUMBER_COLUMN):
        header.setSectionResizeMode(column, QHeaderView.Interactive)
    header.setSectionResizeMode(INVOICE_NUMBER_COLUMN, QHeaderView.Stretch)

    min_widths = getattr(window, "_min_column_widths", None)
    if isinstance(min_widths, dict):
        min_widths[SELLER_COLUMN] = max(180, int(min_widths.get(SELLER_COLUMN, 180)))
        min_widths[INVOICE_NUMBER_COLUMN] = max(178, int(min_widths.get(INVOICE_NUMBER_COLUMN, 178)))

    if table.columnWidth(SELLER_COLUMN) < 220:
        table.setColumnWidth(SELLER_COLUMN, 260)
    if table.columnWidth(INVOICE_NUMBER_COLUMN) < 178:
        table.setColumnWidth(INVOICE_NUMBER_COLUMN, 190)

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
    _fill_table_remainder(window)


__all__ = [
    "INVOICE_NUMBER_COLUMN",
    "PREVIEW_MIN_HEIGHT",
    "RECORD_MAX_HEIGHT",
    "RECORD_MIN_HEIGHT",
    "SELLER_COLUMN",
    "apply_review_workspace_closure",
]
