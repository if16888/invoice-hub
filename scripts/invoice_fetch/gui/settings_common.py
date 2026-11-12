"""Reusable common-settings surface for high-frequency local preferences."""

from __future__ import annotations

from functools import wraps
from types import MethodType

from .design_tokens import DESIGN_V1_METRICS

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..credentials import has_auth_code
from ..log_privacy import mask_email
from .company_tax_profile import (
    CompanyTaxProfileDialog,
    format_company_tax_info,
    normalize_company_tax_profile,
    refresh_company_tax_profile_status,
    save_company_tax_profile,
)
from .mailbox_feedback import connection_feedback
from .ui_components import (
    ElidedTextLabel,
    MiddleElidedTextLabel,
    ReadOnlyDetailPanel,
    WrappedTextLabel,
    make_badge,
    make_button,
)


def ai_key_source_text(source: str) -> str:
    """Translate the credential resolver's values without parsing UI copy."""
    return {
        "profile": "已保存（当前配置专属）",
        "provider": "已保存（此服务通用）",
        "env": "使用环境变量",
    }.get(source, "未配置")


class CommonSettingsPage(QWidget):
    """Small, action-oriented summary of reimbursement, export, and mailbox setup."""

    edit_profile_requested = Signal()
    choose_export_directory_requested = Signal()
    open_export_directory_requested = Signal()
    manage_mailbox_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommonSettingsPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignTop)

        self.profile_panel = ReadOnlyDetailPanel(
            "报销抬头与税号",
            "用于核对发票购买方信息；完整开票资料可在高级设置中维护。",
            self,
        )
        self.lbl_profile_name = self.profile_panel.add_row("单位名称", "未设置")
        self.lbl_profile_tax_id = self.profile_panel.add_row("纳税人识别号", "未设置")
        self.btn_profile_edit = make_button("编辑开票信息", variant="secondary")
        self.btn_profile_edit.clicked.connect(self.edit_profile_requested.emit)
        profile_actions = QHBoxLayout()
        profile_actions.setContentsMargins(0, 0, 0, 0)
        profile_actions.addWidget(self.btn_profile_edit)
        profile_actions.addStretch(1)
        self.profile_panel.body_layout.addLayout(profile_actions)
        layout.addWidget(self.profile_panel)

        self.export_panel = ReadOnlyDetailPanel(
            "报销单导出位置",
            "新的报销单和导出文件将保存到此文件夹。",
            self,
        )
        self.lbl_export_path = self.export_panel.add_row("当前目录", "—")
        export_actions = QHBoxLayout()
        export_actions.setContentsMargins(0, 0, 0, 0)
        self.btn_export_choose = make_button("更改目录", variant="secondary")
        self.btn_export_choose.clicked.connect(self.choose_export_directory_requested.emit)
        self.btn_export_open = make_button("打开目录", variant="secondary")
        self.btn_export_open.clicked.connect(self.open_export_directory_requested.emit)
        export_actions.addWidget(self.btn_export_choose)
        export_actions.addWidget(self.btn_export_open)
        export_actions.addStretch(1)
        self.export_panel.body_layout.addLayout(export_actions)
        layout.addWidget(self.export_panel)

        self.mailbox_panel = ReadOnlyDetailPanel(
            "邮箱账户",
            "查看已启用账号数量和授权状态；账号增删、扫描规则等选项在高级设置中。",
            self,
        )
        self.lbl_mailbox_status = self.mailbox_panel.add_row("当前状态", "尚未配置")
        self.btn_mailbox_manage = make_button("管理邮箱账户", variant="secondary")
        self.btn_mailbox_manage.clicked.connect(self.manage_mailbox_requested.emit)
        mailbox_actions = QHBoxLayout()
        mailbox_actions.setContentsMargins(0, 0, 0, 0)
        mailbox_actions.addWidget(self.btn_mailbox_manage)
        mailbox_actions.addStretch(1)
        self.mailbox_panel.body_layout.addLayout(mailbox_actions)
        layout.addWidget(self.mailbox_panel)
        layout.addStretch(1)

    def set_company_profile(self, name: str, tax_id: str) -> None:
        self.lbl_profile_name.setText(str(name or "未设置"))
        self.lbl_profile_tax_id.setText(str(tax_id or "未设置"))

    def set_export_directory(self, path: str) -> None:
        value = str(path or "—")
        self.lbl_export_path.setText(value)
        self.lbl_export_path.setToolTip(value)

    def set_mailbox_status(self, status: str) -> None:
        self.lbl_mailbox_status.setText(str(status or "尚未配置"))

