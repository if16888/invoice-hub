# -*- coding: utf-8 -*-
"""Invoice Hub mailbox and AI settings dialog."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from ..config import load_config_safe


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

        from ..config import _EMAIL_PROVIDER_PRESETS
        self.cfg = _load_config_safe_compat()

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
            ("outlook", "Outlook", "微软官方邮箱\n支持商务与个人"),
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

        # Form layout for input fields
        form_group = QGroupBox("邮箱基本配置")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(10)

        self.txt_email = QLineEdit()
        self.txt_email.setPlaceholderText("your_email@example.com")
        self.txt_email.textChanged.connect(self._on_email_text_changed)

        self.txt_months = QLineEdit("3")
        self.txt_months.setPlaceholderText("1-24")

        form_layout.addRow("邮箱地址:", self.txt_email)
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
        adv_layout.addRow("IMAP 服务器:", self.txt_imap_server)
        adv_layout.addRow("IMAP 端口:", self.txt_imap_port)
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

        # Form fields
        form = QFormLayout()
        form.setSpacing(12)

        auth_input_layout = QHBoxLayout()
        self.txt_auth_code = QLineEdit()
        self.txt_auth_code.setEchoMode(QLineEdit.Password)
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
        self.txt_ai_key = QLineEdit()
        self.txt_ai_key.setEchoMode(QLineEdit.Password)

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
        # Email settings
        current_provider = self.cfg.get("email", {}).get("provider", "qq")
        self._select_provider_card(current_provider)

        self.txt_email.setText(self.cfg.get("email", {}).get("address", ""))
        self.txt_months.setText(str(self.cfg.get("search", {}).get("months_back", 3)))

        if current_provider == "custom":
            self.advanced_group.setVisible(True)
            self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲")
            self.txt_imap_server.setText(self.cfg.get("imap", {}).get("server", ""))
            self.txt_imap_port.setText(str(self.cfg.get("imap", {}).get("port", 993)))
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(current_provider, _EMAIL_PROVIDER_PRESETS["qq"])
            self.txt_imap_server.setText(preset["server"])
            self.txt_imap_port.setText(str(preset["port"]))

        # AI settings
        ai_prov = self.cfg.get("ai", {}).get("provider", "none")
        self.combo_ai_provider.setCurrentText(ai_prov)
        saved_model = self.cfg.get("ai", {}).get("model", "")
        if saved_model:
            self.txt_ai_model.setCurrentText(saved_model)

        self._update_cred_status_label()

    def _get_selected_provider(self):
        for prov_id, card in self.cards.items():
            if card.isChecked():
                return prov_id
        return "qq"

    def _select_provider_card(self, provider):
        if provider in self.cards:
            self.cards[provider].setChecked(True)
            self._refresh_provider_card_visuals()

    def _refresh_provider_card_visuals(self):
        for provider, title_label in self.card_titles.items():
            title_label.setProperty("selected", self.cards[provider].isChecked())
            title_label.style().unpolish(title_label)
            title_label.style().polish(title_label)

    def _on_provider_card_clicked(self, checked_btn):
        self._refresh_provider_card_visuals()
        provider = self._get_selected_provider()
        if provider == "custom":
            self.advanced_group.setVisible(True)
            self.btn_toggle_advanced.setText("隐藏高级 IMAP 设置 ▲")
        else:
            self.advanced_group.setVisible(False)
            self.btn_toggle_advanced.setText("显示高级 IMAP 设置 ▼")
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider)
            if preset:
                self.txt_imap_server.setText(preset["server"])
                self.txt_imap_port.setText(str(preset["port"]))

    def _update_cred_status_label(self):
        from ..credentials import has_auth_code
        email = self.txt_email.text().strip()
        if not email:
            self.lbl_cred_status.setText("🔒 授权码状态：<b>未输入邮箱地址</b>")
            return
        if has_auth_code(email):
            self.lbl_cred_status.setText("🔒 授权码状态：<font color='#10B981'><b>已安全保存到系统凭据管理器</b></font>")
        else:
            self.lbl_cred_status.setText("🔒 授权码状态：<font color='#EF4444'><b>尚未配置 (点击下一步并保存时将自动加密保存)</b></font>")

    def _on_email_text_changed(self):
        email = self.txt_email.text().strip().lower()
        if "@qq.com" in email:
            self._select_provider_card("qq")
        elif "@163.com" in email:
            self._select_provider_card("netease_163")
        elif "@126.com" in email:
            self._select_provider_card("netease_126")
        elif "@gmail.com" in email:
            self._select_provider_card("gmail")
        elif "@outlook.com" in email or "@hotmail.com" in email or "@live.com" in email:
            self._select_provider_card("outlook")
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
            self.txt_ai_key.setPlaceholderText("••••••••••••••••")
        else:
            self.lbl_ai_key_status.setText(
                "🔑 API Key 状态：<font color='#EF4444'><b>尚未配置</b></font>"
            )
            self.txt_ai_key.setPlaceholderText("请输入 API Key")

    def _show_auth_code_help(self):
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
            "• <b>Outlook / Hotmail 邮箱：</b><br>"
            "  1. 登录网页版微软账号中心 (account.microsoft.com)。<br>"
            "  2. 进入「安全性」 ➜ 「高级安全选项」。<br>"
            "  3. 开启「双重验证」后，在下方生成「应用密码」进行登录。<br><br>"
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
            err_msg = str(e).lower()
            if "login failed" in err_msg or "authentication failed" in err_msg or "credential" in err_msg or "invalid credentials" in err_msg or "authori" in err_msg or "登录失败" in err_msg:
                friendly = "❌ 测试连接失败：授权码错误或 IMAP 服务未开启"
            elif "getaddrinfo" in err_msg or "timed out" in err_msg or "timeout" in err_msg or "connection timed out" in err_msg:
                friendly = "❌ 测试连接失败：网络连接失败"
            elif "refused" in err_msg or "connection refused" in err_msg or "wrong port" in err_msg or "socket" in err_msg or "ssl" in err_msg:
                friendly = "❌ 测试连接失败：IMAP服务器/端口配置有误"
            elif "未找到授权码" in err_msg:
                friendly = "❌ 测试连接失败：未找到授权码"
            else:
                friendly = "❌ 测试连接失败：授权码错误或 IMAP 未开启；或网络、服务器、端口配置有误。"
            self.lbl_test_result.setText(friendly)
        finally:
            self.btn_test.setEnabled(True)
            self.btn_test.setText("测试连接")
            QApplication.restoreOverrideCursor()

    def _save_mailbox_settings(self):
        email = self.txt_email.text().strip()
        provider = self._get_selected_provider()
        months_str = self.txt_months.text().strip()

        if provider == "custom":
            imap_server = self.txt_imap_server.text().strip()
            imap_port_str = self.txt_imap_port.text().strip()
        else:
            from ..config import _EMAIL_PROVIDER_PRESETS
            preset = _EMAIL_PROVIDER_PRESETS.get(provider)
            imap_server = preset["server"]
            imap_port_str = str(preset["port"])

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
        if auth_code:
            from ..credentials import set_auth_code
            try:
                set_auth_code(email, auth_code)
                self.parent.write_log(f"💾 [安全凭证] 邮箱 {email} 的授权码凭证已自动保存到 Windows 凭据管理器中。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存凭据失败: {e}")
                return

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
            "enabled": True,
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
            "mailbox_key": email.lower(),
        }
        raw_accounts = self.cfg.get("email_accounts")
        email_accounts = [
            dict(existing)
            for existing in raw_accounts
            if isinstance(existing, dict)
        ] if isinstance(raw_accounts, list) else []
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
            email_accounts.append(account)
        else:
            email_accounts[match_index] = account
        self.cfg["email_accounts"] = email_accounts

        try:
            save_config(self.cfg)
            self.parent.config = _load_config_safe_compat()
            self.parent.write_log(f"⚙️ [设置保存] 全局 config.json 邮箱服务配置已成功保存。")
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
            self.parent.config = _load_config_safe_compat()
            self.parent.write_log(f"⚙️ [设置保存] 全局 config.json AI 辅助分类配置已成功保存。")
            QMessageBox.information(self, "成功", "AI 分类配置已成功保存！")
            self._on_ai_provider_changed()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存 AI 配置文件失败: {e}")
