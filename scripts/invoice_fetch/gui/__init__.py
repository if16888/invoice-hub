# -*- coding: utf-8 -*-
"""
Invoice Hub PySide6 GUI Package
"""

import logging
import os
import sys
import time
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
        startup_probe: If True, run the full desktop startup path and exit only
            after the main window's first Qt Paint event has completed.
        app_init_ms: Milliseconds already spent importing the GUI package. The
            launcher adds the concrete app/probe module import time before
            reporting APP_INIT_MS.
    """
    if not PYSIDE6_AVAILABLE:
        print("=" * 60)
        print(" ❌ 无法启动发票审核桌面端：检测到未安装 PySide6 依赖库。")
        print(" 请在您的命令行终端中执行以下命令进行安装：")
        print("    pip install PySide6")
        print("=" * 60)
        sys.exit(1)

    is_probe = startup_probe or os.environ.get("INVOICE_HUB_STARTUP_PROBE") == "1"
    import_started_at = time.monotonic()
    from .startup_lifecycle import start_first_paint_deferred_gui_app
    if is_probe:
        from .startup_probe import start_first_paint_startup_probe
    import_ms = int((time.monotonic() - import_started_at) * 1000)
    total_app_init_ms = max(0, int(app_init_ms)) + max(0, import_ms)

    if is_probe:
        # Probe stdout/stderr is a machine-readable evidence channel. Keep
        # normal INFO console logging out of it while preserving file logging
        # and direct Qt diagnostics such as QFont warnings.
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if type(handler) is logging.StreamHandler:
                handler.setLevel(logging.CRITICAL + 1)
        start_first_paint_startup_probe(db_path, app_init_ms=total_app_init_ms)
        return

    start_first_paint_deferred_gui_app(
        db_path,
        app_init_ms=total_app_init_ms,
    )
