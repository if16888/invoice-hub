"""Shared spacing and typography for task-focused input dialogs."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QLabel, QFormLayout, QWidget, QScrollArea, QFrame


class DialogFormScroll(QScrollArea):
    """Use the visible form's natural height instead of an oversized viewport."""

    def sizeHint(self):
        body = self.widget()
        if body is None:
            return super().sizeHint()
        hint = body.sizeHint()
        return QSize(hint.width() + 18, min(440, hint.height() + 4))


def style_dialog_form(dialog, layout, form, title, hint=""):
    dialog.setProperty("inputDialog", True)
    layout.setContentsMargins(20, 18, 20, 16)
    layout.setSpacing(12)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(10)
    form.setRowWrapPolicy(QFormLayout.WrapLongRows)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setContentsMargins(0, 0, 6, 0)
    # Keep the footer reachable on small or DPI-scaled desktops.
    form_index = layout.indexOf(form)
    if form_index >= 0:
        layout.removeItem(form)
        form.setParent(None)
        body = QWidget(dialog)
        body.setObjectName("DialogFormBody")
        body.setLayout(form)
        scroll = DialogFormScroll(dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        scroll.setMinimumHeight(160)
        layout.insertWidget(form_index, scroll, 1)
        dialog.form_scroll = scroll
        screen = dialog.screen()
        if screen:
            maximum = max(320, screen.availableGeometry().height() - 48)
            dialog.setMaximumHeight(maximum)
            dialog.resize(dialog.width(), min(form.sizeHint().height() + 140, maximum))
    if title:
        heading = QLabel(title, dialog)
        heading.setProperty("class", "DialogTitle")
        layout.insertWidget(0, heading)
    if hint:
        description = QLabel(hint, dialog)
        description.setWordWrap(True)
        description.setProperty("class", "DialogHint")
        layout.insertWidget(1, description)


MAILBOX_DOMAINS = {
    "qq": "qq.com", "netease_163": "163.com", "netease_126": "126.com",
    "gmail": "gmail.com", "outlook": "outlook.com",
}


def complete_mailbox_address(value, provider):
    value = value.strip()
    if value and "@" not in value and provider in MAILBOX_DOMAINS:
        return f"{value}@{MAILBOX_DOMAINS[provider]}"
    return value
