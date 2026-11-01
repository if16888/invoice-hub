"""One shell for task dialogs: margins, title/hint and a right-aligned footer."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QVBoxLayout


def apply_dialog_shell(dialog, layout: QVBoxLayout, title: str, hint: str = "",
                       buttons: QDialogButtonBox | None = None) -> None:
    """Apply the shared 20/18 margin, title/hint and right-aligned footer."""
    layout.setContentsMargins(20, 18, 20, 16)
    layout.setSpacing(12)
    heading = QLabel(title, dialog)
    heading.setProperty("class", "DialogTitle")
    heading.setWordWrap(True)
    layout.insertWidget(0, heading)
    if hint:
        description = QLabel(hint, dialog)
        description.setWordWrap(True)
        description.setProperty("class", "DialogHint")
        layout.insertWidget(1, description)
    if buttons is not None:
        buttons.setCenterButtons(False)
        layout.addWidget(buttons, 0, Qt.AlignRight)
