"""Diagnostic-only native Qt first-window probe; called after frozen A/B runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--variant", choices=("plain", "label", "production-splash"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))

    import PySide6
    from PySide6.QtCore import Qt, qVersion
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    from scripts.invoice_fetch.gui.app import StartupSplash
    from scripts.invoice_fetch.gui.high_dpi import configure_high_dpi_platform
    from scripts.invoice_fetch.gui.i18n import install_chinese_translations

    stages = {}

    def measure(name, operation):
        wall, cpu = time.perf_counter(), time.process_time()
        result = operation()
        stages[name] = {"wall_ms": round((time.perf_counter() - wall) * 1000, 3),
                        "cpu_ms": round((time.process_time() - cpu) * 1000, 3)}
        return result

    configure_high_dpi_platform()
    app = measure("application", lambda: QApplication([]))
    if app.platformName().lower() != "windows":
        raise RuntimeError("Native Qt Windows platform required")
    app.setQuitOnLastWindowClosed(False)
    # Each source uses its own exact translation decision. No QFontInfo or
    # other eager font queries before the first show operation.
    probe_source = args.source / "scripts/invoice_fetch/gui/startup_probe.py"
    translation_enabled = "install_chinese_translations(app)" in probe_source.read_text(encoding="utf-8")
    translator = measure("translator", lambda: install_chinese_translations(app) if translation_enabled else None)
    screen = app.primaryScreen()

    def prefix_window():
        window = QWidget()
        # Hold the native surface type constant with StartupSplash; only the
        # optional text/font/layout and then the production contents differ.
        window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        window.setAttribute(Qt.WA_TranslucentBackground)
        window.resize(400, 220)
        if args.variant == "label":
            layout = QVBoxLayout(window)
            label = QLabel("正在启动 Invoice Hub...", window)
            label.setFont(QFont("Segoe UI", 10))
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
        if screen:
            geometry = screen.geometry()
            window.move((geometry.width() - window.width()) // 2,
                        (geometry.height() - window.height()) // 2)
        return window

    prefix = None
    if args.variant != "production-splash":
        prefix = measure("prefix_construct", prefix_window)
        measure("prefix_show", prefix.show)
        measure("prefix_events", app.processEvents)
        measure("prefix_close", prefix.close)
    splash = measure("splash_construct", StartupSplash)
    measure("splash_show", splash.show)
    measure("splash_events", lambda: splash.show_message("正在启动 Invoice Hub...", 15))
    data = {"variant": args.variant, "platform": app.platformName(), "qt": qVersion(),
            "pyside": PySide6.__version__, "translator_enabled": translation_enabled,
            "translator_loaded": translator is not None, "stages": stages}
    if screen:
        geometry = screen.geometry()
        data["screen"] = {"width": geometry.width(), "height": geometry.height(),
                          "device_pixel_ratio": screen.devicePixelRatio()}
    splash.close()
    app.processEvents()
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
