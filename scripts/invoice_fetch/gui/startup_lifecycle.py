# -*- coding: utf-8 -*-
"""Desktop startup lifecycle boundary.

Keep the review workbench that is actually visible at launch on the first-paint
critical path. Invoice/claim data loading and non-visible business pages are
materialized only after that boundary: data immediately after the first real Qt
Paint event, and hidden pages on their first navigation. This preserves the
normal InvoiceReviewApp business behavior while avoiding work the user cannot
see before first paint.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from .app import InvoiceReviewApp, StartupSplash


class FirstPaintDeferredInvoiceReviewApp(InvoiceReviewApp):
    """Keep only the launch-visible review workbench on the first-paint path."""

    _STARTUP_LAZY_PAGE_SPECS = {
        "overview": (0, "_build_overview_page_view", ("overview_page", "dashboard_page")),
        "imports": (2, "_build_imports_page_view", ("imports_page", "import_center_page")),
        "export": (3, "_build_export_page_view", ("export_page",)),
        "logs": (4, "_build_logs_page_view", ("logs_page", "audit_log_page")),
        "settings": (5, "_build_settings_page_view", ("settings_page",)),
    }

    def __init__(self, *args, **kwargs):
        self._startup_first_paint_seen = False
        self._startup_first_paint_completed_at: float | None = None
        self._startup_post_paint_load_scheduled = False
        self._startup_defer_hidden_pages = True
        self._startup_lazy_placeholders: dict[str, QWidget] = {}
        self._startup_page_materializing: set[str] = set()
        super().__init__(*args, **kwargs)

    def _startup_placeholder(self, page_key: str) -> QWidget:
        """Return a zero-work placeholder that preserves QStackedWidget indices."""
        placeholder = QWidget()
        placeholder.setObjectName(f"StartupDeferredPage_{page_key}")
        placeholder.setProperty("startupDeferredPage", page_key)
        self._startup_lazy_placeholders[page_key] = placeholder
        return placeholder

    def _build_overview_page_view(self):
        if self._startup_defer_hidden_pages:
            return self._startup_placeholder("overview")
        return super()._build_overview_page_view()

    def _build_imports_page_view(self):
        if self._startup_defer_hidden_pages:
            return self._startup_placeholder("imports")
        return super()._build_imports_page_view()

    def _build_export_page_view(self):
        if self._startup_defer_hidden_pages:
            return self._startup_placeholder("export")
        return super()._build_export_page_view()

    def _build_logs_page_view(self):
        if self._startup_defer_hidden_pages:
            return self._startup_placeholder("logs")
        return super()._build_logs_page_view()

    def _build_settings_page_view(self):
        if self._startup_defer_hidden_pages:
            return self._startup_placeholder("settings")
        return super()._build_settings_page_view()

    def _startup_page_is_deferred(self, page_key: str) -> bool:
        return page_key in self._startup_lazy_placeholders

    def _materialize_startup_page(self, page_key: str) -> None:
        """Build one hidden business page exactly when the user first opens it."""
        spec = self._STARTUP_LAZY_PAGE_SPECS.get(page_key)
        placeholder = self._startup_lazy_placeholders.get(page_key)
        if spec is None or placeholder is None or page_key in self._startup_page_materializing:
            return
        if not hasattr(self, "center_stack") or self.center_stack is None:
            return

        index, builder_name, aliases = spec
        self._startup_page_materializing.add(page_key)
        try:
            # Call the base builder directly so the startup override does not
            # hand back another placeholder during first-use materialization.
            builder = getattr(super(), builder_name)
            page = builder()

            current_widget = self.center_stack.currentWidget()
            self.center_stack.removeWidget(placeholder)
            self.center_stack.insertWidget(index, page)
            for alias in aliases:
                setattr(self, alias, page)
            self._startup_lazy_placeholders.pop(page_key, None)
            placeholder.deleteLater()

            # Preserve the page that was visible while construction happened;
            # the normal page switch below owns the actual navigation change.
            if current_widget is not None and current_widget is not placeholder:
                self.center_stack.setCurrentWidget(current_widget)

            observer = getattr(self, "_performance_paint_observer", None)
            if observer is not None and page_key in {"overview", "imports"}:
                observer.observe(page_key, page)
        finally:
            self._startup_page_materializing.discard(page_key)

    def _reflow_after_lazy_page_switch(self) -> None:
        """Apply responsive geometry after a materialized page becomes current."""
        self._apply_workbench_metrics()
        # Page builders intentionally queue baseline/HCI normalization with
        # zero-delay timers. Run one final metrics pass after those callbacks so
        # first navigation has the same geometry as a later native resize.
        QTimer.singleShot(0, self._apply_workbench_metrics)

    def _reflow_launch_page_after_first_paint(self) -> None:
        """Settle the launch page against the real shown-window geometry."""
        self._apply_workbench_metrics()
        controller = getattr(self, "_review_detail_width_controller", None)
        if controller is not None:
            controller.schedule()
        # Some review baseline callbacks are also zero-delay. A final queued
        # metrics pass makes the launch state converge to the same geometry as
        # a later native resize without moving any work back before first paint.
        QTimer.singleShot(0, self._apply_workbench_metrics)

    def _switch_main_page(
        self,
        page_key: str,
        sub_tab: int = 0,
        *,
        preserve_review_scope: bool = False,
    ) -> None:
        # Hidden-page construction is deliberately outside launch/first paint.
        was_deferred = self._startup_page_is_deferred(page_key)
        self._materialize_startup_page(page_key)
        result = super()._switch_main_page(
            page_key,
            sub_tab=sub_tab,
            preserve_review_scope=preserve_review_scope,
        )
        if was_deferred:
            self._reflow_after_lazy_page_switch()
        return result

    def _refresh_overview_page(self) -> None:
        if self._startup_page_is_deferred("overview"):
            self.overview_dirty = True
            return
        return super()._refresh_overview_page()

    def _refresh_imports_page(self) -> None:
        if self._startup_page_is_deferred("imports"):
            self.imports_dirty = True
            return
        return super()._refresh_imports_page()

    def _refresh_settings_page(self) -> None:
        if self._startup_page_is_deferred("settings"):
            self.settings_dirty = True
            return
        return super()._refresh_settings_page()

    def _deferred_init(self):
        """Preserve the original data load verbatim, but never before first paint."""
        if not self._startup_first_paint_seen:
            return
        return super()._deferred_init()

    def event(self, event):
        """Capture the completed first Paint before scheduling post-paint work."""
        handled = super().event(event)
        if (
            event.type() == QEvent.Paint
            and self.isVisible()
            and not self._startup_first_paint_seen
        ):
            self._startup_first_paint_seen = True
            # This timestamp is captured synchronously after QWidget has
            # handled the Paint event. The release probe reads this exact
            # boundary instead of timing a later event-loop callback.
            self._startup_first_paint_completed_at = time.monotonic()
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
        self._reflow_launch_page_after_first_paint()
        super()._deferred_init()


def build_startup_window(db_path: Path, splash: StartupSplash | None):
    """Construct the launch-visible workbench and defer hidden business pages."""
    return FirstPaintDeferredInvoiceReviewApp(
        db_path,
        splash=splash,
        startup_probe=False,
    )


def reveal_startup_window(
    window: FirstPaintDeferredInvoiceReviewApp,
    splash: StartupSplash | None,
) -> None:
    """Reveal the real review workbench before invoice/claim data loading."""
    # InvoiceReviewApp historically kept the window hidden until
    # ``_deferred_init`` finished. This startup boundary owns visibility now.
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
    """Run normal desktop startup with non-visible work outside first paint."""
    # Kept in the public launcher signature because import time is measured by
    # the release probe path. Normal interactive startup does not emit it.
    _ = app_init_ms
    app = QApplication(sys.argv)
    splash = StartupSplash()
    splash.show()
    splash.show_message("正在启动 Invoice Hub...", 15)

    window = build_startup_window(db_path, splash)
    reveal_startup_window(window, splash)
    sys.exit(app.exec())
