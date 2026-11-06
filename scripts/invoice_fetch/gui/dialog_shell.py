"""Shared desktop presentation for task dialogs and standard message boxes."""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QMessageBox, QProxyStyle, QPushButton, QStyle, QVBoxLayout, QWidget,
)

from .design_tokens import DESIGN_V1_SPACING


class _DialogButtonStyle(QProxyStyle):
    """Use Cancel then the main action, without changing button-box signals."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):  # noqa: N802
        if hint == QStyle.SH_DialogButtonLayout:
            return QDialogButtonBox.MacLayout.value
        return super().styleHint(hint, option, widget, returnData)


def prepare_dialog(dialog) -> None:
    install_dialog_presentation(QApplication.instance())
    dialog.setProperty("dialogStyle", "desktop")
    dialog.setSizeGripEnabled(True)
    dialog.setAccessibleName(dialog.windowTitle())
    screen = dialog.screen()
    if screen is not None:
        available = screen.availableGeometry()
        maximum_width, maximum_height = max(240, available.width() - 32), max(240, available.height() - 48)
        dialog.setMinimumSize(min(dialog.minimumWidth(), maximum_width), min(dialog.minimumHeight(), maximum_height))
        dialog.setMaximumSize(maximum_width, maximum_height)


def style_dialog_buttons(buttons: QDialogButtonBox, *, default_action=False) -> None:
    if not buttons.property("desktopButtonOrder"):
        style = _DialogButtonStyle(QApplication.style().objectName() or "Fusion")
        style.setParent(buttons)
        buttons.setStyle(style)
        buttons.setProperty("desktopButtonOrder", True)
    buttons.setCenterButtons(False)
    labels = {QDialogButtonBox.Ok: "确定", QDialogButtonBox.Save: "保存",
              QDialogButtonBox.Cancel: "取消", QDialogButtonBox.Close: "关闭",
              QDialogButtonBox.Yes: "是", QDialogButtonBox.No: "否"}
    primary = None
    for button in buttons.buttons():
        standard = buttons.standardButton(button)
        if standard in labels and button.text().replace("&", "") in {
                "OK", "Save", "Cancel", "Close", "Yes", "No"}:
            button.setText(labels[standard])
        role = buttons.buttonRole(button)
        variant = ("danger" if role == QDialogButtonBox.DestructiveRole or button.property('variant') == 'danger' else
                   "primary" if role in (QDialogButtonBox.AcceptRole, QDialogButtonBox.YesRole) else "secondary")
        button.setProperty("variant", variant)
        button.setAccessibleName(button.text().replace("&", ""))
        if default_action:
            button.setAutoDefault(False)
            button.setDefault(False)
            if variant == "primary" and primary is None:
                primary = button
        button.style().unpolish(button)
        button.style().polish(button)
    if default_action and primary is not None:
        primary.setDefault(True)
    elif default_action:
        for button in buttons.buttons():
            if buttons.buttonRole(button) in (QDialogButtonBox.RejectRole, QDialogButtonBox.NoRole):
                button.setDefault(True)
                break


def add_dialog_footer(dialog, layout, content) -> QFrame:
    footer = QFrame(dialog)
    footer.setObjectName("DialogFooter")
    row = QHBoxLayout(footer)
    row.setContentsMargins(0, 12, 0, 0)
    row.setSpacing(DESIGN_V1_SPACING["sm"])
    if isinstance(content, QDialogButtonBox):
        style_dialog_buttons(content, default_action=True)
        row.addWidget(content)
    else:
        row.addLayout(content)
        for button in footer.findChildren(QPushButton):
            button.setAutoDefault(False)
            if button.property("variant") == "primary":
                button.setDefault(True)
    layout.addWidget(footer)
    _fit_form_dialog(dialog)
    return footer


def _fit_form_dialog(dialog) -> None:
    if not hasattr(dialog, 'form_scroll'):
        return
    dialog.ensurePolished()
    dialog.form_scroll.widget().layout().activate()
    dialog.form_scroll.updateGeometry()
    root = dialog.layout()
    root.activate()
    dialog.resize(min(max(dialog.width(), root.minimumSize().width()), dialog.maximumWidth()),
                  min(root.sizeHint().height(), dialog.maximumHeight()))


def apply_dialog_shell(dialog, layout: QVBoxLayout, title: str, hint: str = "",
                       buttons: QDialogButtonBox | None = None) -> None:
    prepare_dialog(dialog)
    margin = DESIGN_V1_SPACING["xl"]
    layout.setContentsMargins(margin, margin, margin, 16)
    layout.setSpacing(DESIGN_V1_SPACING["lg"])
    if title:
        heading = QLabel(title, dialog)
        heading.setProperty("class", "DialogTitle")
        heading.setTextFormat(Qt.PlainText)
        heading.setWordWrap(True)
        layout.insertWidget(0, heading)
    if hint:
        description = QLabel(hint, dialog)
        description.setTextFormat(Qt.PlainText)
        description.setWordWrap(True)
        description.setProperty("class", "DialogHint")
        layout.insertWidget(1 if title else 0, description)
    if buttons is not None:
        add_dialog_footer(dialog, layout, buttons)


class _StandardDialogPresentation(QObject):
    def eventFilter(self, dialog, event):
        if event.type() != QEvent.Show:
            return False
        if isinstance(dialog, QDialog) and dialog.property('dialogStyle') == 'desktop':
            _fit_form_dialog(dialog)
        if not isinstance(dialog, (QMessageBox, QInputDialog)):
            return False
        prepare_dialog(dialog)
        dialog.setSizeGripEnabled(False)
        if dialog.layout() is not None:
            dialog.layout().setContentsMargins(24, 20, 24, 20)
        for box in dialog.findChildren(QDialogButtonBox):
            # Message-box defaults belong to the caller, especially Cancel/No.
            style_dialog_buttons(box, default_action=isinstance(dialog, QInputDialog))
        if isinstance(dialog, QInputDialog):
            dialog.setMinimumWidth(min(440, dialog.maximumWidth()))
        for widget in (dialog, *dialog.findChildren(QWidget)):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        dialog.updateGeometry()
        return False


def install_dialog_presentation(app) -> None:
    if app is not None and not hasattr(app, "_desktop_dialog_presentation"):
        handler = _StandardDialogPresentation(app)
        app._desktop_dialog_presentation = handler
        app.installEventFilter(handler)
