# -*- coding: utf-8 -*-
"""Truthful startup-probe execution for the desktop application.

The release probe follows the same full workbench construction and deferred
first-load path as a normal desktop launch. It exits only after the main
window's first Qt Paint event has returned to the event loop. This is a Qt
render-readiness milestone; it does not claim OS compositor/display presentation.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication

from .app import InvoiceReviewApp, StartupSplash


PROBE_CONTRACT = "main_window_first_paint_v1"
PROBE_TIMEOUT_MS = 25_000


def build_startup_probe_metrics(
    *,
    app_init_ms: int,
    db_open_ms: int,
    gui_init_ms: int,
    first_load_ms: int,
    main_window_show_ms: int,
    first_paint_ms: int,
) -> dict[str, object]:
    """Build one self-describing completed-Qt-Paint metric payload."""
    app_init_ms = max(0, int(app_init_ms))
    main_window_show_ms = max(0, int(main_window_show_ms))
    first_paint_ms = max(0, int(first_paint_ms))
    total_startup_ms = app_init_ms + first_paint_ms
    return {
        "PROBE_CONTRACT": PROBE_CONTRACT,
        "QT_PAINT_EVENT_COMPLETED": True,
        "APP_INIT_MS": app_init_ms,
        "DB_OPEN_MS": max(0, int(db_open_ms)),
        "MAIN_WINDOW_SHOW_MS": main_window_show_ms,
        "STARTUP_MS": total_startup_ms,
        "GUI_INIT_MS": max(0, int(gui_init_ms)),
        "FIRST_LOAD_MS": max(0, int(first_load_ms)),
        "FIRST_PAINT_MS": first_paint_ms,
        "TOTAL_STARTUP_MS": total_startup_ms,
    }


def _print_metrics(metrics: Mapping[str, object]) -> None:
    for key in (
        "PROBE_CONTRACT",
        "QT_PAINT_EVENT_COMPLETED",
        "APP_INIT_MS",
        "DB_OPEN_MS",
        "MAIN_WINDOW_SHOW_MS",
        "STARTUP_MS",
        "GUI_INIT_MS",
        "FIRST_LOAD_MS",
        "FIRST_PAINT_MS",
        "TOTAL_STARTUP_MS",
    ):
        value = metrics[key]
        if isinstance(value, bool):
            value = 1 if value else 0
        print(f"{key}={value}", flush=True)


def _write_metrics(metrics: Mapping[str, object]) -> None:
    output_path = os.environ.get("INVOICE_HUB_STARTUP_PROBE_FILE", "").strip()
    if not output_path:
        return
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(metrics), ensure_ascii=False), encoding="utf-8")


class StartupProbeSession(QObject):
    """Observe main-window Show/Paint milestones and end the probe safely."""

    def __init__(
        self,
        app: QApplication,
        window: InvoiceReviewApp,
        *,
        launch_started_at: float,
        app_init_ms: int,
    ) -> None:
        super().__init__(window)
        self._app = app
        self._window = window
        self._launch_started_at = float(launch_started_at)
        self._app_init_ms = max(0, int(app_init_ms))
        self._show_ms: int | None = None
        self._paint_pending = False
        self._finished = False

    def start(self) -> None:
        self._window.installEventFilter(self)
        QTimer.singleShot(PROBE_TIMEOUT_MS, self._timeout)

    def _elapsed_ms(self) -> int:
        return max(0, int((time.monotonic() - self._launch_started_at) * 1000))

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API name
        if watched is self._window and not self._finished:
            event_type = event.type()
            if event_type == QEvent.Show and self._show_ms is None:
                self._show_ms = self._elapsed_ms()
            elif (
                event_type == QEvent.Paint
                and self._show_ms is not None
                and not self._paint_pending
            ):
                # Event filters run before QWidget handles the Paint event. A
                # zero-delay callback records the milestone only after that
                # event has returned to the Qt event loop.
                self._paint_pending = True
                QTimer.singleShot(0, self._finish_after_paint)
        return False

    def _finish_after_paint(self) -> None:
        if self._finished:
            return
        first_paint_ms = self._elapsed_ms()
        show_ms = self._show_ms
        if show_ms is None:
            self._fail("main window painted without an observed Show event")
            return

        metrics = build_startup_probe_metrics(
            app_init_ms=self._app_init_ms,
            db_open_ms=getattr(self._window, "db_open_ms", 0),
            gui_init_ms=getattr(self._window, "gui_init_ms", 0),
            first_load_ms=getattr(self._window, "first_load_ms", 0),
            main_window_show_ms=show_ms,
            first_paint_ms=first_paint_ms,
        )
        try:
            _write_metrics(metrics)
            _print_metrics(metrics)
        except Exception as exc:
            self._fail(f"could not persist startup-probe metrics: {exc}", exit_code=3)
            return

        self._finished = True
        self._window.removeEventFilter(self)
        self._app.exit(0)

    def _timeout(self) -> None:
        if not self._finished:
            self._fail(
                "main window first Qt Paint event was not observed before timeout",
                exit_code=2,
            )

    def _fail(self, message: str, *, exit_code: int = 2) -> None:
        if self._finished:
            return
        self._finished = True
        failure = {
            "PROBE_CONTRACT": PROBE_CONTRACT,
            "QT_PAINT_EVENT_COMPLETED": False,
            "ERROR": message,
        }
        try:
            _write_metrics(failure)
            _print_metrics(
                {
                    "PROBE_CONTRACT": PROBE_CONTRACT,
                    "QT_PAINT_EVENT_COMPLETED": False,
                    "APP_INIT_MS": self._app_init_ms,
                    "DB_OPEN_MS": max(0, int(getattr(self._window, "db_open_ms", 0))),
                    "MAIN_WINDOW_SHOW_MS": (
                        self._show_ms if self._show_ms is not None else 0
                    ),
                    "STARTUP_MS": 0,
                    "GUI_INIT_MS": max(0, int(getattr(self._window, "gui_init_ms", 0))),
                    "FIRST_LOAD_MS": max(0, int(getattr(self._window, "first_load_ms", 0))),
                    "FIRST_PAINT_MS": 0,
                    "TOTAL_STARTUP_MS": 0,
                }
            )
        except Exception:
            pass
        print(f"STARTUP_PROBE_ERROR={message}", file=sys.stderr, flush=True)
        self._window.removeEventFilter(self)
        self._app.exit(exit_code)


def start_first_paint_startup_probe(db_path: Path, *, app_init_ms: int = 0) -> None:
    """Launch the full desktop path and exit after the first completed Qt Paint."""
    launch_started_at = time.monotonic()
    app = QApplication(sys.argv)

    # Match normal production startup: show the splash, build the complete
    # workbench, run the deferred first data load, then show the main window.
    splash = StartupSplash()
    splash.show()
    splash.show_message("正在启动 Invoice Hub...", 15)
    window = InvoiceReviewApp(db_path, splash=splash, startup_probe=False)

    session = StartupProbeSession(
        app,
        window,
        launch_started_at=launch_started_at,
        app_init_ms=app_init_ms,
    )
    # Keep an explicit Python reference in addition to QObject parent ownership.
    window._startup_probe_session = session
    session.start()
    sys.exit(app.exec())