# ── Settings page baseline (merged from settings_baseline) ──
_SETTINGS_MAX_WIDTH = 1120
_SETTINGS_NAV_WIDTH = 168
_PAGE_MARGIN = DESIGN_V1_METRICS["page_margin"]
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
    settings_tabs.viewportResized.connect(lambda: apply_settings_responsive_metrics(window))
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
        QStackedWidget#SettingsPageStack {{ background: {_BG_SURFACE}; }}
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
        elif label.wordWrap():
            policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            policy.setHeightForWidth(True)
            label.setSizePolicy(policy)
            label.setMinimumHeight(0)
            label.setMaximumHeight(16777215)

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
    # The centered settings shell can be far narrower than the main window.
    # Reserve scrollbar/frame space so its appearance cannot flip the layout.
    available_width = settings_tabs.contentsRect().width()
    compact = available_width < (_SETTINGS_NAV_WIDTH + _MAILBOX_LIST_WIDTH
                                 + _MAILBOX_DETAIL_MIN_WIDTH + 16 + 24)

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
        mailbox_shell.setAlignment(Qt.AlignTop)
        if account_list is not None:
            mailbox_shell.setAlignment(account_list, Qt.AlignTop)
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
        mailbox_editor.setMinimumWidth(0)
    if mailbox_surface is not None:
        mailbox_surface.setMinimumWidth(0)
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
        ai_surface.setMinimumWidth(0)
        ai_surface.setMaximumWidth(_MAILBOX_DETAIL_MAX_WIDTH)
    ai_empty = getattr(window, "settings_ai_empty_state", None)
    if ai_empty is not None:
        content_width = max(0, available_width - (nav_list.width() if nav_list else 0) - 24)
        ai_empty.setMinimumWidth(min(520, content_width))
        ai_empty.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    for attr in (
        "lbl_settings_runtime",
        "lbl_settings_privacy",
        "lbl_settings_data",
        "lbl_settings_about",
    ):
        surface = getattr(window, attr, None)
        if surface is not None:
            surface.setMinimumWidth(0)
            surface.setMaximumWidth(_MAILBOX_DETAIL_MAX_WIDTH)

    label_width = 88 if compact else _FIELD_LABEL_WIDTH
    for surface in settings_tabs.findChildren(QFrame):
        for label in surface.findChildren(QLabel):
            if label.property("class") in {"DetailFieldKey", "SettingsFieldKey"}:
                label.setMinimumWidth(label_width)
                label.setMaximumWidth(label_width)
                label.setFixedWidth(label_width)

    # Stacking the list does not imply that three short buttons need three rows.
    narrow_actions = available_width - nav_list.width() < 470 if nav_list is not None else compact
    for layout_attr in ("mailbox_action_footer_layout", "settings_ai_footer_layout"):
        footer_layout = getattr(window, layout_attr, None)
        if footer_layout is not None:
            footer_layout.setDirection(QBoxLayout.TopToBottom if narrow_actions else QBoxLayout.LeftToRight)

    QTimer.singleShot(0, lambda target=window: _fit_mailbox_status_wrapping(target))


