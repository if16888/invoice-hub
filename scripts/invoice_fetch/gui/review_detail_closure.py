"""Final Design Baseline v1.0 ownership contract for Review details.

The earlier migration made every important value visible, but it left the same
invoice facts in both the summary header and the basic-information grid. It also
kept obsolete material-row cards alive behind the two final ``StatusLine`` rows.
This module runs after the other Review migrations and establishes one visible
owner for each fact while preserving the existing business callbacks.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QLayout, QWidget


SUMMARY_OWNED_FIELDS = ("amount", "category", "seller")
DETAIL_OWNED_FIELDS = ("number", "date", "buyer")


def _find_layout_containing(layout: QLayout | None, target: QWidget):
    if layout is None:
        return None
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is target:
            return layout
        nested = item.layout()
        if nested is not None:
            found = _find_layout_containing(nested, target)
            if found is not None:
                return found
    return None


def _remove_nested_layout(parent: QLayout | None, target: QLayout) -> bool:
    if parent is None:
        return False
    for index in range(parent.count() - 1, -1, -1):
        item = parent.itemAt(index)
        nested = item.layout()
        if nested is target:
            parent.takeAt(index)
            return True
        if nested is not None and _remove_nested_layout(nested, target):
            return True
    return False


def _preserve_hidden(widget: QWidget | None, parent: QWidget) -> None:
    if widget is None:
        return
    widget.setParent(parent)
    widget.hide()


def _remove_summary_row(summary_layout: QLayout, widget: QWidget, detail: QWidget) -> None:
    row = _find_layout_containing(summary_layout, widget)
    if row is None:
        widget.hide()
        return
    _remove_nested_layout(summary_layout, row)
    while row.count():
        item = row.takeAt(0)
        child = item.widget()
        nested = item.layout()
        if child is widget:
            _preserve_hidden(child, detail)
        elif child is not None:
            child.deleteLater()
        elif nested is not None:
            nested.deleteLater()
    row.deleteLater()


def _deduplicate_summary(detail) -> None:
    if detail.property("detailSummaryOwnershipApplied"):
        return
    detail.setProperty("detailSummaryOwnershipApplied", True)
    summary_layout = detail.summary_card.layout()

    # Amount, category and seller are the compact decision header. Invoice
    # number, expense date and buyer belong to the complete field grid below.
    _remove_summary_row(summary_layout, detail.lbl_sum_buyer, detail)
    _remove_summary_row(summary_layout, detail.lbl_sum_number, detail)

    date_row = _find_layout_containing(summary_layout, detail.lbl_sum_date)
    if date_row is not None:
        for index in range(date_row.count() - 1, -1, -1):
            item = date_row.itemAt(index)
            child = item.widget()
            if child is detail.lbl_sum_date:
                date_row.removeWidget(child)
                _preserve_hidden(child, detail)
            elif isinstance(child, QLabel) and child.text().strip() in {"费用日期", "|"}:
                date_row.removeWidget(child)
                child.deleteLater()
    else:
        detail.lbl_sum_date.hide()

    detail.lbl_sum_date.setProperty("detailDuplicateHidden", True)
    detail.lbl_sum_buyer.setProperty("detailDuplicateHidden", True)
    detail.lbl_sum_number.setProperty("detailDuplicateHidden", True)
    # Keep the long-standing embedded-header surface contract. Information
    # ownership is now deduplicated without changing the surrounding workbench
    # hierarchy expected by the detail-section integration tests.
    detail.summary_card.setProperty("variant", "embedded")
    detail.summary_card.layout().setSpacing(6)
    detail.fixed_header_container.setMaximumHeight(310)


def _field_position(grid: QGridLayout, field: QWidget) -> tuple[int, QWidget | None]:
    index = grid.indexOf(field)
    if index < 0:
        return -1, None
    row, _column, _row_span, _column_span = grid.getItemPosition(index)
    label_item = grid.itemAtPosition(row, 0)
    label = label_item.widget() if label_item is not None else None
    if label is field:
        label = None
    return row, label


def _remove_core_field(detail, name: str) -> None:
    grid = detail.invoice_core_grid
    field = getattr(detail, f"lbl_core_{name}")
    row, label = _field_position(grid, field)
    if row < 0:
        field.hide()
        return
    grid.removeWidget(field)
    _preserve_hidden(field, detail.detail_core_section)
    field.setProperty("summaryOwned", True)
    if label is not None:
        grid.removeWidget(label)
        label.hide()
        label.deleteLater()
    grid.setRowMinimumHeight(row, 0)
    grid.setRowStretch(row, 0)


def _move_core_field(detail, name: str, target_row: int) -> None:
    grid = detail.invoice_core_grid
    field = getattr(detail, f"lbl_core_{name}")
    _row, label = _field_position(grid, field)
    if label is None:
        return
    grid.removeWidget(label)
    grid.removeWidget(field)
    grid.addWidget(label, target_row, 0)
    grid.addWidget(field, target_row, 1)
    label.show()
    field.show()
    field.setProperty("detailOwned", True)


def _compact_core_information(detail) -> None:
    if detail.property("detailCoreOwnershipApplied"):
        return
    detail.setProperty("detailCoreOwnershipApplied", True)

    for name in SUMMARY_OWNED_FIELDS:
        _remove_core_field(detail, name)
    _move_core_field(detail, "buyer", 2)

    for name in DETAIL_OWNED_FIELDS:
        field = getattr(detail, f"lbl_core_{name}")
        field.show()
        field.setProperty("detailOwned", True)

    detail.invoice_core_grid.setColumnStretch(0, 0)
    detail.invoice_core_grid.setColumnStretch(1, 1)
    detail.invoice_core_grid.setHorizontalSpacing(10)
    detail.invoice_core_grid.setVerticalSpacing(8)

    for label in detail.detail_core_section.findChildren(QLabel):
        if label.text().strip() == "核验字段":
            label.setText("基本信息")
            break


def _detach_legacy_card(detail, attr: str, preserved: tuple[QWidget | None, ...]) -> None:
    card = getattr(detail, attr, None)
    if card is None:
        return
    for widget in preserved:
        if widget is not None and card.isAncestorOf(widget):
            _preserve_hidden(widget, detail)
    card.setParent(None)
    card.deleteLater()
    setattr(detail, attr, None)


def _remove_material_compatibility_surfaces(detail) -> None:
    if detail.property("materialCompatibilitySurfacesRemoved"):
        return
    detail.setProperty("materialCompatibilitySurfacesRemoved", True)

    _detach_legacy_card(
        detail,
        "original_card",
        (
            detail.txt_path,
            detail.btn_open_file,
            detail.btn_locate_file,
            detail.btn_add_attachment,
            detail.btn_retry_download,
        ),
    )
    _detach_legacy_card(
        detail,
        "evidence_card",
        (
            detail.evidence_content_widget,
            detail.btn_open_extra_files,
            detail.btn_add_evidence,
        ),
    )

    for attr in (
        "original_row",
        "original_actions_frame",
        "evidence_row",
        "evidence_actions_frame",
    ):
        setattr(detail, attr, None)

    # The combo remains a compatibility data model for preview callbacks, but it
    # is no longer part of the visible material layout or a hidden UI surface.
    combo = detail.combo_supporting_docs
    layout = _find_layout_containing(detail.layout(), combo)
    if layout is not None:
        layout.removeWidget(combo)
    combo.setParent(detail)
    combo.hide()
    combo.setAttribute(Qt.WA_DontShowOnScreen, True)
    combo.setProperty("compatibilityModelOnly", True)

    for line in (detail.original_status_line, detail.evidence_status_line):
        line.setProperty("finalMaterialRow", True)
        line.lbl_label.setFixedWidth(40)
        line.lbl_status.setSizePolicy(line.lbl_status.sizePolicy())


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.updateGeometry()


def apply_review_detail_closure(page: QWidget) -> None:
    """Apply the final information-ownership and material-row contract."""
    if page is None or page.property("reviewDetailClosureApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    detail = getattr(window, "_detail_panel", None)
    if detail is None:
        return

    page.setProperty("reviewDetailClosureApplied", True)
    _deduplicate_summary(detail)
    _compact_core_information(detail)
    _remove_material_compatibility_surfaces(detail)
    _repolish(detail.summary_card)
    _repolish(detail.detail_core_section)


__all__ = [
    "DETAIL_OWNED_FIELDS",
    "SUMMARY_OWNED_FIELDS",
    "apply_review_detail_closure",
]
