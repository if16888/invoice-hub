from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from scripts.invoice_fetch.gui import startup_lifecycle, startup_probe


class StartupLifecycleOrderingTests(unittest.TestCase):
    def test_public_launcher_uses_first_paint_lifecycle_for_normal_desktop(self):
        source = Path("scripts/invoice_fetch/gui/__init__.py").read_text(encoding="utf-8")
        self.assertIn("start_first_paint_deferred_gui_app", source)
        self.assertNotIn("from .app import start_gui_app", source)

    def test_deferred_init_is_hard_gated_by_completed_first_paint(self):
        source = inspect.getsource(
            startup_lifecycle.FirstPaintDeferredInvoiceReviewApp._deferred_init
        )
        self.assertIn("if not self._startup_first_paint_seen", source)
        self.assertIn("return super()._deferred_init()", source)

    def test_first_paint_is_handled_before_post_paint_load_is_scheduled(self):
        source = inspect.getsource(
            startup_lifecycle.FirstPaintDeferredInvoiceReviewApp.event
        )
        handled_at = source.index("handled = super().event(event)")
        paint_at = source.index("event.type() == QEvent.Paint")
        schedule_at = source.index(
            "QTimer.singleShot(0, self._run_post_paint_deferred_init)"
        )
        self.assertLess(handled_at, paint_at)
        self.assertLess(paint_at, schedule_at)

    def test_reveal_disarms_legacy_show_after_load_before_showing_window(self):
        source = inspect.getsource(startup_lifecycle.reveal_startup_window)
        disarm_at = source.index("window._show_after_deferred_init = False")
        detach_splash_at = source.index("window.splash = None")
        show_at = source.index("window.show()")
        close_at = source.index("splash.close()")
        self.assertLess(disarm_at, show_at)
        self.assertLess(detach_splash_at, show_at)
        self.assertLess(show_at, close_at)

    def test_probe_installs_observer_before_revealing_main_window(self):
        source = inspect.getsource(startup_probe.start_first_paint_startup_probe)
        session_at = source.index("session.start()")
        reveal_at = source.index("reveal_startup_window(window, splash)")
        self.assertLess(session_at, reveal_at)

    def test_normal_and_probe_startup_share_same_window_class(self):
        build_source = inspect.getsource(startup_lifecycle.build_startup_window)
        probe_source = inspect.getsource(startup_probe.start_first_paint_startup_probe)
        class_name = "FirstPaintDeferredInvoiceReviewApp"
        self.assertIn(class_name, build_source)
        self.assertIn(class_name, probe_source)


if __name__ == "__main__":
    unittest.main()
