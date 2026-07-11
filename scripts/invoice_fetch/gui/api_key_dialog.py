"""Purpose-built secure API credential dialog."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from .ui_components import InlineErrorCard, make_button


class ApiKeyDialog(QDialog):
    def __init__(self, provider: str, parent=None, has_existing_key: bool = False):
        super().__init__(parent)
        self.provider = str(provider or "AI").strip()
        self.save_and_test = False
        self.setWindowTitle(f"配置 {self.provider} API Key")
        self.setModal(True)
        self.setFixedWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        title = QLabel(f"配置 {self.provider} API Key")
        title.setProperty("class", "DialogTitle")
        layout.addWidget(title)

        field_row = QHBoxLayout()
        self.txt_key = QLineEdit(self)
        self.txt_key.setEchoMode(QLineEdit.Password)
        self.txt_key.setPlaceholderText("输入新的 API Key")
        self.btn_show_hide = make_button("显示", variant="secondary")
        self.btn_show_hide.setCheckable(True)
        self.btn_show_hide.setToolTip("显示或隐藏 API Key")
        self.btn_show_hide.setAccessibleName("显示或隐藏 API Key")
        self.btn_show_hide.toggled.connect(self._toggle_visibility)
        field_row.addWidget(self.txt_key, 1)
        field_row.addWidget(self.btn_show_hide)
        layout.addWidget(QLabel("API Key"))
        layout.addLayout(field_row)

        guidance = QLabel(
            "Key 将安全保存到 Windows 凭据管理器。\n"
            "不会写入 config.json，也不会进入诊断包。"
            + ("\n输入新 Key 将替换现有凭据。" if has_existing_key else "")
        )
        guidance.setWordWrap(True)
        guidance.setProperty("class", "SectionHint")
        layout.addWidget(guidance)
        self.inline_error = InlineErrorCard("")
        self.inline_error.hide()
        layout.addWidget(self.inline_error)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.btn_cancel = make_button("取消", variant="secondary")
        self.btn_save = make_button("保存", variant="secondary")
        self.btn_save_and_test = make_button("保存并测试", variant="primary")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._accept_save)
        self.btn_save_and_test.clicked.connect(self._accept_save_and_test)
        footer.addWidget(self.btn_cancel)
        footer.addWidget(self.btn_save)
        footer.addWidget(self.btn_save_and_test)
        layout.addLayout(footer)
        self.txt_key.returnPressed.connect(self._accept_save_and_test)

    def _toggle_visibility(self, visible: bool):
        self.txt_key.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.btn_show_hide.setText("隐藏" if visible else "显示")

    def _validate(self) -> bool:
        if self.key_text():
            self.inline_error.hide()
            return True
        self.inline_error.set_error("请输入 API Key。")
        self.inline_error.show()
        return False

    def _accept_save(self):
        if self._validate():
            self.save_and_test = False
            self.accept()

    def _accept_save_and_test(self):
        if self._validate():
            self.save_and_test = True
            self.accept()

    def key_text(self) -> str:
        return self.txt_key.text().strip()

