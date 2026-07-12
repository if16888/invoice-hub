"""Bounded, user-resizable invoice-table column widths.

The legacy workbench stretched the seller column to consume every spare pixel.
That made long seller names dominate the review table and also undid manual
column resizing whenever the table viewport changed.  Install a bounded
replacement for that legacy adjustment while preserving interactive resizing.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


SELLER_COLUMN = 4
INVOICE_NUMBER_COLUMN = 5
SELLER_DEFAULT_WIDTH = 260
SELLER_MIN_WIDTH = 180
SELLER_MAX_WIDTH = 320
INVOICE_NUMBER_DEFAULT_WIDTH = 190
INVOICE_NUMBER_MIN_WIDTH = 160


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


__all__ = [
    "SELLER_DEFAULT_WIDTH",
    "SELLER_MIN_WIDTH",
    "SELLER_MAX_WIDTH",
    "apply_review_table_width_contract",
]
