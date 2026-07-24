"""Focused UI fixes for review attachment actions and settings clarity.

The functions in this module are installed by the deterministic Review and
Settings pipelines. They adjust presentation and navigation only; existing
callbacks continue to own attachment, credential, and configuration logic.
"""

from __future__ import annotations

from functools import wraps
from types import MethodType

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidgetItem,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .company_tax_profile import (
    CompanyTaxProfileDialog,
    format_company_tax_info,
    normalize_company_tax_profile,
    refresh_company_tax_profile_status,
    save_company_tax_profile,
)
from .ui_components import ElidedTextLabel, make_button


_COMPANY_NAV_ROLE = "company_tax_profile"
_STACK_INDEX_ROLE = int(Qt.UserRole) + 701


def _repolish(widget: QWidget | None) -> None:
    if widget is None:
        return
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _remove_from_layout(widget: QWidget) -> None:
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        layout.removeWidget(widget)


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


def _company_profile(window) -> dict:
    config = getattr(window, "config", {}) or {}
    return normalize_company_tax_profile(config.get("reimbursement", {}))


def _refresh_company_settings_page(window, status_text: str = "") -> None:
    values = getattr(window, "settings_company_profile_values", None)
    if not isinstance(values, dict):
        return

    profile = _company_profile(window)
    values["单位名称"].set_value(profile["buyer_name"] or "未设置")
    values["纳税人识别号"].set_value(profile["buyer_tax_id"] or "未设置")
    values["注册地址"].set_value(profile["registered_address"] or "未设置")
    values["注册电话"].set_value(profile["registered_phone"] or "未设置")
    values["开户行"].set_value(profile["bank_name"] or "未设置")
    values["银行账号"].set_value(profile["bank_account"] or "未设置")

    checks: list[str] = []
    if profile["strict_buyer_check"]:
        checks.append("购买方名称")
    if profile["strict_buyer_tax_check"]:
        checks.append("纳税人识别号")
    values["审核核对"].set_value("、".join(checks) if checks else "未启用")

    status = getattr(window, "lbl_settings_company_profile_status", None)
    if status is not None:
        status.setText(status_text)
        status.setVisible(bool(status_text))

    edit = getattr(window, "btn_settings_company_profile_edit", None)
    copy = getattr(window, "btn_settings_company_profile_copy", None)
    configured = bool(profile["buyer_name"] or profile["buyer_tax_id"])
    if edit is not None:
        edit.setText("编辑开票信息" if configured else "设置开票信息")
    if copy is not None:
        copy.setEnabled(bool(format_company_tax_info(profile)))


def _edit_company_profile(window) -> None:
    dialog = CompanyTaxProfileDialog(_company_profile(window), window)
    if dialog.exec() != QDialog.Accepted:
        return
    try:
        save_company_tax_profile(window, dialog.values())
    except OSError as exc:
        QMessageBox.critical(window, "保存失败", f"无法保存公司开票信息：{exc}")
        return
    refresh_company_tax_profile_status(window)
    _refresh_company_settings_page(window, "公司开票信息已保存到本机。")


def _copy_company_profile(window) -> None:
    text = format_company_tax_info(_company_profile(window))
    if not text:
        _refresh_company_settings_page(window, "尚未填写可复制的公司开票信息。")
        return
    QApplication.clipboard().setText(text)
    _refresh_company_settings_page(window, "开票信息已复制到剪贴板。")


