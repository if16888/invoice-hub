"""Reusable common-settings surface for high-frequency local preferences."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .ui_components import ReadOnlyDetailPanel, make_button


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
        self.profile_panel.body_layout.addWidget(self.btn_profile_edit)
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
        self.mailbox_panel.body_layout.addWidget(self.btn_mailbox_manage)
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


__all__ = ["CommonSettingsPage"]
