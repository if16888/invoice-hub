"""Targeted physical-review fixes for the review toolbar and invoice table.

The review page owns reviewing invoices, not importing infrastructure. This
module keeps existing callbacks but clarifies their labels, makes the
already-supported Excel-style column filters discoverable, caps the seller
column, repairs the narrow material rows, and provides a direct place to
configure the expected reimbursement buyer title.
"""

from __future__ import annotations

from functools import wraps

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..config import save_config
from ..reimbursement import buyer_warning
from .column_filters import has_active_filters
from .icon_provider import IconProvider
from .ui_components import make_button


SELLER_COLUMN = 4
INVOICE_NUMBER_COLUMN = 5
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
        title.setProperty("class", "SettingsSurfaceTitle")
        root.addWidget(title)
        hint = QLabel("用于核对发票购买方是否与实际报销单位一致。此设置只保存在本地。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #667085; font-size: 12px;")
        root.addWidget(hint)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
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


def _find_layout_containing(layout, widget: QWidget):
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
        ("action_import_local", "本地文件", "选择 PDF、OFD、XML 或压缩包导入"),
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
    detail = getattr(window, "_detail_panel", None)
    if detail is None or not hasattr(detail, "lbl_buyer_warning"):
        return
    invoice = getattr(window, "current_invoice", None) or {}
    warning = buyer_warning(invoice, getattr(window, "config", {}) or {}) if invoice else ""
    detail.lbl_buyer_warning.setText(warning)
    detail.lbl_buyer_warning.setVisible(bool(warning))
    row = getattr(detail, "buyer_warning_action_row", None)
    if row is not None:
        row.setVisible(bool(warning))
    button = getattr(detail, "btn_edit_reimbursement_title", None)
    if button is not None:
        expected = str(
            (getattr(window, "config", {}) or {}).get("reimbursement", {}).get("buyer_name") or ""
        ).strip()
        button.setText("修改抬头" if expected else "设置抬头")
        button.setToolTip("设置用于报销核对的购买方单位名称")


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
        warning.setParent(row)
        warning.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row_layout.addWidget(warning, 1)
        edit_button = make_button("设置抬头", variant="secondary", min_width=76)
        edit_button.setMaximumWidth(92)
        edit_button.setFixedHeight(30)
        edit_button.clicked.connect(lambda _checked=False: _open_reimbursement_title_dialog(window))
        row_layout.addWidget(edit_button, 0, Qt.AlignTop)
        detail.buyer_warning_action_row = row
        detail.btn_edit_reimbursement_title = edit_button
        window.btn_edit_reimbursement_title = edit_button

    table = getattr(window, "table", None)
    if table is not None:
        table.itemSelectionChanged.connect(
            lambda: QTimer.singleShot(0, lambda: _refresh_buyer_warning(window))
        )
    _refresh_buyer_warning(window)


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


__all__ = [
    "ReimbursementTitleDialog",
    "apply_review_toolbar_filter_fixes",
    "_refresh_buyer_warning",
    "_repair_material_rows",
    "_save_reimbursement_title",
]