def _build_company_settings_page(window) -> QWidget:
    page = QWidget()
    page.setObjectName("CompanyTaxProfileSettingsPage")
    page_layout = QVBoxLayout(page)
    page_layout.setContentsMargins(0, 0, 0, 0)
    page_layout.setSpacing(16)
    page_layout.setAlignment(Qt.AlignTop)

    header = QFrame(page)
    header.setObjectName("SettingsSubpageHeader")
    header_layout = QVBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(4)
    title = QLabel("开票信息", header)
    title.setProperty("class", "SettingsSubpageTitle")
    hint = QLabel(
        "维护公司开票资料，并用于审核发票购买方名称和纳税人识别号。",
        header,
    )
    hint.setProperty("class", "SettingsSubpageHint")
    hint.setWordWrap(True)
    header_layout.addWidget(title)
    header_layout.addWidget(hint)
    page_layout.addWidget(header)

    surface = QFrame(page)
    surface.setObjectName("CompanyTaxProfileSurface")
    surface.setProperty("class", "SettingsDetailSurface")
    surface.setMinimumWidth(560)
    surface.setMaximumWidth(760)
    surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    surface_layout = QVBoxLayout(surface)
    surface_layout.setContentsMargins(20, 18, 20, 14)
    surface_layout.setSpacing(12)

    surface_title = QLabel("开票与报销主体", surface)
    surface_title.setProperty("class", "SettingsSurfaceTitle")
    surface_hint = QLabel(
        "信息仅保存在本机；可以复制给商户开票，也可作为发票审核的期望主体。",
        surface,
    )
    surface_hint.setProperty("class", "SettingsSurfaceHint")
    surface_hint.setWordWrap(True)
    surface_layout.addWidget(surface_title)
    surface_layout.addWidget(surface_hint)

    divider = QFrame(surface)
    divider.setFrameShape(QFrame.HLine)
    divider.setProperty("class", "SettingsSectionDivider")
    divider.setFixedHeight(1)
    surface_layout.addWidget(divider)

    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    values: dict[str, ElidedTextLabel] = {}
    for key in (
        "单位名称",
        "纳税人识别号",
        "注册地址",
        "注册电话",
        "开户行",
        "银行账号",
        "审核核对",
    ):
        value = ElidedTextLabel("未设置", surface)
        value.setProperty("class", "SettingsFieldValue")
        values[key] = value
        form.addRow(key, value)
        label = form.labelForField(value)
        if label is not None:
            label.setFixedWidth(104)
            label.setProperty("class", "SettingsFieldKey")
    surface_layout.addLayout(form)

    status = QLabel("", surface)
    status.setProperty("class", "SettingsInlineStatus")
    status.setWordWrap(True)
    status.hide()
    surface_layout.addWidget(status)

    footer_divider = QFrame(surface)
    footer_divider.setFrameShape(QFrame.HLine)
    footer_divider.setProperty("class", "SettingsSectionDivider")
    footer_divider.setFixedHeight(1)
    surface_layout.addWidget(footer_divider)

    footer = QFrame(surface)
    footer.setObjectName("SettingsActionFooter")
    footer.setMinimumHeight(52)
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(0, 4, 0, 0)
    footer_layout.setSpacing(8)
    edit = make_button("设置开票信息", variant="primary", min_width=112)
    edit.clicked.connect(lambda _checked=False: _edit_company_profile(window))
    copy = make_button("复制开票信息", variant="secondary", min_width=112)
    copy.clicked.connect(lambda _checked=False: _copy_company_profile(window))
    footer_layout.addWidget(edit)
    footer_layout.addWidget(copy)
    footer_layout.addStretch(1)
    surface_layout.addWidget(footer)

    page_layout.addWidget(surface, 0, Qt.AlignTop)
    page_layout.addStretch(1)

    window.settings_company_profile_page = page
    window.settings_company_profile_surface = surface
    window.settings_company_profile_values = values
    window.lbl_settings_company_profile_status = status
    window.btn_settings_company_profile_edit = edit
    window.btn_settings_company_profile_copy = copy
    _refresh_company_settings_page(window)
    return page


def _remove_legacy_company_header_action(window) -> None:
    button = getattr(window, "btn_settings_company_profile", None)
    if button is None:
        return
    _remove_from_layout(button)
    button.hide()
    button.setParent(window)
    button.setProperty("legacyCompanyHeaderActionRemoved", True)


