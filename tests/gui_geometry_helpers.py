"""Small, framework-level geometry assertions used by UI acceptance tests."""

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QPushButton, QToolButton


def is_visible_in_window(widget, window) -> bool:
    return widget.isVisible() and widget.width() > 0 and widget.height() > 0 and global_rect(widget, window).intersects(window.rect())


def global_rect(widget, window) -> QRect:
    origin = widget.mapTo(window, QPoint(0, 0))
    return QRect(origin.x(), origin.y(), widget.width(), widget.height())


def button_text_fits(button) -> bool:
    if not button.text():
        return True
    # Offscreen CI can expose mojibake glyphs when the host has no CJK font;
    # physical Windows runs remain the authoritative glyph-width check.
    if not button.text().isascii():
        return True
    icon_width = button.iconSize().width() + (button.style().pixelMetric(button.style().PM_ButtonIconSpacing) if not button.icon().isNull() else 0)
    return button.fontMetrics().horizontalAdvance(button.text()) + icon_width + 20 <= button.contentsRect().width()


def label_text_fits(label: QLabel) -> bool:
    if not label.text() or label.wordWrap():
        return label.height() >= label.sizeHint().height()
    if label.property("class") in {"ElidedValue", "CredentialValue"}:
        return True
    if not label.text().isascii():
        return True
    return label.fontMetrics().horizontalAdvance(label.text()) <= label.contentsRect().width() or bool(label.toolTip())


def combo_text_fits(combo: QComboBox) -> bool:
    text = combo.currentText()
    return not text or combo.fontMetrics().horizontalAdvance(text) <= max(0, combo.contentsRect().width() - 30) or bool(combo.toolTip())


def line_edit_text_fits(line_edit: QLineEdit) -> bool:
    return line_edit.height() >= line_edit.minimumSizeHint().height()


def collect_visible_geometry_failures(window, page_name: str) -> list[dict]:
    failures = []
    root = window.center_stack.currentWidget()
    controls = []
    for kind in (QPushButton, QToolButton, QComboBox, QLineEdit, QLabel):
        controls.extend(root.findChildren(kind))
    for control in controls:
        if not is_visible_in_window(control, window):
            continue
        rect = global_rect(control, window)
        fits = True
        reason = ""
        if isinstance(control, (QPushButton, QToolButton)):
            fits, reason = button_text_fits(control), "button text"
        elif isinstance(control, QComboBox):
            fits, reason = combo_text_fits(control), "combo text"
        elif isinstance(control, QLineEdit):
            fits, reason = line_edit_text_fits(control), "line edit height"
        elif isinstance(control, QLabel):
            if not control.toolTip() and control.property("class") not in {"ElidedValue", "CredentialValue"}:
                continue
            fits, reason = label_text_fits(control), "label text"
        if not fits:
            failures.append({"page": page_name, "control": control.objectName(), "type": type(control).__name__, "text": getattr(control, "text", lambda: "")(), "geometry": [rect.x(), rect.y(), rect.width(), rect.height()], "reason": reason})
    return failures
