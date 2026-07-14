"""Local company tax profile used for invoice issuance and buyer checks."""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..config import save_config
from ..reimbursement import buyer_warning, normalize_tax_id
from .ui_components import make_button


_PROFILE_DEFAULTS = {
    "buyer_name": "",
    "buyer_tax_id": "",
    "registered_address": "",
    "registered_phone": "",
    "bank_name": "",
    "bank_account": "",
    "strict_buyer_check": False,
    "strict_buyer_tax_check": False,
}


def normalize_company_tax_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a stable, whitespace-normalized local company profile."""
    profile = dict(_PROFILE_DEFAULTS)
    if isinstance(raw, dict):
        profile.update(raw)

    for key in (
        "buyer_name",
        "registered_address",
        "registered_phone",
        "bank_name",
    ):
        profile[key] = str(profile.get(key) or "").strip()
    profile["buyer_tax_id"] = normalize_tax_id(profile.get("buyer_tax_id"))
    profile["bank_account"] = re.sub(r"\s+", "", str(profile.get("bank_account") or ""))
    profile["strict_buyer_check"] = bool(profile.get("strict_buyer_check", False))
    profile["strict_buyer_tax_check"] = bool(
        profile.get("strict_buyer_tax_check", False)
    )
    return profile


def format_company_tax_info(raw: dict[str, Any] | None) -> str:
    """Build copy-ready invoice issuance information, omitting blank fields."""
    profile = normalize_company_tax_profile(raw)
    rows = (
        ("单位名称", profile["buyer_name"]),
        ("纳税人识别号", profile["buyer_tax_id"]),
        ("注册地址", profile["registered_address"]),
        ("注册电话", profile["registered_phone"]),
        ("开户行", profile["bank_name"]),
        ("银行账号", profile["bank_account"]),
    )
    return "\n".join(f"{label}：{value}" for label, value in rows if value)


def _valid_tax_id(value: str) -> bool:
    """Accept common domestic taxpayer IDs without over-rejecting legacy forms."""
    tax_id = normalize_tax_id(value)
    return not tax_id or bool(re.fullmatch(r"[0-9A-Z]{15,20}", tax_id))


class CompanyTaxProfileDialog(QDialog):
    """Edit and copy the local company invoice profile."""

    def __init__(self, reimbursement_cfg: dict | None = None, parent=None):
        super().__init__(parent)
        profile = normalize_company_tax_profile(reimbursement_cfg)
        self.setWindowTitle("公司开票信息")
        self.setModal(True)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel("公司开票信息", self)
        title.setProperty("class", "SettingsSurfaceTitle")
        root.addWidget(title)

        hint = QLabel(
            "用于向商户提供开票资料，并在审核时核对发票购买方。信息仅保存在本机。",
            self,
        )
        hint.setProperty("class", "SettingsSurfaceHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.txt_buyer_name = QLineEdit(profile["buyer_name"], self)
        self.txt_buyer_name.setPlaceholderText("例如：示例科技有限公司")
        self.txt_buyer_name.setClearButtonEnabled(True)

        self.txt_tax_id = QLineEdit(profile["buyer_tax_id"], self)
        self.txt_tax_id.setPlaceholderText("统一社会信用代码或纳税人识别号")
        self.txt_tax_id.setClearButtonEnabled(True)

        self.txt_registered_address = QLineEdit(profile["registered_address"], self)
        self.txt_registered_address.setPlaceholderText("选填：营业执照登记地址")
        self.txt_registered_address.setClearButtonEnabled(True)

        self.txt_registered_phone = QLineEdit(profile["registered_phone"], self)
        self.txt_registered_phone.setPlaceholderText("选填：税务登记电话")
        self.txt_registered_phone.setClearButtonEnabled(True)

        self.txt_bank_name = QLineEdit(profile["bank_name"], self)
        self.txt_bank_name.setPlaceholderText("选填：开户银行及支行")
        self.txt_bank_name.setClearButtonEnabled(True)

        self.txt_bank_account = QLineEdit(profile["bank_account"], self)
        self.txt_bank_account.setPlaceholderText("选填：银行账号")
        self.txt_bank_account.setClearButtonEnabled(True)

        self.chk_strict_name = QCheckBox("购买方名称不一致时提醒", self)
        self.chk_strict_name.setChecked(profile["strict_buyer_check"])
        self.chk_strict_tax = QCheckBox("发票已识别税号且不一致时提醒", self)
        self.chk_strict_tax.setChecked(profile["strict_buyer_tax_check"])

        form.addRow("单位名称", self.txt_buyer_name)
        form.addRow("纳税人识别号", self.txt_tax_id)
        form.addRow("注册地址", self.txt_registered_address)
        form.addRow("注册电话", self.txt_registered_phone)
        form.addRow("开户行", self.txt_bank_name)
        form.addRow("银行账号", self.txt_bank_account)
        form.addRow("", self.chk_strict_name)
        form.addRow("", self.chk_strict_tax)
        root.addLayout(form)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.btn_copy = make_button("复制开票信息", variant="secondary", min_width=112)
        self.btn_copy.clicked.connect(self._copy_profile)
        footer.addWidget(self.btn_copy)
        footer.addStretch(1)
        cancel = make_button("取消", variant="secondary", min_width=80)
        save = make_button("保存", variant="primary", min_width=96)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept_if_valid)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

    def values(self) -> dict[str, Any]:
        return normalize_company_tax_profile(
            {
                "buyer_name": self.txt_buyer_name.text(),
                "buyer_tax_id": self.txt_tax_id.text(),
                "registered_address": self.txt_registered_address.text(),
                "registered_phone": self.txt_registered_phone.text(),
                "bank_name": self.txt_bank_name.text(),
                "bank_account": self.txt_bank_account.text(),
                "strict_buyer_check": self.chk_strict_name.isChecked(),
                "strict_buyer_tax_check": self.chk_strict_tax.isChecked(),
            }
        )

    def _accept_if_valid(self) -> None:
        profile = self.values()
        if (profile["strict_buyer_check"] or profile["strict_buyer_tax_check"]) and not profile[
            "buyer_name"
        ]:
            QMessageBox.warning(self, "缺少单位名称", "启用开票核对前，请填写单位名称。")
            self.txt_buyer_name.setFocus()
            return
        if profile["strict_buyer_tax_check"] and not profile["buyer_tax_id"]:
            QMessageBox.warning(
                self,
                "缺少纳税人识别号",
                "启用税号核对前，请填写纳税人识别号。",
            )
            self.txt_tax_id.setFocus()
            return
        if not _valid_tax_id(profile["buyer_tax_id"]):
            QMessageBox.warning(
                self,
                "纳税人识别号格式异常",
                "请输入 15 至 20 位数字或大写字母；空格和连字符会自动去除。",
            )
            self.txt_tax_id.setFocus()
            return
        self.accept()

    def _copy_profile(self) -> None:
        text = format_company_tax_info(self.values())
        if not text:
            QMessageBox.information(self, "暂无内容", "请先填写至少一项公司开票信息。")
            return
        QApplication.clipboard().setText(text)
        self.btn_copy.setText("已复制")
        self.btn_copy.setEnabled(False)
        QTimer.singleShot(1200, self._restore_copy_button)

    def _restore_copy_button(self) -> None:
        try:
            self.btn_copy.setText("复制开票信息")
            self.btn_copy.setEnabled(True)
        except RuntimeError:
            pass


def save_company_tax_profile(window, profile: dict[str, Any]) -> dict[str, Any]:
    """Persist the normalized company profile in the local reimbursement config."""
    normalized = normalize_company_tax_profile(profile)
    cfg = dict(getattr(window, "config", {}) or {})
    reimbursement_cfg = dict(cfg.get("reimbursement") or {})
    reimbursement_cfg.update(normalized)
    cfg["reimbursement"] = reimbursement_cfg
    save_config(cfg)
    window.config = cfg
    if hasattr(window, "_desktop_settings_cfg"):
        window._desktop_settings_cfg = dict(cfg)
    return normalized


def refresh_company_tax_profile_status(window) -> None:
    """Keep the company-profile entry visible and show the current check result."""
    detail = getattr(window, "_detail_panel", None)
    if detail is None or not hasattr(detail, "lbl_buyer_warning"):
        return

    profile = normalize_company_tax_profile(
        (getattr(window, "config", {}) or {}).get("reimbursement", {})
    )
    invoice = getattr(window, "current_invoice", None) or {}
    warning = buyer_warning(invoice, {"reimbursement": profile}) if invoice else ""

    label = detail.lbl_buyer_warning
    if warning:
        text = warning
        tone = "warning"
    elif profile["buyer_name"]:
        text = f"开票单位：{profile['buyer_name']}"
        tone = "muted"
    else:
        text = "未设置公司开票信息"
        tone = "muted"
    label.setText(text)
    label.setToolTip(text)
    label.setProperty("tone", tone)
    label.setVisible(True)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    row = getattr(detail, "buyer_warning_action_row", None)
    if row is not None:
        row.setVisible(True)

    button = getattr(detail, "btn_edit_reimbursement_title", None)
    if button is not None:
        button.setText("公司开票信息")
        button.setToolTip("查看、复制或修改本机保存的公司开票资料")
        button.setAccessibleName("公司开票信息")
        button.setMinimumWidth(96)
        button.setMaximumWidth(116)

    for widget in (label, row):
        if widget is not None:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()


def _open_company_tax_profile_dialog(window) -> None:
    profile = (getattr(window, "config", {}) or {}).get("reimbursement", {})
    dialog = CompanyTaxProfileDialog(profile, window)
    if dialog.exec() != QDialog.Accepted:
        return
    try:
        save_company_tax_profile(window, dialog.values())
    except OSError as exc:
        QMessageBox.critical(window, "保存失败", f"无法保存公司开票信息：{exc}")
        return
    refresh_company_tax_profile_status(window)
    QMessageBox.information(window, "已保存", "公司开票信息已保存到本机。")


def apply_company_tax_profile(page: QWidget | None) -> None:
    """Upgrade the existing buyer-title entry to a complete company profile."""
    if page is None or page.property("companyTaxProfileApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    detail = getattr(window, "_detail_panel", None)
    button = getattr(detail, "btn_edit_reimbursement_title", None) if detail else None
    if detail is None or button is None:
        return

    from . import review_toolbar_filter_fixes as toolbar_fixes

    toolbar_fixes._refresh_buyer_warning = refresh_company_tax_profile_status
    refresh_company_tax_profile_status._company_tax_profile_refresh = True

    try:
        button.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    button.clicked.connect(
        lambda _checked=False, target=window: _open_company_tax_profile_dialog(target)
    )

    page.setProperty("companyTaxProfileApplied", True)
    refresh_company_tax_profile_status(window)


__all__ = [
    "CompanyTaxProfileDialog",
    "apply_company_tax_profile",
    "format_company_tax_info",
    "normalize_company_tax_profile",
    "refresh_company_tax_profile_status",
    "save_company_tax_profile",
]
