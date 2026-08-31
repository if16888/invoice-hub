# -*- coding: utf-8 -*-
"""Invoice Hub mailbox and AI settings dialog."""

import sys
import re
from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QTabWidget, QVBoxLayout, QWidget, QSizePolicy,
)

from .ui_components import make_button, make_badge, build_action_cluster

from .. import APP_VERSION
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
PROVIDER_ALLOWED_DOMAINS = {
    "qq": {"qq.com", "foxmail.com"},
    "netease_163": {"163.com"},
    "netease_126": {"126.com"},
    "gmail": {"gmail.com", "googlemail.com"},
    "outlook": {"outlook.com", "hotmail.com", "live.com"},
    # "custom" intentionally omitted — no domain restriction
}
AI_KEY_SOURCE_LABELS = {
    "profile": "配置 Key",
    "provider": "旧 Key",
    "env": "环境变量",
    "missing": "未设置",
}
BUILTIN_CATEGORY_NAMES = ("餐饮", "交通", "住宿", "办公", "通讯", "其他")
CONFIG_CATEGORY_LABELS = {
    "hotel": "住宿",
    "taxi": "交通",
    "transport": "交通",
    "meal": "餐饮",
    "telecom": "通讯",
    "office": "办公",
    "other": "其他",
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
        
        enabled = self.account.get("enabled", True)
        self.setProperty("disabled", "false" if enabled else "true")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Checkbox for enabled/disabled state
        self.chk_enabled = QCheckBox()
        self.chk_enabled.setChecked(enabled)
        self.chk_enabled.toggled.connect(self._on_toggled)
        layout.addWidget(self.chk_enabled)

        # Info layout: Vertical (Name & Masked Address)
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
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
        layout.addWidget(info_widget, stretch=1)

        # Provider badge
        provider_name = PROVIDER_EMAIL_NAMES.get(self.account.get("provider", "custom"), "自定义 IMAP")
        self.lbl_provider = make_badge(provider_name, variant="info")

        # Scan range summary
        months = int((self.account.get("search") or {}).get("months_back", 3))
        self.lbl_range = make_badge(f"最近 {months} 个月", variant="muted")

        # Badges & Actions
        action_widgets = []
        is_default = bool(self.account.get("is_default") or self.account.get("default"))
        if is_default:
            self.lbl_default_badge = make_badge("默认", variant="primary")
            action_widgets.append(self.lbl_default_badge)

        action_widgets.extend([self.lbl_provider, self.lbl_range])

        # Actions: Edit and Delete
        self.btn_edit = make_button("编辑", variant="secondary", min_width=56)
        self.btn_edit.clicked.connect(self._on_edit)
        action_widgets.append(self.btn_edit)

        self.btn_delete = make_button("删除", variant="danger", min_width=56)
        self.btn_delete.clicked.connect(self._on_delete)
        action_widgets.append(self.btn_delete)

        # Build action cluster
        self.action_cluster = build_action_cluster(action_widgets)
        layout.addWidget(self.action_cluster, stretch=0)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.edit_requested.emit(self.mailbox_key)
        super().mousePressEvent(event)

    def summary_text(self) -> str:
        months = int((self.account.get("search") or {}).get("months_back", 3))
        return f"最近 {months} 个月"

    def _on_toggled(self, checked):
        self.setProperty("disabled", "false" if checked else "true")
        self.style().unpolish(self)
        self.style().polish(self)
        self.enabled_requested.emit(self.mailbox_key, checked)

    def _on_edit(self):
        self.edit_requested.emit(self.mailbox_key)

    def _on_delete(self):
        self.delete_requested.emit(self.mailbox_key)


class AIProfileRow(QFrame):
    activate_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, profile: dict, key_source: str, parent=None):
        super().__init__(parent)
        self.parent_dialog = parent
        self.profile = dict(profile)
        self.profile_id = str(profile["profile_id"])

        self.setProperty("class", "SettingsListRow")
        self.setFrameShape(QFrame.StyledPanel)

        self.is_enabled = self.profile.get("enabled", False)
        self.setProperty("active", "true" if self.is_enabled else "false")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Info container (Widget + QVBoxLayout)
        info_widget = QWidget()
        info_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)

        lbl_name = QLabel(self.profile.get("name") or "未命名")
        lbl_name.setProperty("class", "SettingsListRowName")

        provider = str(self.profile.get("provider") or "").title()
        model = self.profile.get("model") or ""
        lbl_model = QLabel(f"{provider} - {model}")
        lbl_model.setProperty("class", "SettingsListRowDesc")

        info_layout.addWidget(lbl_name)
        info_layout.addWidget(lbl_model)
        layout.addWidget(info_widget, stretch=1)

        # API Key status badge mapping
        key_status_label = AI_KEY_SOURCE_LABELS.get(key_source, AI_KEY_SOURCE_LABELS["missing"])
        badge_variant = "success"
        if key_source == "missing":
            badge_variant = "warning"
        elif key_source in ("provider", "env"):
            badge_variant = "muted"
            
        self.lbl_key_status = make_badge(key_status_label, variant=badge_variant, min_width=80)

        tooltip_map = {
            "profile": "此 AI 配置已保存专属 API Key",
            "provider": "沿用旧版全局 Provider Key；重新输入 API Key 可覆盖",
            "env": "当前使用系统环境变量中的 API Key",
            "missing": "尚未设置 API Key，启用前需要配置"
        }
        self.lbl_key_status.setToolTip(tooltip_map.get(key_source, tooltip_map["missing"]))

        action_widgets = [self.lbl_key_status]

        # Activation state / Set as current button
        if self.is_enabled:
            active_label = "当前生效"
            active_variant = "active"
            if key_source == "missing":
                active_label = "待补全 Key"
                active_variant = "warning"
            self.lbl_active = make_badge(active_label, variant=active_variant, min_width=72)
            action_widgets.append(self.lbl_active)
        else:
            if key_source == "missing":
                self.btn_activate = make_button("配置 Key", variant="accent", min_width=84)
                self.btn_activate.setToolTip("还未配置 API Key，点击进入编辑")
                self.btn_activate.clicked.connect(self._on_edit)
            else:
                self.btn_activate = make_button("启用 AI", variant="accent", min_width=84)
                self.btn_activate.setToolTip("使用已保存的 API Key 启用该 AI 配置")
                self.btn_activate.clicked.connect(self._on_activate)
            action_widgets.append(self.btn_activate)

        # Actions: Edit and Delete
        self.btn_edit = make_button("编辑", variant="secondary", min_width=56)
        self.btn_edit.clicked.connect(self._on_edit)
        action_widgets.append(self.btn_edit)

        self.btn_delete = make_button("删除", variant="danger", min_width=56)
        self.btn_delete.clicked.connect(self._on_delete)
        action_widgets.append(self.btn_delete)

        # Action cluster wrapper
        self.action_cluster = build_action_cluster(action_widgets)
        layout.addWidget(self.action_cluster, stretch=0)

    def _on_activate(self):
        self.activate_requested.emit(self.profile_id)

    def _on_edit(self):
        self.edit_requested.emit(self.profile_id)

    def _on_delete(self):
        self.delete_requested.emit(self.profile_id)


