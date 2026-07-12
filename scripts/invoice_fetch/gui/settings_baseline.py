"""Golden-page visual normalization for the desktop settings center.

The settings center is still assembled by :mod:`app`; this module owns the
shared visual contract applied after the page tree exists.  It deliberately
contains no database or mailbox business logic.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..credentials import has_auth_code
from ..log_privacy import mask_email
from .styles import COLOR_TOKENS
from .ui_components import ElidedTextLabel, make_badge, make_button


_SETTINGS_MAX_WIDTH = 1240
_SETTINGS_NAV_WIDTH = 176
_MAILBOX_LIST_WIDTH = 280
_MAILBOX_ROW_HEIGHT = 68
_MAILBOX_DETAIL_MIN_WIDTH = 600


def apply_settings_baseline(page: QWidget) -> None:
    """Apply the Settings Golden Page contract once the full widget tree exists."""
    if page is None or page.property("settingsBaselineApplied"):
        return

    window = page.window()
    settings_tabs = getattr(window, "settings_tabs", None)
    if settings_tabs is None:
        return

    page.setProperty("settingsBaselineApplied", True)
    settings_tabs.setMaximumWidth(_SETTINGS_MAX_WIDTH)
    settings_tabs.setMinimumWidth(900)
    if hasattr(settings_tabs, "nav_list"):
        settings_tabs.nav_list.setFixedWidth(_SETTINGS_NAV_WIDTH)

    _install_settings_styles(settings_tabs)
    _polish_mailbox_title(window)
    _polish_mailbox_structure(window)
    _install_empty_state_action(window)
    _connect_mailbox_refresh(window)
    _refresh_mailbox_visuals(window)


def _install_settings_styles(settings_tabs: QWidget) -> None:
    colors = COLOR_TOKENS
    settings_tabs.setStyleSheet(
        f"""
        QFrame#SecondaryNavStack {{
            background: {colors['surface_primary']};
            border: 1px solid {colors['border_subtle']};
            border-radius: 10px;
        }}
        QListWidget#SecondaryNavList {{
            background: {colors['surface_secondary']};
            border: none;
            border-right: 1px solid {colors['border_subtle']};
            padding: 10px 8px;
        }}
        QLabel#SettingsSubpageTitle {{
            color: {colors['text_primary']};
            font-size: 15px;
            font-weight: 700;
        }}
        QLabel#SettingsSubpageHint {{
            color: {colors['text_muted']};
            font-size: 12px;
            font-weight: 400;
        }}
        QListWidget#MailboxAccountList {{
            background: {colors['surface_primary']};
            border: 1px solid {colors['border_subtle']};
            border-radius: 10px;
            padding: 4px;
        }}
        QListWidget#MailboxAccountList::item {{
            min-height: {_MAILBOX_ROW_HEIGHT}px;
            border-radius: 8px;
            padding: 0;
        }}
        QListWidget#MailboxAccountList::item:selected {{
            background: #EFF6FF;
            color: #1D4ED8;
        }}
        QFrame#MailboxAccountRow {{
            background: transparent;
            border: none;
        }}
        QLabel[class="MailboxAccountTitle"] {{
            color: {colors['text_primary']};
            font-size: 13px;
            font-weight: 650;
        }}
        QLabel[class="MailboxAccountAddress"] {{
            color: {colors['text_muted']};
            font-size: 12px;
            font-weight: 400;
        }}
        QFrame#MailboxDetailSurface {{
            background: {colors['surface_primary']};
            border: 1px solid {colors['border_subtle']};
            border-radius: 10px;
        }}
        QFrame#MailboxDetailHeader,
        QFrame#MailboxActionFooter {{
            background: transparent;
            border: none;
        }}
        QLabel#MailboxDetailTitle {{
            color: {colors['text_primary']};
            font-size: 16px;
            font-weight: 700;
        }}
        QLabel#MailboxDetailSubtitle {{
            color: {colors['text_muted']};
            font-size: 12px;
            font-weight: 400;
        }}
        QFrame[class="SectionDivider"] {{
            background: {colors['border_subtle']};
            border: none;
            min-height: 1px;
            max-height: 1px;
        }}
        QFrame#MailboxDetailSurface QLabel[class="SectionTitle"] {{
            color: {colors['text_primary']};
            font-size: 13px;
            font-weight: 650;
        }}
        QFrame#MailboxDetailSurface QLabel[class="DetailFieldKey"] {{
            color: {colors['text_muted']};
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
    account_list.setFixedWidth(_MAILBOX_LIST_WIDTH)
    account_list.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    surface.setMinimumWidth(_MAILBOX_DETAIL_MIN_WIDTH)
    surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    surface_layout.setContentsMargins(20, 18, 20, 14)
    surface_layout.setSpacing(12)
    surface_layout.setAlignment(Qt.AlignTop)

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
    footer.setMinimumHeight(48)
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(0, 4, 0, 0)
    footer_layout.setSpacing(8)

    # The first three actions are mutually exclusive primaries.  Keeping them
    # first guarantees a stable left-to-right hierarchy at every mailbox state.
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

    enabled = getattr(window, "btn_settings_mailbox_toggle", None)
    repair = getattr(window, "btn_settings_mailbox_add_credential", None)
    scan = getattr(window, "btn_settings_mailbox_scan", None)
    more_update = getattr(window, "settings_mailbox_more_update_credential", None)
    more_toggle = getattr(window, "settings_mailbox_more_toggle", None)
    if enabled is not None and repair is not None and scan is not None:
        account_enabled = enabled.text() != "启用"
        credential_missing = repair.isVisible()
        if more_update is not None:
            more_update.setVisible(account_enabled and not credential_missing)
        if more_toggle is not None:
            more_toggle.setVisible(account_enabled)


__all__ = ["apply_settings_baseline"]
