"""Design Baseline v1.0 migration for Settings pages after Mailbox Accounts.

The module changes presentation only. Existing buttons keep their signal
connections and the app's refresh methods continue to own data.
"""

from __future__ import annotations

from functools import wraps

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .ui_components import ElidedTextLabel, make_button

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
        self.values: dict[str, ElidedTextLabel] = {}

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
            value = ElidedTextLabel(default, self)
            value.setProperty("class", "SettingsFieldValue")
            value.setToolTip("" if default in {"", "—"} else default)
            value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
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
        self.footer_layout = QHBoxLayout(self.footer)
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
        for action in actions:
            action.setParent(self.footer)
            self.footer_layout.addWidget(action)
        self.footer_layout.addStretch(1)
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
        value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
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
    profile_list.setFixedWidth(PROFILE_LIST_WIDTH)
    profile_list.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
    shell.addWidget(profile_list, 0, Qt.AlignTop)

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
    root.addWidget(window.lbl_settings_ai_failure_status)
    root.addWidget(_divider(surface))
    footer = QFrame(surface)
    footer.setObjectName("SettingsActionFooter")
    footer.setMinimumHeight(52)
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(0, 4, 0, 0)
    footer_layout.setSpacing(8)
    for action in actions:
        action.setParent(footer)
        footer_layout.addWidget(action)
    footer_layout.addStretch(1)
    root.addWidget(footer)
    shell.addWidget(surface, 1, Qt.AlignTop)
    shell.addStretch(1)
    layout.addLayout(shell)

    empty_action = make_button("配置 AI", variant="primary", min_width=120)
    empty_action.clicked.connect(window._open_edit_ai_profile_dialog)
    empty_state.set_action(empty_action)
    empty_state.setMaximumWidth(520)
    empty_state.setMaximumHeight(190)
    layout.addWidget(empty_state, 0, Qt.AlignTop)
    layout.addStretch(1)
    window.settings_ai_detail_panel = surface
    window.lbl_settings_ai_status_badge = badge
    window.btn_settings_ai_empty_add = empty_action
    summary = getattr(window, "settings_ai_summary_strip", None)
    if summary is not None:
        summary.hide()


def _normalize_ai(window) -> None:
    if not hasattr(window, "lbl_settings_ai_status_badge"):
        return
    key_text = window.lbl_settings_ai_key_status.text().strip()
    window.lbl_settings_ai_key_status.setText("未配置" if "未配置" in key_text or key_text in {"", "—"} else "已安全保存")
    window.lbl_settings_ai_key_status.setToolTip("API Key 保存于 Windows 凭据管理器")
    enabled = window.lbl_settings_ai_enabled.text().strip() in {"开启", "已启用"}
    paused = "暂停" in window.lbl_settings_ai_session_state.text()
    if not enabled:
        status, tone = "已禁用", "muted"
    elif paused:
        status, tone = "已暂停", "warning"
    else:
        status, tone = "正常", "success"
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
    _migrate_info_page(window, 4, "数据与备份", "查看本地数据、备份和导出位置；页面不展示技术日志。", "lbl_settings_data", [
        ("数据库大小", "—"), ("数据目录", "—"), ("备份目录", "—"), ("导出目录", "—")])
    _migrate_info_page(window, 5, "关于", "Invoice Hub 是本地优先的个人报销工作台。", "lbl_settings_about", [
        ("产品", "Invoice Hub"), ("版本与构建", "—"), ("产品定位", "本地优先的个人报销工作台")])
    _install_refresh_contract(window, page)
    window._refresh_settings_page()
    QTimer.singleShot(0, lambda: _normalize_ai(window))


__all__ = ["StructuredSettingsSurface", "apply_remaining_settings_baseline"]