def _install_compatibility_api(settings_tabs, base_widgets: list[QWidget], base_labels: list[str]) -> None:
    """Keep the six established tab indexes while exposing a seventh nav item.

    Existing application code and regression tests address AI/Runtime/etc. by
    their historical indexes. The new company page is supplemental navigation:
    it is visible in the left list but does not renumber the compatibility API.
    """
    settings_tabs._compat_base_widgets = list(base_widgets)
    settings_tabs._compat_base_labels = list(base_labels)

    def count(self):
        return len(self._compat_base_widgets)

    def widget(self, index):
        if 0 <= index < len(self._compat_base_widgets):
            return self._compat_base_widgets[index]
        return None

    def tab_text(self, index):
        if 0 <= index < len(self._compat_base_labels):
            return self._compat_base_labels[index]
        return ""

    def current_index(self):
        current = self.stack.currentWidget()
        try:
            return self._compat_base_widgets.index(current)
        except ValueError:
            return -1

    def set_current_index(self, index):
        target = widget(self, index)
        if target is None:
            return
        physical_index = self.stack.indexOf(target)
        for row in range(self.nav_list.count()):
            item = self.nav_list.item(row)
            if item is not None and item.data(_STACK_INDEX_ROLE) == physical_index:
                self.nav_list.setCurrentRow(row)
                return
        self.stack.setCurrentWidget(target)

    settings_tabs.count = MethodType(count, settings_tabs)
    settings_tabs.widget = MethodType(widget, settings_tabs)
    settings_tabs.tabText = MethodType(tab_text, settings_tabs)
    settings_tabs.currentIndex = MethodType(current_index, settings_tabs)
    settings_tabs.setCurrentIndex = MethodType(set_current_index, settings_tabs)


def _insert_company_settings_page(window) -> None:
    """Insert an actual Settings navigation page below Mailbox Accounts."""
    settings_tabs = getattr(window, "settings_tabs", None)
    nav_list = getattr(settings_tabs, "nav_list", None)
    stack = getattr(settings_tabs, "stack", None)
    if settings_tabs is None or nav_list is None or stack is None:
        return

    for row in range(nav_list.count()):
        item = nav_list.item(row)
        if item is not None and item.data(Qt.UserRole) == _COMPANY_NAV_ROLE:
            return

    base_widgets = [stack.widget(index) for index in range(stack.count())]
    base_labels = [nav_list.item(index).text() for index in range(nav_list.count())]
    for row, widget in enumerate(base_widgets):
        item = nav_list.item(row)
        if item is not None:
            item.setData(_STACK_INDEX_ROLE, stack.indexOf(widget))

    current_widget = stack.currentWidget()
    company_page = _build_company_settings_page(window)
    company_index = stack.addWidget(company_page)
    item = QListWidgetItem("开票信息")
    item.setData(Qt.UserRole, _COMPANY_NAV_ROLE)
    item.setData(_STACK_INDEX_ROLE, company_index)
    item.setToolTip("维护公司开票与报销主体")
    nav_list.insertItem(1, item)

    try:
        nav_list.currentRowChanged.disconnect(settings_tabs._on_nav_changed)
    except (RuntimeError, TypeError):
        pass

    def on_nav_changed(row: int) -> None:
        nav_item = nav_list.item(row)
        if nav_item is None:
            return
        physical_index = nav_item.data(_STACK_INDEX_ROLE)
        if isinstance(physical_index, int) and 0 <= physical_index < stack.count():
            if stack.currentIndex() != physical_index:
                stack.setCurrentIndex(physical_index)

    settings_tabs._company_nav_changed = on_nav_changed
    nav_list.currentRowChanged.connect(on_nav_changed)
    _install_compatibility_api(settings_tabs, base_widgets, base_labels)

    if current_widget is not None:
        settings_tabs.setCurrentIndex(base_widgets.index(current_widget))
    elif nav_list.count():
        nav_list.setCurrentRow(0)


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


