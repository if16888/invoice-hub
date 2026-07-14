"""Focused UI fixes for review attachment actions and settings clarity.

The functions in this module are installed by the deterministic Review and
Settings pipelines. They adjust presentation and navigation only; existing
callbacks continue to own attachment, credential, and configuration logic.
"""

from __future__ import annotations

from functools import wraps

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLayout, QMessageBox, QWidget

from .company_tax_profile import (
    CompanyTaxProfileDialog,
    normalize_company_tax_profile,
    refresh_company_tax_profile_status,
    save_company_tax_profile,
)
from .ui_components import make_button


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
    """Keep original-file controls inside the Materials / Original row.

    The final detail migration deletes the legacy material card. Buttons that
    were not the current ``StatusLine`` action were reparented to the detail
    panel for compatibility. A later refresh could make one of those unmanaged
    buttons visible at coordinate (0, 0), which produced the escaped “替换”
    control over the amount summary.
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

    # Low-frequency locating remains available through the invoice More menu.
    # It must never be shown as an unmanaged child of the detail panel.
    _hide_non_primary_action(status_line, detail.btn_locate_file)

    # Preserve the established primary-action contract while showing one useful
    # secondary action: existing file -> 打开 + 替换原件; downloadable missing
    # file -> 重新下载 + 补充原件; otherwise 补充原件 is itself primary.
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


def _find_layout_containing(layout: QLayout | None, target: QWidget):
    if layout is None:
        return None, -1
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is target:
            return layout, index
        nested = item.layout()
        if nested is not None:
            found, found_index = _find_layout_containing(nested, target)
            if found is not None:
                return found, found_index
    return None, -1


def _install_company_settings_action(window) -> None:
    """Expose company invoice information from the existing Settings page.

    The action is placed next to “添加邮箱账号” and opens the established local
    company-profile editor. Keeping the existing six settings tabs stable avoids
    breaking tab-index contracts while making the feature discoverable in
    Settings rather than only from an invoice warning.
    """
    if getattr(window, "btn_settings_company_profile", None) is not None:
        return
    add_mailbox = getattr(window, "btn_settings_mailbox_add", None)
    settings_tabs = getattr(window, "settings_tabs", None)
    if add_mailbox is None or settings_tabs is None:
        return

    company_button = make_button("公司开票信息", variant="secondary", min_width=104)
    company_button.setAccessibleName("公司开票信息")
    company_button.setToolTip("维护、复制公司开票与报销主体；信息仅保存在本机")
    company_button.clicked.connect(lambda _checked=False: _edit_company_profile(window))

    owner_layout, index = _find_layout_containing(settings_tabs.layout(), add_mailbox)
    if owner_layout is None:
        owner_layout, index = _find_layout_containing(
            add_mailbox.parentWidget().layout() if add_mailbox.parentWidget() else None,
            add_mailbox,
        )
    if owner_layout is not None and hasattr(owner_layout, "insertWidget"):
        owner_layout.insertWidget(max(0, index), company_button)
    else:
        company_button.setParent(add_mailbox.parentWidget())
        company_button.move(max(0, add_mailbox.x() - company_button.sizeHint().width() - 8), add_mailbox.y())
        company_button.show()

    window.btn_settings_company_profile = company_button


def _open_company_settings(window) -> None:
    """Open the company editor from the Settings context."""
    settings_button = (getattr(window, "workbench_nav_buttons", {}) or {}).get("settings")
    settings_tabs = getattr(window, "settings_tabs", None)
    if settings_button is not None:
        settings_button.click()
    if settings_tabs is not None:
        settings_tabs.setCurrentIndex(0)
    action = getattr(window, "btn_settings_company_profile", None)
    if action is not None:
        QTimer.singleShot(0, action.click)
    else:
        QTimer.singleShot(0, lambda: _edit_company_profile(window))


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
        _stabilize_original_file_actions(detail, has_file=bool(has_file))
        return result

    detail.set_attachment_state = set_attachment_state

    company_button = getattr(detail, "btn_edit_reimbursement_title", None)
    if company_button is not None:
        try:
            company_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        company_button.setText("公司开票信息")
        company_button.setToolTip("前往系统设置维护、复制公司开票与报销主体")
        company_button.clicked.connect(
            lambda _checked=False, target=window: _open_company_settings(target)
        )


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
            return result

        window._refresh_settings_page = refresh

    account_list = getattr(window, "settings_mailbox_list", None)
    if account_list is not None:
        account_list.currentRowChanged.connect(
            lambda _row: QTimer.singleShot(0, lambda: _polish_mailbox_actions(window))
        )


def apply_settings_action_clarity(page: QWidget | None) -> None:
    """Expose company settings and clarify contextual mailbox actions."""
    if page is None or page.property("settingsActionClarityApplied"):
        return
    window = page.window()
    if not hasattr(window, "settings_tabs"):
        return
    page.setProperty("settingsActionClarityApplied", True)
    _install_company_settings_action(window)
    _polish_mailbox_actions(window)
    _install_settings_refresh(window, page)


__all__ = [
    "apply_review_attachment_action_fix",
    "apply_settings_action_clarity",
]
