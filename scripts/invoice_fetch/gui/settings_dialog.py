# -*- coding: utf-8 -*-
"""Invoice Hub mailbox and AI settings dialog."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFormLayout, QFrame,
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


class SettingsDialog(QDialog):
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

        from ..config import _EMAIL_PROVIDER_PRESETS
        self.cfg = _load_config_safe_compat()
        self._build_saved_account_maps()

        # Tab Widget to isolate Mailbox setup from AI Setup
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)

        self.tab_widget = QTabWidget()
        self.main_layout.addWidget(self.tab_widget)

        # Tab 1: Mailbox Setup Wizard
        self.tab_mailbox = QWidget()
        self._init_mailbox_wizard_tab()
        self.tab_widget.addTab(self.tab_mailbox, "邮箱服务配置")

        # Tab 2: AI Setup Configuration
        self.tab_ai = QWidget()
        self._init_ai_tab()
        self.tab_widget.addTab(self.tab_ai, "AI 辅助分类")

        # Load initial values
        self._load_initial_values()
        self._loading_initial_values = False
        self._advanced_settings_dirty = False
        self._update_provider_hint()

    def _init_mailbox_wizard_tab(self):
        layout = QVBoxLayout(self.tab_mailbox)
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
        self.btn_cancel_wizard.clicked.connect(self.reject)
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
        self.txt_imap_server.textChanged.connect(self._mark_advanced_settings_dirty)
        self.txt_imap_port.textChanged.connect(self._mark_advanced_settings_dirty)
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

    def _init_ai_tab(self):
        layout = QVBoxLayout(self.tab_ai)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Config box
        ai_box = QGroupBox("AI 辅助分类配置")
        ai_form = QFormLayout(ai_box)
        ai_form.setSpacing(12)

        self.combo_ai_provider = QComboBox()
        self.combo_ai_provider.addItems(["none", "deepseek", "gemini"])
        self.combo_ai_provider.currentTextChanged.connect(self._on_ai_provider_changed)

        self.txt_ai_model = QComboBox()
        self.txt_ai_model.setEditable(True)
        self.txt_ai_model.lineEdit().setPlaceholderText("请选择或输入模型名称")

        self.lbl_ai_key_status = QLabel()
        self.lbl_ai_key_status.setWordWrap(True)
        self.lbl_ai_key_status.setStyleSheet("font-size: 11px;")

        self.lbl_ai_key_title = QLabel("API Key:")
        self.txt_ai_key = SecurePasswordLineEdit()

        ai_form.addRow("AI 分类提供商:", self.combo_ai_provider)
        ai_form.addRow("模型名称:", self.txt_ai_model)
        ai_form.addRow(self.lbl_ai_key_status)
        ai_form.addRow(self.lbl_ai_key_title, self.txt_ai_key)

        lbl_ai_note = QLabel(
            "提示：不配置 AI 也可以正常导入和审核发票（AI 默认关闭）。\n"
            "建议：发票邮件分类推荐使用便宜且快速的模型（例如 deepseek-v4-flash 或 gemini-2.5-flash）。\n"
            "隐私提示：显式启用 AI 时，仅发送脱敏后的邮件主题和发件人；默认不上传发票附件、PDF 文本或生成的 Excel 报表。"
        )
        lbl_ai_note.setStyleSheet("color: #6B7280; font-size: 11px;")
        lbl_ai_note.setWordWrap(True)
        ai_form.addRow(lbl_ai_note)

        layout.addWidget(ai_box)
        layout.addStretch()

        # Dedicated AI Save button
        ai_footer = QHBoxLayout()
        btn_save_ai = QPushButton("保存 AI 配置")
        btn_save_ai.clicked.connect(self._save_ai_settings)
        btn_save_ai.setProperty("class", "PrimaryBtn")
        btn_save_ai.setFixedHeight(28)

        btn_cancel_ai = QPushButton("取消")
        btn_cancel_ai.clicked.connect(self.reject)
        btn_cancel_ai.setProperty("class", "SecondaryBtn")
        btn_cancel_ai.setFixedHeight(28)

        ai_footer.addStretch()
        ai_footer.addWidget(btn_save_ai)
        ai_footer.addWidget(btn_cancel_ai)
        layout.addLayout(ai_footer)

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

    def _mark_advanced_settings_dirty(self, *_args):
        if not self._loading_initial_values and not self._applying_provider_defaults:
            self._advanced_settings_dirty = True

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