def _credential_is_missing(window) -> bool:
    button = getattr(window, "btn_settings_mailbox_add_credential", None)
    return bool(button is not None and not button.isHidden())


def _polish_mailbox_actions(window) -> None:
    add = getattr(window, "btn_settings_mailbox_add", None)
    if add is not None:
        add.setText("＋ 添加邮箱账号")
        add.setAccessibleName("添加邮箱账号")
        add.setToolTip("添加新的邮箱扫描账号")
        add.setMinimumWidth(132)
        add.setMaximumWidth(180)
        add.setFixedHeight(34)
        add.setProperty("variant", "primary")
        _repolish(add)

    repair = getattr(window, "btn_settings_mailbox_add_credential", None)
    edit = getattr(window, "btn_settings_mailbox_edit_config", None)
    scan = getattr(window, "btn_settings_mailbox_scan", None)
    test = getattr(window, "btn_settings_mailbox_test", None)
    toggle = getattr(window, "btn_settings_mailbox_toggle", None)
    more = getattr(window, "settings_mailbox_more", None)
    if repair is None or edit is None or scan is None or test is None or toggle is None:
        return

    enabled = toggle.text() != "启用"
    missing = _credential_is_missing(window)

    repair.setText("设置授权码")
    repair.setToolTip("授权码只保存到系统凭据管理器")
    repair.setMinimumWidth(96)
    edit.setText("编辑")
    edit.setToolTip("修改邮箱地址、服务器和扫描范围")
    edit.setVisible(True)
    if more is not None:
        more.setVisible(True)
        more.setToolTip("更多邮箱管理操作")

    if not enabled:
        toggle.setVisible(True)
        repair.setVisible(False)
        scan.setVisible(False)
        test.setVisible(False)
    elif missing:
        toggle.setVisible(False)
        repair.setVisible(True)
        scan.setVisible(False)
        test.setVisible(False)
    else:
        toggle.setVisible(False)
        repair.setVisible(False)
        scan.setVisible(True)
        test.setVisible(True)

    update_credential = getattr(window, "settings_mailbox_more_update_credential", None)
    if update_credential is not None:
        update_credential.setText("更新授权码")
        update_credential.setVisible(enabled and not missing)
    more_toggle = getattr(window, "settings_mailbox_more_toggle", None)
    if more_toggle is not None:
        more_toggle.setVisible(enabled)


def _install_settings_refresh(window, page: QWidget) -> None:
    if page.property("settingsActionClarityRefreshInstalled"):
        return
    page.setProperty("settingsActionClarityRefreshInstalled", True)
    original = getattr(window, "_refresh_settings_page", None)
    if callable(original):

        @wraps(original)
        def refresh(*args, **kwargs):
            result = original(*args, **kwargs)
            QTimer.singleShot(0, lambda: _polish_mailbox_actions(window))
            QTimer.singleShot(0, lambda: _refresh_company_settings_page(window))
            return result

        window._refresh_settings_page = refresh

    account_list = getattr(window, "settings_mailbox_list", None)
    if account_list is not None:
        account_list.currentRowChanged.connect(
            lambda _row: QTimer.singleShot(0, lambda: _polish_mailbox_actions(window))
        )


def apply_settings_action_clarity(page: QWidget | None) -> None:
    """Add the company Settings page and clarify contextual mailbox actions."""
    if page is None or page.property("settingsActionClarityApplied"):
        return
    window = page.window()
    if not hasattr(window, "settings_tabs"):
        return
    page.setProperty("settingsActionClarityApplied", True)
    _remove_legacy_company_header_action(window)
    _insert_company_settings_page(window)
    _polish_mailbox_actions(window)
    _install_settings_refresh(window, page)
    _remove_status_bar_version(window)


__all__ = [
    "apply_review_attachment_action_fix",
    "apply_settings_action_clarity",
]
