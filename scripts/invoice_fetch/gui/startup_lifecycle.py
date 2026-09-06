# -*- coding: utf-8 -*-
"""Desktop startup lifecycle boundary.

Keep the complete InvoiceReviewApp workbench construction unchanged, but do not
run the first invoice/claim data load until the main window has completed its
first real Qt Paint event.  This keeps data loading out of the first-paint
critical path without weakening the startup probe or changing review behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication

from .app import InvoiceReviewApp, StartupSplash


class FirstPaintDeferredInvoiceReviewApp(InvoiceReviewApp):
    """Gate the existing deferred data load behind the first completed Paint."""

    def __init__(self, *args, **kwargs):
        self._startup_first_paint_seen = False
        self._startup_post_paint_load_scheduled = False
        super().__init__(*args, **kwargs)

    def _deferred_init(self):
        """Preserve the original load verbatim, but never before first paint."""
        if not self._startup_first_paint_seen:
            return
        return super()._deferred_init()

    def event(self, event):
        """Schedule first data load only after QWidget has handled first Paint."""
        handled = super().event(event)
        if (
            event.type() == QEvent.Paint
            and self.isVisible()
            and not self._startup_first_paint_seen
        ):
            self._startup_first_paint_seen = True
            if not self._startup_post_paint_load_scheduled:
                self._startup_post_paint_load_scheduled = True
                QTimer.singleShot(0, self._run_post_paint_deferred_init)
        return handled

    def _run_post_paint_deferred_init(self) -> None:
        self._startup_post_paint_load_scheduled = False
        if getattr(self, "_shutdown_requested", False):
            return
        if getattr(self, "_deferred_init_done", False):
            return
        super()._deferred_init()


def build_startup_window(db_path: Path, splash: StartupSplash | None):
    """Construct the same complete workbench used by normal desktop startup."""
    return FirstPaintDeferredInvoiceReviewApp(
        db_path,
        splash=splash,
        startup_probe=False,
    )


def reveal_startup_window(
    window: FirstPaintDeferredInvoiceReviewApp,
    splash: StartupSplash | None,
) -> None:
    """Reveal the real workbench shell before any invoice/claim data load."""
    # InvoiceReviewApp historically kept the window hidden until
    # ``_deferred_init`` finished.  This startup boundary owns visibility now.
    window._show_after_deferred_init = False
    window.splash = None
    window.show()
    if splash is not None:
        splash.close()


def start_first_paint_deferred_gui_app(
    db_path: Path,
    *,
    app_init_ms: int = 0,
) -> None:
    """Run normal desktop startup with first data load after first paint."""
    # Kept in the public launcher signature because import time is measured by
    # the release probe path.  Normal interactive startup does not emit it.
    _ = app_init_ms
    app = QApplication(sys.argv)
    splash = StartupSplash()
    splash.show()
    splash.show_message("正在启动 Invoice Hub...", 15)

    window = build_startup_window(db_path, splash)
    reveal_startup_window(window, splash)
    sys.exit(app.exec())