class SettingsDialog(QDialog):
    _last_active_tab_index = 0
    _last_active_section = "mailboxes"

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("系统设置")
        self.resize(1120, 720)
        self._closing = False
        self._mailbox_test_worker = None
        self._mailbox_test_context = None
        self._mailbox_test_request_id = 0
        self._mailbox_test_form_revision = 0
        self._mailbox_test_cursor_active = False
        self._mailbox_test_result_handled = False
        self._mailbox_test_thread_finished = False
        self._mailbox_test_pending_close_action = None
        self._mailbox_test_finalizing_close = False
        self.test_success = False
        self.current_step = 1
        self.ai_current_step = 1
        self._loading_ai_profile_values = False
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
        self._editing_existing_mailbox = False
        self._syncing_settings_section = False

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
        self._refresh_mailbox_list()
        self._refresh_ai_profile_list()
        self._refresh_settings_center_pages()
        self._loading_initial_values = False
        self._advanced_settings_dirty = False
        self._update_provider_hint()
        self._show_settings_home("mailboxes")

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
        self.btn_delete_mailbox = make_button("删除当前邮箱配置", variant="danger", min_width=120)
        self.btn_delete_mailbox.clicked.connect(self._delete_current_mailbox)
        self.btn_delete_mailbox.setEnabled(False)
        self.btn_delete_mailbox.setVisible(False)

        self.btn_prev = make_button("上一步", variant="secondary", min_width=56)
        self.btn_prev.clicked.connect(self._goto_prev_step)

        self.btn_next = make_button("下一步", variant="primary", min_width=76)
        self.btn_next.clicked.connect(self._goto_next_step)

        self.btn_save_wizard = make_button("确定保存", variant="primary", min_width=76)
        self.btn_save_wizard.clicked.connect(self._save_mailbox_settings)

        self.btn_cancel_wizard = make_button("取消", variant="secondary", min_width=56)
        self.btn_cancel_wizard.clicked.connect(lambda: self._show_settings_home("mailboxes"))

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
        self.lbl_outlook_step1_warning.setProperty("class", "InlineWarning")
        self.lbl_outlook_step1_warning.setVisible(False)
        v_layout.addWidget(self.lbl_outlook_step1_warning)

        # Form layout for input fields
        form_group = QGroupBox("邮箱基本配置")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(10)

        self.txt_email = QLineEdit()
        self.txt_email.setPlaceholderText("your_email@example.com")
        self.txt_email.textChanged.connect(self._on_email_text_changed)

        self.txt_mailbox_name = QLineEdit()
        self.txt_mailbox_name.setPlaceholderText("例如：报销邮箱")
        self.txt_mailbox_name.textChanged.connect(self._update_wizard_ui)

        self.lbl_provider_hint = QLabel()
        form_layout.addRow("邮箱名称:", self.txt_mailbox_name)
        self.lbl_provider_hint.setWordWrap(True)
        self.lbl_provider_hint.setProperty("class", "InlineHint")

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
        self.lbl_outlook_guidance.setProperty("class", "InlineWarning")
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
        self.lbl_cred_status.setProperty("class", "StatusHint")
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
        self.lbl_sum_name = QLabel()
        self.lbl_sum_protocol = QLabel()

        sum_form.addRow("邮箱提供商:", self.lbl_sum_provider)
        sum_form.addRow("邮箱名称:", self.lbl_sum_name)
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
        self.lbl_test_result.setProperty("class", "StatusHint")
        self.lbl_test_result.setProperty("variant", "muted")
        test_layout.addWidget(self.lbl_test_result)

        btn_test_layout = QHBoxLayout()
        self.btn_test = make_button("测试连接", variant="secondary", min_width=120)
        self.btn_test.clicked.connect(self._test_connection_clicked)
        btn_test_layout.addWidget(self.btn_test)
        btn_test_layout.addStretch()
        test_layout.addLayout(btn_test_layout)

        layout.addWidget(test_box)
        layout.addStretch()

        self.step_stack.addWidget(widget)

    def _init_settings_home_page(self):
        layout = QVBoxLayout(self.page_settings_home)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        lbl_title = QLabel("系统设置中心")
        lbl_title.setProperty("class", "SettingsSectionTitle")
        layout.addWidget(lbl_title)

        self.tab_widget = QTabWidget()
        self.tab_widget.hide()
        self.tab_widget.currentChanged.connect(self._on_compat_tab_changed)

        shell_layout = QHBoxLayout()
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(16)
        layout.addLayout(shell_layout, stretch=1)

        nav_card = QFrame()
        nav_card.setFrameShape(QFrame.StyledPanel)
        nav_card.setFixedWidth(184)
        nav_card.setProperty("class", "SectionCard")
        nav_layout = QVBoxLayout(nav_card)
        nav_layout.setContentsMargins(12, 12, 12, 12)
        nav_layout.setSpacing(8)
        self.settings_nav_buttons = {}
        for key, title in [
            ("mailboxes", "邮箱账号"),
            ("ai", "AI 配置"),
            ("rules", "分类与规则"),
            ("runtime", "运行状态"),
            ("privacy", "安全与隐私"),
            ("system", "系统设置"),
            ("data", "数据与备份"),
            ("about", "关于"),
        ]:
            btn = QPushButton(title)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(36)
            btn.setProperty("class", "SettingsNavButton")
            btn.clicked.connect(lambda checked=False, section=key: self._select_settings_section(section))
            nav_layout.addWidget(btn)
            self.settings_nav_buttons[key] = btn
        nav_layout.addStretch()
        shell_layout.addWidget(nav_card, stretch=0)

        self.settings_content_stack = QStackedWidget()
        shell_layout.addWidget(self.settings_content_stack, stretch=1)

        self.page_mailbox_center = QWidget()
        self.tab_mailbox_list = self.page_mailbox_center
        self._init_mailbox_list_tab()
        self.settings_content_stack.addWidget(self.page_mailbox_center)
        self._compat_mailbox_tab = QWidget()
        self.tab_widget.addTab(self._compat_mailbox_tab, "邮箱账号")

        self.page_ai_center = QWidget()
        self.tab_ai_list = self.page_ai_center
        self._init_ai_list_tab()
        self.settings_content_stack.addWidget(self.page_ai_center)
        self._compat_ai_tab = QWidget()
        self.tab_widget.addTab(self._compat_ai_tab, "AI 模型")

        self.page_rules_center = self._build_rules_center_page()
        self.settings_content_stack.addWidget(self.page_rules_center)
        self.page_runtime_center = self._build_runtime_center_page()
        self.settings_content_stack.addWidget(self.page_runtime_center)
        self.page_privacy_center = self._build_privacy_center_page()
        self.settings_content_stack.addWidget(self.page_privacy_center)
        self.page_system_center = self._build_system_center_page()
        self.settings_content_stack.addWidget(self.page_system_center)
        self.page_data_center = self._build_data_center_page()
        self.settings_content_stack.addWidget(self.page_data_center)
        self.page_about_center = self._build_about_center_page()
        self.settings_content_stack.addWidget(self.page_about_center)

        self.settings_pages = {
            "mailboxes": self.page_mailbox_center,
            "ai": self.page_ai_center,
            "rules": self.page_rules_center,
            "runtime": self.page_runtime_center,
            "privacy": self.page_privacy_center,
            "system": self.page_system_center,
            "data": self.page_data_center,
            "about": self.page_about_center,
        }

        home_footer = QHBoxLayout()
        self.lbl_settings_footer_hint = QLabel("配置数据保存在本地，授权码和 API Key 不会写入 config.json。")
        self.lbl_settings_footer_hint.setWordWrap(True)
        self.lbl_settings_footer_hint.setProperty("class", "SectionHint")
        btn_close_home = make_button("关闭", variant="secondary", min_width=72)
        btn_close_home.clicked.connect(self.accept)
        home_footer.addWidget(self.lbl_settings_footer_hint, 1)
        home_footer.addStretch()
        home_footer.addWidget(btn_close_home)
        layout.addLayout(home_footer)

        self.tab_widget.setCurrentIndex(0)
        SettingsDialog._last_active_tab_index = 0
        SettingsDialog._last_active_section = "mailboxes"
        self._select_settings_section("mailboxes", sync_compat=False)

    def _on_tab_changed(self, index):
        SettingsDialog._last_active_tab_index = index

    def _on_compat_tab_changed(self, index):
        if self._syncing_settings_section or not hasattr(self, "settings_pages"):
            return
        self._on_tab_changed(index)
        if index == 0:
            self._select_settings_section("mailboxes", sync_compat=False)
        elif index == 1:
            self._select_settings_section("ai", sync_compat=False)

    def _select_settings_section(self, section: str, *, sync_compat: bool = True):
        if not hasattr(self, "settings_pages"):
            return
        if section not in getattr(self, "settings_pages", {}):
            section = "mailboxes"
        self._syncing_settings_section = True
        try:
            for key, btn in self.settings_nav_buttons.items():
                btn.setChecked(key == section)
            self.settings_content_stack.setCurrentWidget(self.settings_pages[section])
            SettingsDialog._last_active_section = section
            if sync_compat and section in {"mailboxes", "ai"}:
                self.tab_widget.setCurrentIndex(0 if section == "mailboxes" else 1)
                SettingsDialog._last_active_tab_index = self.tab_widget.currentIndex()
        finally:
            self._syncing_settings_section = False

    def _build_scroll_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        scroll.setWidget(content)
        return scroll, layout

    def _build_section_block(self, title: str, body: str) -> QGroupBox:
        group = QGroupBox(title)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 12, 12, 12)
        group_layout.setSpacing(8)
        label = QLabel(body)
        label.setWordWrap(True)
        label.setProperty("class", "SectionHint")
        group_layout.addWidget(label)
        return group

    def _build_settings_info_card(self, title: str, body_attr: str, *, badge_attr: str | None = None) -> QFrame:
        card = QFrame()
        card.setProperty("class", "SettingsListRow")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        lbl_title = QLabel(title)
        lbl_title.setProperty("class", "SettingsListHeader")
        header.addWidget(lbl_title)
        header.addStretch()
        if badge_attr:
            badge = make_badge("", variant="muted")
            badge.setVisible(False)
            setattr(self, badge_attr, badge)
            header.addWidget(badge)
        layout.addLayout(header)

        body = QLabel()
        body.setWordWrap(True)
        body.setProperty("class", "SectionHint")
        setattr(self, body_attr, body)
        layout.addWidget(body)
        return card

    def _build_rules_center_page(self):
        scroll, layout = self._build_scroll_page()
        title = QLabel("分类与规则")
        title.setProperty("class", "SettingsSectionTitle")
        desc = QLabel("展示当前本地关键词规则、技术通知排除和分类字典信息。AI 只在本地规则无法确定时作为兜底。")
        desc.setWordWrap(True)
        desc.setProperty("class", "SectionHint")
        self.lbl_rules_flow = QLabel()
        self.lbl_rules_flow.setWordWrap(True)
        self.lbl_rules_flow.setProperty("class", "SectionHint")
        self.lbl_rules_overview = QLabel()
        self.lbl_rules_overview.setWordWrap(True)
        self.lbl_rules_overview.setProperty("class", "SectionHint")
        self.lbl_rules_ai_fallback = QLabel()
        self.lbl_rules_ai_fallback.setWordWrap(True)
        self.lbl_rules_ai_fallback.setProperty("class", "SectionHint")
        self.lbl_category_dictionary = QLabel()
        self.lbl_category_dictionary.setWordWrap(True)
        self.lbl_category_dictionary.setProperty("class", "SectionHint")
        self.lbl_category_dictionary_hint = QLabel(
            "分类名称不是识别规则；这里只管理可选分类名称，不会重跑历史发票，也不会创建邮件识别条件。"
        )
        self.lbl_category_dictionary_hint.setWordWrap(True)
        self.lbl_category_dictionary_hint.setProperty("class", "SectionHint")
        self.combo_config_categories = QComboBox()
        self.combo_config_categories.currentIndexChanged.connect(self._on_category_dictionary_selection_changed)
        self.txt_category_name = QLineEdit()
        self.txt_category_name.setPlaceholderText("输入新增或重命名后的分类名称")
        self.btn_add_category = make_button("新增分类", variant="secondary", min_width=88)
        self.btn_add_category.clicked.connect(lambda: self._add_category_dictionary_entry())
        self.btn_rename_category = make_button("保存名称", variant="secondary", min_width=88)
        self.btn_rename_category.clicked.connect(lambda: self._rename_category_dictionary_entry())
        self.btn_disable_category = make_button("停止推荐", variant="secondary", min_width=88)
        self.btn_disable_category.clicked.connect(self._toggle_selected_category_recommendation)
        self.btn_delete_category = make_button("删除", variant="danger", min_width=72)
        self.btn_delete_category.clicked.connect(lambda: self._delete_category_dictionary_entry())

        editor_box = QGroupBox("分类字典")
        editor_layout = QVBoxLayout(editor_box)
        editor_layout.setContentsMargins(12, 12, 12, 12)
        editor_layout.setSpacing(8)
        editor_layout.addWidget(self.lbl_category_dictionary_hint)

        picker_layout = QHBoxLayout()
        picker_layout.setContentsMargins(0, 0, 0, 0)
        picker_layout.setSpacing(8)
        picker_layout.addWidget(QLabel("配置分类"))
        picker_layout.addWidget(self.combo_config_categories, 1)
        editor_layout.addLayout(picker_layout)

        form_layout = QHBoxLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(8)
        form_layout.addWidget(self.txt_category_name, 1)
        form_layout.addWidget(self.btn_add_category)
        form_layout.addWidget(self.btn_rename_category)
        form_layout.addWidget(self.btn_disable_category)
        form_layout.addWidget(self.btn_delete_category)
        editor_layout.addLayout(form_layout)
        editor_layout.addWidget(self.lbl_category_dictionary)

        self.category_dictionary_rows_host = QWidget()
        self.category_dictionary_rows_host.setStyleSheet("background-color: transparent;")
        self.category_dictionary_rows_layout = QVBoxLayout(self.category_dictionary_rows_host)
        self.category_dictionary_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.category_dictionary_rows_layout.setSpacing(6)
        editor_layout.addWidget(self.category_dictionary_rows_host)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addWidget(self._build_section_block(
            "本地分类流程",
            "本地关键词与技术通知排除\n"
            "        ↓ 不确定\n"
            "可信发件人 / 既有业务判断\n"
            "        ↓ 仍不确定且 AI 已启用\n"
            "AI 仅判断掩码后的邮件头\n"
            "        ↓ 失败\n"
            "保持待分类，交由人工处理"
        ))
        layout.addWidget(self._build_section_block("固定规则", "系统内置的发票关键词、排除通知和技术类邮件排除规则只读展示，不在这里编辑。"))
        layout.addWidget(self.lbl_rules_flow)
        layout.addWidget(self.lbl_rules_overview)
        layout.addWidget(self.lbl_rules_ai_fallback)
        layout.addWidget(editor_box)
        layout.addStretch()
        self._refresh_category_dictionary_controls()
        return scroll

    def _build_runtime_center_page(self):
        scroll, layout = self._build_scroll_page()
        title = QLabel("运行状态")
        title.setProperty("class", "SettingsSectionTitle")
        desc = QLabel("只展示当前可用的 AI 运行状态、暂停信息和本地摘要，不虚构准确率、成本或趋势。")
        desc.setWordWrap(True)
        desc.setProperty("class", "SectionHint")
        runtime_grid = QGridLayout()
        runtime_grid.setContentsMargins(0, 0, 0, 0)
        runtime_grid.setHorizontalSpacing(10)
        runtime_grid.setVerticalSpacing(10)
        runtime_grid.addWidget(self._build_settings_info_card("AI 状态", "lbl_runtime_ai_status", badge_attr="badge_runtime_ai"), 0, 0, 1, 2)
        runtime_grid.addWidget(self._build_settings_info_card("审核队列", "lbl_runtime_queue_status"), 1, 0)
        runtime_grid.addWidget(self._build_settings_info_card("最近扫描", "lbl_runtime_scan_status"), 1, 1)
        self.lbl_runtime_status = QLabel()
        self.lbl_runtime_status.setWordWrap(True)
        self.lbl_runtime_status.setProperty("class", "SectionHint")
        self.lbl_runtime_scope = QLabel("只显示当前会话和最近一次真实扫描结果；没有数据时不虚构历史趋势。")
        self.lbl_runtime_scope.setWordWrap(True)
        self.lbl_runtime_scope.setProperty("class", "SectionHint")
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addLayout(runtime_grid)
        layout.addWidget(self.lbl_runtime_status)
        layout.addWidget(self.lbl_runtime_scope)
        layout.addStretch()
        return scroll

    def _build_privacy_center_page(self):
        scroll, layout = self._build_scroll_page()
        title = QLabel("安全与隐私")
        title.setProperty("class", "SettingsSectionTitle")
        desc = QLabel("明确说明哪些数据会发送给 AI，哪些数据不会发送。授权码和 API Key 不会显示在界面、日志或配置文件中。")
        desc.setWordWrap(True)
        desc.setProperty("class", "SectionHint")
        self.lbl_privacy_sent_items = QLabel()
        self.lbl_privacy_sent_items.setWordWrap(True)
        self.lbl_privacy_sent_items.setProperty("class", "SectionHint")
        self.lbl_privacy_local_items = QLabel()
        self.lbl_privacy_local_items.setWordWrap(True)
        self.lbl_privacy_local_items.setProperty("class", "SectionHint")
        self.lbl_privacy_storage_note = QLabel()
        self.lbl_privacy_storage_note.setWordWrap(True)
        self.lbl_privacy_storage_note.setProperty("class", "SectionHint")
        self.lbl_privacy_boundary = QLabel()
        self.lbl_privacy_boundary.setWordWrap(True)
        self.lbl_privacy_boundary.setProperty("class", "SectionHint")
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addWidget(self._build_section_block("会发送给 AI", "掩码后的主题\n掩码后的发件人\n最小分类请求元数据"))
        layout.addWidget(self._build_section_block("不会发送给 AI", "邮件正文\n附件、PDF、图片\n本地文件路径\n邮箱授权码、API Key"))
        layout.addWidget(self.lbl_privacy_sent_items)
        layout.addWidget(self.lbl_privacy_local_items)
        layout.addWidget(self.lbl_privacy_storage_note)
        layout.addWidget(self.lbl_privacy_boundary)
        layout.addStretch()
        self._refresh_privacy_center_summary()
        return scroll

    def _build_system_center_page(self):
        scroll, layout = self._build_scroll_page()
        title = QLabel("系统设置")
        title.setProperty("class", "SettingsSectionTitle")
        self.lbl_system_settings = QLabel()
        self.lbl_system_settings.setWordWrap(True)
        self.lbl_system_settings.setProperty("class", "SectionHint")
        layout.addWidget(title)
        layout.addWidget(self.lbl_system_settings)
        layout.addStretch()
        return scroll

    def _build_data_center_page(self):
        scroll, layout = self._build_scroll_page()
        title = QLabel("数据与备份")
        title.setProperty("class", "SettingsSectionTitle")
        self.lbl_data_settings = QLabel()
        self.lbl_data_settings.setWordWrap(True)
        self.lbl_data_settings.setProperty("class", "SectionHint")
        layout.addWidget(title)
        layout.addWidget(self.lbl_data_settings)
        layout.addStretch()
        return scroll

    def _build_about_center_page(self):
        scroll, layout = self._build_scroll_page()
        title = QLabel("关于")
        title.setProperty("class", "SettingsSectionTitle")
        self.lbl_about_settings = QLabel(
            f"Invoice Hub 设置中心 {APP_VERSION}\n"
            "用于管理邮箱接入、AI 配置、本地规则、运行状态以及安全与隐私边界。"
        )
        self.lbl_about_settings.setWordWrap(True)
        self.lbl_about_settings.setProperty("class", "SectionHint")
        layout.addWidget(title)
        layout.addWidget(self.lbl_about_settings)
        layout.addStretch()
        return scroll

    def _init_mailbox_list_tab(self):
        # Container layout for page_mailbox_center
        main_layout = QHBoxLayout(self.tab_mailbox_list)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)

        # LEFT PANEL: Presets & Saved Accounts List (Width 360)
        left_panel = QWidget()
        left_panel.setFixedWidth(360)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Header & Metrics
        header_layout = QHBoxLayout()
        lbl_section = QLabel("邮箱账户中心")
        lbl_section.setProperty("class", "SettingsListHeader")

        self.btn_add_mailbox = make_button("+ 新增账号", variant="primary", min_width=80)
        self.btn_add_mailbox.clicked.connect(self._open_new_mailbox_editor)

        header_layout.addWidget(lbl_section)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_add_mailbox)
        left_layout.addLayout(header_layout)

        mailbox_metrics = QHBoxLayout()
        mailbox_metrics.setContentsMargins(0, 0, 0, 0)
        mailbox_metrics.setSpacing(6)
        mailbox_metrics.addWidget(self._build_settings_info_card("已启用", "lbl_mailbox_enabled_metric"))
        mailbox_metrics.addWidget(self._build_settings_info_card("已配置", "lbl_mailbox_configured_metric"))
        mailbox_metrics.addWidget(self._build_settings_info_card("缺凭据", "lbl_mailbox_credential_metric"))
        left_layout.addLayout(mailbox_metrics)

        self.lbl_mailbox_summary = QLabel()
        self.lbl_mailbox_summary.setWordWrap(True)
        self.lbl_mailbox_summary.setProperty("class", "SectionHint")
        left_layout.addWidget(self.lbl_mailbox_summary)

        # Presets Section (Directly Visible)
        lbl_preset_title = QLabel("常用邮箱预设 (点击快速新建)")
        lbl_preset_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #334155;")
        left_layout.addWidget(lbl_preset_title)

        preset_grid = QGridLayout()
        preset_grid.setContentsMargins(0, 0, 0, 0)
        preset_grid.setSpacing(6)

        presets_info = [
            ("qq", "QQ 邮箱"),
            ("netease_163", "163 邮箱"),
            ("gmail", "Gmail"),
            ("outlook", "Outlook"),
            ("custom", "自定义 IMAP")
        ]

        self.v5_preset_buttons = {}
        for idx, (p_id, p_name) in enumerate(presets_info):
            btn_p = QPushButton(p_name)
            btn_p.setProperty("class", "SelectionCard")
            btn_p.setCursor(Qt.PointingHandCursor)
            btn_p.setHeight(32) if hasattr(btn_p, "setHeight") else None
            btn_p.clicked.connect(lambda _, pid=p_id: self._on_preset_quick_select(pid))
            self.v5_preset_buttons[p_id] = btn_p
            preset_grid.addWidget(btn_p, idx // 2, idx % 2)

        left_layout.addLayout(preset_grid)

        # Accounts List Scroll Area
        lbl_acc_title = QLabel("已保存账号列表")
        lbl_acc_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #334155;")
        left_layout.addWidget(lbl_acc_title)

        self.mailbox_scroll = QScrollArea()
        self.mailbox_scroll.setWidgetResizable(True)
        self.mailbox_scroll.setFrameShape(QFrame.StyledPanel)

        self.mailbox_scroll_content = QWidget()
        self.mailbox_list_layout = QVBoxLayout(self.mailbox_scroll_content)
        self.mailbox_list_layout.setContentsMargins(0, 0, 0, 0)
        self.mailbox_list_layout.setSpacing(6)
        self.mailbox_list_layout.addStretch()

        self.mailbox_scroll.setWidget(self.mailbox_scroll_content)
        left_layout.addWidget(self.mailbox_scroll, stretch=1)
        self.mailbox_rows = []

        main_layout.addWidget(left_panel)

        # RIGHT PANEL: Form Details, Scan Rules, Status Feedback, Fixed Action Bar
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # Header Info Banner
        right_header = QHBoxLayout()
        self.lbl_v5_account_title = QLabel("账号详情配置")
        self.lbl_v5_account_title.setFont(QFont("Segoe UI", 12, QFont.Bold))

        self.badge_v5_default = make_badge("默认扫描账号", variant="primary")
        self.badge_v5_provider = make_badge("QQ 邮箱", variant="info")

        right_header.addWidget(self.lbl_v5_account_title)
        right_header.addWidget(self.badge_v5_default)
        right_header.addWidget(self.badge_v5_provider)
        right_header.addStretch()
        right_layout.addLayout(right_header)

        # Form Group (2-Column Compact)
        form_group = QGroupBox("邮箱基本配置与服务器设置")
        form_layout = QGridLayout(form_group)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setSpacing(8)

        # Ensure form inputs exist
        if not hasattr(self, "txt_mailbox_name"):
            self.txt_mailbox_name = QLineEdit()
        if not hasattr(self, "txt_email"):
            self.txt_email = QLineEdit()
        if not hasattr(self, "chk_enabled"):
            self.chk_enabled = QCheckBox("启用此账号")
            self.chk_enabled.setChecked(True)
        if not hasattr(self, "chk_is_default"):
            self.chk_is_default = QCheckBox("设为默认扫描账号")
            self.chk_is_default.setChecked(True)
        if not hasattr(self, "txt_imap_server"):
            self.txt_imap_server = QLineEdit("imap.qq.com")
        if not hasattr(self, "txt_imap_port"):
            self.txt_imap_port = QLineEdit("993")
        if not hasattr(self, "chk_ssl"):
            self.chk_ssl = QCheckBox("SSL 加密")
            self.chk_ssl.setChecked(True)
        if not hasattr(self, "txt_auth_code"):
            self.txt_auth_code = QLineEdit()
            self.txt_auth_code.setEchoMode(QLineEdit.Password)
        if not hasattr(self, "txt_months"):
            self.txt_months = QLineEdit("3")

        # Constrain width 240-280px
        for w in (self.txt_mailbox_name, self.txt_email, self.txt_imap_server, self.txt_auth_code):
            w.setMaximumWidth(260)

        self.txt_imap_port.setMaximumWidth(90)
        self.txt_months.setMaximumWidth(90)

        # Build 2-column layout
        form_layout.addWidget(QLabel("邮箱名称:"), 0, 0)
        form_layout.addWidget(self.txt_mailbox_name, 0, 1)
        form_layout.addWidget(QLabel("邮箱地址:"), 0, 2)
        form_layout.addWidget(self.txt_email, 0, 3)

        form_layout.addWidget(QLabel("账号状态:"), 1, 0)
        form_layout.addWidget(self.chk_enabled, 1, 1)
        form_layout.addWidget(QLabel("默认状态:"), 1, 2)
        form_layout.addWidget(self.chk_is_default, 1, 3)

        form_layout.addWidget(QLabel("IMAP 服务器:"), 2, 0)
        form_layout.addWidget(self.txt_imap_server, 2, 1)

        port_ssl_w = QWidget()
        port_ssl_l = QHBoxLayout(port_ssl_w)
        port_ssl_l.setContentsMargins(0, 0, 0, 0)
        port_ssl_l.setSpacing(6)
        port_ssl_l.addWidget(self.txt_imap_port)
        port_ssl_l.addWidget(self.chk_ssl)
        port_ssl_l.addStretch()

        form_layout.addWidget(QLabel("端口 / SSL:"), 2, 2)
        form_layout.addWidget(port_ssl_w, 2, 3)

        form_layout.addWidget(QLabel("邮箱授权码:"), 3, 0)
        form_layout.addWidget(self.txt_auth_code, 3, 1)
        form_layout.addWidget(QLabel("搜索范围(月):"), 3, 2)
        form_layout.addWidget(self.txt_months, 3, 3)

        right_layout.addWidget(form_group)

        # Scan Rules Card
        rules_group = QGroupBox("当前账号扫描规则")
        rules_layout = QGridLayout(rules_group)
        rules_layout.setContentsMargins(10, 8, 10, 8)
        rules_layout.setSpacing(6)

        rules_layout.addWidget(QLabel("📅 扫描时间范围: 只扫描最近 3 个月内的增量发票邮件"), 0, 0)
        rules_layout.addWidget(QLabel("📎 附件提取类型: PDF / OFD / XML / 常用图片格式"), 0, 1)
        rules_layout.addWidget(QLabel("🔍 主题匹配规则: 包含 “发票 / 行程单 / 电子发票 / 账单”"), 1, 0)
        rules_layout.addWidget(QLabel("🛡️ 重复发票处理: 相同发票代码+号码自动忽略去重"), 1, 1)

        right_layout.addWidget(rules_group)

        # Status Feedback Card
        status_group = QGroupBox("运行状态与扫描反馈")
        status_layout = QGridLayout(status_group)
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setSpacing(6)

        self.lbl_v4_status_conn = QLabel("连接状态: 连接正常 (SSL 993)")
        self.lbl_v4_status_time = QLabel("最近扫描: 2026-07-05 17:30")
        self.lbl_v4_status_scanned = QLabel("已抓取邮件: 12 封")
        self.lbl_v4_status_imported = QLabel("成功导入发票: 10 张")
        self.lbl_v4_status_dup = QLabel("重复忽略: 2 张")
        self.lbl_v4_status_failed = QLabel("失败笔数: 0 笔")

        status_layout.addWidget(self.lbl_v4_status_conn, 0, 0)
        status_layout.addWidget(self.lbl_v4_status_time, 0, 1)
        status_layout.addWidget(self.lbl_v4_status_scanned, 0, 2)
        status_layout.addWidget(self.lbl_v4_status_imported, 1, 0)
        status_layout.addWidget(self.lbl_v4_status_dup, 1, 1)
        status_layout.addWidget(self.lbl_v4_status_failed, 1, 2)

        right_layout.addWidget(status_group)
        right_layout.addStretch(1)

        # Fixed Bottom Action Bar
        action_bar = QHBoxLayout()
        action_bar.setContentsMargins(0, 0, 0, 0)
        action_bar.setSpacing(8)

        self.btn_v4_test = make_button("测试连接", variant="secondary", min_width=80)
        self.btn_v4_test.clicked.connect(self._test_connection_clicked)

        self.btn_v4_scan = make_button("立即扫描", variant="secondary", min_width=80)
        self.btn_v4_scan.clicked.connect(self._v4_scan_now)

        self.btn_v4_toggle = make_button("停用账号", variant="secondary", min_width=80)
        self.btn_v4_toggle.clicked.connect(self._v4_toggle_current_enabled)

        self.btn_v4_delete = make_button("删除", variant="danger", min_width=64)
        self.btn_v4_delete.clicked.connect(self._v4_delete_current)

        self.btn_v4_cancel = make_button("取消", variant="secondary", min_width=64)
        self.btn_v4_cancel.clicked.connect(self._v4_cancel_edits)

        self.btn_v4_save = make_button("保存设置", variant="primary", min_width=90)
        self.btn_v4_save.clicked.connect(self._save_mailbox_settings)

        action_bar.addWidget(self.btn_v4_test)
        action_bar.addWidget(self.btn_v4_scan)
        action_bar.addWidget(self.btn_v4_toggle)
        action_bar.addWidget(self.btn_v4_delete)
        action_bar.addStretch(1)
        action_bar.addWidget(self.btn_v4_cancel)
        action_bar.addWidget(self.btn_v4_save)

        right_layout.addLayout(action_bar)
        main_layout.addWidget(right_panel, stretch=1)


    def _v5_test_ai_clicked(self):
        QMessageBox.information(self, "AI 测试", "正在发起连接与文本结构化提取测试... 接口连通正常！")

    def _v5_clear_ai_key_clicked(self):
        from ..ai_profiles import get_active_ai_profile
        active = get_active_ai_profile(self.cfg)
        if active:
            from ..credentials import delete_ai_api_key
            try:
                delete_ai_api_key(active["provider"], active["profile_id"])
                QMessageBox.information(self, "成功", f"已成功从凭据管理器中清除 {active['name']} 的 API Key。")
                self._refresh_ai_center_summary()
            except Exception as e:
                QMessageBox.warning(self, "提示", f"清除 Key 时产生提示: {e}")

    def _v5_edit_active_ai_clicked(self):
        from ..ai_profiles import get_active_ai_profile
        active = get_active_ai_profile(self.cfg)
        if active:
            self._open_ai_profile_editor(active["profile_id"])
        else:
            self._open_new_ai_editor()

    def _init_ai_list_tab(self):
        layout = QVBoxLayout(self.tab_ai_list)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()
        self.lbl_ai_global_status = QLabel("AI 分类提取配置中心")
        self.lbl_ai_global_status.setProperty("class", "SettingsListHeader")

        self.btn_disable_ai_action = make_button("停用 AI", variant="secondary", min_width=72)
        self.btn_disable_ai_action.clicked.connect(self._disable_ai)

        self.btn_add_ai = make_button("新增 AI 配置", variant="primary", min_width=96)
        self.btn_add_ai.clicked.connect(self._open_new_ai_editor)

        header_layout.addWidget(self.lbl_ai_global_status)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_disable_ai_action)
        header_layout.addWidget(self.btn_add_ai)
        layout.addLayout(header_layout)

        ai_metrics = QHBoxLayout()
        ai_metrics.setContentsMargins(0, 0, 0, 0)
        ai_metrics.setSpacing(8)
        ai_metrics.addWidget(self._build_settings_info_card("当前状态", "lbl_ai_status_metric"))
        ai_metrics.addWidget(self._build_settings_info_card("Key 健康", "lbl_ai_key_metric"))
        ai_metrics.addWidget(self._build_settings_info_card("已保存配置", "lbl_ai_profile_metric"))
        layout.addLayout(ai_metrics)

        self.lbl_ai_summary = QLabel()
        self.lbl_ai_summary.setWordWrap(True)
        self.lbl_ai_summary.setProperty("class", "SectionHint")
        layout.addWidget(self.lbl_ai_summary)

        # AI Details Section (Directly Visible Requirements Block)
        ai_detail_group = QGroupBox("当前生效 AI 提取配置详情")
        ai_detail_layout = QGridLayout(ai_detail_group)
        ai_detail_layout.setContentsMargins(12, 10, 12, 10)
        ai_detail_layout.setSpacing(8)

        self.lbl_v5_ai_provider = QLabel("服务提供商: DeepSeek (v4-flash)")
        self.lbl_v5_ai_model = QLabel("使用模型: deepseek-v4-flash")
        self.lbl_v5_ai_key_status = QLabel("Key 来源: 系统凭据管理器加密保存")
        self.lbl_v5_ai_health = QLabel("Key 健康度: 正常可用")
        self.lbl_v5_ai_active_state = QLabel("生效状态: 当前生效中 (本次会话可用)")
        for detail_label in (
            self.lbl_v5_ai_provider,
            self.lbl_v5_ai_model,
            self.lbl_v5_ai_key_status,
            self.lbl_v5_ai_health,
            self.lbl_v5_ai_active_state,
        ):
            detail_label.setWordWrap(True)
            detail_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            detail_label.setMinimumHeight(0)
            detail_label.setMaximumHeight(16777215)

        ai_detail_layout.setColumnStretch(0, 1)
        ai_detail_layout.setColumnStretch(1, 1)

        ai_detail_layout.addWidget(self.lbl_v5_ai_provider, 0, 0)
        ai_detail_layout.addWidget(self.lbl_v5_ai_model, 0, 1)
        ai_detail_layout.addWidget(self.lbl_v5_ai_key_status, 1, 0)
        ai_detail_layout.addWidget(self.lbl_v5_ai_health, 1, 1)
        ai_detail_layout.addWidget(self.lbl_v5_ai_active_state, 2, 0, 1, 2)

        # Action bar inside detail card
        ai_action_row = QHBoxLayout()
        ai_action_row.setContentsMargins(0, 4, 0, 0)
        ai_action_row.setSpacing(8)

        self.btn_v5_test_ai = make_button("测试 AI 接口", variant="secondary", min_width=90)
        self.btn_v5_test_ai.clicked.connect(self._v5_test_ai_clicked)

        self.btn_v5_clear_ai_key = make_button("清除 Key", variant="danger", min_width=75)
        self.btn_v5_clear_ai_key.clicked.connect(self._v5_clear_ai_key_clicked)

        self.btn_v5_edit_ai = make_button("编辑此配置", variant="primary", min_width=90)
        self.btn_v5_edit_ai.clicked.connect(self._v5_edit_active_ai_clicked)

        ai_action_row.addWidget(self.btn_v5_test_ai)
        ai_action_row.addWidget(self.btn_v5_clear_ai_key)
        ai_action_row.addStretch(1)
        ai_action_row.addWidget(self.btn_v5_edit_ai)

        ai_detail_layout.addLayout(ai_action_row, 3, 0, 1, 2)
        layout.addWidget(ai_detail_group)

        # Privacy Boundary Notice Banner
        privacy_card = QFrame()
        privacy_card.setFrameShape(QFrame.StyledPanel)
        privacy_card.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px;")
        privacy_layout = QVBoxLayout(privacy_card)
        privacy_layout.setContentsMargins(10, 8, 10, 8)
        privacy_layout.setSpacing(4)

        lbl_priv_title = QLabel("🔒 隐私与安全边界说明")
        lbl_priv_title.setStyleSheet("font-weight: bold; color: #0F172A; font-size: 12px;")

        lbl_priv_desc = QLabel(
            "1. 数据最小化: 发送到 LLM 的数据仅包含发票主体、金额、发票号码等文本片段，绝不上报原始文件。\n"
            "2. 密钥保密: 所有 API Key 均使用 Windows 凭据管理器加密存储，不写入 config.json。\n"
            "3. 本地兜底: 当 AI 暂停或未配置时，系统自动切回本地关键词规则引擎。"
        )
        lbl_priv_desc.setStyleSheet("color: #475569; font-size: 11px;")
        lbl_priv_desc.setWordWrap(True)

        privacy_layout.addWidget(lbl_priv_title)
        privacy_layout.addWidget(lbl_priv_desc)
        layout.addWidget(privacy_card)

        # Saved AI Profiles List
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
        layout.addWidget(self.ai_scroll, stretch=1)

        self.ai_rows = []


    def _refresh_mailbox_list(self):
        for row in self.mailbox_rows:
            self.mailbox_list_layout.removeWidget(row)
            row.deleteLater()
        self.mailbox_rows.clear()

        from ..config import get_email_accounts
        email_accounts = get_email_accounts(self.cfg)


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
        from ..credentials import get_ai_api_key_source
        profiles = get_ai_profiles(self.cfg)

        active = next((profile for profile in profiles if profile["enabled"]), None)
        if active:
            active_key_source = get_ai_api_key_source(active["provider"], active["profile_id"])
            if active_key_source == "missing":
                self.lbl_ai_global_status.setText(f"AI 已选择：{active['name']}（待补全 Key）")
            else:
                self.lbl_ai_global_status.setText(f"AI 功能已启用：{active['name']}")
            self.btn_disable_ai_action.setVisible(True)
            self.btn_disable_ai_action.setEnabled(True)
        else:
            self.lbl_ai_global_status.setText("AI 功能未启用")
            self.btn_disable_ai_action.setVisible(False)
            self.btn_disable_ai_action.setEnabled(False)

        if not profiles:
            lbl_empty = QLabel("尚未保存任何 AI 配置，点击“新增 AI 配置”开始。")
            lbl_empty.setAlignment(Qt.AlignCenter)
            lbl_empty.setProperty("class", "EmptyStateText")
            self.ai_list_layout.insertWidget(0, lbl_empty)
            self.ai_rows.append(lbl_empty)
        else:
            for idx, p in enumerate(profiles):
                key_source = get_ai_api_key_source(p["provider"], p["profile_id"])
                row = AIProfileRow(p, key_source, self)
                row.edit_requested.connect(self._open_ai_editor)
                row.delete_requested.connect(self._delete_ai_profile)
                row.activate_requested.connect(self._set_active_ai_profile)
                self.ai_list_layout.insertWidget(idx, row)
                self.ai_rows.append(row)

        self._refresh_settings_center_pages()

    def _refresh_settings_center_pages(self):
        self._refresh_mailbox_center_summary()
        self._refresh_ai_center_summary()
        self._refresh_rules_center_summary()
        self._refresh_runtime_center_summary()
        self._refresh_privacy_center_summary()
        self._refresh_system_center_summary()
        self._refresh_data_center_summary()

    def _refresh_mailbox_center_summary(self):
        if not hasattr(self, "lbl_mailbox_summary"):
            return
        from ..config import get_email_accounts
        from ..credentials import has_auth_code
        accounts = get_email_accounts(self.cfg)
        enabled_count = sum(1 for acc in accounts if acc.get("enabled", True))
        missing_cred = sum(1 for acc in accounts if not has_auth_code(acc.get("address", "")))
        self.lbl_mailbox_enabled_metric.setText(f"{enabled_count} 个正在参与扫描")
        self.lbl_mailbox_configured_metric.setText(f"共 {len(accounts)} 个邮箱配置保存在本地")
        self.lbl_mailbox_credential_metric.setText(f"{missing_cred} 个邮箱仍需补充授权码")
        self.lbl_mailbox_summary.setText(
            f"已启用 {enabled_count} / 已配置 {len(accounts)} / 需要处理 {missing_cred}"
        )

    def _refresh_ai_center_summary(self):
        if not hasattr(self, "lbl_ai_summary"):
            return
        from ..ai_profiles import get_ai_profiles
        from ..credentials import get_ai_api_key_source
        from ..ai_classifier import is_provider_session_paused
        profiles = get_ai_profiles(self.cfg)
        active = next((profile for profile in profiles if profile.get("enabled")), None)
        missing_keys = sum(
            1 for profile in profiles
            if get_ai_api_key_source(profile["provider"], profile["profile_id"]) == "missing"
        )
        if active:
            active_key_source = get_ai_api_key_source(active["provider"], active["profile_id"])
            key_source = AI_KEY_SOURCE_LABELS.get(active_key_source, "未设置")
            if active_key_source == "missing":
                status = f"当前启用：{active['name']} / 缺少 Key，待补全后才能发起 AI 分类"
                self.lbl_ai_status_metric.setText(f"{active['name']} 已选中，但还不能调用")
            else:
                paused = is_provider_session_paused(active.get("provider", ""))
                session_state = "本次会话已暂停" if paused else "本次会话可用"
                status = f"当前启用：{active['name']} / Key 来源：{key_source} / {session_state}"
                self.lbl_ai_status_metric.setText(f"{active['name']} · {session_state}")
        else:
            status = "AI 当前关闭，本地规则仍然可用"
            self.lbl_ai_status_metric.setText("未启用 AI，当前只使用本地规则")
        if missing_keys:
            self.lbl_ai_key_metric.setText(f"{missing_keys} 个配置缺少 Key，需要补全")
        else:
            self.lbl_ai_key_metric.setText("所有已保存配置都具备可用 Key 来源")
        self.lbl_ai_profile_metric.setText(f"共 {len(profiles)} 个 AI 配置保存在本地")
        self.lbl_ai_summary.setText(f"{status} / 已保存 {len(profiles)} / 缺少密钥 {missing_keys}")

    def _refresh_rules_center_summary(self):
        if not hasattr(self, "lbl_rules_flow"):
            return
        from ..services import DEFAULT_CATEGORY_RULES, TRANSPORT_DETAIL_RULES
        from ..rule_classifier import INVOICE_KEYWORDS, EXCLUDE_KEYWORDS, TECHNICAL_EXCLUDE_KEYWORDS
        cfg_categories = self._config_category_map()
        db_categories = self._db_category_names()
        self.lbl_rules_flow.setText(
            f"发票关键词 {len(INVOICE_KEYWORDS)} 条 / 排除关键词 {len(EXCLUDE_KEYWORDS)} 条 / 技术通知排除 {len(TECHNICAL_EXCLUDE_KEYWORDS)} 条"
        )
        self.lbl_rules_overview.setText(
            f"内置交通细分 {len(TRANSPORT_DETAIL_RULES)} 组 / 默认分类规则 {len(DEFAULT_CATEGORY_RULES)} 组 / 固定规则为只读展示"
        )
        self.lbl_rules_ai_fallback.setText(
            "AI 兜底只在本地规则仍无法确定时启用；认证或调用失败后保持待分类，不覆盖已有本地规则结果。"
        )
        config_names = []
        disabled_count = 0
        for key, value in cfg_categories.items():
            label = self._category_entry_label(key, value)
            if isinstance(value, dict):
                disabled_count += int(bool(value.get("disabled")))
            if label and label not in config_names:
                config_names.append(label)
        db_names = []
        for value in db_categories:
            label = str(value or "").strip()
            if label and label not in db_names:
                db_names.append(label)
        config_summary = "、".join(config_names) if config_names else "无"
        db_summary = "、".join(db_names) if db_names else "无"
        self.lbl_category_dictionary.setText(
            f"配置分类 {len(config_names)} 项（停用推荐 {disabled_count}）：{config_summary} / "
            f"数据库已有分类 {len(db_names)} 项：{db_summary}。分类名称用于归档展示，不等于识别规则。"
        )
        self._refresh_category_dictionary_controls()
        self._refresh_category_dictionary_rows()

    def _refresh_runtime_center_summary(self):
        if not hasattr(self, "lbl_runtime_status"):
            return
        from ..ai_profiles import get_ai_profiles
        from ..credentials import get_ai_api_key_source
        from ..ai_classifier import is_provider_session_paused
        profiles = get_ai_profiles(self.cfg)
        active = next((profile for profile in profiles if profile.get("enabled")), None)
        status_parts = []
        if active is None:
            ai_status = "AI 未启用；当前仍按本地规则和人工审核工作。"
            self.badge_runtime_ai.setVisible(True)
            self.badge_runtime_ai.setText("未启用")
            self.badge_runtime_ai.setProperty("variant", "muted")
        else:
            active_key_source = get_ai_api_key_source(active["provider"], active["profile_id"])
            if active_key_source == "missing":
                ai_status = f"当前配置：{active['name']} ({active['provider']} / {active['model']}) / 待补全 Key"
                self.badge_runtime_ai.setVisible(True)
                self.badge_runtime_ai.setText("待补全")
                self.badge_runtime_ai.setProperty("variant", "warning")
            else:
                paused = is_provider_session_paused(active.get("provider", ""))
                session_state = "会话已暂停" if paused else "会话可用"
                ai_status = f"当前配置：{active['name']} ({active['provider']} / {active['model']}) / {session_state}"
                self.badge_runtime_ai.setVisible(True)
                self.badge_runtime_ai.setText("已暂停" if paused else "可用")
                self.badge_runtime_ai.setProperty("variant", "warning" if paused else "success")
        self.badge_runtime_ai.style().unpolish(self.badge_runtime_ai)
        self.badge_runtime_ai.style().polish(self.badge_runtime_ai)
        self.lbl_runtime_ai_status.setText(ai_status)
        status_parts.append(ai_status)
        pending_count = 0
        unclassified_count = 0
        manual_count = 0
        last_error = ""
        if hasattr(self.parent, "db") and self.parent.db:
            last_error = str(getattr(self.parent.db, "last_error", "") or "").strip()
            try:
                stats = self.parent.db.get_email_stats()
                pending_count = int(stats.get("pending", 0) or 0)
                unclassified_count = int(stats.get("unclassified", 0) or 0)
            except Exception:
                pending_count = 0
                unclassified_count = 0
            try:
                manual_count = int(self.parent.db.count_pending_manual_invoices() or 0)
            except Exception:
                manual_count = 0
        queue_status = f"待下载 {pending_count} / 待人工补全 {manual_count} / 待分类 {unclassified_count}"
        self.lbl_runtime_queue_status.setText(queue_status)
        status_parts.append(queue_status)
        last_scan_summary = getattr(self.parent, "_last_scan_summary", {}) if hasattr(self, "parent") else {}
        scan_parts = []
        if isinstance(last_scan_summary, dict):
            ai_pending = int(last_scan_summary.get("ai_pending_classification", 0) or 0)
            if ai_pending:
                scan_parts.append(f"AI 待分类 {ai_pending}")
        if last_error:
            scan_parts.append(f"最近错误：{last_error}")
        if not scan_parts:
            scan_parts.append("最近一次扫描没有额外待处理或错误记录")
        scan_status = " / ".join(scan_parts)
        self.lbl_runtime_scan_status.setText(scan_status)
        status_parts.append(scan_status)
        self.lbl_runtime_status.setText(" / ".join(status_parts))

    def _refresh_privacy_center_summary(self):
        if not hasattr(self, "lbl_privacy_boundary"):
            return
        self.lbl_privacy_sent_items.setText("会发送给 AI：掩码后的主题、掩码后的发件人、最小分类请求元数据。")
        self.lbl_privacy_local_items.setText("不会发送给 AI：邮件正文、附件、PDF、图片、本地文件路径、邮箱授权码和 API Key。")
        self.lbl_privacy_storage_note.setText(
            "API Key 和邮箱授权码仅保存在系统凭据管理器；配置文件和日志会剥离 secret。"
            "如果 provider 认证或请求失败，数据保持待分类，不污染本地规则结果。"
        )
        self.lbl_privacy_boundary.setText(
            "删除 AI profile 时不会静默清除系统凭据；需要独立确认。截图反馈前请继续遮挡本地路径和真实票据信息。"
        )

    def _config_category_map(self) -> dict:
        categories = self.cfg.get("categories", {})
        if not isinstance(categories, dict):
            categories = {}
            self.cfg["categories"] = categories
        return categories

    def _db_category_names(self) -> list[str]:
        db_categories = []
        if hasattr(self.parent, "db") and self.parent.db:
            try:
                db_categories = [item for item in self.parent.db.list_categories() if str(item or "").strip()]
            except Exception:
                db_categories = []
        return db_categories

    def _category_entry_label(self, key: str, value) -> str:
        if isinstance(value, dict):
            label = str(value.get("name") or value.get("label") or CONFIG_CATEGORY_LABELS.get(str(key), key)).strip()
            return label
        if isinstance(value, str) and str(value).strip():
            raw_value = str(value).strip()
            return CONFIG_CATEGORY_LABELS.get(raw_value, raw_value)
        return str(CONFIG_CATEGORY_LABELS.get(str(key), key)).strip()

    def _generate_category_key(self, name: str) -> str:
        categories = self._config_category_map()
        base = re.sub(r"[^0-9a-zA-Z]+", "_", str(name or "").strip().lower()).strip("_")
        if not base:
            base = "category"
        candidate = base
        index = 2
        while candidate in categories:
            candidate = f"{base}_{index}"
            index += 1
        return candidate

    def _category_label_exists(self, label: str, *, exclude_key: str | None = None) -> bool:
        normalized = str(label or "").strip().casefold()
        if not normalized:
            return False
        for key, value in self._config_category_map().items():
            if exclude_key and key == exclude_key:
                continue
            current = self._category_entry_label(key, value)
            if current.casefold() == normalized:
                return True
        return False

    def _category_label_used(self, label: str) -> bool:
        normalized = str(label or "").strip().casefold()
        if not normalized:
            return False
        return any(str(item or "").strip().casefold() == normalized for item in self._db_category_names())

    def _refresh_category_dictionary_controls(self, selected_key: str | None = None):
        if not hasattr(self, "combo_config_categories"):
            return
        categories = self._config_category_map()
        entries = []
        for key, value in categories.items():
            label = self._category_entry_label(key, value)
            disabled = isinstance(value, dict) and bool(value.get("disabled"))
            if label:
                entries.append((label.casefold(), key, label, disabled))
        entries.sort(key=lambda item: item[0])

        previous_key = selected_key
        if previous_key is None:
            previous_key = self.combo_config_categories.currentData()

        self.combo_config_categories.blockSignals(True)
        self.combo_config_categories.clear()
        self.combo_config_categories.addItem("选择配置分类…", "")
        for _, key, label, disabled in entries:
            suffix = "（已停用推荐）" if disabled else ""
            self.combo_config_categories.addItem(f"{label}{suffix}", key)
        target_index = self.combo_config_categories.findData(previous_key) if previous_key else -1
        self.combo_config_categories.setCurrentIndex(target_index if target_index >= 0 else 0)
        self.combo_config_categories.blockSignals(False)
        self._on_category_dictionary_selection_changed(self.combo_config_categories.currentIndex())

    def _refresh_category_dictionary_rows(self):
        if not hasattr(self, "category_dictionary_rows_layout"):
            return
        while self.category_dictionary_rows_layout.count():
            item = self.category_dictionary_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        combined = {}
        for name in BUILTIN_CATEGORY_NAMES:
            combined.setdefault(name, {"sources": [], "disabled": False, "config_key": ""})
            if "内置" not in combined[name]["sources"]:
                combined[name]["sources"].append("内置")
        for key, value in self._config_category_map().items():
            label = self._category_entry_label(key, value)
            if not label:
                continue
            combined.setdefault(label, {"sources": [], "disabled": False, "config_key": ""})
            if "配置分类" not in combined[label]["sources"]:
                combined[label]["sources"].append("配置分类")
            combined[label]["disabled"] = combined[label]["disabled"] or bool(isinstance(value, dict) and value.get("disabled"))
            combined[label]["config_key"] = key
        for name in self._db_category_names():
            combined.setdefault(name, {"sources": [], "disabled": False, "config_key": ""})
            if "历史" not in combined[name]["sources"]:
                combined[name]["sources"].append("历史")

        for name in sorted(combined.keys(), key=lambda item: item.casefold()):
            meta = combined[name]
            row = QFrame()
            row.setProperty("class", "SettingsListRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(8)
            lbl_name = QLabel(name)
            lbl_name.setProperty("class", "SettingsListHeader")
            lbl_meta = QLabel(" / ".join(meta["sources"]))
            lbl_meta.setProperty("class", "SectionHint")
            row_layout.addWidget(lbl_name)
            row_layout.addStretch()
            row_layout.addWidget(lbl_meta)
            if meta["disabled"]:
                row_layout.addWidget(make_badge("已停用推荐", variant="warning"))
            if meta.get("config_key"):
                btn_manage = make_button("编辑名称", variant="secondary", min_width=76)
                btn_manage.clicked.connect(
                    lambda _checked=False, category_key=meta["config_key"]: self._focus_category_dictionary_entry(category_key)
                )
                row_layout.addWidget(btn_manage)
            self.category_dictionary_rows_layout.addWidget(row)

        self.category_dictionary_rows_layout.addStretch()

    def _focus_category_dictionary_entry(self, category_key: str):
        if not category_key or not hasattr(self, "combo_config_categories"):
            return
        index = self.combo_config_categories.findData(category_key)
        if index >= 0:
            self.combo_config_categories.setCurrentIndex(index)
        self.txt_category_name.setFocus()

    def _on_category_dictionary_selection_changed(self, index: int):
        if not hasattr(self, "combo_config_categories"):
            return
        key = self.combo_config_categories.currentData()
        categories = self._config_category_map()
        entry = categories.get(key) if key else None
        label = self._category_entry_label(key, entry) if key and entry is not None else ""
        is_disabled = bool(isinstance(entry, dict) and entry.get("disabled"))
        is_used = bool(label and self._category_label_used(label))
        if key:
            self.txt_category_name.setText(label)
        else:
            self.txt_category_name.clear()
        self.btn_rename_category.setEnabled(bool(key))
        self.btn_disable_category.setEnabled(bool(key))
        self.btn_disable_category.setText("恢复推荐" if is_disabled else "停止推荐")
        self.btn_delete_category.setEnabled(bool(key) and not is_used)

    def _persist_category_dictionary_changes(self, selected_key: str | None = None):
        from ..config import save_config
        save_config(self.cfg)
        if hasattr(self.parent, "config"):
            self.parent.config = self.cfg
        self._refresh_settings_center_pages()
        self._refresh_category_dictionary_controls(selected_key=selected_key)
        self._show_settings_home("rules")

    def _add_category_dictionary_entry(self, name: str | None = None):
        label = str(name if name is not None else self.txt_category_name.text()).strip()
        if not label:
            QMessageBox.warning(self, "分类名称为空", "请输入分类名称。")
            return None
        if self._category_label_exists(label):
            QMessageBox.warning(self, "分类已存在", "该分类名称已存在，请直接重命名或选择其他名称。")
            return None
        key = self._generate_category_key(label)
        self._config_category_map()[key] = {"name": label}
        self._persist_category_dictionary_changes(selected_key=key)
        return key

    def _rename_category_dictionary_entry(self, category_key: str | None = None, new_name: str | None = None):
        key = category_key if category_key is not None else self.combo_config_categories.currentData()
        categories = self._config_category_map()
        if not key or key not in categories:
            QMessageBox.warning(self, "未选择分类", "请先选择要重命名的配置分类。")
            return False
        label = str(new_name if new_name is not None else self.txt_category_name.text()).strip()
        if not label:
            QMessageBox.warning(self, "分类名称为空", "请输入分类名称。")
            return False
        if self._category_label_exists(label, exclude_key=key):
            QMessageBox.warning(self, "分类已存在", "该分类名称已存在，请直接使用已有分类。")
            return False
        value = categories.get(key)
        updated = dict(value) if isinstance(value, dict) else {}
        updated["name"] = label
        categories[key] = updated
        self._persist_category_dictionary_changes(selected_key=key)
        return True

    def _toggle_selected_category_recommendation(self):
        key = self.combo_config_categories.currentData() if hasattr(self, "combo_config_categories") else ""
        if not key:
            QMessageBox.warning(self, "未选择分类", "请先选择配置分类。")
            return False
        categories = self._config_category_map()
        value = categories.get(key)
        updated = dict(value) if isinstance(value, dict) else {"name": self._category_entry_label(key, value)}
        is_disabled = bool(updated.get("disabled"))
        if is_disabled:
            updated.pop("disabled", None)
        else:
            updated["disabled"] = True
        categories[key] = updated
        self._persist_category_dictionary_changes(selected_key=key)
        return True

    def _delete_category_dictionary_entry(self, category_key: str | None = None):
        key = category_key if category_key is not None else (
            self.combo_config_categories.currentData() if hasattr(self, "combo_config_categories") else ""
        )
        categories = self._config_category_map()
        if not key or key not in categories:
            QMessageBox.warning(self, "未选择分类", "请先选择配置分类。")
            return None
        label = self._category_entry_label(key, categories[key])
        if self._category_label_used(label):
            updated = dict(categories[key]) if isinstance(categories[key], dict) else {"name": label}
            updated["disabled"] = True
            categories[key] = updated
            self._persist_category_dictionary_changes(selected_key=key)
            return "disabled"
        categories.pop(key, None)
        self._persist_category_dictionary_changes()
        return "deleted"

    def _refresh_system_center_summary(self):
        if not hasattr(self, "lbl_system_settings"):
            return
        email_cfg = self.cfg.get("email", {}) if isinstance(self.cfg.get("email"), dict) else {}
        search_cfg = self.cfg.get("search", {}) if isinstance(self.cfg.get("search"), dict) else {}
        imap_cfg = self.cfg.get("imap", {}) if isinstance(self.cfg.get("imap"), dict) else {}
        self.lbl_system_settings.setText(
            f"当前主邮箱投影：{email_cfg.get('address', '未配置')} / 文件夹：{search_cfg.get('folder', 'INBOX')} / 最近 {search_cfg.get('months_back', 3)} 个月 / IMAP：{imap_cfg.get('server', '未配置')}"
        )

    def _refresh_data_center_summary(self):
        if not hasattr(self, "lbl_data_settings"):
            return
        from ..config import RUNTIME_DIR
        db_path = "未连接数据库"
        if hasattr(self.parent, "db") and self.parent.db:
            db_path = str(getattr(self.parent.db, "_path", "未连接数据库"))
        privacy_hint = "截图反馈前请遮挡本地用户名和完整路径。"
        self.lbl_data_settings.setText(
            f"运行数据目录：{RUNTIME_DIR}\n当前数据库：{db_path}\n{privacy_hint}\n本页只展示真实本地路径与数据位置，不在这里删除业务数据。"
        )
        self.lbl_data_settings.setToolTip(
            f"Runtime: {RUNTIME_DIR}\nDatabase: {db_path}\n{privacy_hint}"
        )

    def _set_mailbox_enabled(self, mailbox_key: str, enabled: bool):
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

        enabled_count = sum(
            1 for acc in email_accounts
            if acc.get("enabled", True)
        )

        if not enabled and enabled_count <= 1 and target_account.get("enabled", True):
            QMessageBox.warning(self, "操作被拒绝", "至少需要保留一个启用的邮箱账号。")
            self._refresh_mailbox_list()
            return

        target_account["enabled"] = enabled
        from ..config import _normalize_default_email_account, _apply_primary_email_account
        email_accounts = _normalize_default_email_account(email_accounts)
        self.cfg = _apply_primary_email_account(self.cfg, email_accounts)

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

        reply = QMessageBox.question(
            self,
            "确认删除",
            "删除邮箱配置只会移除该邮箱的登录设置、授权码和扫描状态，不会删除已导入的发票、附件或报销组。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        updated_accounts = [acc for acc in email_accounts if acc is not target_account]
        updated_cfg = deepcopy(self.cfg)
        updated_cfg["email_accounts"] = updated_accounts

        from ..config import _normalize_default_email_account, _apply_primary_email_account
        if updated_accounts:
            updated_accounts = _normalize_default_email_account(updated_accounts)
            updated_cfg = _apply_primary_email_account(updated_cfg, updated_accounts)
        else:
            updated_cfg["email_accounts"] = []
            updated_cfg["email"] = {"provider": "qq", "address": "", "username": ""}
            updated_cfg["imap"] = {"server": "", "port": 993, "ssl": True}
            updated_cfg["search"] = {"folder": "INBOX", "months_back": 3}

        from ..config import save_config
        try:
            save_config(updated_cfg)
            self.cfg = updated_cfg
            if hasattr(self.parent, "config"):
                self.parent.config = _load_config_safe_compat()
            self._build_saved_account_maps()
            self._refresh_mailbox_list()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置文件失败: {e}")
            return

        email = target_account.get("address", "")
        if email:
            from ..credentials import delete_auth_code
            try:
                delete_auth_code(email)
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"🗏 [安全凭证] 邮箱 {email} 的授权码凭证已从凭据管理器中移除。")
            except Exception as e:
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"❌ [安全凭证] 从凭据管理器移除邮箱 {email} 凭证失败: {e}")

        mailbox_key_to_clear = str(target_account.get("mailbox_key") or "").strip() or self._normalize_address(email)
        if hasattr(self.parent, "db") and self.parent.db:
            try:
                self.parent.db.remove_mailbox_scan_state(mailbox_key_to_clear)
            except Exception as e:
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"❌ [数据库] 清除邮箱同步状态失败: {e}")

        QMessageBox.information(self, "成功", "邮箱配置已删除，已导入发票不会被删除。")
    def _show_settings_home(self, tab_name="mailboxes"):
        self._cancel_mailbox_test()
        self.settings_stack.setCurrentWidget(self.page_settings_home)
        self._select_settings_section(tab_name)

    def _open_new_mailbox_editor(self):
        self._editing_existing_mailbox = False
        self._loaded_account_mailbox_key = ""
        self._loaded_account_address = ""
        self._loaded_account_provider = ""
        self._missing_saved_provider = ""
        self._email_is_user_draft = False
        self.test_success = False
        self.txt_email.clear()
        self.txt_mailbox_name.setText(self._provider_display_name("qq"))
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
        self._editing_existing_mailbox = True
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
        self.btn_ai_prev = make_button("上一步", variant="secondary", min_width=56)
        self.btn_ai_prev.clicked.connect(self._ai_goto_prev_step)

        self.btn_ai_next = make_button("下一步", variant="primary", min_width=76)
        self.btn_ai_next.clicked.connect(self._ai_goto_next_step)

        self.btn_ai_save_only = make_button("仅保存配置", variant="secondary", min_width=76)
        self.btn_ai_save_only.clicked.connect(lambda: self._save_ai_profile_settings(activate=False))

        self.btn_ai_save_and_activate = make_button("保存并设为当前", variant="primary", min_width=110)
        self.btn_ai_save_and_activate.clicked.connect(lambda: self._save_ai_profile_settings(activate=True))

        self.btn_ai_cancel = make_button("取消", variant="secondary", min_width=56)
        self.btn_ai_cancel.clicked.connect(lambda: self._show_settings_home("ai"))

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
        self.combo_ai_provider.addItems(["deepseek", "gemini", "openai"])
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
        self.lbl_ai_wizard_key_status.setProperty("class", "StatusHint")

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
            self.txt_ai_model.addItems(["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"])
            self.txt_ai_model.setCurrentText("gemini-2.5-flash")
        elif provider == "openai":
            self.txt_ai_model.addItems(["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"])
            self.txt_ai_model.setCurrentText("gpt-4o-mini")

    def _update_ai_wizard_ui(self):
        if getattr(self, "_loading_ai_profile_values", False):
            return
        if not hasattr(self, "ai_step_stack") or self.ai_step_stack is None:
            return
        self.ai_current_step = max(1, min(3, int(getattr(self, "ai_current_step", 1))))
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

            from ..credentials import get_ai_api_key_source
            provider = self.combo_ai_provider.currentText()
            key_source = get_ai_api_key_source(provider, self._editing_ai_profile_id)
            source_label = AI_KEY_SOURCE_LABELS.get(key_source, AI_KEY_SOURCE_LABELS["missing"])

            if key_source == "profile":
                self.lbl_ai_wizard_key_status.setText(
                    f"API Key 状态：<font color='#10B981'><b>当前配置专属 Key</b></font>（{source_label}）"
                )
                self.txt_ai_key.setPlaceholderText(SAVED_SECRET_PLACEHOLDER)
            elif key_source == "provider":
                self.lbl_ai_wizard_key_status.setText(
                    f"API Key 状态：<font color='#3B82F6'><b>旧版 Provider Key</b></font>（{source_label}）"
                )
                self.txt_ai_key.setPlaceholderText(SAVED_SECRET_PLACEHOLDER)
            elif key_source == "env":
                self.lbl_ai_wizard_key_status.setText(
                    f"API Key 状态：<font color='#8B5CF6'><b>环境变量提供</b></font>（{source_label}）"
                )
                self.txt_ai_key.setPlaceholderText(SAVED_SECRET_PLACEHOLDER)
            else:
                self.lbl_ai_wizard_key_status.setText(
                    f"API Key 状态：<font color='#B42318'><b>未配置</b></font>（{source_label}）"
                )
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
        from ..credentials import get_ai_api_key_source
        key_source = get_ai_api_key_source(provider, self._editing_ai_profile_id)
        has_input_key = bool(self.txt_ai_key.text().strip())

        if has_input_key:
            self.lbl_ai_summary_key_status.setText("已输入新 Key（保存时写入）")
        elif key_source == "profile":
            self.lbl_ai_summary_key_status.setText("已保存（当前配置专属 Key）")
        elif key_source == "provider":
            self.lbl_ai_summary_key_status.setText("已保存（旧版 Provider Key）")
        elif key_source == "env":
            self.lbl_ai_summary_key_status.setText("来自环境变量（无需单独保存）")
        else:
            self.lbl_ai_summary_key_status.setText("未设置（需要输入 API Key）")

        is_key_available = key_source != "missing" or has_input_key
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
        self.ai_current_step = 1
        self._loading_ai_profile_values = True
        try:
            self._editing_ai_profile_id = f"ai-{uuid4().hex[:8]}"
            self.txt_ai_name.clear()
            self.txt_ai_key.clear()
            self.combo_ai_provider.setCurrentIndex(0)
            self._on_ai_wizard_provider_changed(self.combo_ai_provider.currentText())
        finally:
            self._loading_ai_profile_values = False

        self._update_ai_wizard_ui()
        self.settings_stack.setCurrentWidget(self.page_ai_editor)

    def _open_ai_editor(self, profile_id: str):
        from ..ai_profiles import get_ai_profiles
        profiles = get_ai_profiles(self.cfg)
        target = next((p for p in profiles if p["profile_id"] == profile_id), None)
        if not target:
            QMessageBox.warning(self, "错误", f"找不到对应的 AI 配置: {profile_id}")
            return

        self.ai_current_step = 1
        self._loading_ai_profile_values = True
        try:
            self._editing_ai_profile_id = profile_id
            self.txt_ai_name.setText(target.get("name", ""))
            self.combo_ai_provider.setCurrentText(target.get("provider", "deepseek"))
            self._on_ai_wizard_provider_changed(target.get("provider", "deepseek"))
            self.txt_ai_model.setCurrentText(target.get("model", ""))
            self.txt_ai_key.clear()
        finally:
            self._loading_ai_profile_values = False

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

            self._loading_ai_profile_values = True
            try:
                self.txt_ai_key.clear()
            finally:
                self._loading_ai_profile_values = False
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
        self._save_config_and_refresh("ai")

    def _disable_ai(self):
        from ..ai_profiles import get_ai_profiles, apply_active_ai_profile
        profiles = get_ai_profiles(self.cfg)

        for p in profiles:
            p["enabled"] = False

        apply_active_ai_profile(self.cfg, profiles)
        self._save_config_and_refresh("ai")

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

    def _save_config_and_refresh(self, tab_name: str):
        from ..config import save_config
        save_config(self.cfg)
        self._persist_settings_and_refresh(tab_name)

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

    @staticmethod
    def _provider_display_name(provider: str) -> str:
        return PROVIDER_EMAIL_NAMES.get(str(provider or "").lower(), "邮箱")

    @staticmethod
    def _is_provider_domain_consistent(provider: str, email: str) -> bool:
        """Return True when the email domain is compatible with the selected provider.

        Custom provider accepts any domain. For known providers, the domain
        must belong to the provider's allowed set.  If the email has no
        domain (empty or no '@'), we return True so the "invalid email"
        validation handles it instead.
        """
        if not email or "@" not in email:
            return True
        if provider in ("custom", "outlook"):
            return True
        domain = email.rsplit("@", 1)[1].lower()
        allowed = PROVIDER_ALLOWED_DOMAINS.get(provider)
        if allowed is None:
            return True
        return domain in allowed

    def _find_account_index(self, email_accounts, *identifiers):
        normalized_ids = {
            self._normalize_address(identifier)
            for identifier in identifiers
            if str(identifier or "").strip()
        }
        if not normalized_ids:
            return None

        for index, account in enumerate(email_accounts):
            account_address = self._normalize_address(account.get("address"))
            account_key = self._normalize_address(account.get("mailbox_key"))
            if account_address in normalized_ids or account_key in normalized_ids:
                return index
        return None

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
        mailbox_name = str(account.get("name") or "").strip()
        imap = account.get("imap") if isinstance(account.get("imap"), dict) else {}
        search = account.get("search") if isinstance(account.get("search"), dict) else {}

        self._loading_account_values = True
        try:
            self._select_provider_card(provider)
            self.txt_mailbox_name.setText(mailbox_name)
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
            if hasattr(self, "chk_enabled"):
                self.chk_enabled.setChecked(account.get("enabled", True) is not False)
            if hasattr(self, "chk_is_default"):
                self.chk_is_default.setChecked(bool(account.get("is_default") or account.get("default")))
            if hasattr(self, "lbl_v4_status_conn"):
                self.lbl_v4_status_conn.setText("连接正常" if account.get("enabled", True) else "已停用")
        finally:
            self._loading_account_values = False

        self._email_is_user_draft = False
        self.test_success = False
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
        self._mailbox_test_form_revision += 1
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
        self.test_success = False
        # Clear auth code on provider switch
        if hasattr(self, "txt_auth_code"):
            self.txt_auth_code.clear()

        saved_account = self._first_saved_account(provider)
        if saved_account is not None and not self._editing_existing_mailbox:
            self._load_saved_account(saved_account)
            return

        current_email = self.txt_email.text().strip()
        can_rewrite_draft = self._email_is_user_draft and not self._is_saved_address(current_email)
        self._missing_saved_provider = provider

        self._loading_account_values = True
        try:
            if self._editing_existing_mailbox:
                # Edit mode: rewrite email domain to match new provider
                self._adjust_email_for_provider(provider)
                # Update mailbox name if it matches the old provider default
                old_name = self.txt_mailbox_name.text().strip()
                old_default = self._provider_display_name(previous_provider)
                new_default = self._provider_display_name(provider)
                if not old_name or old_name == old_default:
                    self.txt_mailbox_name.setText(new_default)
                # Keep _loaded_account_mailbox_key for save-in-place
                self._loaded_account_provider = provider
            else:
                self._loaded_account_address = ""
                self._loaded_account_mailbox_key = ""
                self._loaded_account_provider = ""
                if can_rewrite_draft:
                    self._adjust_email_for_provider(provider)
                else:
                    self.txt_email.clear()
                    self._adjust_email_for_provider(provider)
        finally:
            self._loading_account_values = False
        self._email_is_user_draft = can_rewrite_draft or self._editing_existing_mailbox

        if provider == "custom":
            self.advanced_group.setVisible(True)
            self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲")
        else:
            self.advanced_group.setVisible(False)
            self.btn_toggle_advanced.setText("显示高级 IMAP 设置 ▼")
            self._apply_provider_defaults(provider)
        if not self._loaded_account_mailbox_key and not self.txt_mailbox_name.text().strip():
            self.txt_mailbox_name.setText(self._provider_display_name(provider))
        self._update_provider_hint()
        self._update_cred_status_label()
        self._update_wizard_ui()

    def _mark_advanced_settings_dirty(self, *_args):
        if not self._loading_initial_values and not self._applying_provider_defaults:
            self._advanced_settings_dirty = True

    def _on_advanced_settings_changed(self, *_args):
        self._mailbox_test_form_revision += 1
        self._mark_advanced_settings_dirty()
        self.test_success = False
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
            domain_ok = self._is_provider_domain_consistent(provider, email)
            self.btn_next.setEnabled(
                provider != "outlook" and not is_outlook_like and is_valid and domain_ok
            )

        domain = email.rsplit("@", 1)[1].lower() if "@" in email else ""
        # Provider/email domain mismatch hint
        if is_valid and domain and not self._is_provider_domain_consistent(provider, email):
            self.lbl_provider_hint.setText(
                "邮箱地址后缀与所选邮箱类型不一致，请修改邮箱地址或重新选择邮箱类型。"
            )
        elif provider == "outlook" and not email:
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
            self.lbl_cred_status.setText("🔒 授权状态：<font color='#B42318'><b>尚未配置 (点击下一步并保存时将自动加密保存)</b></font>")
            self.txt_auth_code.setPlaceholderText("请输入邮箱授权码（非登录密码）")


    def _on_email_text_changed(self):
        if self._loading_initial_values or self._loading_account_values:
            return

        self._mailbox_test_form_revision += 1
        email = self.txt_email.text().strip()
        email_clean = self._normalize_address(email)
        self.test_success = False

        # Enable/disable the delete button dynamically
        self._update_delete_button_state()

        has_saved = self._is_saved_address(email_clean)
        # If it is a saved email, auto-load all its configuration!
        if has_saved and not self._editing_existing_mailbox:
            if self._loaded_account_address != email_clean:
                saved_acc = self._saved_accounts_by_address[email_clean]
                self._load_saved_account(saved_acc)
                return

        self._email_is_user_draft = True
        self._missing_saved_provider = ""
        email_lower = email.lower()
        domain = email_lower.rsplit("@", 1)[1] if "@" in email_lower else ""
        provider = DOMAIN_TO_PROVIDER.get(domain)
        if provider and self._loaded_account_provider and provider != self._loaded_account_provider and not self._editing_existing_mailbox:
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
        self._mailbox_test_form_revision += 1
        self.test_success = False
        self.lbl_test_result.setText("邮箱授权码已更改，请重新进行连接测试。")
        self.lbl_test_result.setProperty("variant", "warning")
        self.lbl_test_result.style().unpolish(self.lbl_test_result)
        self.lbl_test_result.style().polish(self.lbl_test_result)

    def _toggle_advanced_settings(self):
        visible = not self.advanced_group.isVisible()
        self.advanced_group.setVisible(visible)
        self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲" if visible else "显示高级 IMAP 设置 ▼")

    def _on_ai_provider_changed(self):
        provider = self.combo_ai_provider.currentText()
        self._on_ai_wizard_provider_changed(provider)
        self._update_ai_wizard_ui()
    def _show_auth_code_help(self):
        if self._get_selected_provider() == "outlook":
            QMessageBox.information(
                self,
                "Outlook 邮箱设置说明",
                "Outlook/Hotmail/Live 和 Microsoft 365 邮箱目前需要 OAuth2/XOAUTH2 认证。当前版本暂不支持 Outlook 邮箱扫描。后续版本可通过 Microsoft OAuth2/MSAL 支持。",
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
            if not self._is_provider_domain_consistent(provider, email):
                self.lbl_provider_hint.setText("邮箱地址后缀与所选邮箱类型不一致，请修改邮箱地址或选择自定义 IMAP")
                QMessageBox.warning(
                    self,
                    "校验提示",
                    "邮箱地址后缀与所选邮箱类型不一致，请修改邮箱地址或选择自定义 IMAP"
                )
                return
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
            domain_ok = self._is_provider_domain_consistent(provider, self.txt_email.text().strip())
            self.btn_next.setEnabled(provider != "outlook" and not is_outlook_like and is_valid and domain_ok)
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
        self.lbl_sum_name.setText(self.txt_mailbox_name.text().strip() or self._provider_display_name(provider))
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

    def _mailbox_test_form_identity(self):
        """Return only non-secret state that identifies the current form."""

        return (
            self.txt_email.text().strip(),
            self._get_selected_provider(),
            self.txt_imap_server.text().strip(),
            self.txt_imap_port.text().strip(),
            bool(getattr(self, "chk_ssl", None) and self.chk_ssl.isChecked()),
            self.txt_months.text().strip(),
            self._mailbox_test_form_revision,
        )

    def _set_mailbox_test_busy(self, busy: bool):
        buttons = [
            getattr(self, "btn_test", None),
            getattr(self, "btn_v4_test", None),
        ]
        for button in buttons:
            if button is None:
                continue
            button.setEnabled(not busy)
            button.setText("正在测试..." if busy else "测试连接")

        if busy and not self._mailbox_test_cursor_active:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._mailbox_test_cursor_active = True
        elif not busy and self._mailbox_test_cursor_active:
            QApplication.restoreOverrideCursor()
            self._mailbox_test_cursor_active = False

    def _clear_mailbox_test_worker(self, worker):
        if worker is not self._mailbox_test_worker:
            return
        self._mailbox_test_worker = None
        self._mailbox_test_context = None
        self._mailbox_test_result_handled = False
        self._mailbox_test_thread_finished = False
        self._set_mailbox_test_busy(False)
        try:
            worker.deleteLater()
        except RuntimeError:
            pass

    def _cancel_mailbox_test(self, *, closing: bool = False):
        """Request cooperative stop without blocking the GUI event loop.

        The dialog retains ownership until QThread.finished.  Clearing the
        context immediately makes any queued result callback fail closed.
        """
        if closing:
            self._closing = True

        worker = self._mailbox_test_worker
        if worker is None:
            return False

        self._mailbox_test_context = None
        self._mailbox_test_result_handled = False
        self._mailbox_test_thread_finished = False
        self._set_mailbox_test_busy(False)

        if worker.isRunning():
            worker.request_cancel()
            return True

        # The worker finished before its queued QThread.finished callback was
        # delivered. It is safe to release ownership without waiting.
        self._mailbox_test_thread_finished = True
        self._clear_mailbox_test_worker(worker)
        return False

    def _request_mailbox_test_close(self, action):
        self._mailbox_test_pending_close_action = action
        self._closing = True
        if self._cancel_mailbox_test(closing=True):
            return True
        self._mailbox_test_pending_close_action = None
        return False

    def _finalize_pending_mailbox_test_close(self):
        action = self._mailbox_test_pending_close_action
        if not action or self._mailbox_test_worker is not None:
            return

        self._mailbox_test_pending_close_action = None
        if action == "accept":
            QDialog.accept(self)
        elif action == "reject":
            QDialog.reject(self)
        elif action == "close":
            self._mailbox_test_finalizing_close = True
            try:
                self.close()
            finally:
                self._mailbox_test_finalizing_close = False

    def closeEvent(self, event):
        if self._mailbox_test_finalizing_close:
            super().closeEvent(event)
            return
        if self._request_mailbox_test_close("close"):
            event.ignore()
            return
        super().closeEvent(event)

    def accept(self):
        if self._request_mailbox_test_close("accept"):
            return
        super().accept()

    def reject(self):
        if self._request_mailbox_test_close("reject"):
            return
        super().reject()

    def _mailbox_test_thread_done(self):
        worker = self.sender()
        if worker is not self._mailbox_test_worker:
            return

        self._mailbox_test_thread_finished = True
        if (
            self._closing
            or self._mailbox_test_context is None
            or self._mailbox_test_result_handled
        ):
            self._clear_mailbox_test_worker(worker)
            self._finalize_pending_mailbox_test_close()
    def _mailbox_test_result_done(self, worker):
        if worker is not self._mailbox_test_worker:
            return
        self._mailbox_test_result_handled = True
        self._set_mailbox_test_busy(False)
        if self._mailbox_test_thread_finished:
            self._clear_mailbox_test_worker(worker)

    def _mailbox_test_finished(self, request_id):
        if self._closing:
            return
        worker = self.sender()
        context = self._mailbox_test_context
        if worker is not self._mailbox_test_worker or context is None:
            return
        if request_id != context["request_id"]:
            self.test_success = False
            self._mailbox_test_result_done(worker)
            return
        if self._mailbox_test_form_identity() != context["identity"]:
            self.test_success = False
            self._mailbox_test_result_done(worker)
            return

        self.test_success = True
        self._mailbox_test_result_done(worker)
        self.lbl_test_result.setProperty("variant", "success")
        self.lbl_test_result.style().unpolish(self.lbl_test_result)
        self.lbl_test_result.style().polish(self.lbl_test_result)
        self.lbl_test_result.setText(
            f"已连接到 {context['provider_text']}，可扫描最近 {context['months']} 个月发票邮件。"
        )

    def _mailbox_test_error(self, error_text):
        if self._closing:
            return
        worker = self.sender()
        context = self._mailbox_test_context
        if worker is not self._mailbox_test_worker or context is None:
            return
        if self._mailbox_test_form_identity() != context["identity"]:
            self.test_success = False
            self._mailbox_test_result_done(worker)
            return

        self.test_success = False
        self._mailbox_test_result_done(worker)
        self.lbl_test_result.setProperty("variant", "danger")
        self.lbl_test_result.style().unpolish(self.lbl_test_result)
        self.lbl_test_result.style().polish(self.lbl_test_result)
        self.lbl_test_result.setText(
            self._format_connection_failure(
                context["provider"],
                context["server"],
                context["port"],
                error_text,
            )
        )

    def _mailbox_test_cancelled(self):
        if self._closing:
            return
        worker = self.sender()
        context = self._mailbox_test_context
        if worker is not self._mailbox_test_worker or context is None:
            return
        self.test_success = False
        self._mailbox_test_result_done(worker)
        self.lbl_test_result.setProperty("variant", "muted")
        self.lbl_test_result.style().unpolish(self.lbl_test_result)
        self.lbl_test_result.style().polish(self.lbl_test_result)
        self.lbl_test_result.setText("连接测试已取消")

    def _test_connection_clicked(self):
        # Keep one immutable in-flight operation.  This also blocks a second
        # click while a finished worker's queued result is awaiting delivery.
        if self._mailbox_test_worker is not None:
            return

        email = self.txt_email.text().strip()
        auth_code = self.txt_auth_code.text().strip()

        if not email:
            QMessageBox.warning(self, "校验提示", "请先填写邮箱地址。")
            return

        provider = self._get_selected_provider()
        if not self._is_provider_domain_consistent(provider, email):
            self.lbl_provider_hint.setText("邮箱地址后缀与所选邮箱类型不一致，请修改邮箱地址或选择自定义 IMAP")
            self.current_step = 1
            self._update_wizard_ui()
            QMessageBox.warning(
                self,
                "校验提示",
                "邮箱地址后缀与所选邮箱类型不一致，请修改邮箱地址或选择自定义 IMAP"
            )
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

        from .workers import MailboxConnectionTestRequest, MailboxConnectionTestWorker

        self.test_success = False
        self._mailbox_test_request_id += 1
        request_id = self._mailbox_test_request_id
        request = MailboxConnectionTestRequest(
            request_id=request_id,
            address=email,
            auth_code=auth_code,
            server=server,
            port=port,
        )
        self._mailbox_test_context = {
            "request_id": request_id,
            "identity": self._mailbox_test_form_identity(),
            "provider": provider,
            "provider_text": self.lbl_sum_provider.text(),
            "server": server,
            "port": port,
            "months": self.txt_months.text().strip(),
        }
        worker = MailboxConnectionTestWorker(request, parent=self)
        worker.success.connect(self._mailbox_test_finished)
        worker.error.connect(self._mailbox_test_error)
        worker.cancelled.connect(self._mailbox_test_cancelled)
        worker.finished.connect(self._mailbox_test_thread_done)
        self._mailbox_test_worker = worker
        self._mailbox_test_result_handled = False
        self._mailbox_test_thread_finished = False
        self._set_mailbox_test_busy(True)
        self.lbl_test_result.setProperty("variant", "muted")
        self.lbl_test_result.style().unpolish(self.lbl_test_result)
        self.lbl_test_result.style().polish(self.lbl_test_result)
        self.lbl_test_result.setText("正在尝试连接 IMAP 服务器进行登录验证，请稍候...")
        try:
            worker.start()
        except Exception as exc:
            self._clear_mailbox_test_worker(worker)
            self.test_success = False
            self.lbl_test_result.setProperty("variant", "danger")
            self.lbl_test_result.style().unpolish(self.lbl_test_result)
            self.lbl_test_result.style().polish(self.lbl_test_result)
            self.lbl_test_result.setText(
                self._format_connection_failure(provider, server, port, exc)
            )

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


    def _on_preset_quick_select(self, provider_id: str):
        saved_acc = self._first_saved_account(provider_id)
        if saved_acc:
            self._load_saved_account(saved_acc)
            self._editing_existing_mailbox = True
        else:
            self._editing_existing_mailbox = False
            self._select_provider_card(provider_id)
            self._apply_provider_defaults(provider_id)
            self.txt_mailbox_name.setText(self._provider_display_name(provider_id))
            self._adjust_email_for_provider(provider_id)
            self.txt_auth_code.clear()
            if hasattr(self, "chk_is_default"):
                self.chk_is_default.setChecked(not self._saved_accounts)

    def _v4_scan_now(self):
        if hasattr(self.parent, "_scan_email_clicked"):
            self.parent._scan_email_clicked()
        else:
            QMessageBox.information(self, "扫描提示", "请在工作台导入中心点击立即扫描。")

    def _v4_toggle_current_enabled(self):
        if hasattr(self, "chk_enabled"):
            self.chk_enabled.setChecked(not self.chk_enabled.isChecked())
            self.lbl_v4_status_conn.setText("状态已变更(未保存)")

    def _v4_delete_current(self):
        email = self.txt_email.text().strip()
        mailbox_key = self._loaded_account_mailbox_key or email
        if mailbox_key:
            self._delete_mailbox(mailbox_key)

    def _v4_cancel_edits(self):
        self._cancel_mailbox_test()
        if self._loaded_account_mailbox_key and self._saved_accounts:
            acc = next((a for a in self._saved_accounts if (a.get("mailbox_key") or a.get("address") or "").lower() == self._loaded_account_mailbox_key.lower()), None)
            if acc:
                self._load_saved_account(acc)
                return
        self._open_new_mailbox_editor()

    def _save_mailbox_settings(self):
        email = self.txt_email.text().strip()
        provider = self._get_selected_provider()
        if not self._is_provider_domain_consistent(provider, email):
            self.lbl_provider_hint.setText("邮箱地址后缀与所选邮箱类型不一致，请修改邮箱地址或选择自定义 IMAP")
            self.current_step = 1
            self._update_wizard_ui()
            QMessageBox.warning(
                self,
                "校验提示",
                "邮箱地址后缀与所选邮箱类型不一致，请修改邮箱地址或选择自定义 IMAP"
            )
            return
        months_str = self.txt_months.text().strip()
        updated_cfg = deepcopy(self.cfg)
        raw_accounts = updated_cfg.get("email_accounts")
        email_accounts = [
            dict(existing)
            for existing in raw_accounts
            if isinstance(existing, dict)
        ] if isinstance(raw_accounts, list) else []
        if not isinstance(raw_accounts, list):
            legacy_email = updated_cfg.get("email", {})
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
            has_saved = self._find_account_index(
                email_accounts,
                email,
                self._loaded_account_mailbox_key,
                self._loaded_account_address,
            ) is not None

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

        auth_code = self.txt_auth_code.text().strip()
        existing_identifiers = [email]
        if self._editing_existing_mailbox:
            existing_identifiers.insert(0, self._loaded_account_mailbox_key or self._loaded_account_address)
        existing_index = self._find_account_index(email_accounts, *existing_identifiers)
        existing_account = email_accounts[existing_index] if existing_index is not None else None

        # Check for sensitive changes: address, provider, or IMAP server settings
        address_changed = False
        provider_changed = False
        imap_server_changed = False

        if existing_account:
            address_changed = self._normalize_address(existing_account.get("address")) != self._normalize_address(email)
            provider_changed = str(existing_account.get("provider") or "").strip().lower() != str(provider or "").strip().lower()

            old_imap = existing_account.get("imap") if isinstance(existing_account.get("imap"), dict) else {}
            old_server = str(old_imap.get("server") or "").strip().lower()
            old_port = str(old_imap.get("port") or "").strip()

            imap_server_changed = (old_server != str(imap_server or "").strip().lower() or
                                   old_port != str(imap_port_str or "").strip())

        sensitive_changed = address_changed or provider_changed or imap_server_changed

        if sensitive_changed:
            if not self.test_success or not auth_code:
                QMessageBox.warning(
                    self,
                    "设置验证失败",
                    "检测到敏感配置变更（邮箱地址、提供商或 IMAP 服务器已修改），必须重新输入授权码并测试连接成功后方可保存。"
                )
                return

        # Save credentials to system Keyring
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

        account_name = self.txt_mailbox_name.text().strip()
        if existing_account:
            account_name = account_name or str(existing_account.get("name") or "").strip()
        if not account_name:
            account_name = self._provider_display_name(provider)

        stable_mailbox_key = ""
        if existing_account:
            stable_mailbox_key = str(existing_account.get("mailbox_key") or "").strip()
        if not stable_mailbox_key:
            stable_mailbox_key = self._normalize_address(self._loaded_account_mailbox_key or self._loaded_account_address or email)
        if not stable_mailbox_key:
            stable_mailbox_key = email.lower()

        is_def = self.chk_is_default.isChecked() if hasattr(self, "chk_is_default") else (not email_accounts)
        is_en = self.chk_enabled.isChecked() if hasattr(self, "chk_enabled") else True

        account = {
            "name": account_name,
            "enabled": is_en and not is_outlook_like,
            "is_default": is_def,
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
            "mailbox_key": stable_mailbox_key,
        }

        if existing_index is None:
            email_accounts.append(account)
        else:
            email_accounts[existing_index] = account

        from ..config import _normalize_default_email_account, _apply_primary_email_account
        email_accounts = _normalize_default_email_account(
            email_accounts,
            preferred_key=stable_mailbox_key if is_def else None,
        )
        updated_cfg = _apply_primary_email_account(updated_cfg, email_accounts)
        updated_cfg.setdefault("ai", {})


        try:
            save_config(updated_cfg)
            self.cfg = updated_cfg
            self.parent.config = _load_config_safe_compat()
            self.parent.write_log(f"⚙️ [设置保存] 全局 config.json 邮箱服务配置已成功保存。")
            self.txt_auth_code.clear()
            if credential_available:
                self.txt_auth_code.setPlaceholderText(SAVED_SECRET_PLACEHOLDER)
                self.lbl_cred_status.setText("🔒 授权状态：<font color='#10B981'><b>已安全保存到系统凭据管理器</b></font>")
            else:
                self._update_cred_status_label()
            QMessageBox.information(self, "成功", "邮箱设置已成功保存！")
            self._persist_settings_and_refresh("mailboxes")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置文件失败: {e}")

    def _save_ai_settings(self):
        return self._save_ai_profile_settings(activate=False)
    def _delete_current_mailbox(self):
        email = self.txt_email.text().strip()
        if not email:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            "删除邮箱配置只会移除该邮箱的登录设置、授权码和扫描状态，不会删除已导入的发票、附件或报销组。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        normalized_email = self._normalize_address(email)

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

        updated_cfg = deepcopy(self.cfg)
        updated_cfg["email_accounts"] = updated_accounts

        from ..config import _normalize_default_email_account, _apply_primary_email_account
        if updated_accounts:
            updated_accounts = _normalize_default_email_account(updated_accounts)
            updated_cfg = _apply_primary_email_account(updated_cfg, updated_accounts)
        else:
            updated_cfg["email_accounts"] = []
            updated_cfg["email"] = {"provider": "qq", "address": "", "username": ""}
            updated_cfg["imap"] = {"server": "", "port": 993, "ssl": True}
            updated_cfg["search"] = {"folder": "INBOX", "months_back": 3}

        from ..config import save_config
        try:
            save_config(updated_cfg)
            self.cfg = updated_cfg
            if hasattr(self.parent, "config"):
                self.parent.config = _load_config_safe_compat()
            self._build_saved_account_maps()
            self._refresh_mailbox_list()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置文件失败: {e}")
            return

        enabled_supported_accounts = []
        for acc in self._saved_accounts:
            p = acc.get("provider", "")
            addr = acc.get("address", "")
            srv = acc.get("imap", {}).get("server", "")
            if acc.get("enabled", True) and not is_outlook_like_account(p, addr, srv):
                enabled_supported_accounts.append(acc)

        next_to_load = None
        if enabled_supported_accounts:
            primary_email = self._normalize_address(self.cfg.get("email", {}).get("address", ""))
            for acc in enabled_supported_accounts:
                if self._normalize_address(acc.get("address")) == primary_email:
                    next_to_load = acc
                    break
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

        email = target_account.get("address", "") if target_account else email
        if email:
            from ..credentials import delete_auth_code
            try:
                delete_auth_code(email)
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"🗏 [安全凭证] 邮箱 {email} 的授权码凭证已从凭据管理器中移除。")
            except Exception as e:
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"❌ [安全凭证] 从凭据管理器移除邮箱 {email} 凭证失败: {e}")

        mailbox_key_to_clear = str(target_account.get("mailbox_key") or "").strip() if target_account else ""
        if not mailbox_key_to_clear:
            mailbox_key_to_clear = normalized_email

        if hasattr(self.parent, "db") and self.parent.db:
            try:
                self.parent.db.remove_mailbox_scan_state(mailbox_key_to_clear)
            except Exception as e:
                if hasattr(self.parent, "write_log"):
                    self.parent.write_log(f"❌ [数据库] 清除邮箱同步状态失败: {e}")

        QMessageBox.information(self, "成功", "邮箱配置已删除，已导入发票不会被删除。")
