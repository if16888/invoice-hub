#!/usr/bin/env python3
"""Print AI profile row widget details for local UI debugging."""

import sys

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from scripts.invoice_fetch.gui.settings_dialog import SettingsDialog
from scripts.invoice_fetch.gui.styles import APP_STYLESHEET


def _geometry_text(widget) -> str:
    rect = widget.geometry()
    return f"({rect.x()}, {rect.y()}, {rect.width()}, {rect.height()})"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    parent = QWidget()
    parent.config = {}
    parent.write_log = lambda *args, **kwargs: None

    dialog = SettingsDialog(parent)
    dialog.setStyleSheet(APP_STYLESHEET)
    dialog.resize(650, 580)
    dialog.tab_widget.setCurrentIndex(1)
    dialog.show()
    app.processEvents()

    print(f"AI rows: {len(dialog.ai_rows)}")
    for row_index, row in enumerate(dialog.ai_rows):
        print(f"Row {row_index}: {type(row).__name__}")
        for widget in row.findChildren(QPushButton):
            palette = widget.palette()
            text_color = palette.buttonText().color()
            print(
                "  "
                f"{type(widget).__name__} "
                f"text={widget.text()!r} "
                f"variant={widget.property('variant')!r} "
                f"enabled={widget.isEnabled()} "
                f"visible={widget.isVisible()} "
                f"geometry={_geometry_text(widget)} "
                f"buttonText={text_color.name()}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
