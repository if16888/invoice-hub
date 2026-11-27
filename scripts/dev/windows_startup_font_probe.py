"""Untimed Windows Qt glyph/dialog smoke using the exact build's locked source env."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def glyph_probe(family: str) -> dict:
    from PySide6.QtGui import QFont, QTextLayout

    # Everyday simplified/traditional Hanzi and money glyphs; no controls,
    # whitespace or complex joining. Inspect the real
    # shaped fallback runs, not just the requested QFont's name or metrics.
    text = "发票审核报销金额發票審核報銷金額¥￥−106.00"
    layout = QTextLayout(text, QFont(family, 10))
    layout.beginLayout()
    line = layout.createLine()
    if line.isValid():
        line.setLineWidth(2000)
    layout.endLayout()
    runs = []
    for run in layout.glyphRuns():
        font = run.rawFont()
        indexes = run.glyphIndexes()
        runs.append({"family": font.familyName(), "valid": font.isValid(),
                     "glyph_count": len(indexes), "missing_glyphs": indexes.count(0)})
    count = sum(run["glyph_count"] for run in runs)
    return {"requested_family": family, "text": text, "runs": runs,
            "passed": count == len(text) and all(run["valid"] and run["missing_glyphs"] == 0 for run in runs)}


def exercise_qt(app) -> dict:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox, QWidget
    from scripts.invoice_fetch.gui.dialog_shell import install_dialog_presentation
    from scripts.invoice_fetch.gui.i18n import install_chinese_translations
    from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

    translator = install_chinese_translations(app)
    install_dialog_presentation(app)
    glyphs = [glyph_probe(family) for family in ("Segoe UI", "Microsoft YaHei UI")]
    host = QWidget()
    host.setStyleSheet(APP_STYLESHEET)
    host.resize(420, 240)

    class PaintedMessageBox(QMessageBox):
        paint_count = 0

        def paintEvent(self, event):
            super().paintEvent(event)
            self.paint_count += 1

    box = PaintedMessageBox(host)
    box.setWindowTitle("报销信息")
    box.setText("确认保存合成发票？")
    box.setIcon(QMessageBox.Question)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    box.setEscapeButton(QMessageBox.No)
    try:
        host.show()
        box.show()
        for _ in range(8):
            app.processEvents()
            if box.paint_count:
                break
            QTest.qWait(25)
        yes, no = box.button(QMessageBox.Yes), box.button(QMessageBox.No)
        dialog = {"translator_loaded": translator is not None, "visible": box.isVisible(),
                  "paint_event_completed": box.paint_count > 0, "yes_text": yes.text(), "no_text": no.text(),
                  "translated_buttons": "是" in yes.text() and "否" in no.text(),
                  "default_no": box.defaultButton() is no, "desktop_style": box.property("dialogStyle") == "desktop"}
        QTest.keyClick(box, Qt.Key_Escape)
        app.processEvents()
        dialog["escape_selected_no"] = box.clickedButton() is no and not box.isVisible()
        dialog["passed"] = all(dialog[key] for key in ("translator_loaded", "visible", "paint_event_completed",
            "translated_buttons", "default_no", "desktop_style", "escape_selected_no"))
        return {"glyphs": glyphs, "dialog": dialog, "passed": dialog["passed"] and all(g["passed"] for g in glyphs)}
    finally:
        box.close()
        host.close()
        app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt" or os.environ.get("QT_QPA_PLATFORM") not in {"windows", "windows:fontengine=gdi"}:
        parser.error("Use the native Windows harness with one of the two explicit QPA options")
    sys.path.insert(0, str(args.source.resolve()))
    import PySide6
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QApplication
    from scripts.invoice_fetch.gui.high_dpi import configure_high_dpi_platform

    configure_high_dpi_platform()
    app = QApplication([])
    if app.platformName().lower() != "windows":
        raise RuntimeError("Native Qt Windows platform required")
    app.setQuitOnLastWindowClosed(False)
    data = {"scope": "untimed locked-source Qt smoke; not a frozen startup or per-glyph engine measurement",
            "qt_qpa_platform": os.environ["QT_QPA_PLATFORM"], "platform": app.platformName(),
            "qt": qVersion(), "pyside": PySide6.__version__, **exercise_qt(app)}
    screen = app.primaryScreen()
    if screen is not None:
        size = screen.geometry()
        data["screen"] = {"width": size.width(), "height": size.height(), "device_pixel_ratio": screen.devicePixelRatio()}
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if data["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
