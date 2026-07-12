"""Migrate the remaining Settings pages to Design Baseline v1.0.

Mailbox Accounts is the Golden Page.  This module applies the same information
ownership, one-surface hierarchy, field grid, and contextual footer to AI,
runtime, privacy, data/backup, and About without changing their business logic.
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
SELECTED = "#EFF6FF"
BORDER = "#E5E7EB"
TEXT = "#182230"
MUTED = "#667085"
ACCENT = "#2563EB"
SUCCESS = "#16803C"
WARNING = "#B54708"
DANGER = "#B42318"

_FIELD_LABEL_WIDTH = 104
_DETAIL_MIN_WIDTH = 560
_DETAIL_MAX_WIDTH = 760
_PROFILE_LIST_WIDTH = 240


class StructuredSettingsSurface(QFrame):
    """One outer settings surface that also accepts legacy ``setText`` updates."""

    def __init__(
        self,
        title: str,
        hint: str,
        fields: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsDetailSurface")
        self.setProperty("class", "SettingsDetailSurface")
        self.setMinimumWidth(_DETAIL_MIN_WIDTH)
        self.setMaximumWidth(_DETAIL_MAX_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._raw_text = ""
        self._field_order = [key for key, _default in fields]
        self.values: dict[str, ElidedTextLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)

        title_label = QLabel(title, self)
        title_label.setProperty("class", "SettingsSurfaceTitle")
        layout.addWidget(title_label)
        hint_label = QLabel(hint, self)
        hint_label.setProperty("class", "SettingsSurfaceHint")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
        layout.addWidget(_divider(self))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for key, default in fields:
            value = ElidedTextLabel(default, self)
            value.setProperty("class", "SettingsFieldValue")
            value.setToolTip("" if default in {"", "—"} else default)
            value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self.values[key] = value
            form.addRow(key, value)
            label = form.labelForField(value)
            if label is not None:
                label.setFixedWidth(_FIELD_LABEL_WIDTH)
                label.setProperty("class", "SettingsFieldKey")
        layout.addLayout(form)

        self.inline_status = QLabel("", self)
        self.inline_status.setObjectName("SettingsInlineStatus")
        self.inline_status.setProperty("class", "SettingsInlineStatus")
        self.inline_status.setWordWrap(True)
        self.inline_status.setVisible(False)
        layout.addWidget(self.inline_status)

        self.footer_divider = _divider(self)
        self.footer_divider.setVisible(False)
        layout.addWidget(self.footer_divider)
        self.footer = QFrame(self)
        self.footer.setObjectName("SettingsActionFooter")
        self.footer.setMinimumHeight(52)
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(0, 4, 0, 0)
        self.footer_layout.setSpacing(8)
        self.footer.setVisible(False)
        layout.addWidget(self.footer)

    def setText(self, text: str) -> None:  # compatibility with the old QLabel API
        self._raw_text = str(text or "")
        parsed: dict[str, str] = {}
        free_lines: list[str] = []
        for line in self._raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "：" in line:
                key, value = line.split("：", 1)
                parsed[key.strip()] = value.strip() or "—"
            else:
                free_lines.append(line)

        for key in self._field_order:
            if key in parsed:
                self.set_value(key, parsed[key])

        if free_lines:
            remaining = [key for key in self._field_order if key not in parsed]
            if remaining:
                self.set_value(remaining[0], " · ".join(free_lines))

    def text(self) -> str:
        return self._raw_text

    def set_value(self, key: str, value: str) -> None:
        label = self.values.get(key)
        if label is None:
            return
        text = str(value or "—")
        label.setText(text)
        label.setToolTip("" if text in {"", "—"} else text)

    def set_status(self, text: str, *, tone: str = "muted") -> None:
        text = str(text or "").strip()
        self.inline_status.setText(text)
        self.inline_status.setProperty("tone", tone)
        self.inline_status.setVisible(bool(text))
        _repolish(self.inline_status)

    def set_actions(self, actions: list[QWidget]) -> None:
        while self.footer_layout.count():
            item = self.footer_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        for action in actions:
            action.setParent(self.footer)
            self.footer_layout.addWidget(action)
        self.footer_layout.addStretch(1)
        visible = bool(actions)
        self.footer_divider.setVisible(visible)
        self.footer.setVisible(visible)


def _divider(parent: QWidget) -> QFrame:
    divider = QFrame(parent)
    divider.setProperty("class", "SettingsSectionDivider")
    divider.setFrameShape(QFrame.HLine)
    divider.setFixedHeight(1)
    return divider


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _clear_layout(layout, preserve: set[QWidget] | None = None) -> None:
    preserve = preserve or set()
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        widget = item.widget()
        if child_layout is not None:
            _clear_layout(child_layout, preserve)
            child_layout.deleteLater()
        elif widget is not None:
            if widget in preserve:
                widget.setParent(None)
            else:
                widget.deleteLater()


def _subpage_header(title: str, hint: str, parent: QWidget) -> QWidget:
    header = QFrame(parent)
    header.setObjectName("SettingsSubpageHeader")
    layout = QVBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    lbl_title = QLabel(title, header)
    lbl_title.setProperty("class", "SettingsSubpageTitle")
    lbl_hint = QLabel(hint, header)
    lbl_hint.setProperty("class", "SettingsSubpageHint")
    lbl_hint.setWordWrap(True)
    layout.addWidget(lbl_title)
    layout.addWidget(lbl_hint)
    return header


def _collect_actions(page: QWidget) -> list[QWidget]:
    actions: list[QWidget] = []
    for widget in page.findChildren((QPushButton, QToolButton)):
        if widget.parentWidget() is None:
            continue
        if widget.objectName() == "WorkbenchTopIconButton" or isinstance(widget, QPushButton):
            if widget not in actions:
                actions.append(widget)
    return actions


def _migrate_info_page(
    window,
    index: int,
    title: str,
    hint: str,
    attr_name: str,
    fields: list[tuple[str, str]],
) -> None:
    page = window.settings_tabs.widget(index)
    if page is None or page.property("settingsBaselineMigrated"):
        return

    page.setProperty("settingsBaselineMigrated", True)
    old_source = getattr(window, attr_name, None)
    actions = _collect_actions(page)
    preserve = set(actions)
    layout = page.layout()
    if layout is None:
        layout = QVBoxLayout(page)
    _clear_layout(layout, preserve)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    layout.setAlignment(Qt.AlignTop)

    layout.addWidget(_subpage_header(title, hint, page))
    surface = StructuredSettingsSurface(title, hint, fields, page)
    if old_source is not None and hasattr(old_source, "text"):
        surface.setText(old_source.text())
    surface.set_actions(actions)
    layout.addWidget(surface, 0, Qt.AlignTop)
    layout.addStretch(1)
    setattr(window, attr_name, surface)
    setattr(window, f"{attr_name}_surface", surface)


def _detach(widget: QWidget | None) -> None:
    if widget is not None:
        widget.setParent(None)


def _add_section(layout: QVBoxLayout, parent: QWidget, title: str, rows: list[tuple[str, QWidget]]) -> None:
    if layout.count():
        layout.addWidget(_divider(parent))
    heading = QLabel(title, parent)
    heading.setProperty("class", "SettingsSectionTitle")
    layout.addWidget(heading)
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    for key, value in rows:
        value.setParent(parent)
        value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        form.addRow(key, value)
        label = form.labelForField(value)
        if label is not None:
            label.setFixedWidth(_FIELD_LABEL_WIDTH)
            label.setProperty("class", "SettingsFieldKey")
    layout.addLayout(form)


def _migrate_ai_page(window) -> None:
    page = window.settings_tabs.widget(1)
    if page is None or page.property("settingsBaselineMigrated"):
        return
    page.setProperty("settingsBaselineMigrated", True)

    profile_list = window.settings_ai_profile_list
    empty_state = window.settings_ai_empty_state
    fields = [
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
    preserve = {profile_list, empty_state, *fields, *actions}
    for widget in preserve:
        _detach(widget)

    layout = page.layout()
    if layout is None:
        layout = QVBoxLayout(page)
    _clear_layout(layout, preserve)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    layout.setAlignment(Qt.AlignTop)
    layout.addWidget(_subpage_header("AI 配置", "使用 AI 辅助分类和字段核验；凭据与数据边界保持可见。", page))

    shell = QHBoxLayout()
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(16)
    shell.setAlignment(Qt.AlignTop)
    profile_list.setFixedWidth(_PROFILE_LIST_WIDTH)
    profile_list.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
    shell.addWidget(profile_list, 0, Qt.AlignTop)

    surface = QFrame(page)
    surface.setObjectName("AISettingsDetailSurface")
    surface.setProperty("class", "SettingsDetailSurface")
    surface.setMinimumWidth(_DETAIL_MIN_WIDTH)
    surface.setMaximumWidth(_DETAIL_MAX_WIDTH)
    surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    surface_layout = QVBoxLayout(surface)
    surface_layout.setContentsMargins(20, 18, 20, 14)
    surface_layout.setSpacing(12)

    header_row = QHBoxLayout()
    header_row.setContentsMargins(0, 0, 0, 0)
    header_row.setSpacing(8)
    title = QLabel("AI 服务", surface)
    title.setProperty("class", "SettingsSurfaceTitle")
    status_badge = QLabel("未配置", surface)
    status_badge.setObjectName("AISettingsStatusBadge")
    status_badge.setProperty("class", "SettingsStatusBadge")
    status_badge.setAlignment(Qt.AlignCenter)
    status_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    header_row.addWidget(title)
    header_row.addStretch(1)
    header_row.addWidget(status_badge)
    surface_layout.addLayout(header_row)

    credential_store = ElidedTextLabel("Windows 凭据管理器", surface)
    credential_store.setToolTip("Windows 凭据管理器")
    window.lbl_settings_ai_credential_store = credential_store

    _add_section(
        surface_layout,
        surface,
        "当前配置",
        [
            ("Provider", window.lbl_settings_ai_provider),
            ("模型", window.lbl_settings_ai_model),
            ("AI 状态", window.lbl_settings_ai_enabled),
            ("API Key", window.lbl_settings_ai_key_status),
            ("会话状态", window.lbl_settings_ai_session_state),
            ("最近校验", window.lbl_settings_ai_validation_status),
            ("凭据存储", credential_store),
        ],
    )
    _add_section(
        surface_layout,
        surface,
        "隐私边界",
        [
            ("发送内容", window.lbl_settings_ai_send_boundary),
            ("本地保护", window.lbl_settings_ai_log_redaction),
        ],
    )

    window.lbl_settings_ai_failure_status.setProperty("class", "SettingsInlineStatus")
    window.lbl_settings_ai_failure_status.setParent(surface)
    surface_layout.addWidget(window.lbl_settings_ai_failure_status)
    surface_layout.addWidget(_divider(surface))

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
    surface_layout.addWidget(footer)

    shell.addWidget(surface, 1, Qt.AlignTop)
    shell.addStretch(1)
    layout.addLayout(shell)

    empty_action = make_button("配置 AI", variant="primary", min_width=120)
    empty_action.setAccessibleName("配置 AI")
    empty_action.clicked.connect(window._open_edit_ai_profile_dialog)
    empty_state.set_action(empty_action)
    empty_state.setMaximumWidth(520)
    empty_state.setMaximumHeight(190)
    layout.addWidget(empty_state, 0, Qt.AlignTop)
    layout.addStretch(1)

    window.settings_ai_detail_panel = surface
    window.lbl_settings_ai_status_badge = status_badge
    window.btn_settings_ai_empty_add = empty_action


def _normalize_ai_surface(window) -> None:
    if not hasattr(window, "lbl_settings_ai_status_badge"):
        return

    enabled = window.lbl_settings_ai_enabled.text().strip() in {"开启", "已启用"}
    paused = "暂停" in window.lbl_settings_ai_session_state.text()
    key_text = window.lbl_settings_ai_key_status.text().strip()
    if "未配置" in key_text or key_text in {"", "—"}:
        key_value = "未配置"
    else:
        key_value = "已安全保存"
    window.lbl_settings_ai_key_status.setText(key_value)
    window.lbl_settings_ai_key_status.setToolTip("API Key 保存于 Windows 凭据管理器")

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
    for prefix in ("失败状态：", "状态："):
        if failure.startswith(prefix):
            failure = failure[len(prefix):].strip()
    window.lbl_settings_ai_failure_status.setText(failure)
    window.lbl_settings_ai_failure_status.setVisible(bool(failure and failure not in {"暂无异常。", "暂无异常"}))

    profile_count = window.settings_ai_profile_list.count()
    window.settings_ai_profile_list.setVisible(profile_count > 1)
    window.settings_ai_detail_panel.setVisible(profile_count > 0)
    window.settings_ai_empty_state.setVisible(profile_count == 0)


def _install_refresh_contract(window, page: QWidget) -> None:
    if page.property("settingsRemainingRefreshContractInstalled"):
        return
    page.setProperty("settingsRemainingRefreshContractInstalled", True)

    original_refresh = window._refresh_settings_page

    @wraps(original_refresh)
    def refresh_settings_page(*args, **kwargs):
        result = original_refresh(*args, **kwargs)
        QTimer.singleShot(0, lambda: _normalize_ai_surface(window))
        return result

    window._refresh_settings_page = refresh_settings_page
    window.settings_ai_profile_list.currentRowChanged.connect(
        lambda _row: QTimer.singleShot(0, lambda: _normalize_ai_surface(window))
    )
    for button in (
        window.btn_settings_ai_test,
        window.btn_settings_ai_edit,
        window.btn_settings_ai_configure_key,
        window.settings_ai_more,
    ):
        button.clicked.connect(lambda _checked=False: QTimer.singleShot(0, lambda: _normalize_ai_surface(window)))


def _install_styles(settings_tabs: QWidget) -> None:
    existing = settings_tabs.styleSheet()
    settings_tabs.setStyleSheet(
        existing
        + f"""
        QFrame#SettingsSubpageHeader {{ background: transparent; border: none; }}
        QLabel[class="SettingsSubpageTitle"] {{ color: {TEXT}; font-size: 15px; font-weight: 600; }}
        QLabel[class="SettingsSubpageHint"] {{ color: {MUTED}; font-size: 12px; font-weight: 400; }}
        QFrame[class="SettingsDetailSurface"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
        QLabel[class="SettingsSurfaceTitle"] {{ color: {TEXT}; font-size: 16px; font-weight: 600; }}
        QLabel[class="SettingsSurfaceHint"] {{ color: {MUTED}; font-size: 12px; font-weight: 400; }}
        QLabel[class="SettingsSectionTitle"] {{ color: {TEXT}; font-size: 14px; font-weight: 600; }}
        QLabel[class="SettingsFieldKey"] {{ color: {MUTED}; font-size: 12px; font-weight: 500; }}
        QLabel[class="SettingsFieldValue"] {{ color: {TEXT}; font-size: 13px; font-weight: 400; }}
        QFrame[class="SettingsSectionDivider"] {{ background: {BORDER}; border: none; min-height: 1px; max-height: 1px; }}
        QFrame#SettingsActionFooter {{ background: transparent; border: none; }}
        QLabel[class="SettingsInlineStatus"] {{ color: {MUTED}; background: {SURFACE_SECONDARY}; border-radius: 6px; padding: 8px 10px; }}
        QLabel#AISettingsStatusBadge {{ border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 600; }}
        QLabel#AISettingsStatusBadge[tone="success"] {{ color: {SUCCESS}; background: #ECFDF3; }}
        QLabel#AISettingsStatusBadge[tone="warning"] {{ color: {WARNING}; background: #FFFAEB; }}
        QLabel#AISettingsStatusBadge[tone="muted"] {{ color: {MUTED}; background: #F2F4F7; }}
        """
    )


def apply_remaining_settings_baseline(page: QWidget) -> None:
    """Apply Golden Page hierarchy to every Settings subpage after Mailbox."""
    if page is None or page.property("remainingSettingsBaselineApplied"):
        return
    window = page.window()
    if not hasattr(window, "settings_tabs") or window.settings_tabs.count() < 6:
        return
    page.setProperty("remainingSettingsBaselineApplied", True)

    _install_styles(window.settings_tabs)
    _migrate_ai_page(window)
    _migrate_info_page(
        window,
        2,
        "运行状态",
        "查看本地数据库、日志、最近扫描和错误状态。",
        "lbl_settings_runtime",
        [("数据库", "—"), ("日志目录", "—"), ("最近扫描", "暂无记录"), ("最近错误", "无")],
    )
    _migrate_info_page(
        window,
        3,
        "安全与隐私",
        "默认本地处理；凭据、日志和诊断包遵循最小披露原则。",
        "lbl_settings_privacy",
        [
            ("处理方式", "本地处理"),
            ("凭据存储", "Windows 凭据管理器"),
            ("配置与日志", "仅保留脱敏内容"),
            ("诊断包", "仅导出白名单与脱敏信息"),
        ],
    )
    _migrate_info_page(
        window,
        4,
        "数据与备份",
        "查看本地数据、备份和导出位置；页面不展示技术日志。",
        "lbl_settings_data",
        [("数据库大小", "—"), ("数据目录", "—"), ("备份目录", "—"), ("导出目录", "—")],
    )
    _migrate_info_page(
        window,
        5,
        "关于",
        "Invoice Hub 是本地优先的个人报销工作台。",
        "lbl_settings_about",
        [("产品", "Invoice Hub"), ("版本与构建", "—"), ("产品定位", "本地优先的个人报销工作台")],
    )
    _install_refresh_contract(window, page)
    window._refresh_settings_page()
    QTimer.singleShot(0, lambda: _normalize_ai_surface(window))


__all__ = ["StructuredSettingsSurface", "apply_remaining_settings_baseline"]
