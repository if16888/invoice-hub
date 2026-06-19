# -*- coding: utf-8 -*-
"""Invoice Hub mailbox and AI settings dialog."""

import sys
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from ..config import load_config_safe, is_outlook_like_account



SAVED_SECRET_PLACEHOLDER = "已安全保存，重新输入可覆盖"
PROVIDER_EMAIL_SUFFIXES = {
    "qq": "qq.com",
    "netease_163": "163.com",
    "netease_126": "126.com",
    "gmail": "gmail.com",
    "outlook": "outlook.com",
}
KNOWN_PROVIDER_DOMAINS = {
    "qq.com", "163.com", "126.com", "gmail.com",
    "outlook.com", "hotmail.com", "live.com",
}
OUTLOOK_FAMILY_DOMAINS = {"outlook.com", "hotmail.com", "live.com"}
DOMAIN_TO_PROVIDER = {
    "qq.com": "qq",
    "163.com": "netease_163",
    "126.com": "netease_126",
    "gmail.com": "gmail",
    "outlook.com": "outlook",
    "hotmail.com": "outlook",
    "live.com": "outlook",
}
PROVIDER_EMAIL_NAMES = {
    "qq": "QQ",
    "netease_163": "163",
    "netease_126": "126",
    "gmail": "Gmail",
    "outlook": "Outlook",
    "custom": "自定义 IMAP",
}


