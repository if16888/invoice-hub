# -*- coding: utf-8 -*-
"""
Invoice Hub PySide6 GUI Package
"""

import sys
from pathlib import Path

try:
    from PySide6.QtWidgets import QMainWindow
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False
    class QMainWindow: pass


def start_gui(db_path: Path, startup_probe: bool = False, app_init_ms: int = 0):
    """Launcher entry called from the main CLI dispatch logic.

    Args:
        db_path: Path to the SQLite database.
        startup_probe: If True, exit immediately after the main window is shown
            (used for CI startup-performance measurement).
        app_init_ms: Milliseconds elapsed for the GUI import step, recorded as
            APP_INIT_MS in the startup probe output.
    """
    if not PYSIDE6_AVAILABLE:
        print("=" * 60)
        print(" ❌ 无法启动发票审核桌面端：检测到未安装 PySide6 依赖库。")
        print(" 请在您的命令行终端中执行以下命令进行安装：")
        print("    pip install PySide6")
        print("=" * 60)
        sys.exit(1)

    from .app import start_gui_app
    start_gui_app(db_path, startup_probe=startup_probe, app_init_ms=app_init_ms)