def _fit_mailbox_status_wrapping(window) -> None:
    """Give wrapped connection/scan feedback its measured height after resize."""
    for name in ("lbl_settings_mailbox_test_status", "lbl_settings_mailbox_scan_result"):
        label = getattr(window, name, None)
        if label is None:
            continue
        try:
            if not label.wordWrap() or label.width() <= 0:
                continue
            label.setMinimumHeight(0)
            required = label.heightForWidth(label.width())
            if required > 0:
                label.setMinimumHeight(required)
                label.updateGeometry()
        except RuntimeError:
            return


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


def _account_state(account: dict, window=None) -> tuple[str, str]:
    address = str(account.get("address") or "").strip()
    state, variant, _ = connection_feedback(window, account, has_auth_code(address))
    return state, variant


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
        state_text, state_variant = _account_state(account, window)
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
        "连接成功": "approved",
        "尚未验证": "muted",
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

# ── Remaining settings pages (merged from settings_pages_baseline) ──
SURFACE = "#FFFFFF"
SURFACE_SECONDARY = "#F8FAFC"
BORDER = "#E5E7EB"
TEXT = "#182230"
MUTED = "#667085"
SUCCESS = "#16803C"
WARNING = "#B54708"

FIELD_LABEL_WIDTH = 104
DETAIL_MIN_WIDTH = 560
DETAIL_MAX_WIDTH = 760
PROFILE_LIST_WIDTH = 240
FIELD_ALIASES = {
    "Version": "版本与构建",
    "版本": "版本与构建",
    "本地数据目录": "数据目录",
}

LONG_VALUE_FIELDS = {
    "发送内容",
    "本地保护",
    "扫描规则",
    "最近运行",
    "最近校验",
    "最近扫描",
    "最近错误",
    "配置与日志",
    "诊断包",
    "产品定位",
}
PATH_VALUE_FIELDS = {
    "数据库",
    "日志目录",
    "数据目录",
    "备份目录",
    "导出目录",
}


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _divider(parent: QWidget) -> QFrame:
    divider = QFrame(parent)
    divider.setProperty("class", "SettingsSectionDivider")
    divider.setFrameShape(QFrame.HLine)
    divider.setFixedHeight(1)
    return divider


def _clear_layout(layout, preserve: set[QWidget] | None = None) -> None:
    preserve = preserve or set()
    while layout.count():
        item = layout.takeAt(0)
        nested = item.layout()
        widget = item.widget()
        if nested is not None:
            _clear_layout(nested, preserve)
            nested.deleteLater()
        elif widget is not None:
            if widget in preserve:
                widget.setParent(None)
            else:
                widget.deleteLater()


def _header(title: str, hint: str, parent: QWidget) -> QWidget:
    frame = QFrame(parent)
    frame.setObjectName("SettingsSubpageHeader")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    lbl_title = QLabel(title, frame)
    lbl_title.setProperty("class", "SettingsSubpageTitle")
    lbl_hint = QLabel(hint, frame)
    lbl_hint.setProperty("class", "SettingsSubpageHint")
    lbl_hint.setWordWrap(True)
    layout.addWidget(lbl_title)
    layout.addWidget(lbl_hint)
    return frame


def _collect_actions(page: QWidget) -> list[QWidget]:
    actions: list[QWidget] = []
    for widget in page.findChildren(QPushButton):
        if widget not in actions:
            actions.append(widget)
    for widget in page.findChildren(QToolButton):
        if widget.objectName() == "WorkbenchTopIconButton" and widget not in actions:
            actions.append(widget)
    return actions


