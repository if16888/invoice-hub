"""Focused UI fixes for review attachment actions and settings clarity.

The functions in this module are installed by the deterministic Review and
Settings pipelines. They only adjust presentation and navigation; existing
callbacks continue to own attachment, credential, and configuration logic.
"""

from __future__ import annotations

from functools import wraps

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from . import company_tax_profile
from .company_tax_profile import (
    CompanyTaxProfileDialog,
    format_company_tax_info,
    normalize_company_tax_profile,
    refresh_company_tax_profile_status,
    save_company_tax_profile,
)
from .settings_pages_baseline import StructuredSettingsSurface
from .ui_components import make_button


_COMPANY_NAV_ROLE = "company_tax_profile"


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


def _stabilize_original_file_actions(detail, *, has_file: bool, has_url: bool) -> None:
    """Keep original-file controls inside the Materials / Original row.

    The final detail migration deletes the legacy material card. Buttons that
    were not the current ``StatusLine`` action were then reparented to the detail
    panel for compatibility. A later refresh could make one of those unmanaged
    buttons visible at coordinate (0, 0), which is the escaped “替换” control seen
    over the summary amount. This function keeps the primary-action contract and
    explicitly manages the one useful secondary action in the final row.
    """
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

    # “定位”是低频操作，继续由更多菜单承载；它不能作为无布局子控件显示。
    _hide_non_primary_action(status_line, detail.btn_locate_file)

    # Existing primary-action behaviour remains intact:
    #   existing file -> 打开
    #   downloadable missing file -> 重新下载
    #   otherwise -> 补充原件
    if primary in (detail.btn_open_file, detail.btn_retry_download):
        _place_secondary_action(status_line, detail.btn_add_attachment)
    else:
        # When 补充原件 itself is primary, ensure it is not duplicated.
        _hide_non_primary_action(status_line, detail.btn_open_file)
        _hide_non_primary_action(status_line, detail.btn_retry_download)

    # Defensive cleanup for controls made visible by the legacy refresh while
    # they were no longer owned by a layout.
    if primary is not detail.btn_open_file:
        _hide_non_primary_action(status_line, detail.btn_open_file)
    if primary is not detail.btn_retry_download:
        _hide_non_primary_action(status_line, detail.btn_retry_download)


def _open_company_settings_or_dialog(window) -> None:
    """Route the review entry to Settings, with the existing dialog as fallback."""
    tabs = getattr(window, "settings_tabs", None)
    nav_list = getattr(tabs, "nav_list", None)
    stack = getattr(tabs, "stack", None)
    target_row = -1
    if nav_list is not None:
        for row in range(nav_list.count()):
            item = nav_list.item(row)
            if item.data(Qt.UserRole) == _COMPANY_NAV_ROLE or item.text() == "开票信息":
                target_row = row
                break

    if target_row >= 0 and stack is not None:
        settings_button = (getattr(window, "workbench_nav_buttons", {}) or {}).get("settings")
        if settings_button is not None:
            settings_button.click()
        nav_list.setCurrentRow(target_row)
        stack.setCurrentIndex(target_row)
        return

    company_tax_profile._open_company_tax_profile_dialog(window)


def apply_review_attachment_action_fix(page: QWidget | None) -> None:
    """Fix escaped attachment controls and route company info to Settings."""
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
        _stabilize_original_file_actions(
            detail,
            has_file=bool(has_file),
            has_url=bool(has_url),
        )
        return result

    detail.set_attachment_state = set_attachment_state

    company_button = getattr(detail, "btn_edit_reimbursement_title", None)
    if company_button is not None:
        try:
            company_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        # Preserve the established product label while changing its destination.
        company_button.setText("公司开票信息")
        company_button.setToolTip("前往系统设置维护、复制公司开票与报销主体")
        company_button.clicked.connect(
            lambda _checked=False, target=window: _open_company_settings_or_dialog(target)
        )


def _company_profile(window) -> dict:
    config = getattr(window, "config", {}) or {}
    return normalize_company_tax_profile(config.get("reimbursement", {}))


