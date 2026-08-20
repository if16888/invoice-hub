"""Invoice Hub Design Baseline v1.0 for the desktop settings center.

The settings center is still assembled by :mod:`app`; this module applies the
approved Golden Page contract after the page tree exists.  It deliberately
contains no database, scanning, or credential business logic.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..credentials import has_auth_code
from ..log_privacy import mask_email
from .ui_components import ElidedTextLabel, make_badge, make_button


# Invoice Hub Design Baseline v1.0: settings Golden Page geometry.
_SETTINGS_MAX_WIDTH = 1120
_SETTINGS_NAV_WIDTH = 168
_PAGE_MARGIN = 24
_HEADER_CONTENT_GAP = 20
_MAILBOX_LIST_WIDTH = 280
_MAILBOX_ROW_HEIGHT = 68
_MAILBOX_DETAIL_MIN_WIDTH = 560
_MAILBOX_DETAIL_MAX_WIDTH = 760
_PROFILE_LIST_WIDTH = 240
_FIELD_LABEL_WIDTH = 104

# Semantic palette from Design Baseline v1.0.
_BG_SURFACE = "#FFFFFF"
_BG_SURFACE_SECONDARY = "#F8FAFC"
_BG_SELECTED = "#EFF6FF"
_BORDER_SUBTLE = "#E5E7EB"
_TEXT_PRIMARY = "#182230"
_TEXT_SECONDARY = "#667085"
_ACCENT = "#2563EB"


def apply_settings_baseline(page: QWidget) -> None:
    """Apply the approved Settings Golden Page contract once per page tree."""
    if page is None or page.property("settingsBaselineApplied"):
        return

    window = page.window()
    settings_tabs = getattr(window, "settings_tabs", None)
    if settings_tabs is None:
        return

    page.setProperty("settingsBaselineApplied", True)
    page_layout = page.layout()
    if page_layout is not None:
        page_layout.setContentsMargins(_PAGE_MARGIN, _PAGE_MARGIN, _PAGE_MARGIN, _PAGE_MARGIN)
        page_layout.setSpacing(_HEADER_CONTENT_GAP)

    settings_tabs.setMaximumWidth(_SETTINGS_MAX_WIDTH)
    settings_tabs.setMinimumWidth(0)
    settings_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    if hasattr(settings_tabs, "nav_list"):
        settings_tabs.nav_list.setMinimumWidth(0)
        settings_tabs.nav_list.setMaximumWidth(_SETTINGS_NAV_WIDTH)
        settings_tabs.nav_list.setTextElideMode(Qt.ElideRight)

    _polish_page_header(window)
    _install_settings_styles(settings_tabs)
    _polish_mailbox_title(window)
    _polish_mailbox_structure(window)
    _install_empty_state_action(window)
    _connect_mailbox_refresh(window)
    _refresh_mailbox_visuals(window)


def _polish_page_header(window) -> None:
    header = getattr(window, "settings_header", None)
    if header is None:
        return
    if hasattr(header, "lbl_title"):
        header.lbl_title.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 22px; font-weight: 600;"
        )
    if hasattr(header, "lbl_hint"):
        header.lbl_hint.setStyleSheet(
            f"color: {_TEXT_SECONDARY}; font-size: 13px; font-weight: 400;"
        )


def _install_settings_styles(settings_tabs: QWidget) -> None:
    settings_tabs.setStyleSheet(
        f"""
        QFrame#SecondaryNavStack {{
            background: {_BG_SURFACE};
            border: 1px solid {_BORDER_SUBTLE};
            border-radius: 8px;
        }}
        QListWidget#SecondaryNavList {{
            background: {_BG_SURFACE_SECONDARY};
            border: none;
            border-right: 1px solid {_BORDER_SUBTLE};
            padding: 10px 8px;
        }}
        QListWidget#SecondaryNavList::item {{
            min-height: 34px;
            border-radius: 6px;
            padding: 7px 10px;
            color: {_TEXT_SECONDARY};
        }}
        QListWidget#SecondaryNavList::item:selected {{
            background: {_BG_SELECTED};
            color: {_ACCENT};
            font-weight: 600;
        }}
        QLabel#SettingsSubpageTitle {{
            color: {_TEXT_PRIMARY};
            font-size: 15px;
            font-weight: 600;
        }}
        QLabel#SettingsSubpageHint {{
            color: {_TEXT_SECONDARY};
            font-size: 12px;
            font-weight: 400;
        }}
        QListWidget#MailboxAccountList {{
            background: {_BG_SURFACE};
            border: 1px solid {_BORDER_SUBTLE};
            border-radius: 8px;
            padding: 4px;
        }}
        QListWidget#MailboxAccountList::item {{
            min-height: {_MAILBOX_ROW_HEIGHT}px;
            border-radius: 6px;
            padding: 0;
        }}
        QListWidget#MailboxAccountList::item:selected {{
            background: {_BG_SELECTED};
            color: {_ACCENT};
        }}
        QFrame#MailboxAccountRow {{
            background: transparent;
            border: none;
        }}
        QLabel[class="MailboxAccountTitle"] {{
            color: {_TEXT_PRIMARY};
            font-size: 13px;
            font-weight: 600;
        }}
        QLabel[class="MailboxAccountAddress"] {{
            color: {_TEXT_SECONDARY};
            font-size: 12px;
            font-weight: 400;
        }}
        QFrame#MailboxDetailSurface {{
            background: {_BG_SURFACE};
            border: 1px solid {_BORDER_SUBTLE};
            border-radius: 8px;
        }}
        QFrame#MailboxDetailHeader,
        QFrame#MailboxActionFooter {{
            background: transparent;
            border: none;
        }}
        QLabel#MailboxDetailTitle {{
            color: {_TEXT_PRIMARY};
            font-size: 16px;
            font-weight: 600;
        }}
        QLabel#MailboxDetailSubtitle {{
            color: {_TEXT_SECONDARY};
            font-size: 12px;
            font-weight: 400;
        }}
        QLabel#MailboxDetailStatus {{
            border-radius: 9px;
            padding: 2px 8px;
        }}
        QFrame[class="SectionDivider"] {{
            background: {_BORDER_SUBTLE};
            border: none;
            min-height: 1px;
            max-height: 1px;
        }}
        QFrame#MailboxDetailSurface QLabel[class="SectionTitle"] {{
            color: {_TEXT_PRIMARY};
            font-size: 14px;
            font-weight: 600;
        }}
        QFrame#MailboxDetailSurface QLabel[class="DetailFieldKey"] {{
            color: {_TEXT_SECONDARY};
            font-size: 12px;
            font-weight: 500;
        }}
        """
    )


def _polish_mailbox_title(window) -> None:
    settings_tabs = getattr(window, "settings_tabs", None)
    mailbox_tab = settings_tabs.widget(0) if settings_tabs is not None else None
    if mailbox_tab is None or mailbox_tab.property("mailboxTitlePolished"):
        return

    mailbox_tab.setProperty("mailboxTitlePolished", True)
    layout = mailbox_tab.layout()
    if layout is None:
        return

    title = None
    for label in mailbox_tab.findChildren(QLabel):
        if label.text() == "邮箱账户" and label.parentWidget() is mailbox_tab:
            title = label
            break
    if title is not None:
        title.setObjectName("SettingsSubpageTitle")

    hint = QLabel("管理用于收集和扫描发票的邮箱账号。", mailbox_tab)
    hint.setObjectName("SettingsSubpageHint")
    hint.setWordWrap(True)
    layout.insertWidget(1, hint)


def _polish_mailbox_structure(window) -> None:
    account_list = getattr(window, "settings_mailbox_list", None)
    surface = getattr(window, "mailbox_detail_surface", None)
    surface_layout = getattr(window, "mailbox_detail_surface_layout", None)
    if account_list is None or surface is None or surface_layout is None:
        return

    account_list.setObjectName("MailboxAccountList")
    account_list.setMinimumWidth(0)
    account_list.setMaximumWidth(_MAILBOX_LIST_WIDTH)
    account_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    surface.setMinimumWidth(_MAILBOX_DETAIL_MIN_WIDTH)
    surface.setMaximumWidth(_MAILBOX_DETAIL_MAX_WIDTH)
    surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    surface_layout.setContentsMargins(20, 18, 20, 14)
    surface_layout.setSpacing(12)
    surface_layout.setAlignment(Qt.AlignTop)

    for label in surface.findChildren(QLabel):
        if label.property("class") == "DetailFieldKey":
            label.setFixedWidth(_FIELD_LABEL_WIDTH)

    _replace_mailbox_header(window, surface, surface_layout)
    _move_action_footer_into_surface(window, surface, surface_layout)

    editor = surface.parentWidget()
    editor_layout = editor.layout() if editor is not None else None
    if editor_layout is not None:
        editor_layout.setStretchFactor(surface, 0)
        editor_layout.setAlignment(Qt.AlignTop)
        if not editor.property("mailboxTrailingStretchAdded"):
            editor.setProperty("mailboxTrailingStretchAdded", True)
            editor_layout.addStretch(1)


def apply_settings_responsive_metrics(window, width: int | None = None) -> None:
    """Keep the settings surfaces inside the available logical pixel width.

    The baseline remains the same at desktop widths.  Once the workbench is
    narrower (which is common after Windows DPI scaling), the two-column
    settings shells stack and all detail surfaces are allowed to shrink.  This
    makes wrapping a layout decision instead of a clipping side effect.
    """
    settings_tabs = getattr(window, "settings_tabs", None)
    if settings_tabs is None:
        return
    available_width = int(width or getattr(window, "width", lambda: 0)() or 0)
    compact = available_width < 1100

    settings_tabs.setMinimumWidth(0)
    settings_tabs.setMaximumWidth(_SETTINGS_MAX_WIDTH)
    settings_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    nav_list = getattr(settings_tabs, "nav_list", None)
    if nav_list is not None:
        nav_width = 132 if compact else _SETTINGS_NAV_WIDTH
        nav_list.setMinimumWidth(nav_width)
        nav_list.setMaximumWidth(nav_width)
        nav_list.setFixedWidth(nav_width)

    mailbox_shell = getattr(window, "settings_mailbox_shell", None)
    mailbox_editor = getattr(window, "settings_mailbox_editor", None)
    account_list = getattr(window, "settings_mailbox_list", None)
    mailbox_surface = getattr(window, "mailbox_detail_surface", None)
    if mailbox_shell is not None:
        mailbox_shell.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
    if account_list is not None:
        if compact:
            account_list.setMinimumWidth(0)
            account_list.setMaximumWidth(16777215)
            account_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            account_list.setMinimumWidth(200)
            account_list.setMaximumWidth(_MAILBOX_LIST_WIDTH)
            account_list.setFixedWidth(_MAILBOX_LIST_WIDTH)
            account_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    if mailbox_editor is not None:
        mailbox_editor.setMinimumWidth(0 if compact else _MAILBOX_DETAIL_MIN_WIDTH)
    if mailbox_surface is not None:
        mailbox_surface.setMinimumWidth(0 if compact else _MAILBOX_DETAIL_MIN_WIDTH)
        mailbox_surface.setMaximumWidth(_MAILBOX_DETAIL_MAX_WIDTH)

    ai_shell = getattr(window, "settings_ai_shell", None)
    profile_list = getattr(window, "settings_ai_profile_list", None)
    ai_surface = getattr(window, "settings_ai_detail_panel", None)
    if ai_shell is not None:
        ai_shell.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
    if profile_list is not None:
        if compact:
            profile_list.setMinimumWidth(0)
            profile_list.setMaximumWidth(16777215)
            profile_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        else:
            profile_list.setMinimumWidth(0)
            profile_list.setMaximumWidth(_PROFILE_LIST_WIDTH)
            profile_list.setFixedWidth(_PROFILE_LIST_WIDTH)
            profile_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    if ai_surface is not None:
        ai_surface.setMinimumWidth(0 if compact else _MAILBOX_DETAIL_MIN_WIDTH)
        ai_surface.setMaximumWidth(_MAILBOX_DETAIL_MAX_WIDTH)

    for attr in (
        "lbl_settings_runtime",
        "lbl_settings_privacy",
        "lbl_settings_data",
        "lbl_settings_about",
    ):
        surface = getattr(window, attr, None)
        if surface is not None:
            surface.setMinimumWidth(0 if compact else _MAILBOX_DETAIL_MIN_WIDTH)
            surface.setMaximumWidth(_MAILBOX_DETAIL_MAX_WIDTH)

    label_width = 88 if compact else _FIELD_LABEL_WIDTH
    for surface in settings_tabs.findChildren(QFrame):
        for label in surface.findChildren(QLabel):
            if label.property("class") in {"DetailFieldKey", "SettingsFieldKey"}:
                label.setMinimumWidth(label_width)
                label.setMaximumWidth(label_width)
                label.setFixedWidth(label_width)

    for layout_attr in ("mailbox_action_footer_layout", "settings_ai_footer_layout"):
        footer_layout = getattr(window, layout_attr, None)
        if footer_layout is not None:
            footer_layout.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)


def _replace_mailbox_header(window, surface: QFrame, surface_layout: QVBoxLayout) -> None:
    if surface.property("mailboxHeaderPolished"):
        return
    surface.setProperty("mailboxHeaderPolished", True)

    name = getattr(window, "lbl_detail_header_name", None)
    email = getattr(window, "lbl_detail_header_email", None)
    status = getattr(window, "lbl_detail_header_status", None)
    if name is None or email is None or status is None:
        return

    old_item = surface_layout.takeAt(0)
    old_layout = old_item.layout() if old_item is not None else None
    if old_layout is not None:
        while old_layout.count():
            old_layout.takeAt(0)
        old_layout.deleteLater()

    header = QFrame(surface)
    header.setObjectName("MailboxDetailHeader")
    header_layout = QVBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(4)

    title_row = QHBoxLayout()
    title_row.setContentsMargins(0, 0, 0, 0)
    title_row.setSpacing(10)
    name.setObjectName("MailboxDetailTitle")
    name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    status.setObjectName("MailboxDetailStatus")
    status.setProperty("class", "StatusBadge")
    status.setAlignment(Qt.AlignCenter)
    status.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    title_row.addWidget(name, 1)
    title_row.addWidget(status, 0, Qt.AlignRight | Qt.AlignVCenter)

    email.setObjectName("MailboxDetailSubtitle")
    email.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    header_layout.addLayout(title_row)
    header_layout.addWidget(email)
    surface_layout.insertWidget(0, header)


def _find_action_layout(window):
    scan = getattr(window, "btn_settings_mailbox_scan", None)
    parent = scan.parentWidget() if scan is not None else None
    layout = parent.layout() if parent is not None else None
    if layout is None:
        return None, None
    for index in range(layout.count()):
        item = layout.itemAt(index)
        nested = item.layout()
        if nested is not None and nested.indexOf(scan) >= 0:
            return layout, nested
    return layout, None


def _move_action_footer_into_surface(window, surface: QFrame, surface_layout: QVBoxLayout) -> None:
    if surface.property("mailboxFooterPolished"):
        return

    parent_layout, old_action_layout = _find_action_layout(window)
    if parent_layout is None or old_action_layout is None:
        return
    surface.setProperty("mailboxFooterPolished", True)

    while old_action_layout.count():
        old_action_layout.takeAt(0)
    parent_layout.removeItem(old_action_layout)
    old_action_layout.deleteLater()

    divider = QFrame(surface)
    divider.setFrameShape(QFrame.HLine)
    divider.setProperty("class", "SectionDivider")
    surface_layout.addWidget(divider)

    footer = QFrame(surface)
    footer.setObjectName("MailboxActionFooter")
    footer.setMinimumHeight(52)
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(0, 4, 0, 0)
    footer_layout.setSpacing(8)
    window.mailbox_action_footer_layout = footer_layout

    # The mutually exclusive primary actions stay first, then contextual
    # secondary actions, then More. Hidden actions do not reserve space.
    for name in (
        "btn_settings_mailbox_toggle",
        "btn_settings_mailbox_add_credential",
        "btn_settings_mailbox_scan",
        "btn_settings_mailbox_test",
        "btn_settings_mailbox_edit_config",
        "settings_mailbox_more",
    ):
        widget = getattr(window, name, None)
        if widget is not None:
            footer_layout.addWidget(widget)
    footer_layout.addStretch(1)
    surface_layout.addWidget(footer)


def _install_empty_state_action(window) -> None:
    empty_state = getattr(window, "settings_mailbox_empty_state", None)
    add_button = getattr(window, "btn_settings_mailbox_add", None)
    if empty_state is None or add_button is None or empty_state.property("mailboxActionInstalled"):
        return

    empty_state.setProperty("mailboxActionInstalled", True)
    empty_state.setMaximumWidth(520)
    empty_state.setMaximumHeight(190)
    action = make_button("新增邮箱账号", variant="primary", min_width=132)
    action.setAccessibleName("新增邮箱账号")
    action.clicked.connect(add_button.showMenu)
    empty_state.set_action(action)
    window.btn_settings_mailbox_empty_add = action


def _connect_mailbox_refresh(window) -> None:
    account_list = getattr(window, "settings_mailbox_list", None)
    if account_list is None or account_list.property("mailboxBaselineSignalsConnected"):
        return

    account_list.setProperty("mailboxBaselineSignalsConnected", True)

    def defer_refresh(*_args):
        QTimer.singleShot(0, lambda: _refresh_mailbox_visuals(window))

    account_list.currentRowChanged.connect(defer_refresh)
    model = account_list.model()
    model.rowsInserted.connect(defer_refresh)
    model.rowsRemoved.connect(defer_refresh)
    model.modelReset.connect(defer_refresh)

    settings_tabs = getattr(window, "settings_tabs", None)
    if settings_tabs is not None and hasattr(settings_tabs, "stack"):
        settings_tabs.stack.currentChanged.connect(
            lambda index: defer_refresh() if index == 0 else None
        )


def _refresh_mailbox_visuals(window) -> None:
    account_list = getattr(window, "settings_mailbox_list", None)
    if account_list is None:
        return

    _rebuild_mailbox_rows(window)
    _sync_mailbox_empty_state(window)
    _sync_mailbox_detail_state(window)


def _account_key(account: dict) -> str:
    return str(account.get("mailbox_key") or account.get("address") or "").strip()


def _account_state(account: dict) -> tuple[str, str]:
    enabled = bool(account.get("enabled", True))
    address = str(account.get("address") or "").strip()
    if not enabled:
        return "已停用", "ignored"
    if not has_auth_code(address):
        return "需要授权", "review"
    return "正常", "approved"


def _rebuild_mailbox_rows(window) -> None:
    account_list = getattr(window, "settings_mailbox_list", None)
    accounts = window._mailbox_accounts_for_settings()
    if account_list is None:
        return

    by_key = {_account_key(account): account for account in accounts}
    for row_index in range(account_list.count()):
        item: QListWidgetItem = account_list.item(row_index)
        account = by_key.get(str(item.data(Qt.UserRole) or ""))
        if account is None:
            continue

        old_widget = account_list.itemWidget(item)
        row = QFrame(account_list)
        row.setObjectName("MailboxAccountRow")
        row.setMinimumHeight(_MAILBOX_ROW_HEIGHT)
        outer = QVBoxLayout(row)
        outer.setContentsMargins(10, 7, 8, 7)
        outer.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        title_text = str(account.get("name") or account.get("address") or "未命名邮箱").strip()
        title = ElidedTextLabel(title_text, row)
        title.setProperty("class", "MailboxAccountTitle")
        title.setToolTip(title_text)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        top.addWidget(title, 1)

        if account.get("is_default"):
            top.addWidget(make_badge("默认", variant="muted"), 0, Qt.AlignRight)
        state_text, state_variant = _account_state(account)
        top.addWidget(make_badge(state_text, variant=state_variant), 0, Qt.AlignRight)

        address = str(account.get("address") or "").strip()
        address_label = ElidedTextLabel(mask_email(address) or "—", row)
        address_label.setProperty("class", "MailboxAccountAddress")
        address_label.setToolTip(address)
        address_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        outer.addLayout(top)
        outer.addWidget(address_label)
        item.setSizeHint(QSize(0, _MAILBOX_ROW_HEIGHT))
        account_list.setItemWidget(item, row)
        if old_widget is not None and old_widget is not row:
            old_widget.deleteLater()


def _sync_mailbox_empty_state(window) -> None:
    account_list = getattr(window, "settings_mailbox_list", None)
    empty_state = getattr(window, "settings_mailbox_empty_state", None)
    surface = getattr(window, "mailbox_detail_surface", None)
    if account_list is None:
        return

    count = account_list.count()
    has_accounts = count > 0
    account_list.setVisible(has_accounts)
    account_list.setFixedHeight(min(540, max(156, count * _MAILBOX_ROW_HEIGHT + 10)))
    if empty_state is not None:
        empty_state.setVisible(not has_accounts)
    if surface is not None:
        surface.setVisible(has_accounts)


def _set_status_badge(label: QLabel, text: str) -> None:
    variants = {
        "正常": "approved",
        "需要授权": "review",
        "已停用": "ignored",
        "连接失败": "error",
        "未配置": "muted",
    }
    label.setProperty("class", "StatusBadge")
    label.setProperty("variant", variants.get(text, "muted"))
    label.setMinimumWidth(max(54, label.fontMetrics().horizontalAdvance(text) + 18))
    label.style().unpolish(label)
    label.style().polish(label)


def _strip_prefix(text: str, prefixes: tuple[str, ...]) -> str:
    value = str(text or "").strip()
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix):].strip() or "—"
    return value or "—"


def _sync_mailbox_detail_state(window) -> None:
    status = getattr(window, "lbl_detail_header_status", None)
    if status is not None:
        _set_status_badge(status, status.text())

    default_label = getattr(window, "lbl_detail_is_default", None)
    if default_label is not None and default_label.text().startswith("是"):
        default_label.setText("是")

    test_status = getattr(window, "lbl_settings_mailbox_test_status", None)
    if test_status is not None:
        test_status.setText(
            _strip_prefix(test_status.text(), ("连接测试：", "测试连接："))
        )
    scan_status = getattr(window, "lbl_settings_mailbox_scan_result", None)
    if scan_status is not None:
        scan_status.setText(
            _strip_prefix(scan_status.text(), ("最近扫描结果：", "最近扫描："))
        )

    for name in (
        "lbl_detail_name",
        "lbl_detail_email",
        "lbl_detail_server",
        "lbl_detail_port_security",
        "lbl_detail_scan_folder",
        "lbl_detail_scan_range",
        "lbl_detail_attachment_types",
        "lbl_settings_mailbox_test_status",
        "lbl_settings_mailbox_scan_result",
    ):
        label = getattr(window, name, None)
        if label is not None:
            label.setToolTip("" if label.text() in {"", "—"} else label.text())

    toggle = getattr(window, "btn_settings_mailbox_toggle", None)
    repair = getattr(window, "btn_settings_mailbox_add_credential", None)
    scan = getattr(window, "btn_settings_mailbox_scan", None)
    more_update = getattr(window, "settings_mailbox_more_update_credential", None)
    more_toggle = getattr(window, "settings_mailbox_more_toggle", None)
    if toggle is not None and repair is not None and scan is not None:
        account_enabled = toggle.text() != "启用"
        credential_missing = repair.isVisible()
        if more_update is not None:
            more_update.setVisible(account_enabled and not credential_missing)
        if more_toggle is not None:
            more_toggle.setVisible(account_enabled)


__all__ = ["apply_settings_baseline"]