class StructuredSettingsSurface(QFrame):
    """One bounded surface with a 104px field grid and an action footer."""

    def __init__(self, title: str, hint: str, fields: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsDetailSurface")
        self.setProperty("class", "SettingsDetailSurface")
        self.setMinimumWidth(DETAIL_MIN_WIDTH)
        self.setMaximumWidth(DETAIL_MAX_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._raw_text = ""
        self._field_order = [key for key, _ in fields]
        self.values: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(12)
        title_label = QLabel(title, self)
        title_label.setProperty("class", "SettingsSurfaceTitle")
        hint_label = QLabel(hint, self)
        hint_label.setProperty("class", "SettingsSurfaceHint")
        hint_label.setWordWrap(True)
        root.addWidget(title_label)
        root.addWidget(hint_label)
        root.addWidget(_divider(self))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for key, default in fields:
            if key in LONG_VALUE_FIELDS:
                value = WrappedTextLabel(default, self)
            elif key in PATH_VALUE_FIELDS:
                value = MiddleElidedTextLabel(default, self)
            else:
                value = ElidedTextLabel(default, self)
            value.setProperty("class", "SettingsFieldValue")
            value.setToolTip("" if default in {"", "—"} else default)
            _configure_value_label(value, key)
            self.values[key] = value
            form.addRow(key, value)
            label = form.labelForField(value)
            if label is not None:
                label.setFixedWidth(FIELD_LABEL_WIDTH)
                label.setProperty("class", "SettingsFieldKey")
        root.addLayout(form)

        self.inline_status = QLabel("", self)
        self.inline_status.setProperty("class", "SettingsInlineStatus")
        self.inline_status.setWordWrap(True)
        self.inline_status.hide()
        root.addWidget(self.inline_status)
        self.footer_divider = _divider(self)
        self.footer_divider.hide()
        root.addWidget(self.footer_divider)
        self.footer = QFrame(self)
        self.footer.setObjectName("SettingsActionFooter")
        self.footer.setMinimumHeight(52)
        self.footer_layout = QGridLayout(self.footer)
        self.footer_layout.setContentsMargins(0, 4, 0, 0)
        self.footer_layout.setSpacing(8)
        self.footer.hide()
        root.addWidget(self.footer)

    def setText(self, text: str) -> None:  # QLabel compatibility used by app.py
        self._raw_text = str(text or "")
        parsed: dict[str, str] = {}
        free_lines: list[str] = []
        for raw_line in self._raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            separator = "：" if "：" in line else (":" if ":" in line else "")
            if separator:
                key, value = line.split(separator, 1)
                key = FIELD_ALIASES.get(key.strip(), key.strip())
                parsed[key] = value.strip() or "—"
            elif line == "Invoice Hub" and "产品" in self.values:
                parsed["产品"] = line
            elif "本地优先" in line and "产品定位" in self.values:
                parsed["产品定位"] = line.rstrip("。")
            elif "凭据" in line and "凭据存储" in self.values:
                parsed["凭据存储"] = "Windows 凭据管理器"
            elif "脱敏" in line and "配置与日志" in self.values:
                parsed["配置与日志"] = "仅保留脱敏内容"
            else:
                free_lines.append(line)
        for key, value in parsed.items():
            self.set_value(key, value)
        # Only surface genuinely unowned information. Known product/privacy copy
        # belongs to the field grid and must not be repeated below it.
        self.set_status(" · ".join(free_lines))

    def text(self) -> str:
        return self._raw_text

    def set_value(self, key: str, value: str) -> None:
        label = self.values.get(key)
        if label is None:
            return
        text = str(value or "—")
        label.setText(text)
        label.setToolTip("" if text in {"", "—"} else text)

    def set_status(self, text: str) -> None:
        text = str(text or "").strip()
        self.inline_status.setText(text)
        self.inline_status.setVisible(bool(text))

    def set_actions(self, actions: list[QWidget]) -> None:
        while self.footer_layout.count():
            item = self.footer_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        columns = 2 if len(actions) > 3 else max(1, len(actions))
        for index, action in enumerate(actions):
            action.setParent(self.footer)
            self.footer_layout.addWidget(action, index // columns, index % columns, Qt.AlignLeft)
        self.footer_layout.setColumnStretch(columns, 1)
        self.footer.setVisible(bool(actions))
        self.footer_divider.setVisible(bool(actions))


def _migrate_info_page(window, index: int, title: str, hint: str, attr: str, fields):
    page = window.settings_tabs.widget(index)
    if page is None or page.property("settingsBaselineMigrated"):
        return
    page.setProperty("settingsBaselineMigrated", True)
    old_source = getattr(window, attr, None)
    actions = _collect_actions(page)
    layout = page.layout() or QVBoxLayout(page)
    _clear_layout(layout, set(actions))
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    layout.setAlignment(Qt.AlignTop)
    layout.addWidget(_header(title, hint, page))
    surface = StructuredSettingsSurface(title, hint, fields, page)
    if old_source is not None and hasattr(old_source, "text"):
        surface.setText(old_source.text())
    surface.set_actions(actions)
    layout.addWidget(surface, 0, Qt.AlignTop)
    layout.addStretch(1)
    setattr(window, attr, surface)
    setattr(window, f"{attr}_surface", surface)


def _configure_value_label(value: QLabel, key: str) -> None:
    """Apply the text contract without changing the surrounding visual style."""
    value.setMinimumHeight(0)
    value.setMaximumHeight(16777215)
    if key in LONG_VALUE_FIELDS:
        value.setWordWrap(True)
        policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        value.setSizePolicy(policy)
    else:
        value.setWordWrap(False)
        value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)


def _add_section(root: QVBoxLayout, parent: QWidget, title: str, rows):
    if root.count():
        root.addWidget(_divider(parent))
    heading = QLabel(title, parent)
    heading.setProperty("class", "SettingsSectionTitle")
    root.addWidget(heading)
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for key, value in rows:
        value.setParent(parent)
        _configure_value_label(value, key)
        form.addRow(key, value)
        label = form.labelForField(value)
        if label is not None:
            label.setFixedWidth(FIELD_LABEL_WIDTH)
            label.setProperty("class", "SettingsFieldKey")
    root.addLayout(form)


def _migrate_ai_page(window) -> None:
    page = window.settings_tabs.widget(1)
    if page is None or page.property("settingsBaselineMigrated"):
        return
    page.setProperty("settingsBaselineMigrated", True)
    for attr in ("lbl_settings_ai_provider", "lbl_settings_ai_model", "lbl_settings_ai_enabled",
                 "lbl_settings_ai_key_status", "lbl_settings_ai_session_state"):
        old = getattr(window, attr)
        label = ElidedTextLabel(old.text(), page)
        label.setProperty("class", old.property("class"))
        setattr(window, attr, label)
    profile_list = window.settings_ai_profile_list
    empty_state = window.settings_ai_empty_state
    labels = [
        window.lbl_settings_ai_provider,
        window.lbl_settings_ai_model,
        window.lbl_settings_ai_enabled,
        window.lbl_settings_ai_key_status,
        window.lbl_settings_ai_session_state,
        window.lbl_settings_ai_validation_status,
        window.lbl_settings_ai_send_boundary,
        window.lbl_settings_ai_log_redaction,
        window.lbl_settings_ai_failure_status,
    ]
    actions = [
        window.btn_settings_ai_test,
        window.btn_settings_ai_edit,
        window.btn_settings_ai_configure_key,
        window.settings_ai_more,
    ]
    preserve = {profile_list, empty_state, *labels, *actions}
    for widget in preserve:
        widget.setParent(None)
    layout = page.layout() or QVBoxLayout(page)
    _clear_layout(layout, preserve)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    layout.setAlignment(Qt.AlignTop)
    layout.addWidget(_header("AI 配置", "使用 AI 辅助分类和字段核验；凭据与数据边界保持可见。", page))

    shell = QHBoxLayout()
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(16)
    shell.setAlignment(Qt.AlignTop)
    profile_list.setMinimumWidth(0)
    profile_list.setMaximumWidth(PROFILE_LIST_WIDTH)
    profile_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    shell.addWidget(profile_list, 0, Qt.AlignTop)
    window.settings_ai_shell = shell

    surface = QFrame(page)
    surface.setObjectName("AISettingsDetailSurface")
    surface.setProperty("class", "SettingsDetailSurface")
    surface.setMinimumWidth(DETAIL_MIN_WIDTH)
    surface.setMaximumWidth(DETAIL_MAX_WIDTH)
    surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    root = QVBoxLayout(surface)
    root.setContentsMargins(20, 18, 20, 14)
    root.setSpacing(12)
    header_row = QHBoxLayout()
    title = QLabel("AI 服务", surface)
    title.setProperty("class", "SettingsSurfaceTitle")
    badge = QLabel("未配置", surface)
    badge.setObjectName("AISettingsStatusBadge")
    badge.setAlignment(Qt.AlignCenter)
    badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    header_row.addWidget(title)
    header_row.addStretch(1)
    header_row.addWidget(badge)
    root.addLayout(header_row)

    credential_store = ElidedTextLabel("Windows 凭据管理器", surface)
    credential_store.setToolTip("Windows 凭据管理器")
    window.lbl_settings_ai_credential_store = credential_store
    _add_section(root, surface, "当前配置", [
        ("Provider", window.lbl_settings_ai_provider),
        ("模型", window.lbl_settings_ai_model),
        ("AI 状态", window.lbl_settings_ai_enabled),
        ("API Key", window.lbl_settings_ai_key_status),
        ("会话状态", window.lbl_settings_ai_session_state),
        ("最近校验", window.lbl_settings_ai_validation_status),
        ("凭据存储", credential_store),
    ])
    _add_section(root, surface, "隐私边界", [
        ("发送内容", window.lbl_settings_ai_send_boundary),
        ("本地保护", window.lbl_settings_ai_log_redaction),
    ])
    window.lbl_settings_ai_failure_status.setParent(surface)
    window.lbl_settings_ai_failure_status.setProperty("class", "SettingsInlineStatus")
    _configure_value_label(window.lbl_settings_ai_failure_status, "最近校验")
    root.addWidget(window.lbl_settings_ai_failure_status)
    root.addWidget(_divider(surface))
    footer = QFrame(surface)
    footer.setObjectName("SettingsActionFooter")
    footer.setMinimumHeight(52)
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(0, 4, 0, 0)
    footer_layout.setSpacing(8)
    window.settings_ai_footer_layout = footer_layout
    for action in actions:
        action.setParent(footer)
        footer_layout.addWidget(action)
    footer_layout.addStretch(1)
    root.addWidget(footer)
    shell.addWidget(surface, 1, Qt.AlignTop)
    layout.addLayout(shell)

    empty_action = make_button("配置 AI", variant="primary", min_width=120)
    empty_action.clicked.connect(window._open_edit_ai_profile_dialog)
    empty_state.set_action(empty_action)

    # Keep the validation capability discoverable even before a profile
    # exists.  It is intentionally disabled rather than hidden because there
    # is no Provider/model/API-key configuration to validate yet.
    empty_validate = make_button("校验配置", variant="secondary", min_width=120)
    empty_validate.setEnabled(False)
    empty_validate.setToolTip("请先配置 AI Provider 和模型，再校验本地配置。")
    empty_state.layout().addWidget(empty_validate, 0, Qt.AlignCenter)

    empty_state.setMaximumWidth(520)
    empty_state.setMaximumHeight(190)
    layout.addWidget(empty_state, 0, Qt.AlignTop)
    layout.addStretch(1)
    window.settings_ai_detail_panel = surface
    window.lbl_settings_ai_status_badge = badge
    window.btn_settings_ai_empty_add = empty_action
    window.btn_settings_ai_empty_validate = empty_validate


def _normalize_ai(window) -> None:
    if not hasattr(window, "lbl_settings_ai_status_badge"):
        return
    for attr in ("lbl_settings_ai_provider", "lbl_settings_ai_model", "lbl_settings_ai_enabled",
                 "lbl_settings_ai_key_status", "lbl_settings_ai_session_state"):
        label = getattr(window, attr)
        label.setToolTip(label.text())
    state = getattr(window, "_settings_ai_state", {})
    key_source = state.get("key_source", "missing")
    configured = key_source in {"profile", "provider", "env"}
    window.lbl_settings_ai_key_status.setText(ai_key_source_text(key_source))
    window.lbl_settings_ai_key_status.setToolTip(
        "API Key 来源：环境变量 / Windows 凭据管理器；配置文件不保存密钥。"
    )
    enabled = bool(state.get("enabled"))
    paused = bool(state.get("paused"))
    if not enabled:
        status, tone = "未启用", "muted"
    elif not configured:
        status, tone = "待补 Key", "warning"
    elif paused:
        status, tone = "已暂停", "warning"
    else:
        status, tone = "已启用", "success"
    window.lbl_settings_ai_enabled.setText(status)
    window.lbl_settings_ai_enabled.setToolTip(
        "配置已启用；补充 API Key 后即可使用。" if enabled and not configured
        else "配置已启用；远端连接将在首次使用时确认。" if enabled
        else "当前配置未启用。"
    )
    badge = window.lbl_settings_ai_status_badge
    badge.setText(status)
    badge.setProperty("tone", tone)
    badge.setMinimumWidth(max(54, badge.fontMetrics().horizontalAdvance(status) + 18))
    _repolish(badge)
    failure = window.lbl_settings_ai_failure_status.text().strip()
    if failure.startswith("失败状态："):
        failure = failure[len("失败状态："):].strip()
    benign = {"", "暂无异常", "暂无异常。", "当前会话可用"}
    window.lbl_settings_ai_failure_status.setText(failure)
    window.lbl_settings_ai_failure_status.setVisible(failure not in benign)
    count = window.settings_ai_profile_list.count()
    window.settings_ai_profile_list.setVisible(count > 1)
    window.settings_ai_detail_panel.setVisible(count > 0)
    window.settings_ai_empty_state.setVisible(count == 0)


def _install_refresh_contract(window, page: QWidget) -> None:
    if page.property("settingsRemainingRefreshContractInstalled"):
        return
    page.setProperty("settingsRemainingRefreshContractInstalled", True)
    original = window._refresh_settings_page

    @wraps(original)
    def refresh(*args, **kwargs):
        result = original(*args, **kwargs)
        QTimer.singleShot(0, lambda: _normalize_ai(window))
        return result

    window._refresh_settings_page = refresh
    window.settings_ai_profile_list.currentRowChanged.connect(lambda _row: QTimer.singleShot(0, lambda: _normalize_ai(window)))
    for button in (window.btn_settings_ai_test, window.btn_settings_ai_edit, window.btn_settings_ai_configure_key):
        button.clicked.connect(lambda _checked=False: QTimer.singleShot(0, lambda: _normalize_ai(window)))


def _install_styles(settings_tabs: QWidget) -> None:
    settings_tabs.setStyleSheet(settings_tabs.styleSheet() + f"""
        QFrame#SettingsSubpageHeader {{ background: transparent; border: none; }}
        QLabel[class="SettingsSubpageTitle"] {{ color: {TEXT}; font-size: 15px; font-weight: 600; }}
        QLabel[class="SettingsSubpageHint"] {{ color: {MUTED}; font-size: 12px; }}
        QFrame[class="SettingsDetailSurface"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
        QLabel[class="SettingsSurfaceTitle"] {{ color: {TEXT}; font-size: 16px; font-weight: 600; }}
        QLabel[class="SettingsSurfaceHint"] {{ color: {MUTED}; font-size: 12px; }}
        QLabel[class="SettingsSectionTitle"] {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
        QLabel[class="SettingsFieldKey"] {{ color: {MUTED}; font-size: 12px; font-weight: 500; }}
        QLabel[class="SettingsFieldValue"] {{ color: {TEXT}; font-size: 13px; }}
        QFrame[class="SettingsSectionDivider"] {{ background: {BORDER}; border: none; }}
        QFrame#SettingsActionFooter {{ background: transparent; border: none; }}
        QLabel[class="SettingsInlineStatus"] {{ color: {MUTED}; background: {SURFACE_SECONDARY}; border-radius: 6px; padding: 8px 10px; }}
        QLabel#AISettingsStatusBadge {{ border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 600; }}
        QLabel#AISettingsStatusBadge[tone="success"] {{ color: {SUCCESS}; background: #ECFDF3; }}
        QLabel#AISettingsStatusBadge[tone="warning"] {{ color: {WARNING}; background: #FFFAEB; }}
        QLabel#AISettingsStatusBadge[tone="muted"] {{ color: {MUTED}; background: #F2F4F7; }}
    """)


def apply_remaining_settings_baseline(page: QWidget) -> None:
    """Apply the Mailbox Golden Page hierarchy to all remaining Settings pages."""
    if page is None or page.property("remainingSettingsBaselineApplied"):
        return
    window = page.window()
    if not hasattr(window, "settings_tabs") or window.settings_tabs.count() < 6:
        return
    page.setProperty("remainingSettingsBaselineApplied", True)
    _install_styles(window.settings_tabs)
    _migrate_ai_page(window)
    _migrate_info_page(window, 2, "运行状态", "查看本地数据库、日志、最近扫描和错误状态。", "lbl_settings_runtime", [
        ("数据库", "—"), ("日志目录", "—"), ("最近扫描", "暂无记录"), ("最近错误", "无")])
    _migrate_info_page(window, 3, "安全与隐私", "默认本地处理；凭据、日志和诊断包遵循最小披露原则。", "lbl_settings_privacy", [
        ("处理方式", "本地处理"), ("凭据存储", "Windows 凭据管理器"),
        ("配置与日志", "仅保留脱敏内容"), ("诊断包", "仅导出白名单与脱敏信息")])
    _migrate_info_page(window, 4, "数据与备份", "完整备份包含记录、原件和证明材料，可用于换机；数据库备份仅包含记录。两者均不包含邮箱或 AI 凭据。", "lbl_settings_data", [
        ("数据库大小", "—"), ("数据目录", "—"), ("备份目录", "—"), ("导出目录", "—")])
    _migrate_info_page(window, 5, "关于", "Invoice Hub 是本地优先的个人报销工作台。", "lbl_settings_about", [
        ("产品", "Invoice Hub"), ("版本与构建", "—"), ("产品定位", "本地优先的个人报销工作台")])
    _install_refresh_contract(window, page)
    window._refresh_settings_page()
    QTimer.singleShot(0, lambda: _normalize_ai(window))
    apply_settings_responsive_metrics(window)

# ── Company settings page and mailbox action clarity (merged from review_settings_issue_fixes) ──
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
    surface.setMinimumWidth(0)
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
        add.setFixedHeight(DESIGN_V1_METRICS['control_height'])
        add.setObjectName('SettingsAddMailbox')
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
    from .selection_surfaces import NAV_GROUP_ROLE

    nav = window.settings_tabs.nav_list
    for row in range(nav.count()):
        item = nav.item(row)
        item.setData(NAV_GROUP_ROLE, "常用" if row == 0 else "高级" if row == 2 else None)
        item.setData(Qt.AccessibleDescriptionRole, "常用设置" if row < 2 else "高级设置")
    for child in window.settings_tabs.stack.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        if child.layout() is not None:
            child.layout().setContentsMargins(16, 12, 16, 16)
    _polish_mailbox_actions(window)
    _install_settings_refresh(window, page)
    _remove_status_bar_version(window)




__all__ = [
    "CommonSettingsPage",
    "StructuredSettingsSurface",
    "apply_settings_baseline",
    "apply_settings_responsive_metrics",
    "apply_remaining_settings_baseline",
    "apply_settings_action_clarity",
    "_normalize_ai",
    "_refresh_mailbox_visuals",
    "LONG_VALUE_FIELDS",
]