def _refresh_company_settings_page(window, status_text: str = "") -> None:
    surface = getattr(window, "settings_company_profile_surface", None)
    if surface is None:
        return
    profile = _company_profile(window)
    surface.set_value("单位名称", profile["buyer_name"] or "未设置")
    surface.set_value("纳税人识别号", profile["buyer_tax_id"] or "未设置")
    address_phone = " / ".join(
        value
        for value in (profile["registered_address"], profile["registered_phone"])
        if value
    )
    surface.set_value("注册地址与电话", address_phone or "未设置")
    bank = " / ".join(
        value for value in (profile["bank_name"], profile["bank_account"]) if value
    )
    surface.set_value("开户行与账号", bank or "未设置")

    checks = []
    if profile["strict_buyer_check"]:
        checks.append("核对购买方名称")
    if profile["strict_buyer_tax_check"]:
        checks.append("核对纳税人识别号")
    surface.set_value("审核核对", "、".join(checks) if checks else "未启用")
    surface.set_status(status_text)

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


def _append_company_settings_page(window) -> None:
    """Append the new page so all established settings indexes stay stable."""
    tabs = getattr(window, "settings_tabs", None)
    nav_list = getattr(tabs, "nav_list", None)
    stack = getattr(tabs, "stack", None)
    if tabs is None or nav_list is None or stack is None:
        return

    for row in range(nav_list.count()):
        if nav_list.item(row).data(Qt.UserRole) == _COMPANY_NAV_ROLE:
            return

    company_page = QWidget(stack)
    company_page.setObjectName("CompanyTaxProfileSettingsPage")
    page_layout = QVBoxLayout(company_page)
    page_layout.setContentsMargins(0, 0, 0, 0)
    page_layout.setSpacing(16)
    page_layout.setAlignment(Qt.AlignTop)

    header = QFrame(company_page)
    header.setObjectName("SettingsSubpageHeader")
    header_layout = QVBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(4)
    title = QLabel("开票与报销主体", header)
    title.setProperty("class", "SettingsSubpageTitle")
    hint = QLabel(
        "集中维护公司开票资料，并用于审核发票购买方名称和纳税人识别号。",
        header,
    )
    hint.setProperty("class", "SettingsSubpageHint")
    hint.setWordWrap(True)
    header_layout.addWidget(title)
    header_layout.addWidget(hint)
    page_layout.addWidget(header)

    surface = StructuredSettingsSurface(
        "公司开票信息",
        "信息仅保存在本机；可直接复制给商户开票，也可作为发票审核的期望主体。",
        [
            ("单位名称", "未设置"),
            ("纳税人识别号", "未设置"),
            ("注册地址与电话", "未设置"),
            ("开户行与账号", "未设置"),
            ("审核核对", "未启用"),
        ],
        company_page,
    )
    edit = make_button("设置开票信息", variant="primary", min_width=112)
    edit.clicked.connect(lambda _checked=False: _edit_company_profile(window))
    copy = make_button("复制开票信息", variant="secondary", min_width=112)
    copy.clicked.connect(lambda _checked=False: _copy_company_profile(window))
    surface.set_actions([edit, copy])
    page_layout.addWidget(surface, 0, Qt.AlignTop)
    page_layout.addStretch(1)

    item = QListWidgetItem("开票信息")
    item.setData(Qt.UserRole, _COMPANY_NAV_ROLE)
    item.setToolTip("维护公司开票与报销主体")
    stack.addWidget(company_page)
    nav_list.addItem(item)

    window.settings_company_profile_page = company_page
    window.settings_company_profile_surface = surface
    window.btn_settings_company_profile_edit = edit
    window.btn_settings_company_profile_copy = copy
    _refresh_company_settings_page(window)


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
    tabs = getattr(window, "settings_tabs", None)
    nav_list = getattr(tabs, "nav_list", None)
    if nav_list is not None:
        nav_list.currentRowChanged.connect(
            lambda _row: QTimer.singleShot(0, lambda: _refresh_company_settings_page(window))
        )


def apply_settings_action_clarity(page: QWidget | None) -> None:
    """Add company-profile settings and clarify contextual mailbox actions."""
    if page is None or page.property("settingsActionClarityApplied"):
        return
    window = page.window()
    if not hasattr(window, "settings_tabs"):
        return
    page.setProperty("settingsActionClarityApplied", True)
    _append_company_settings_page(window)
    _polish_mailbox_actions(window)
    _install_settings_refresh(window, page)


__all__ = [
    "apply_review_attachment_action_fix",
    "apply_settings_action_clarity",
]