class SecurePasswordLineEdit(QLineEdit):
    """Password input that accepts paste but never exports selected text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEchoMode(QLineEdit.Password)

    def copy(self):
        return None

    def cut(self):
        return None

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy) or event.matches(QKeySequence.Cut):
            event.accept()
            return
        super().keyPressEvent(event)

    def createStandardContextMenu(self):
        menu = super().createStandardContextMenu()
        blocked_shortcuts = {
            QKeySequence(QKeySequence.Copy).toString(QKeySequence.NativeText),
            QKeySequence(QKeySequence.Cut).toString(QKeySequence.NativeText),
        }
        for action in list(menu.actions()):
            shortcut = action.text().rsplit("\t", 1)[-1]
            if shortcut in blocked_shortcuts:
                menu.removeAction(action)
        return menu

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.exec(event.globalPos())
        menu.deleteLater()


def _load_config_safe_compat():
    app_module = sys.modules.get(f"{__package__}.app")
    loader = getattr(app_module, "load_config_safe", load_config_safe)
    return loader()


class MailboxConfigRow(QFrame):
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    enabled_requested = Signal(str, bool)

    def __init__(self, account: dict, parent=None):
        super().__init__(parent)
        self.parent_dialog = parent
        self.account = dict(account)
        self.mailbox_key = str(account.get("mailbox_key") or account.get("address") or "")

        self.setProperty("class", "SettingsListRow")
        self.setFrameShape(QFrame.StyledPanel)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Checkbox for enabled/disabled state
        self.chk_enabled = QCheckBox()
        self.chk_enabled.setChecked(self.account.get("enabled", True))
        self.chk_enabled.toggled.connect(self._on_toggled)
        layout.addWidget(self.chk_enabled)

        # Info layout: Vertical (Name & Masked Address)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        lbl_name = QLabel(self.account.get("name") or "未命名")
        lbl_name.setProperty("class", "SettingsListRowName")

        # Mask address
        from ..config import mask_email
        masked_address = mask_email(self.account.get("address") or "")
        lbl_address = QLabel(masked_address)
        lbl_address.setProperty("class", "SettingsListRowDesc")

        info_layout.addWidget(lbl_name)
        info_layout.addWidget(lbl_address)
        layout.addLayout(info_layout)

        layout.addStretch()

        # Provider badge
        provider_name = PROVIDER_EMAIL_NAMES.get(self.account.get("provider", "custom"), "自定义 IMAP")
        lbl_provider = QLabel(provider_name)
        lbl_provider.setProperty("class", "StatusBadge")
        lbl_provider.setProperty("variant", "info")
        layout.addWidget(lbl_provider)

        # Scan range summary
        months = int((self.account.get("search") or {}).get("months_back", 3))
        lbl_range = QLabel(f"最近 {months} 个月")
        lbl_range.setProperty("class", "SettingsListRowMeta")
        layout.addWidget(lbl_range)

        # Actions: Edit and Delete
        self.btn_edit = QPushButton("编辑")
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_edit.setFixedSize(50, 24)
        self.btn_edit.setProperty("class", "SecondaryBtn")
        layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_delete.setFixedSize(50, 24)
        self.btn_delete.setProperty("class", "SettingsDangerBtn")
        layout.addWidget(self.btn_delete)

    def summary_text(self) -> str:
        months = int((self.account.get("search") or {}).get("months_back", 3))
        return f"最近 {months} 个月"

    def _on_toggled(self, checked):
        self.enabled_requested.emit(self.mailbox_key, checked)

    def _on_edit(self):
        self.edit_requested.emit(self.mailbox_key)

    def _on_delete(self):
        self.delete_requested.emit(self.mailbox_key)


class AIProfileRow(QFrame):
    activate_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, profile: dict, key_available: bool, parent=None):
        super().__init__(parent)
        self.parent_dialog = parent
        self.profile = dict(profile)
        self.profile_id = str(profile["profile_id"])

        self.setProperty("class", "SettingsListRow")
        self.setFrameShape(QFrame.StyledPanel)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Info layout: Vertical (Name & Provider/Model)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        lbl_name = QLabel(self.profile.get("name") or "未命名")
        lbl_name.setProperty("class", "SettingsListRowName")

        provider = str(self.profile.get("provider") or "").title()
        model = self.profile.get("model") or ""
        lbl_model = QLabel(f"{provider} - {model}")
        lbl_model.setProperty("class", "SettingsListRowDesc")

        info_layout.addWidget(lbl_name)
        info_layout.addWidget(lbl_model)
        layout.addLayout(info_layout)

        layout.addStretch()

        # API Key status badge
        key_status_text = "🔑 已保存" if key_available else "🔑 未设置"
        lbl_key_status = QLabel(key_status_text)
        lbl_key_status.setProperty("class", "StatusBadge")
        lbl_key_status.setProperty("variant", "success" if key_available else "warning")
        layout.addWidget(lbl_key_status)

        # Activation state / Set as current button
        self.is_enabled = self.profile.get("enabled", False)
        if self.is_enabled:
            self.lbl_active = QLabel("当前生效")
            self.lbl_active.setProperty("class", "StatusBadge")
            self.lbl_active.setProperty("variant", "active")
            layout.addWidget(self.lbl_active)
        else:
            self.btn_activate = QPushButton("设为当前")
            self.btn_activate.clicked.connect(self._on_activate)
            self.btn_activate.setFixedSize(70, 24)
            self.btn_activate.setProperty("class", "PrimaryBtn")
            layout.addWidget(self.btn_activate)

        # Actions: Edit and Delete
        self.btn_edit = QPushButton("编辑")
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_edit.setFixedSize(50, 24)
        self.btn_edit.setProperty("class", "SecondaryBtn")
        layout.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_delete.setFixedSize(50, 24)
        self.btn_delete.setProperty("class", "SettingsDangerBtn")
        layout.addWidget(self.btn_delete)

    def _on_activate(self):
        self.activate_requested.emit(self.profile_id)

    def _on_edit(self):
        self.edit_requested.emit(self.profile_id)

    def _on_delete(self):
        self.delete_requested.emit(self.profile_id)


class SettingsDialog(QDialog):
    _last_active_tab_index = 0

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("系统设置")
        self.resize(650, 580)
        self.test_success = False
        self.current_step = 1
        self._loading_initial_values = True
        self._applying_provider_defaults = False
        self._loading_account_values = False
        self._advanced_settings_dirty = False
        self._active_provider = "qq"
        self._email_is_user_draft = False
        self._loaded_account_address = ""
        self._loaded_account_mailbox_key = ""
        self._loaded_account_provider = ""
        self._missing_saved_provider = ""
        self._editing_ai_profile_id = ""

        from ..config import _EMAIL_PROVIDER_PRESETS
        self.cfg = _load_config_safe_compat()
        self._build_saved_account_maps()

        # Stacked widget shell
        self.settings_stack = QStackedWidget()
        self.page_settings_home = QWidget()
        self.page_mailbox_editor = QWidget()
        self.page_ai_editor = QWidget()

        self.settings_stack.addWidget(self.page_settings_home)
        self.settings_stack.addWidget(self.page_mailbox_editor)
        self.settings_stack.addWidget(self.page_ai_editor)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)
        self.main_layout.addWidget(self.settings_stack)

        # Initialize pages
        self._init_settings_home_page()
        self._init_mailbox_editor_page()
        self._init_ai_editor_page()

        # Load initial values
        self._load_initial_values()
        self._loading_initial_values = False
        self._advanced_settings_dirty = False
        self._update_provider_hint()

    def _init_mailbox_editor_page(self):
        layout = QVBoxLayout(self.page_mailbox_editor)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Step Indicator
        self.lbl_step_indicator = QLabel()
        self.lbl_step_indicator.setAlignment(Qt.AlignCenter)
        self.lbl_step_indicator.setProperty("class", "WizardSteps")
        layout.addWidget(self.lbl_step_indicator)

        # Stacked Widget for Steps
        self.step_stack = QStackedWidget()
        layout.addWidget(self.step_stack)

        # Step 1 Widget
        self._init_step1_view()
        # Step 2 Widget
        self._init_step2_view()
        # Step 3 Widget
        self._init_step3_view()

        # Footer Buttons
        footer_layout = QHBoxLayout()
        self.btn_delete_mailbox = QPushButton("删除当前邮箱配置")
        self.btn_delete_mailbox.clicked.connect(self._delete_current_mailbox)
        self.btn_delete_mailbox.setStyleSheet("background-color: #FEE2E2; color: #DC2626; border: 1px solid #FCA5A5; font-size: 11px; padding: 4px 8px; border-radius: 4px;")
        self.btn_delete_mailbox.setFixedHeight(28)
        self.btn_delete_mailbox.setEnabled(False)
        self.btn_delete_mailbox.setVisible(False)

        self.btn_prev = QPushButton("上一步")
        self.btn_prev.clicked.connect(self._goto_prev_step)
        self.btn_prev.setProperty("class", "SecondaryBtn")
        self.btn_prev.setFixedHeight(28)

        self.btn_next = QPushButton("下一步")
        self.btn_next.clicked.connect(self._goto_next_step)
        self.btn_next.setProperty("class", "PrimaryBtn")
        self.btn_next.setFixedHeight(28)

        self.btn_save_wizard = QPushButton("确定保存")
        self.btn_save_wizard.clicked.connect(self._save_mailbox_settings)
        self.btn_save_wizard.setProperty("class", "PrimaryBtn")
        self.btn_save_wizard.setFixedHeight(28)

        self.btn_cancel_wizard = QPushButton("取消")
        self.btn_cancel_wizard.clicked.connect(lambda: self._show_settings_home("mailboxes"))
        self.btn_cancel_wizard.setProperty("class", "SecondaryBtn")
        self.btn_cancel_wizard.setFixedHeight(28)

        footer_layout.addWidget(self.btn_delete_mailbox)
        footer_layout.addWidget(self.btn_prev)
        footer_layout.addStretch()
        footer_layout.addWidget(self.btn_cancel_wizard)
        footer_layout.addWidget(self.btn_next)
        footer_layout.addWidget(self.btn_save_wizard)
        layout.addLayout(footer_layout)


        # Refresh UI state
        self._update_wizard_ui()

    def _init_step1_view(self):
        step1_widget = QScrollArea()
        step1_widget.setProperty("class", "SettingsScroll")
        step1_widget.setWidgetResizable(True)
        step1_widget.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        scroll_content.setProperty("class", "DialogCanvas")
        v_layout = QVBoxLayout(scroll_content)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(12)

        lbl_intro = QLabel("选择您的邮箱类型：")
        lbl_intro.setProperty("class", "SectionTitle")
        v_layout.addWidget(lbl_intro)

        # Provider cards grid
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        self.provider_group = QButtonGroup(self)
        self.provider_group.setExclusive(True)

        presets = [
            ("qq", "QQ 邮箱", "国内个人首选\n自动识别IMAP"),
            ("netease_163", "163 网易邮箱", "经典个人邮箱\n连接速度极快"),
            ("netease_126", "126 网易邮箱", "网易精品邮\n收发稳定高效"),
            ("gmail", "Gmail", "谷歌邮箱服务\n需海外网络代理"),
            ("outlook", "Outlook", "需要 OAuth2，当前版本暂不支持"),
            ("custom", "自定义 IMAP", "支持任意符合协议\n的第三方邮箱服务")
        ]

        self.cards = {}
        self.card_titles = {}
        for idx, (prov_id, title, desc) in enumerate(presets):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(175, 75)
            btn.setProperty("class", "SelectionCard")
            btn_layout = QVBoxLayout(btn)
            btn_layout.setContentsMargins(10, 8, 10, 8)
            btn_layout.setSpacing(2)

            t_lbl = QLabel(title)
            t_lbl.setProperty("class", "SelectionCardTitle")
            t_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            d_lbl = QLabel(desc)
            d_lbl.setProperty("class", "SelectionCardDescription")
            d_lbl.setWordWrap(True)
            d_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)

            btn_layout.addWidget(t_lbl)
            btn_layout.addWidget(d_lbl)

            self.provider_group.addButton(btn)
            self.cards[prov_id] = btn
            self.card_titles[prov_id] = t_lbl
            grid.addWidget(btn, idx // 3, idx % 3)

        self.provider_group.buttonClicked.connect(self._on_provider_card_clicked)
        v_layout.addWidget(grid_widget)

        self.lbl_outlook_step1_warning = QLabel(
            "Outlook/Hotmail/Live 及 Microsoft 365 邮箱需要 OAuth2/XOAUTH2 登录。当前版本暂不支持 Outlook 邮箱扫描。"
        )
        self.lbl_outlook_step1_warning.setWordWrap(True)
        self.lbl_outlook_step1_warning.setStyleSheet("color: #B45309; font-size: 11px; background-color: #FEF3C7; border: 1px solid #FCD34D; padding: 8px; border-radius: 4px; margin-top: 4px;")
        self.lbl_outlook_step1_warning.setVisible(False)
        v_layout.addWidget(self.lbl_outlook_step1_warning)

        # Form layout for input fields
        form_group = QGroupBox("邮箱基本配置")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(10)

        self.txt_email = QLineEdit()
        self.txt_email.setPlaceholderText("your_email@example.com")
        self.txt_email.textChanged.connect(self._on_email_text_changed)

        self.lbl_provider_hint = QLabel()
        self.lbl_provider_hint.setWordWrap(True)
        self.lbl_provider_hint.setStyleSheet("color: #D97706; font-size: 11px;")

        self.txt_months = QLineEdit("3")
        self.txt_months.setPlaceholderText("1-24")

        form_layout.addRow("邮箱地址:", self.txt_email)
        form_layout.addRow("", self.lbl_provider_hint)
        form_layout.addRow("搜索最近 N 个月:", self.txt_months)
        v_layout.addWidget(form_group)

        # Collapsible Advanced Settings
        self.btn_toggle_advanced = QPushButton("显示高级 IMAP 设置 ▼")
        self.btn_toggle_advanced.setProperty("class", "TextBtn")
        self.btn_toggle_advanced.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_advanced.clicked.connect(self._toggle_advanced_settings)
        v_layout.addWidget(self.btn_toggle_advanced)

        self.advanced_group = QGroupBox("高级 IMAP 参数")
        adv_layout = QFormLayout(self.advanced_group)
        adv_layout.setSpacing(8)
        self.txt_imap_server = QLineEdit()
        self.txt_imap_port = QLineEdit()
        self.lbl_imap_security = QLabel("SSL/TLS（启用）")
        self.txt_imap_server.textChanged.connect(self._on_advanced_settings_changed)
        self.txt_imap_port.textChanged.connect(self._on_advanced_settings_changed)
        adv_layout.addRow("IMAP 服务器:", self.txt_imap_server)
        adv_layout.addRow("IMAP 端口:", self.txt_imap_port)
        adv_layout.addRow("连接安全:", self.lbl_imap_security)
        v_layout.addWidget(self.advanced_group)

        self.advanced_group.setVisible(False)
        step1_widget.setWidget(scroll_content)
        self.step_stack.addWidget(step1_widget)

    def _init_step2_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(16)

        # Light Info Alert Panel
        alert_box = QFrame()
        alert_box.setProperty("class", "PrivacyPanel")
        alert_layout = QVBoxLayout(alert_box)
        alert_layout.setContentsMargins(12, 12, 12, 12)
        alert_text = QLabel(
            "<b>凭据安全说明</b><br>"
            "您的授权码直接交由 Windows 系统级别的凭据管理器加密存储，不会以明文写入配置，更不会上传至任何第三方服务器。"
        )
        alert_text.setProperty("class", "SectionHint")
        alert_text.setWordWrap(True)
        alert_layout.addWidget(alert_text)
        layout.addWidget(alert_box)

        self.lbl_outlook_guidance = QLabel(
            "Outlook/Hotmail/Live 及 Microsoft 365 邮箱需要 OAuth2/XOAUTH2 登录。当前版本暂不支持 Outlook 邮箱扫描。"
        )
        self.lbl_outlook_guidance.setWordWrap(True)
        self.lbl_outlook_guidance.setStyleSheet("color: #92400E; font-size: 11px;")
        self.lbl_outlook_guidance.setVisible(False)
        layout.addWidget(self.lbl_outlook_guidance)

        # Form fields
        form = QFormLayout()
        form.setSpacing(12)

        auth_input_layout = QHBoxLayout()
        self.txt_auth_code = SecurePasswordLineEdit()
        self.txt_auth_code.setPlaceholderText("请输入邮箱授权码（非登录密码）")
        self.txt_auth_code.textChanged.connect(self._on_auth_code_changed)

        btn_help = QPushButton("如何获取授权码")
        btn_help.clicked.connect(self._show_auth_code_help)
        btn_help.setProperty("class", "TextBtn")
        btn_help.setCursor(Qt.PointingHandCursor)

        auth_input_layout.addWidget(self.txt_auth_code, 1)
        auth_input_layout.addWidget(btn_help)

        form.addRow("邮箱授权码:", auth_input_layout)
        layout.addLayout(form)

        self.lbl_cred_status = QLabel()
        self.lbl_cred_status.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.lbl_cred_status)
        layout.addStretch()

        self.step_stack.addWidget(widget)

    def _init_step3_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        # Summary box
        sum_box = QGroupBox("邮箱设置摘要")
        sum_form = QFormLayout(sum_box)
        sum_form.setSpacing(8)

        self.lbl_sum_provider = QLabel()
        self.lbl_sum_email = QLabel()
        self.lbl_sum_months = QLabel()
        self.lbl_sum_protocol = QLabel()

        sum_form.addRow("邮箱提供商:", self.lbl_sum_provider)
        sum_form.addRow("邮箱账号:", self.lbl_sum_email)
        sum_form.addRow("检索月份范围:", self.lbl_sum_months)
        sum_form.addRow("接收协议/服务器:", self.lbl_sum_protocol)
        layout.addWidget(sum_box)

        # Verification controls
        test_box = QGroupBox("连接验证测试")
        test_layout = QVBoxLayout(test_box)
        test_layout.setSpacing(10)

        self.lbl_test_result = QLabel("未进行连接测试。")
        self.lbl_test_result.setWordWrap(True)
        self.lbl_test_result.setStyleSheet("color: #6B7280; font-size: 11px;")
        test_layout.addWidget(self.lbl_test_result)

        btn_test_layout = QHBoxLayout()
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(self._test_connection_clicked)
        self.btn_test.setProperty("class", "SecondaryBtn")
        self.btn_test.setFixedSize(120, 28)
        btn_test_layout.addWidget(self.btn_test)
        btn_test_layout.addStretch()
        test_layout.addLayout(btn_test_layout)

        layout.addWidget(test_box)
        layout.addStretch()

        self.step_stack.addWidget(widget)

    def _init_settings_home_page(self):
        layout = QVBoxLayout(self.page_settings_home)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        lbl_title = QLabel("系统配置中心")
        lbl_title.setProperty("class", "SettingsSectionTitle")
        layout.addWidget(lbl_title)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        self.tab_mailbox_list = QWidget()
        self._init_mailbox_list_tab()
        self.tab_widget.addTab(self.tab_mailbox_list, "邮箱账号")

        self.tab_ai_list = QWidget()
        self._init_ai_list_tab()
        self.tab_widget.addTab(self.tab_ai_list, "AI 模型")

        home_footer = QHBoxLayout()
        btn_close_home = QPushButton("关闭")
        btn_close_home.clicked.connect(self.accept)
        btn_close_home.setProperty("class", "SecondaryBtn")
        btn_close_home.setFixedHeight(28)
        home_footer.addStretch()
        home_footer.addWidget(btn_close_home)
        layout.addLayout(home_footer)

        self.tab_widget.setCurrentIndex(SettingsDialog._last_active_tab_index)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index):
        SettingsDialog._last_active_tab_index = index

    def _init_mailbox_list_tab(self):
        layout = QVBoxLayout(self.tab_mailbox_list)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header_layout = QHBoxLayout()
        lbl_section = QLabel("已配置的邮箱列表")
        lbl_section.setProperty("class", "SettingsListHeader")

        self.btn_add_mailbox = QPushButton("新增邮箱账号")
        self.btn_add_mailbox.clicked.connect(self._open_new_mailbox_editor)
        self.btn_add_mailbox.setProperty("class", "PrimaryBtn")
        self.btn_add_mailbox.setFixedHeight(26)

        header_layout.addWidget(lbl_section)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_add_mailbox)
        layout.addLayout(header_layout)

        self.mailbox_scroll = QScrollArea()
        self.mailbox_scroll.setWidgetResizable(True)
        self.mailbox_scroll.setFrameShape(QFrame.NoFrame)
        self.mailbox_scroll.setStyleSheet("background-color: transparent;")

        self.mailbox_scroll_content = QWidget()
        self.mailbox_scroll_content.setStyleSheet("background-color: transparent;")
        self.mailbox_list_layout = QVBoxLayout(self.mailbox_scroll_content)
        self.mailbox_list_layout.setContentsMargins(0, 0, 0, 0)
        self.mailbox_list_layout.setSpacing(6)
        self.mailbox_list_layout.addStretch()

        self.mailbox_scroll.setWidget(self.mailbox_scroll_content)
        layout.addWidget(self.mailbox_scroll)

        self.mailbox_rows = []

    def _init_ai_list_tab(self):
        layout = QVBoxLayout(self.tab_ai_list)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header_layout = QHBoxLayout()
        self.lbl_ai_global_status = QLabel("AI 功能未启用")
        self.lbl_ai_global_status.setProperty("class", "SettingsListHeader")

        self.btn_disable_ai_action = QPushButton("停用 AI")
        self.btn_disable_ai_action.clicked.connect(self._disable_ai)
        self.btn_disable_ai_action.setProperty("class", "SecondaryBtn")
        self.btn_disable_ai_action.setFixedHeight(26)

        self.btn_add_ai = QPushButton("新增 AI 配置")
        self.btn_add_ai.clicked.connect(self._open_new_ai_editor)
        self.btn_add_ai.setProperty("class", "PrimaryBtn")
        self.btn_add_ai.setFixedHeight(26)

        header_layout.addWidget(self.lbl_ai_global_status)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_disable_ai_action)
        header_layout.addWidget(self.btn_add_ai)
        layout.addLayout(header_layout)

        self.ai_scroll = QScrollArea()
        self.ai_scroll.setWidgetResizable(True)
        self.ai_scroll.setFrameShape(QFrame.NoFrame)
        self.ai_scroll.setStyleSheet("background-color: transparent;")

        self.ai_scroll_content = QWidget()
        self.ai_scroll_content.setStyleSheet("background-color: transparent;")
        self.ai_list_layout = QVBoxLayout(self.ai_scroll_content)
        self.ai_list_layout.setContentsMargins(0, 0, 0, 0)
        self.ai_list_layout.setSpacing(6)
        self.ai_list_layout.addStretch()

        self.ai_scroll.setWidget(self.ai_scroll_content)
        layout.addWidget(self.ai_scroll)

        self.ai_rows = []

    def _refresh_mailbox_list(self):
        for row in self.mailbox_rows:
            self.mailbox_list_layout.removeWidget(row)
            row.deleteLater()
        self.mailbox_rows.clear()

        raw_accounts = self.cfg.get("email_accounts")
        email_accounts = [
            dict(existing)
            for existing in raw_accounts
            if isinstance(existing, dict)
        ] if isinstance(raw_accounts, list) else []

        if not email_accounts:
            legacy_email = self.cfg.get("email", {})
            legacy_address = str(legacy_email.get("address") or "").strip()
            if legacy_address:
                email_accounts.append({
                    "name": legacy_email.get("name") or "默认邮箱",
                    "enabled": True,
                    "provider": legacy_email.get("provider", "qq"),
                    "address": legacy_address,
                    "username": legacy_email.get("username") or legacy_address,
                    "imap": dict(self.cfg.get("imap", {})),
                    "search": dict(self.cfg.get("search", {})),
                    "mailbox_key": legacy_email.get("mailbox_key") or legacy_address.lower(),
                })
                self.cfg["email_accounts"] = email_accounts
                from ..config import save_config
                try:
                    save_config(self.cfg)
                except Exception:
                    pass

        if not email_accounts:
            lbl_empty = QLabel("尚未配置任何邮箱账号，请点击上方“新增邮箱账号”。")
            lbl_empty.setAlignment(Qt.AlignCenter)
            lbl_empty.setProperty("class", "EmptyStateText")
            self.mailbox_list_layout.insertWidget(0, lbl_empty)
            self.mailbox_rows.append(lbl_empty)
        else:
            for idx, acc in enumerate(email_accounts):
                row = MailboxConfigRow(acc, self)
                row.edit_requested.connect(self._open_mailbox_editor)
                row.delete_requested.connect(self._delete_mailbox)
                row.enabled_requested.connect(self._set_mailbox_enabled)
                self.mailbox_list_layout.insertWidget(idx, row)
                self.mailbox_rows.append(row)

    def _refresh_ai_profile_list(self):
        for row in self.ai_rows:
            self.ai_list_layout.removeWidget(row)
            row.deleteLater()
        self.ai_rows.clear()

        from ..ai_profiles import get_ai_profiles
        profiles = get_ai_profiles(self.cfg)

        active = next((profile for profile in profiles if profile["enabled"]), None)
        if active:
            self.lbl_ai_global_status.setText(f"AI 功能已启用：{active['name']}")
        else:
            self.lbl_ai_global_status.setText("AI 功能未启用")

        if not profiles:
            lbl_empty = QLabel("尚未保存任何 AI 配置，点击“新增 AI 配置”开始。")
            lbl_empty.setAlignment(Qt.AlignCenter)
            lbl_empty.setProperty("class", "EmptyStateText")
            self.ai_list_layout.insertWidget(0, lbl_empty)
            self.ai_rows.append(lbl_empty)
        else:
            from ..credentials import has_ai_api_key
            for idx, p in enumerate(profiles):
                key_avail = has_ai_api_key(p["provider"], p["profile_id"])
                row = AIProfileRow(p, key_avail, self)
                row.edit_requested.connect(self._open_ai_editor)
                row.delete_requested.connect(self._delete_ai_profile)
                row.activate_requested.connect(self._set_active_ai_profile)
                self.ai_list_layout.insertWidget(idx, row)
                self.ai_rows.append(row)

    def _set_mailbox_enabled(self, mailbox_key: str, enabled: bool):
        raw_accounts = self.cfg.get("email_accounts")
        email_accounts = [
            dict(existing)
            for existing in raw_accounts
            if isinstance(existing, dict)
        ] if isinstance(raw_accounts, list) else []

        enabled_count = sum(1 for acc in email_accounts if acc.get("enabled", True))

        target_account = None
        for acc in email_accounts:
            if str(acc.get("mailbox_key") or acc.get("address") or "").strip().lower() == mailbox_key.lower():
                target_account = acc
                break

        if not target_account:
            return

        if not enabled and enabled_count <= 1 and target_account.get("enabled", True):
            QMessageBox.warning(self, "操作被拒绝", "至少需要保留一个启用的邮箱账号。")
            self._refresh_mailbox_list()
            return

        target_account["enabled"] = enabled
        self.cfg["email_accounts"] = email_accounts

        first_enabled = next((acc for acc in email_accounts if acc.get("enabled", True)), None)
        if first_enabled:
            self.cfg["email"] = {
                "provider": first_enabled.get("provider", "qq"),
                "address": first_enabled.get("address", ""),
                "username": first_enabled.get("username", first_enabled.get("address", "")),
            }
            self.cfg["imap"] = dict(first_enabled.get("imap", {}))
            self.cfg["search"] = dict(first_enabled.get("search", {}))

        from ..config import save_config
        try:
            save_config(self.cfg)
            if hasattr(self.parent, "config"):
                self.parent.config = _load_config_safe_compat()
            self._build_saved_account_maps()
            self._refresh_mailbox_list()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

    def _delete_mailbox(self, mailbox_key: str):
        raw_accounts = self.cfg.get("email_accounts")
        email_accounts = [
            dict(existing)
            for existing in raw_accounts
            if isinstance(existing, dict)
        ] if isinstance(raw_accounts, list) else []

        target_account = None
        for acc in email_accounts:
            if str(acc.get("mailbox_key") or acc.get("address") or "").strip().lower() == mailbox_key.lower():
                target_account = acc
                break

        if not target_account:
            return

        enabled_count = sum(1 for acc in email_accounts if acc.get("enabled", True))
        if enabled_count <= 1 and target_account.get("enabled", True):
            QMessageBox.warning(self, "操作被拒绝", "至少需要保留一个启用的邮箱账号。")
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            "删除邮箱配置只会移除该邮箱的登录设置、授权码和扫描同步状态，不会删除已导入的发票、本地附件或报销组。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        email_accounts = [acc for acc in email_accounts if acc != target_account]
        self.cfg["email_accounts"] = email_accounts

        email = target_account.get("address", "")
        if email:
            from ..credentials import delete_auth_code
            try:
                delete_auth_code(email)
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"🗑️ [安全凭证] 邮箱 {email} 的授权码凭证已从凭据管理器中移除。")
            except Exception as e:
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"⚠️ [安全凭证] 从凭据管理器移除邮箱 {email} 凭证失败: {e}")

        if hasattr(self.parent, "db") and self.parent.db:
            try:
                self.parent.db.remove_mailbox_scan_state(mailbox_key)
            except Exception as e:
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"⚠️ [数据库] 清除邮箱同步状态失败: {e}")

        first_enabled = next((acc for acc in email_accounts if acc.get("enabled", True)), None)
        if first_enabled:
            self.cfg["email"] = {
                "provider": first_enabled.get("provider", "qq"),
                "address": first_enabled.get("address", ""),
                "username": first_enabled.get("username", first_enabled.get("address", "")),
            }
            self.cfg["imap"] = dict(first_enabled.get("imap", {}))
            self.cfg["search"] = dict(first_enabled.get("search", {}))
        else:
            self.cfg["email"] = {"provider": "qq", "address": "", "username": ""}
            self.cfg["imap"] = {"server": "", "port": 993, "ssl": True}
            self.cfg["search"] = {"folder": "INBOX", "months_back": 3}

        from ..config import save_config
        try:
            save_config(self.cfg)
            if hasattr(self.parent, "config"):
                self.parent.config = _load_config_safe_compat()
            self._build_saved_account_maps()
            self._refresh_mailbox_list()
            QMessageBox.information(self, "成功", "邮箱配置已删除，已导入发票不会被删除。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

    def _show_settings_home(self, tab_name="mailboxes"):
        self.settings_stack.setCurrentWidget(self.page_settings_home)
        if tab_name == "mailboxes":
            self.tab_widget.setCurrentIndex(0)
        elif tab_name == "ai":
            self.tab_widget.setCurrentIndex(1)

    def _open_new_mailbox_editor(self):
        self._loaded_account_mailbox_key = ""
        self._loaded_account_address = ""
        self._loaded_account_provider = ""
        self._missing_saved_provider = ""
        self.txt_email.clear()
        self.txt_months.setText("3")
        self.txt_auth_code.clear()
        self.txt_auth_code.setPlaceholderText("请输入授权码/应用密码")
        self._select_provider_card("qq")
        self._apply_provider_defaults("qq")
        self.advanced_group.setVisible(False)
        self.btn_toggle_advanced.setText("显示高级 IMAP 设置 ▼")

        self.current_step = 1
        self._update_wizard_ui()
        self.settings_stack.setCurrentWidget(self.page_mailbox_editor)

    def _open_mailbox_editor(self, mailbox_key: str):
        acc = next((a for a in self._saved_accounts if (a.get("mailbox_key") or a.get("address") or "").lower() == mailbox_key.lower()), None)
        if not acc:
            QMessageBox.warning(self, "错误", f"找不到对应的邮箱配置: {mailbox_key}")
            return

        self._load_saved_account(acc)
        self.current_step = 1
        self._update_wizard_ui()
        self.settings_stack.setCurrentWidget(self.page_mailbox_editor)

    def _init_ai_editor_page(self):
        layout = QVBoxLayout(self.page_ai_editor)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        self.lbl_ai_step_indicator = QLabel()
        self.lbl_ai_step_indicator.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_ai_step_indicator)

        self.ai_step_stack = QStackedWidget()
        layout.addWidget(self.ai_step_stack)

        self._init_ai_step1_view()
        self._init_ai_step2_view()
        self._init_ai_step3_view()

        footer_layout = QHBoxLayout()
        self.btn_ai_prev = QPushButton("上一步")
        self.btn_ai_prev.clicked.connect(self._ai_goto_prev_step)
        self.btn_ai_prev.setProperty("class", "SecondaryBtn")
        self.btn_ai_prev.setFixedHeight(28)

        self.btn_ai_next = QPushButton("下一步")
        self.btn_ai_next.clicked.connect(self._ai_goto_next_step)
        self.btn_ai_next.setProperty("class", "PrimaryBtn")
        self.btn_ai_next.setFixedHeight(28)

        self.btn_ai_save_only = QPushButton("仅保存配置")
        self.btn_ai_save_only.clicked.connect(lambda: self._save_ai_profile_settings(activate=False))
        self.btn_ai_save_only.setProperty("class", "SecondaryBtn")
        self.btn_ai_save_only.setFixedHeight(28)

        self.btn_ai_save_and_activate = QPushButton("保存并设为当前")
        self.btn_ai_save_and_activate.clicked.connect(lambda: self._save_ai_profile_settings(activate=True))
        self.btn_ai_save_and_activate.setProperty("class", "PrimaryBtn")
        self.btn_ai_save_and_activate.setFixedHeight(28)

        self.btn_ai_cancel = QPushButton("取消")
        self.btn_ai_cancel.clicked.connect(lambda: self._show_settings_home("ai"))
        self.btn_ai_cancel.setProperty("class", "SecondaryBtn")
        self.btn_ai_cancel.setFixedHeight(28)

        footer_layout.addWidget(self.btn_ai_prev)
        footer_layout.addStretch()
        footer_layout.addWidget(self.btn_ai_cancel)
        footer_layout.addWidget(self.btn_ai_next)
        footer_layout.addWidget(self.btn_ai_save_only)
        footer_layout.addWidget(self.btn_ai_save_and_activate)
        layout.addLayout(footer_layout)

    def _init_ai_step1_view(self):
        widget = QScrollArea()
        widget.setWidgetResizable(True)
        widget.setFrameShape(QFrame.NoFrame)
        widget.setStyleSheet("background-color: transparent;")

        scroll_content = QWidget()
        v_layout = QVBoxLayout(scroll_content)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(12)

        form_group = QGroupBox("AI 基本配置")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(10)

        self.txt_ai_name = QLineEdit()
        self.txt_ai_name.setPlaceholderText("例如：我的主要分类模型")
        self.txt_ai_name.textChanged.connect(self._update_ai_wizard_ui)

        self.combo_ai_provider = QComboBox()
        self.combo_ai_provider.addItems(["deepseek", "gemini"])
        self.combo_ai_provider.currentTextChanged.connect(self._on_ai_wizard_provider_changed)

        form_layout.addRow("配置名称:", self.txt_ai_name)
        form_layout.addRow("AI 提供商:", self.combo_ai_provider)
        v_layout.addWidget(form_group)

        widget.setWidget(scroll_content)
        self.ai_step_stack.addWidget(widget)

    def _init_ai_step2_view(self):
        widget = QScrollArea()
        widget.setWidgetResizable(True)
        widget.setFrameShape(QFrame.NoFrame)
        widget.setStyleSheet("background-color: transparent;")

        scroll_content = QWidget()
        v_layout = QVBoxLayout(scroll_content)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(12)

        form_group = QGroupBox("模型与密钥配置")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(10)

        self.txt_ai_model = QComboBox()
        self.txt_ai_model.setEditable(True)
        self.txt_ai_model.lineEdit().setPlaceholderText("请选择或输入模型名称")

        self.lbl_ai_key_title = QLabel("API Key:")
        self.txt_ai_key = SecurePasswordLineEdit()
        self.txt_ai_key.textChanged.connect(self._update_ai_wizard_ui)

        self.lbl_ai_wizard_key_status = QLabel()
        self.lbl_ai_wizard_key_status.setWordWrap(True)
        self.lbl_ai_wizard_key_status.setStyleSheet("font-size: 11px;")

        form_layout.addRow("模型名称:", self.txt_ai_model)
        form_layout.addRow(self.lbl_ai_wizard_key_status)
        form_layout.addRow(self.lbl_ai_key_title, self.txt_ai_key)
        v_layout.addWidget(form_group)

        widget.setWidget(scroll_content)
        self.ai_step_stack.addWidget(widget)

    def _init_ai_step3_view(self):
        widget = QScrollArea()
        widget.setWidgetResizable(True)
        widget.setFrameShape(QFrame.NoFrame)
        widget.setStyleSheet("background-color: transparent;")

        scroll_content = QWidget()
        v_layout = QVBoxLayout(scroll_content)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(12)

        sum_group = QGroupBox("配置摘要")
        sum_layout = QFormLayout(sum_group)
        sum_layout.setSpacing(12)

        self.lbl_ai_summary_name = QLabel()
        self.lbl_ai_summary_provider = QLabel()
        self.lbl_ai_summary_model = QLabel()
        self.lbl_ai_summary_key_status = QLabel()

        sum_layout.addRow("配置名称:", self.lbl_ai_summary_name)
        sum_layout.addRow("服务提供商:", self.lbl_ai_summary_provider)
        sum_layout.addRow("所选模型:", self.lbl_ai_summary_model)
        sum_layout.addRow("API Key:", self.lbl_ai_summary_key_status)
        v_layout.addWidget(sum_group)

        widget.setWidget(scroll_content)
        self.ai_step_stack.addWidget(widget)

    def _on_ai_wizard_provider_changed(self, provider):
        self.txt_ai_model.clear()
        if provider == "deepseek":
            self.txt_ai_model.addItems(["deepseek-chat", "deepseek-coder"])
        elif provider == "gemini":
            self.txt_ai_model.addItems(["gemini-2.0-flash", "gemini-2.0-pro-exp", "gemini-1.5-flash", "gemini-1.5-pro"])

    def _update_ai_wizard_ui(self):
        self.ai_step_stack.setCurrentIndex(self.ai_current_step - 1)

        if self.ai_current_step == 1:
            self.lbl_ai_step_indicator.setText('<font color="#2563EB"><b>① 基本信息</b></font>  ➜  ② 模型与密钥  ➜  ③ 确认并保存')
            self.btn_ai_prev.setEnabled(False)
            self.btn_ai_next.setVisible(True)
            self.btn_ai_save_only.setVisible(False)
            self.btn_ai_save_and_activate.setVisible(False)
            self.btn_ai_next.setEnabled(bool(self.txt_ai_name.text().strip()))
        elif self.ai_current_step == 2:
            self.lbl_ai_step_indicator.setText('① 基本信息  ➜  <font color="#2563EB"><b>② 模型与密钥</b></font>  ➜  ③ 确认并保存')
            self.btn_ai_prev.setEnabled(True)
            self.btn_ai_next.setVisible(True)
            self.btn_ai_save_only.setVisible(False)
            self.btn_ai_save_and_activate.setVisible(False)

            from ..credentials import has_ai_api_key
            provider = self.combo_ai_provider.currentText()
            has_key = has_ai_api_key(provider, self._editing_ai_profile_id)
            if has_key:
                self.lbl_ai_wizard_key_status.setText("🔒 <font color='#10B981'><b>API Key 已安全保存。</b></font>如需覆盖，请在下方输入新 Key。")
                self.txt_ai_key.setPlaceholderText(SAVED_SECRET_PLACEHOLDER)
            else:
                self.lbl_ai_wizard_key_status.setText("🔑 未找到已保存的 API Key。请输入有效的 API Key 凭据。")
                self.txt_ai_key.setPlaceholderText("请输入 API Key")

            self.btn_ai_next.setEnabled(True)
        elif self.ai_current_step == 3:
            self.lbl_ai_step_indicator.setText('① 基本信息  ➜  ② 模型与密钥  ➜  <font color="#2563EB"><b>③ 确认并保存</b></font>')
            self.btn_ai_prev.setEnabled(True)
            self.btn_ai_next.setVisible(False)
            self.btn_ai_save_only.setVisible(True)
            self.btn_ai_save_and_activate.setVisible(True)

            self._update_ai_summary_fields()

    def _update_ai_summary_fields(self):
        self.lbl_ai_summary_name.setText(self.txt_ai_name.text().strip())
        self.lbl_ai_summary_provider.setText(self.combo_ai_provider.currentText())
        self.lbl_ai_summary_model.setText(self.txt_ai_model.currentText().strip())

        provider = self.combo_ai_provider.currentText()
        from ..credentials import has_ai_api_key
        has_saved_key = has_ai_api_key(provider, self._editing_ai_profile_id)
        has_input_key = bool(self.txt_ai_key.text().strip())

        if has_input_key:
            self.lbl_ai_summary_key_status.setText("已输入新 Key（保存时写入）")
        elif has_saved_key:
            self.lbl_ai_summary_key_status.setText("已保存（使用现有凭证）")
        else:
            self.lbl_ai_summary_key_status.setText("未设置（分类功能可能无法工作）")

        is_key_available = has_saved_key or has_input_key
        self.btn_ai_save_and_activate.setEnabled(is_key_available)

    def _ai_goto_next_step(self):
        if self.ai_current_step == 1:
            if not self.txt_ai_name.text().strip():
                QMessageBox.warning(self, "校验提示", "请填写配置名称。")
                return
            self.ai_current_step = 2
        elif self.ai_current_step == 2:
            self.ai_current_step = 3
        self._update_ai_wizard_ui()

    def _ai_goto_prev_step(self):
        if self.ai_current_step > 1:
            self.ai_current_step -= 1
            self._update_ai_wizard_ui()

    def _open_new_ai_editor(self):
        self._editing_ai_profile_id = f"ai-{uuid4().hex[:8]}"
        self.txt_ai_name.clear()
        self.txt_ai_key.clear()
        self.combo_ai_provider.setCurrentIndex(0)
        self._on_ai_wizard_provider_changed(self.combo_ai_provider.currentText())

        self.ai_current_step = 1
        self._update_ai_wizard_ui()
        self.settings_stack.setCurrentWidget(self.page_ai_editor)

    def _open_ai_editor(self, profile_id: str):
        from ..ai_profiles import get_ai_profiles
        profiles = get_ai_profiles(self.cfg)
        target = next((p for p in profiles if p["profile_id"] == profile_id), None)
        if not target:
            QMessageBox.warning(self, "错误", f"找不到对应的 AI 配置: {profile_id}")
            return

        self._editing_ai_profile_id = profile_id
        self.txt_ai_name.setText(target.get("name", ""))
        self.combo_ai_provider.setCurrentText(target.get("provider", "deepseek"))
        self._on_ai_wizard_provider_changed(target.get("provider", "deepseek"))
        self.txt_ai_model.setCurrentText(target.get("model", ""))
        self.txt_ai_key.clear()

        self.ai_current_step = 1
        self._update_ai_wizard_ui()
        self.settings_stack.setCurrentWidget(self.page_ai_editor)

    def _save_ai_profile_settings(self, activate: bool = False):
        provider = self.combo_ai_provider.currentText()
        name = self.txt_ai_name.text().strip()
        model = self.txt_ai_model.currentText().strip()
        key = self.txt_ai_key.text().strip()

        if not name:
            QMessageBox.warning(self, "校验提示", "请填写配置名称。")
            return
        if not model:
            QMessageBox.warning(self, "校验提示", "请选择或输入模型名称。")
            return

        if key:
            from ..credentials import set_ai_api_key
            try:
                set_ai_api_key(provider, key, profile_id=self._editing_ai_profile_id)
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"💾 [安全凭证] AI 配置 {name} 的 API Key 已保存。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存 AI 密钥凭据失败: {e}")
                return

        from ..ai_profiles import get_ai_profiles, apply_active_ai_profile
        profiles = get_ai_profiles(self.cfg)

        existing = next((p for p in profiles if p["profile_id"] == self._editing_ai_profile_id), None)

        if activate:
            for p in profiles:
                p["enabled"] = False

        is_active = activate or (existing.get("enabled", False) if existing else False)

        profile_data = {
            "profile_id": self._editing_ai_profile_id,
            "name": name,
            "provider": provider,
            "model": model,
            "enabled": is_active
        }

        if existing:
            idx = profiles.index(existing)
            profiles[idx] = profile_data
        else:
            profiles.append(profile_data)

        apply_active_ai_profile(self.cfg, profiles)

        from ..config import save_config
        try:
            save_config(self.cfg)
            from ..ai_classifier import clear_provider_session_paused
            clear_provider_session_paused(provider)

            if hasattr(self.parent, "config"):
                self.parent.config = _load_config_safe_compat()
            if hasattr(self.parent, "write_log"):
                self.parent.write_log(f"⚙️ [设置保存] 全局 config.json AI 配置已更新。")

            self.txt_ai_key.clear()
            QMessageBox.information(self, "成功", "AI 配置已成功保存！")
            self._persist_settings_and_refresh("ai")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存 AI 配置文件失败: {e}")

    def _set_active_ai_profile(self, profile_id: str):
        from ..ai_profiles import get_ai_profiles, apply_active_ai_profile
        profiles = get_ai_profiles(self.cfg)

        target = next((p for p in profiles if p["profile_id"] == profile_id), None)
        if not target:
            return

        from ..credentials import has_ai_api_key
        if not has_ai_api_key(target["provider"], target["profile_id"]):
            QMessageBox.warning(self, "无法启用 AI", "请先为该配置保存有效的 API Key。")
            return

        for p in profiles:
            p["enabled"] = (p["profile_id"] == profile_id)

        apply_active_ai_profile(self.cfg, profiles)
        self._persist_settings_and_refresh("ai")

    def _disable_ai(self):
        from ..ai_profiles import get_ai_profiles, apply_active_ai_profile
        profiles = get_ai_profiles(self.cfg)

        for p in profiles:
            p["enabled"] = False

        apply_active_ai_profile(self.cfg, profiles)
        self._persist_settings_and_refresh("ai")

    def _delete_ai_profile(self, profile_id: str):
        from ..ai_profiles import get_ai_profiles, apply_active_ai_profile
        profiles = get_ai_profiles(self.cfg)

        target = next((p for p in profiles if p["profile_id"] == profile_id), None)
        if not target:
            return

        is_active = target.get("enabled", False)
        warn_msg = "确认要删除该 AI 配置吗？"
        if is_active:
            warn_msg = "该配置当前正在使用，删除后 AI 辅助分类功能将被停用。确认删除吗？"

        reply = QMessageBox.question(
            self,
            "确认删除",
            warn_msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        profiles = [p for p in profiles if p["profile_id"] != profile_id]
        apply_active_ai_profile(self.cfg, profiles)

        from ..config import save_config
        try:
            save_config(self.cfg)

            from ..credentials import delete_ai_api_key
            delete_ai_api_key(target["provider"], profile_id=profile_id)

            if hasattr(self.parent, "write_log"):
                self.parent.write_log(f"🗑️ [安全凭证] AI 配置 {target.get('name')} 的凭证已清除。")

            self._persist_settings_and_refresh("ai")
            QMessageBox.information(self, "成功", "AI 配置已成功删除。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除 AI 配置失败: {e}")

    def _persist_settings_and_refresh(self, tab_name: str):
        self.cfg = _load_config_safe_compat()
        if hasattr(self.parent, "config"):
            self.parent.config = self.cfg
        self._build_saved_account_maps()
        self._refresh_mailbox_list()
        self._refresh_ai_profile_list()
        self._show_settings_home(tab_name)

    def _load_initial_values(self):
        current_email = self.cfg.get("email", {}).get("address", "")
        current_provider = self.cfg.get("email", {}).get("provider", "qq")
        current_account = self._saved_accounts_by_address.get(self._normalize_address(current_email))
        if current_account is None:
            current_account = self._first_saved_account(current_provider)
        if current_account is not None:
            self._load_saved_account(current_account)
        else:
            self._select_provider_card(current_provider)
            self._loading_account_values = True
            try:
                self.txt_email.setText(current_email)
                self.txt_months.setText(str(self.cfg.get("search", {}).get("months_back", 3)))
            finally:
                self._loading_account_values = False
            if current_provider == "custom":
                self.advanced_group.setVisible(True)
                self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲")
                self._set_advanced_values(
                    self.cfg.get("imap", {}).get("server", ""),
                    self.cfg.get("imap", {}).get("port", 993),
                )
            else:
                self._apply_provider_defaults(current_provider)

        # AI settings
        ai_prov = self.cfg.get("ai", {}).get("provider", "none")
        self.combo_ai_provider.setCurrentText(ai_prov)
        saved_model = self.cfg.get("ai", {}).get("model", "")
        if saved_model:
            self.txt_ai_model.setCurrentText(saved_model)

        self._update_cred_status_label()

    @staticmethod
    def _normalize_address(address):
        return str(address or "").strip().lower()

    def _build_saved_account_maps(self):
        self._saved_accounts = []
        self._saved_accounts_by_provider = {}
        self._saved_accounts_by_address = {}
        self._saved_accounts_by_mailbox_key = {}

        raw_accounts = self.cfg.get("email_accounts")
        if isinstance(raw_accounts, list):
            self._saved_accounts.extend(
                dict(account) for account in raw_accounts if isinstance(account, dict)
            )

        legacy_email = self.cfg.get("email", {})
        legacy_address = self._normalize_address(legacy_email.get("address"))
        if legacy_address and not any(
            self._normalize_address(account.get("address")) == legacy_address
            for account in self._saved_accounts
        ):
            self._saved_accounts.append({
                "name": legacy_email.get("name", ""),
                "enabled": True,
                "provider": legacy_email.get("provider", "qq"),
                "address": legacy_email.get("address", ""),
                "username": legacy_email.get("username") or legacy_email.get("address", ""),
                "imap": dict(self.cfg.get("imap", {})),
                "search": dict(self.cfg.get("search", {})),
                "mailbox_key": legacy_email.get("mailbox_key") or legacy_address,
            })

        for account in self._saved_accounts:
            provider = str(account.get("provider") or "custom").lower()
            address = self._normalize_address(account.get("address"))
            mailbox_key = self._normalize_address(account.get("mailbox_key"))
            self._saved_accounts_by_provider.setdefault(provider, []).append(account)
            if address:
                self._saved_accounts_by_address[address] = account
            if mailbox_key:
                self._saved_accounts_by_mailbox_key[mailbox_key] = account

    def _first_saved_account(self, provider):
        accounts = self._saved_accounts_by_provider.get(provider, [])
        return next((account for account in accounts if account.get("enabled", True)), None) or (
            accounts[0] if accounts else None
        )

    def _is_saved_address(self, address):
        return self._normalize_address(address) in self._saved_accounts_by_address

    def _is_valid_email(self, email):
        email = (email or "").strip()
        if not email or "@" not in email:
            return False
        parts = email.split("@", 1)
        return len(parts[0]) > 0 and len(parts[1]) > 0

    def _update_delete_button_state(self):
        email = self.txt_email.text().strip()
        email_clean = self._normalize_address(email)
        selected_provider = self._get_selected_provider()
        provider_accounts = self._saved_accounts_by_provider.get(selected_provider, [])

        is_delete_enabled = False
        if email_clean and provider_accounts:
            for acc in provider_accounts:
                acc_addr = self._normalize_address(acc.get("address"))
                acc_key = self._normalize_address(acc.get("mailbox_key"))
                if acc_addr == email_clean or acc_key == email_clean:
                    is_delete_enabled = True
                    break

        self.btn_delete_mailbox.setEnabled(is_delete_enabled)

    def _load_saved_account(self, account):
        provider = str(account.get("provider") or "custom").lower()
        address = str(account.get("address") or "").strip()
        imap = account.get("imap") if isinstance(account.get("imap"), dict) else {}
        search = account.get("search") if isinstance(account.get("search"), dict) else {}

        self._loading_account_values = True
        try:
            self._select_provider_card(provider)
            self.txt_email.setText(address)
            self.txt_months.setText(str(search.get("months_back") or 3))
            if provider == "custom":
                self.advanced_group.setVisible(True)
                self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲")
            else:
                self.advanced_group.setVisible(False)
                self.btn_toggle_advanced.setText("显示高级 IMAP 设置 ▼")
            if imap.get("server"):
                self._set_advanced_values(imap.get("server"), imap.get("port", 993))
            else:
                self._apply_provider_defaults(provider)
        finally:
            self._loading_account_values = False

        self._email_is_user_draft = False
        self._loaded_account_address = self._normalize_address(address)
        self._loaded_account_mailbox_key = self._normalize_address(account.get("mailbox_key"))
        self._loaded_account_provider = provider
        self._missing_saved_provider = ""
        self._advanced_settings_dirty = False
        self._update_provider_hint()
        self._update_cred_status_label()

    def _get_selected_provider(self):
        for prov_id, card in self.cards.items():
            if card.isChecked():
                return prov_id
        return "qq"

    def _select_provider_card(self, provider):
        if provider in self.cards:
            self.cards[provider].setChecked(True)
            self._active_provider = provider
            self._refresh_provider_card_visuals()

    def _refresh_provider_card_visuals(self):
        for provider, title_label in self.card_titles.items():
            title_label.setProperty("selected", self.cards[provider].isChecked())
            title_label.style().unpolish(title_label)
            title_label.style().polish(title_label)

    def _on_provider_card_clicked(self, checked_btn):
        self._refresh_provider_card_visuals()
        provider = self._get_selected_provider()
        previous_provider = self._active_provider
        if previous_provider == provider:
            return

        if provider != "custom" and self._advanced_settings_dirty:

            reply = QMessageBox.question(
                self,
                "重置 IMAP 参数",
                "高级 IMAP 参数已手工修改。是否重置为所选邮箱的默认服务器、端口和 SSL/TLS 设置？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                self._select_provider_card(previous_provider)
                return

        self._active_provider = provider
        saved_account = self._first_saved_account(provider)
        if saved_account is not None:
            self._load_saved_account(saved_account)
            return

        current_email = self.txt_email.text().strip()
        can_rewrite_draft = self._email_is_user_draft and not self._is_saved_address(current_email)
        self._missing_saved_provider = provider
        self._loaded_account_address = ""
        self._loaded_account_mailbox_key = ""
        self._loaded_account_provider = ""
        self._loading_account_values = True
        try:
            if can_rewrite_draft:
                self._adjust_email_for_provider(provider)
            else:
                self.txt_email.clear()
                self._adjust_email_for_provider(provider)
        finally:
            self._loading_account_values = False
        self._email_is_user_draft = can_rewrite_draft
        if provider == "custom":
            self.advanced_group.setVisible(True)
            self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲")
        else:
            self.advanced_group.setVisible(False)
            self.btn_toggle_advanced.setText("显示高级 IMAP 设置 ▼")
            self._apply_provider_defaults(provider)
        self._update_provider_hint()
        self._update_cred_status_label()
        self._update_wizard_ui()

    def _mark_advanced_settings_dirty(self, *_args):
        if not self._loading_initial_values and not self._applying_provider_defaults:
            self._advanced_settings_dirty = True

    def _on_advanced_settings_changed(self, *_args):
        self._mark_advanced_settings_dirty()
        self._update_provider_hint()
        self._update_cred_status_label()
        self._update_wizard_ui()

    def _set_advanced_values(self, server, port):
        self._applying_provider_defaults = True
        try:
            self.txt_imap_server.setText(str(server or ""))
            self.txt_imap_port.setText(str(port or 993))
            self.lbl_imap_security.setText("SSL/TLS（启用）")
        finally:
            self._applying_provider_defaults = False

    def _apply_provider_defaults(self, provider):
        from ..config import _EMAIL_PROVIDER_PRESETS

        preset = _EMAIL_PROVIDER_PRESETS.get(provider)
        if preset:
            self._set_advanced_values(preset["server"], preset["port"])
            self._advanced_settings_dirty = False

    def _adjust_email_for_provider(self, provider):
        provider_name = PROVIDER_EMAIL_NAMES.get(provider, "邮箱")
        if provider == "custom":
            self.txt_email.setPlaceholderText("请输入完整邮箱地址")
            return

        self.txt_email.setPlaceholderText(f"请输入完整 {provider_name} 邮箱地址")
        email = self.txt_email.text().strip()
        if not email or "@" not in email:
            return
        local_part, domain = email.rsplit("@", 1)
        domain = domain.lower()
        if not local_part or not domain:
            return
        if provider == "outlook" and domain in OUTLOOK_FAMILY_DOMAINS:
            return
        if domain in KNOWN_PROVIDER_DOMAINS:
            self.txt_email.setText(f"{local_part}@{PROVIDER_EMAIL_SUFFIXES[provider]}")

    def _update_provider_hint(self):
        if not hasattr(self, "lbl_provider_hint"):
            return
        provider = self._get_selected_provider()
        email = self.txt_email.text().strip()
        if provider == "custom":
            server = self.txt_imap_server.text().strip()
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider, {})
            server = preset.get("server", "")

        is_outlook_like = is_outlook_like_account(provider, email, server)

        self.lbl_outlook_guidance.setVisible(False)
        self.lbl_outlook_step1_warning.setVisible(is_outlook_like)
        if is_outlook_like:
            if provider == "custom":
                self.lbl_outlook_step1_warning.setText(
                    "检测到 Outlook/Microsoft IMAP 服务器。当前版本不支持授权码/应用密码方式连接 Outlook，需要 OAuth2/XOAUTH2，因此不能保存为可扫描账号。"
                )
            else:
                self.lbl_outlook_step1_warning.setText(
                    "Outlook/Hotmail/Live 及 Microsoft 365 邮箱需要 OAuth2/XOAUTH2 登录。当前版本暂不支持 Outlook 邮箱扫描。"
                )

        if hasattr(self, "btn_next") and self.current_step == 1:
            is_valid = self._is_valid_email(email)
            self.btn_next.setEnabled(provider != "outlook" and not is_outlook_like and is_valid)

        domain = email.rsplit("@", 1)[1].lower() if "@" in email else ""
        if provider == "outlook" and not email:
            self.lbl_provider_hint.setText(
                "未找到已保存的 Outlook 邮箱。Outlook 当前版本暂不支持配置/测试。"
            )
        elif not self._saved_accounts and not email:
            self.lbl_provider_hint.setText("尚未配置邮箱，请选择邮箱类型并输入完整邮箱地址。")
        elif self._missing_saved_provider == provider and not email:
            provider_name = PROVIDER_EMAIL_NAMES.get(provider, "邮箱")
            self.lbl_provider_hint.setText(
                f"未找到已保存的 {provider_name} 邮箱，请输入完整邮箱地址。"
            )
        elif (provider == "outlook" or is_outlook_like) and domain and domain not in OUTLOOK_FAMILY_DOMAINS:
            self.lbl_provider_hint.setText(
                "公司/学校 Microsoft 365 邮箱可能不支持授权码 IMAP，可能需要 OAuth2，当前版本暂不支持。"
            )
        elif provider != "custom" and domain and domain not in KNOWN_PROVIDER_DOMAINS:
            self.lbl_provider_hint.setText("检测到自定义域名邮箱，请确认服务器和认证方式。")
        else:
            self.lbl_provider_hint.setText("")

    def _update_cred_status_label(self):
        from ..credentials import has_auth_code
        email = self.txt_email.text().strip()

        # Update delete button state
        self._update_delete_button_state()

        if not email:
            self.lbl_cred_status.setText("🔒 授权状态：<b>未输入邮箱地址</b>")
            self.txt_auth_code.setPlaceholderText("请输入邮箱授权码（非登录密码）")
            return

        provider = self._get_selected_provider()
        if provider == "custom":
            server = self.txt_imap_server.text().strip()
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider, {})
            server = preset.get("server", "")

        is_outlook_like = is_outlook_like_account(provider, email, server)

        if is_outlook_like:
            email_clean = self._normalize_address(email)
            if email_clean in self._saved_accounts_by_address:
                self.lbl_cred_status.setText("🔒 授权状态：<font color='#D97706'><b>已保存 Outlook 账号，但当前版本暂不支持测试/扫描</b></font>")
            else:
                self.lbl_cred_status.setText("🔒 授权状态：<font color='#D97706'><b>Outlook 当前版本暂不支持配置/测试</b></font>")
            self.txt_auth_code.setPlaceholderText(SAVED_SECRET_PLACEHOLDER)
            return

        if has_auth_code(email):
            self.lbl_cred_status.setText("🔒 授权状态：<font color='#10B981'><b>已安全保存到系统凭据管理器</b></font>")
            self.txt_auth_code.setPlaceholderText(SAVED_SECRET_PLACEHOLDER)
        else:
            self.lbl_cred_status.setText("🔒 授权状态：<font color='#EF4444'><b>尚未配置 (点击下一步并保存时将自动加密保存)</b></font>")
            self.txt_auth_code.setPlaceholderText("请输入邮箱授权码（非登录密码）")


    def _on_email_text_changed(self):
        if self._loading_initial_values or self._loading_account_values:
            return

        email = self.txt_email.text().strip()
        email_clean = self._normalize_address(email)

        # Enable/disable the delete button dynamically
        self._update_delete_button_state()

        has_saved = self._is_saved_address(email_clean)
        # If it is a saved email, auto-load all its configuration!
        if has_saved:
            if self._loaded_account_address != email_clean:
                saved_acc = self._saved_accounts_by_address[email_clean]
                self._load_saved_account(saved_acc)
                return

        self._email_is_user_draft = True
        self._missing_saved_provider = ""
        email_lower = email.lower()
        domain = email_lower.rsplit("@", 1)[1] if "@" in email_lower else ""
        provider = DOMAIN_TO_PROVIDER.get(domain)
        if provider and self._loaded_account_provider and provider != self._loaded_account_provider:
            self._loaded_account_address = ""
            self._loaded_account_mailbox_key = ""
            self._loaded_account_provider = ""
        if provider and provider != self._get_selected_provider():
            if self._advanced_settings_dirty:
                reply = QMessageBox.question(
                    self,
                    "重置 IMAP 参数",
                    "高级 IMAP 参数已手工修改。是否重置为识别邮箱的默认服务器、端口和 SSL/TLS 设置？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    self._update_provider_hint()
                    self._update_cred_status_label()
                    return
            self._select_provider_card(provider)
            self._apply_provider_defaults(provider)
        self._update_provider_hint()
        self._update_cred_status_label()


    def _on_auth_code_changed(self):
        self.test_success = False
        self.lbl_test_result.setText("邮箱授权码已更改，请重新进行连接测试。")
        self.lbl_test_result.setStyleSheet("color: #D97706; font-size: 11px;")

    def _toggle_advanced_settings(self):
        visible = not self.advanced_group.isVisible()
        self.advanced_group.setVisible(visible)
        self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲" if visible else "显示高级 IMAP 设置 ▼")

    def _on_ai_provider_changed(self):
        provider = self.combo_ai_provider.currentText()

        # Populate model items based on provider
        self.txt_ai_model.clear()
        if provider == "deepseek":
            self.txt_ai_model.addItems(["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"])
            self.txt_ai_model.setCurrentText("deepseek-v4-flash")
            self.txt_ai_model.setEnabled(True)
        elif provider == "gemini":
            self.txt_ai_model.addItems(["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"])
            self.txt_ai_model.setCurrentText("gemini-2.5-flash")
            self.txt_ai_model.setEnabled(True)
        else: # none
            self.txt_ai_model.setEnabled(False)

        if provider == "none":
            self.lbl_ai_key_status.setVisible(False)
            self.lbl_ai_key_title.setVisible(False)
            self.txt_ai_key.setVisible(False)
            return

        self.lbl_ai_key_status.setVisible(True)
        self.lbl_ai_key_title.setVisible(True)
        self.txt_ai_key.setVisible(True)

        from ..credentials import has_ai_api_key
        if has_ai_api_key(provider):
            self.lbl_ai_key_status.setText(
                "🔑 API Key 状态：<font color='#10B981'><b>已安全保存到系统凭据管理器</b></font>（输入新值可覆盖，留空则保持不变）"
            )
            self.txt_ai_key.setPlaceholderText(SAVED_SECRET_PLACEHOLDER)
        else:
            self.lbl_ai_key_status.setText(
                "🔑 API Key 状态：<font color='#EF4444'><b>尚未配置</b></font>"
            )
            self.txt_ai_key.setPlaceholderText("请输入 API Key")

    def _show_auth_code_help(self):
        if self._get_selected_provider() == "outlook":
            QMessageBox.information(
                self,
                "Outlook 邮箱设置说明",
                "Outlook/Hotmail/Live 和 Microsoft 365 邮箱目前需要 OAuth2/XOAUTH2 认证。Invoice Hub v0.1.3 暂不支持 Outlook 邮箱扫描。后续版本可通过 Microsoft OAuth2/MSAL 支持。",
            )
            return
        QMessageBox.information(
            self,
            "如何获取邮箱授权码？",
            "<b>什么是授权码？</b><br>"
            "授权码（或应用专用密码）是专门用于第三方程序读取邮件的专属密码，<b>绝非您的邮箱登录密码</b>，可随时注销。<br><br>"
            "<b>获取步骤：</b><br>"
            "• <b>QQ邮箱：</b><br>"
            "  1. 登录网页版 QQ 邮箱。<br>"
            "  2. 进入「设置」 ➜ 「账号」。<br>"
            "  3. 滚动至「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」。<br>"
            "  4. 开启「POP3/IMAP服务」服务，验证后获取<b>16位独立授权码</b>。<br><br>"
            "• <b>163 / 126 网易邮箱：</b><br>"
            "  1. 登录网页版网易邮箱。<br>"
            "  2. 选择上方「设置」 ➜ 「POP3/SMTP/IMAP」。<br>"
            "  3. 开启「IMAP/SMTP服务」。<br>"
            "  4. 新增授权密码，按手机短信指引获取授权码。<br><br>"
            "• <b>Gmail 邮箱：</b><br>"
            "  1. 登录网页版 Google 账号中心（myaccount.google.com）。<br>"
            "  2. 进入「安全性」 ➜ 「双重验证」并开启。<br>"
            "  3. 搜索并进入「应用专用密码」创建专有密码，获取 <b>16 位专用密码</b>。<br>"
            "  4. 确保在网页版 Gmail 设置 ➜ 「转发和 POP/IMAP」中手动启用了 IMAP 收信。<br><br>"
            "<b>隐私安全说明：</b><br>"
            "您的授权码直接交由 Windows 系统级别的凭据管理器加密存储，不会以明文写入配置，更不会上传至任何第三方服务器。"
        )

    def _goto_next_step(self):
        if self.current_step == 1:
            email = self.txt_email.text().strip()
            if not email:
                QMessageBox.warning(self, "校验提示", "请先填写邮箱地址。")
                return
            provider = self._get_selected_provider()
            if provider == "outlook":
                QMessageBox.warning(
                    self,
                    "邮箱类型暂不支持",
                    "Outlook/Hotmail/Live 及 Microsoft 365 邮箱需要 OAuth2/XOAUTH2 登录。当前版本暂不支持 Outlook 邮箱扫描。"
                )
                return
            if provider == "custom":
                server = self.txt_imap_server.text().strip()
                port = self.txt_imap_port.text().strip()
                if not server or not port:
                    QMessageBox.warning(self, "校验提示", "自定义 IMAP 必须填写服务器和端口。")
                    return
            self.current_step = 2
        elif self.current_step == 2:
            self.current_step = 3

        self._update_wizard_ui()

    def _goto_prev_step(self):
        if self.current_step > 1:
            self.current_step -= 1
            self._update_wizard_ui()

    def _update_wizard_ui(self):
        # Update stack index
        self.step_stack.setCurrentIndex(self.current_step - 1)

        # Update step highlights
        if self.current_step == 1:
            self.lbl_step_indicator.setText('<font color="#2563EB"><b>① 选择邮箱</b></font>  ➜  ② 填写授权码  ➜  ③ 测试并保存')
            self.btn_prev.setEnabled(False)
            self.btn_next.setVisible(True)
            is_valid = self._is_valid_email(self.txt_email.text())
            provider = self._get_selected_provider()
            if provider == "custom":
                server = self.txt_imap_server.text().strip()
            else:
                from ..config import _EMAIL_PROVIDER_PRESETS
                preset = _EMAIL_PROVIDER_PRESETS.get(provider, {})
                server = preset.get("server", "")
            is_outlook_like = is_outlook_like_account(provider, self.txt_email.text().strip(), server)
            self.btn_next.setEnabled(provider != "outlook" and not is_outlook_like and is_valid)
            self.btn_save_wizard.setVisible(False)
        elif self.current_step == 2:
            self.lbl_step_indicator.setText('① 选择邮箱  ➜  <font color="#2563EB"><b>② 填写授权码</b></font>  ➜  ③ 测试并保存')
            self.btn_prev.setEnabled(True)
            self.btn_next.setVisible(True)
            self.btn_save_wizard.setVisible(False)
            self._update_cred_status_label()
        elif self.current_step == 3:
            self.lbl_step_indicator.setText('① 选择邮箱  ➜  ② 填写授权码  ➜  <font color="#2563EB"><b>③ 测试并保存</b></font>')
            self.btn_prev.setEnabled(True)
            self.btn_next.setVisible(False)
            self.btn_save_wizard.setVisible(True)
            self._update_summary_fields()

    def _update_summary_fields(self):
        provider = self._get_selected_provider()
        prov_map = {
            "qq": "QQ 邮箱",
            "netease_163": "163 网易邮箱",
            "netease_126": "126 网易邮箱",
            "gmail": "Gmail",
            "outlook": "Outlook",
            "custom": "自定义 IMAP"
        }
        self.lbl_sum_provider.setText(prov_map.get(provider, "QQ 邮箱"))
        self.lbl_sum_email.setText(self.txt_email.text().strip())
        self.lbl_sum_months.setText(f"最近 {self.txt_months.text().strip()} 个月")

        if provider == "custom":
            server = self.txt_imap_server.text().strip()
            port = self.txt_imap_port.text().strip()
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider, _EMAIL_PROVIDER_PRESETS["qq"])
            server = preset["server"]
            port = str(preset["port"])
        self.lbl_sum_protocol.setText(f"IMAP ({server}:{port})")

    def _test_connection_clicked(self):
        email = self.txt_email.text().strip()
        auth_code = self.txt_auth_code.text().strip()

        if not email:
            QMessageBox.warning(self, "校验提示", "请先填写邮箱地址。")
            return

        if not auth_code:
            from ..credentials import get_auth_code
            try:
                auth_code = get_auth_code(email) or ""
            except SystemExit:
                auth_code = ""
            if not auth_code:
                QMessageBox.warning(self, "校验提示", "请先输入邮箱授权码。")
                return

        provider = self._get_selected_provider()
        if provider == "custom":
            server = self.txt_imap_server.text().strip()
            port_str = self.txt_imap_port.text().strip()
            if not server or not port_str:
                QMessageBox.warning(self, "校验提示", "自定义 IMAP 必须填写服务器与端口。")
                return
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider)
            server = preset["server"]
            port_str = str(preset["port"])

        if is_outlook_like_account(provider, email, server):
            if provider == "outlook":
                QMessageBox.warning(
                    self,
                    "测试连接",
                    "Outlook 邮箱目前需要 OAuth2/XOAUTH2 认证。当前版本暂不支持 Outlook 邮箱测试/扫描。"
                )
            else:
                QMessageBox.warning(
                    self,
                    "测试连接",
                    "检测到 Outlook IMAP 服务器。Outlook 需要 OAuth2/XOAUTH2，当前版本授权码登录方式不支持。"
                )
            return


        try:
            port = int(port_str)
        except ValueError:
            QMessageBox.warning(self, "校验提示", "IMAP 端口必须是有效的整数。")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.btn_test.setEnabled(False)
        self.btn_test.setText("正在测试...")
        self.lbl_test_result.setStyleSheet("color: #4B5563; font-size: 11px;")
        self.lbl_test_result.setText("正在尝试连接 IMAP 服务器进行登录验证，请稍候...")
        QApplication.processEvents()

        try:
            from ..mail_fetcher import MailFetcher
            fetcher = MailFetcher(address=email, auth_code=auth_code, server=server, port=port)
            fetcher.connect()
            fetcher.disconnect()

            self.test_success = True
            prov_text = self.lbl_sum_provider.text()
            self.lbl_test_result.setStyleSheet("color: #10B981; font-weight: bold; font-size: 11px;")
            self.lbl_test_result.setText(f"✅ 已连接到 {prov_text}，可扫描最近 {self.txt_months.text().strip()} 个月发票邮件。")
        except Exception as e:
            self.test_success = False
            self.lbl_test_result.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 11px;")
            friendly = self._format_connection_failure(provider, server, port, e, auth_code)
            self.lbl_test_result.setText(friendly)
        finally:
            self.btn_test.setEnabled(True)
            self.btn_test.setText("测试连接")
            QApplication.restoreOverrideCursor()

    def _format_connection_failure(self, provider, server, port, error, auth_code=""):
        from ..log_privacy import sanitize_log_message

        raw_reason = str(error or "")
        if auth_code:
            raw_reason = raw_reason.replace(auth_code, "<redacted>")
        err_msg = raw_reason.lower()
        oauth_markers = (
            "oauth", "basic authentication disabled", "basic auth disabled",
            "login disabled", "modern authentication", "authenticate disabled",
        )
        network_markers = (
            "getaddrinfo", "timed out", "timeout", "connection timed out",
            "network is unreachable", "proxy", "firewall",
        )
        auth_markers = (
            "login failed", "authentication failed", "credential",
            "invalid credentials", "authori", "登录失败",
        )
        if provider == "outlook" and any(marker in err_msg for marker in oauth_markers):
            return "❌ 该 Outlook/Microsoft 365 账号可能不支持授权码 IMAP 登录，需要 OAuth2。当前版本暂不支持。"
        if any(marker in err_msg for marker in network_markers):
            if provider == "outlook":
                return f"❌ 无法连接 {server}:{port}，请检查网络、代理或防火墙。"
            return "❌ 测试连接失败：网络连接失败"
        if any(marker in err_msg for marker in auth_markers):
            if provider == "outlook":
                return "❌ 认证失败，请确认邮箱地址完整、授权码/应用密码正确。"
            return "❌ 测试连接失败：授权码错误或 IMAP 服务未开启"
        if any(marker in err_msg for marker in ("refused", "wrong port", "socket", "ssl")):
            return "❌ 测试连接失败：IMAP服务器/端口配置有误"
        if "未找到授权码" in err_msg:
            return "❌ 测试连接失败：未找到授权码"
        safe_reason = sanitize_log_message(raw_reason).strip()
        if provider == "outlook" and safe_reason:
            return f"❌ Outlook IMAP 连接失败：{safe_reason}"
        return "❌ 测试连接失败：授权码错误或 IMAP 未开启；或网络、服务器、端口配置有误。"

    def _save_mailbox_settings(self):
        email = self.txt_email.text().strip()
        provider = self._get_selected_provider()
        months_str = self.txt_months.text().strip()
        raw_accounts = self.cfg.get("email_accounts")
        email_accounts = [
            dict(existing)
            for existing in raw_accounts
            if isinstance(existing, dict)
        ] if isinstance(raw_accounts, list) else []
        if not isinstance(raw_accounts, list):
            legacy_email = self.cfg.get("email", {})
            legacy_address = str(legacy_email.get("address") or "").strip()
            if legacy_address:
                email_accounts.append({
                    "name": legacy_email.get("name", ""),
                    "enabled": True,
                    "provider": legacy_email.get("provider", "qq"),
                    "address": legacy_address,
                    "username": legacy_email.get("username") or legacy_address,
                    "imap": dict(self.cfg.get("imap", {})),
                    "search": dict(self.cfg.get("search", {})),
                    "mailbox_key": legacy_email.get("mailbox_key") or legacy_address.lower(),
                })

        if provider == "custom":
            imap_server = self.txt_imap_server.text().strip()
            imap_port_str = self.txt_imap_port.text().strip()
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider)
            imap_server = preset["server"]
            imap_port_str = str(preset["port"])

        is_outlook_like = is_outlook_like_account(provider, email, imap_server)
        if is_outlook_like:
            has_saved = False
            for acc in email_accounts:
                acc_addr = str(acc.get("address") or "").strip().lower()
                acc_key = str(acc.get("mailbox_key") or "").strip().lower()
                if acc_addr == email.lower() or acc_key == email.lower():
                    has_saved = True
                    break

            if not has_saved:
                QMessageBox.warning(
                    self,
                    "设置验证失败",
                    "检测到 Outlook/Microsoft IMAP 服务器。当前版本不支持授权码/应用密码方式连接 Outlook，需要 OAuth2/XOAUTH2，因此不能保存为可扫描账号。"
                )
                return

        proposed_cfg = {
            "email": {
                "provider": provider,
                "address": email
            },
            "imap": {
                "server": imap_server,
                "port": imap_port_str
            },
            "search": {
                "months_back": months_str
            },
            "ai": self.cfg.get("ai", {
                "provider": "none",
                "model": "",
                "enabled": False
            })
        }

        from ..config import save_config, validate_config_gui
        try:
            validate_config_gui(proposed_cfg)
        except ValueError as val_err:
            QMessageBox.warning(self, "设置验证失败", str(val_err))
            return

        if not self.test_success:
            reply = QMessageBox.question(
                self,
                "连接未验证",
                "邮箱连接尚未测试成功，是否仍保存？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        # Save credentials to system Keyring
        auth_code = self.txt_auth_code.text().strip()
        credential_available = False
        if auth_code:
            from ..credentials import set_auth_code
            try:
                set_auth_code(email, auth_code)
                credential_available = True
                self.parent.write_log(f"💾 [安全凭证] 邮箱 {email} 的授权码凭证已自动保存到 Windows 凭据管理器中。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存凭据失败: {e}")
                return
        else:
            from ..credentials import get_auth_code, has_auth_code
            if has_auth_code(email):
                try:
                    credential_available = bool(get_auth_code(email))
                except (Exception, SystemExit):
                    # Saving non-secret settings remains allowed if credential access fails.
                    pass

        # Update configuration
        self.cfg.setdefault("email", {})
        self.cfg.setdefault("imap", {})
        self.cfg.setdefault("search", {})
        self.cfg.setdefault("ai", {})
        self.cfg["email"]["provider"] = provider
        self.cfg["email"]["address"] = email
        self.cfg["email"]["username"] = email
        self.cfg["imap"]["server"] = imap_server
        self.cfg["imap"]["port"] = int(imap_port_str)
        self.cfg["imap"]["ssl"] = True
        self.cfg["search"]["folder"] = "INBOX"
        self.cfg["search"]["months_back"] = int(months_str)

        provider_names = {
            "qq": "QQ 邮箱",
            "netease_163": "163 网易邮箱",
            "netease_126": "126 网易邮箱",
            "gmail": "Gmail",
            "outlook": "Outlook",
            "custom": "自定义 IMAP",
        }
        account = {
            "name": provider_names.get(provider, provider),
            "enabled": not is_outlook_like,
            "provider": provider,
            "address": email,
            "username": email,
            "imap": {
                "server": imap_server,
                "port": int(imap_port_str),
                "ssl": True,
            },
            "search": {
                "folder": "INBOX",
                "months_back": int(months_str),
            },
        }
        match_index = next(
            (
                index
                for index, existing in enumerate(email_accounts)
                if str(existing.get("address") or "").strip().lower() == email.lower()
                or str(existing.get("mailbox_key") or "").strip().lower() == email.lower()
            ),
            None,
        )
        if match_index is None:
            account["mailbox_key"] = email.lower()
        else:
            account["mailbox_key"] = (
                str(email_accounts[match_index].get("mailbox_key") or "").strip()
                or email.lower()
            )
        if match_index is None:
            email_accounts.append(account)
        else:
            email_accounts[match_index] = account
        self.cfg["email_accounts"] = email_accounts


        try:
            save_config(self.cfg)
            self.parent.config = _load_config_safe_compat()
            self.parent.write_log(f"⚙️ [设置保存] 全局 config.json 邮箱服务配置已成功保存。")
            self.txt_auth_code.clear()
            if credential_available:
                self.txt_auth_code.setPlaceholderText(SAVED_SECRET_PLACEHOLDER)
                self.lbl_cred_status.setText("🔒 授权状态：<font color='#10B981'><b>已安全保存到系统凭据管理器</b></font>")
            else:
                self._update_cred_status_label()
            QMessageBox.information(self, "成功", "邮箱设置已成功保存！")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置文件失败: {e}")

    def _save_ai_settings(self):
        ai_provider = self.combo_ai_provider.currentText()
        ai_model = self.txt_ai_model.currentText().strip()
        ai_key = self.txt_ai_key.text().strip()

        proposed_cfg = {
            "email": self.cfg.get("email", {
                "provider": "qq",
                "address": ""
            }),
            "imap": self.cfg.get("imap", {
                "server": "imap.qq.com",
                "port": 993
            }),
            "search": self.cfg.get("search", {
                "months_back": 3
            }),
            "ai": {
                "provider": ai_provider,
                "model": ai_model
            }
        }

        from ..config import save_config, validate_config_gui
        try:
            validate_config_gui(proposed_cfg)
        except ValueError as val_err:
            QMessageBox.warning(self, "AI 设置验证失败", str(val_err))
            return

        # Save AI API Key to Keyring (only if provider is not "none" and key is provided)
        if ai_provider != "none" and ai_key:
            from ..credentials import set_ai_api_key
            try:
                set_ai_api_key(ai_provider, ai_key)
                self.parent.write_log(f"💾 [安全凭证] AI 提供商 {ai_provider} 的 API Key 已保存到 Windows 凭据管理器中。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存 AI 凭据失败: {e}")
                return

        # Update global config dict
        self.cfg.setdefault("ai", {})
        self.cfg["ai"]["provider"] = ai_provider
        self.cfg["ai"]["model"] = ai_model
        self.cfg["ai"]["enabled"] = (ai_provider != "none")

        try:
            save_config(self.cfg)
            from ..ai_classifier import clear_provider_session_paused
            clear_provider_session_paused(ai_provider)

            self.parent.config = _load_config_safe_compat()
            self.parent.write_log(f"⚙️ [设置保存] 全局 config.json AI 辅助分类配置已成功保存。")
            self.txt_ai_key.clear()
            QMessageBox.information(self, "成功", "AI 分类配置已成功保存！")
            self._on_ai_provider_changed()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存 AI 配置文件失败: {e}")

    def _delete_current_mailbox(self):
        email = self.txt_email.text().strip()
        if not email:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            "删除邮箱配置只会移除该邮箱的登录设置、授权码和扫描同步状态，不会删除已导入的发票、本地附件或报销组。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        normalized_email = self._normalize_address(email)

        # 1. Remove the matching account from cfg["email_accounts"] by address or mailbox_key
        raw_accounts = self.cfg.get("email_accounts")
        email_accounts = [
            dict(existing)
            for existing in raw_accounts
            if isinstance(existing, dict)
        ] if isinstance(raw_accounts, list) else []

        updated_accounts = []
        target_account = None
        for acc in email_accounts:
            acc_addr = self._normalize_address(acc.get("address"))
            acc_key = self._normalize_address(acc.get("mailbox_key"))
            if acc_addr == normalized_email or acc_key == normalized_email:
                target_account = acc
            else:
                updated_accounts.append(acc)

        self.cfg["email_accounts"] = updated_accounts

        # 2. Remove the corresponding keyring credential if possible
        from ..credentials import delete_auth_code
        try:
            delete_auth_code(email)
            if hasattr(self.parent, "write_log"):
                self.parent.write_log(f"🗑️ [安全凭证] 邮箱 {email} 的授权码凭证已从凭据管理器中移除。")
        except Exception as e:
            if hasattr(self.parent, "write_log"):
                self.parent.write_log(f"⚠️ [安全凭证] 从凭据管理器移除邮箱 {email} 凭证失败: {e}")

        # 3. Remove related scan cursor/sync state for that mailbox_key if such state exists
        mailbox_key = ""
        if target_account:
            mailbox_key = target_account.get("mailbox_key") or ""
        if not mailbox_key:
            mailbox_key = normalized_email

        if hasattr(self.parent, "db") and self.parent.db:
            try:
                self.parent.db.remove_mailbox_scan_state(mailbox_key)
            except Exception as e:
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"⚠️ [数据库] 清除邮箱同步状态失败: {e}")

        # 4. If legacy cfg["email"] points to the deleted account, set it to the next enabled supported account, or clear it if none exists
        legacy_email = self.cfg.get("email", {})
        legacy_addr = self._normalize_address(legacy_email.get("address"))
        if legacy_addr == normalized_email or not updated_accounts:
            # Find the next enabled supported account
            next_acc = None
            for acc in updated_accounts:
                p = acc.get("provider", "")
                addr = acc.get("address", "")
                srv = acc.get("imap", {}).get("server", "")
                if acc.get("enabled", True) and not is_outlook_like_account(p, addr, srv):
                    next_acc = acc
                    break

            if next_acc:
                self.cfg["email"] = {
                    "provider": next_acc.get("provider", "qq"),
                    "address": next_acc.get("address", ""),
                    "username": next_acc.get("username", next_acc.get("address", "")),
                }
                self.cfg["imap"] = dict(next_acc.get("imap", {}))
                self.cfg["search"] = dict(next_acc.get("search", {}))
            else:
                # clear it if none exists
                self.cfg["email"] = {"provider": "qq", "address": "", "username": ""}
                self.cfg["imap"] = {"server": "", "port": 993, "ssl": True}
                self.cfg["search"] = {"folder": "INBOX", "months_back": 3}

        # 5. Save the configuration
        from ..config import save_config
        try:
            save_config(self.cfg)
            if hasattr(self.parent, "config"):
                self.parent.config = _load_config_safe_compat()
            if hasattr(self.parent, "write_log"):
                self.parent.write_log(f"⚙️ [设置保存] 邮箱配置已删除。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置文件失败: {e}")
            return

        # 6. Rebuild saved account maps
        self._build_saved_account_maps()

        # 7. Clear stale loaded account state before deciding what to load
        self._loaded_account_address = ""
        self._loaded_account_mailbox_key = ""
        self._loaded_account_provider = ""

        # Find enabled and supported accounts
        enabled_supported_accounts = []
        for acc in self._saved_accounts:
            p = acc.get("provider", "")
            addr = acc.get("address", "")
            srv = acc.get("imap", {}).get("server", "")
            if acc.get("enabled", True) and not is_outlook_like_account(p, addr, srv):
                enabled_supported_accounts.append(acc)

        next_to_load = None
        if enabled_supported_accounts:
            # Prefer the primary account if it still exists in the enabled & supported list
            primary_email = self._normalize_address(self.cfg.get("email", {}).get("address", ""))
            for acc in enabled_supported_accounts:
                if self._normalize_address(acc.get("address")) == primary_email:
                    next_to_load = acc
                    break
            # Otherwise choose the first enabled non-Outlook-like account
            if not next_to_load:
                next_to_load = enabled_supported_accounts[0]

        if next_to_load:
            self._load_saved_account(next_to_load)
        else:
            self._loading_account_values = True
            try:
                self.txt_email.clear()
                self.txt_months.setText("3")
                self.txt_auth_code.clear()
                self._select_provider_card("qq")
                self._apply_provider_defaults("qq")
                self.advanced_group.setVisible(False)
                self.btn_toggle_advanced.setText("显示高级 IMAP 设置 ▼")
            finally:
                self._loading_account_values = False
            self._loaded_account_address = ""
            self._loaded_account_mailbox_key = ""
            self._loaded_account_provider = ""
            self._missing_saved_provider = ""
            self._update_delete_button_state()
            self._update_provider_hint()
            self._update_cred_status_label()
            self._update_wizard_ui()

        QMessageBox.information(self, "成功", "邮箱配置已删除，已导入发票不会被删除。")
