from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QBoxLayout

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

    def test_first_paint_is_handled_and_timestamped_before_post_paint_load(self):
        source = inspect.getsource(
            startup_lifecycle.FirstPaintDeferredInvoiceReviewApp.event
        )
        handled_at = source.index("handled = super().event(event)")
        paint_at = source.index("event.type() == QEvent.Paint")
        timestamp_at = source.index(
            "self._startup_first_paint_completed_at = time.monotonic()"
        )
        schedule_at = source.index(
            "QTimer.singleShot(0, self._run_post_paint_deferred_init)"
        )
        self.assertLess(handled_at, paint_at)
        self.assertLess(paint_at, timestamp_at)
        self.assertLess(timestamp_at, schedule_at)

    def test_hidden_pages_have_stable_lazy_stack_indices(self):
        specs = startup_lifecycle.FirstPaintDeferredInvoiceReviewApp._STARTUP_LAZY_PAGE_SPECS
        self.assertEqual(
            {key: spec[0] for key, spec in specs.items()},
            {
                "overview": 0,
                "imports": 2,
                "export": 3,
                "logs": 4,
                "settings": 5,
            },
        )
        self.assertNotIn("review", specs)

    def test_navigation_materializes_then_switches_then_reflows_lazy_page(self):
        source = inspect.getsource(
            startup_lifecycle.FirstPaintDeferredInvoiceReviewApp._switch_main_page
        )
        materialize_at = source.index("self._materialize_startup_page(page_key)")
        switch_at = source.index("result = super()._switch_main_page(")
        reflow_at = source.index("self._reflow_after_lazy_page_switch()")
        self.assertLess(materialize_at, switch_at)
        self.assertLess(switch_at, reflow_at)

    def test_lazy_reflow_has_immediate_and_post_baseline_metrics_passes(self):
        source = inspect.getsource(
            startup_lifecycle.FirstPaintDeferredInvoiceReviewApp._reflow_after_lazy_page_switch
        )
        immediate_at = source.index("self._apply_workbench_metrics()")
        queued_at = source.index("QTimer.singleShot(0, self._apply_workbench_metrics)")
        self.assertLess(immediate_at, queued_at)

    def test_post_paint_launch_reflow_precedes_initial_data_load(self):
        source = inspect.getsource(
            startup_lifecycle.FirstPaintDeferredInvoiceReviewApp._run_post_paint_deferred_init
        )
        reflow_at = source.index("self._reflow_launch_page_after_first_paint()")
        load_at = source.index("super()._deferred_init()")
        self.assertLess(reflow_at, load_at)

    def test_launch_reflow_uses_metrics_and_review_width_controller(self):
        source = inspect.getsource(
            startup_lifecycle.FirstPaintDeferredInvoiceReviewApp._reflow_launch_page_after_first_paint
        )
        self.assertIn("self._apply_workbench_metrics()", source)
        self.assertIn('getattr(self, "_review_detail_width_controller", None)', source)
        self.assertIn("controller.schedule()", source)
        self.assertIn("QTimer.singleShot(0, self._apply_workbench_metrics)", source)

    def test_hidden_refreshes_are_invalidated_instead_of_touching_placeholders(self):
        for method_name, page_key, dirty_flag in (
            ("_refresh_overview_page", "overview", "overview_dirty"),
            ("_refresh_imports_page", "imports", "imports_dirty"),
            ("_refresh_settings_page", "settings", "settings_dirty"),
        ):
            source = inspect.getsource(
                getattr(startup_lifecycle.FirstPaintDeferredInvoiceReviewApp, method_name)
            )
            self.assertIn(f'_startup_page_is_deferred("{page_key}")', source)
            self.assertIn(f"self.{dirty_flag} = True", source)

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


class StartupLazyPageIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_settings_page_is_built_on_first_navigation_without_index_drift(self):
        with tempfile.TemporaryDirectory(prefix="invoice-hub-startup-lazy-") as td:
            window = startup_lifecycle.FirstPaintDeferredInvoiceReviewApp(
                Path(td) / "startup.db",
                splash=None,
            )
            try:
                self.assertEqual(window.center_stack.count(), 6)
                self.assertIs(window.center_stack.currentWidget(), window.review_page)
                self.assertEqual(
                    window.settings_page.property("startupDeferredPage"),
                    "settings",
                )
                self.assertFalse(hasattr(window, "settings_tabs"))

                window._switch_main_page("settings")
                self.qt_app.processEvents()

                self.assertEqual(window.center_stack.count(), 6)
                self.assertEqual(window.center_stack.indexOf(window.settings_page), 5)
                self.assertIs(window.center_stack.currentWidget(), window.settings_page)
                self.assertTrue(hasattr(window, "settings_tabs"))
                self.assertNotIn("settings", window._startup_lazy_placeholders)
            finally:
                window.close()
                self.qt_app.processEvents()

    def test_imports_first_navigation_reflows_without_window_resize(self):
        with tempfile.TemporaryDirectory(prefix="invoice-hub-startup-lazy-imports-") as td:
            window = startup_lifecycle.FirstPaintDeferredInvoiceReviewApp(
                Path(td) / "startup.db",
                splash=None,
            )
            try:
                # Keep this contract independent of the CI runner's physical
                # 1024x768 desktop. 1276x875 is the product viewport under test;
                # no native show/WM clamp is needed to verify the lazy-page
                # lifecycle. There is deliberately no resize between first
                # navigation and the responsive assertions below.
                window.resize(1276, 875)
                window._nav_collapsed_manual = True
                window._apply_workbench_metrics(1276, 875)

                self.assertEqual(
                    window.imports_page.property("startupDeferredPage"),
                    "imports",
                )
                window._switch_main_page("imports")
                for _ in range(4):
                    self.qt_app.processEvents()

                self.assertIs(window.center_stack.currentWidget(), window.imports_page)
                self.assertNotIn("imports", window._startup_lazy_placeholders)
                self.assertTrue(window._nav_compact)
                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(
                    window.import_source_card.body_layout.direction(),
                    QBoxLayout.LeftToRight,
                )
                # The Imports builder starts with a stacked/default geometry.
                # Reaching the wide mail-task contract here proves that the
                # post-switch reflow ran without a user resize event.
                self.assertEqual(window.import_main_row_layout.direction(), QBoxLayout.LeftToRight)
                self.assertEqual(window.import_task_stack.maximumWidth(), 900)
            finally:
                window.close()
                self.qt_app.processEvents()

    def test_launch_review_reflows_after_real_first_paint_without_resize(self):
        with tempfile.TemporaryDirectory(prefix="invoice-hub-startup-review-geometry-") as td:
            window = startup_lifecycle.FirstPaintDeferredInvoiceReviewApp(
                Path(td) / "startup.db",
                splash=None,
            )
            try:
                window.resize(1700, 900)
                startup_lifecycle.reveal_startup_window(window, splash=None)
                for _ in range(6):
                    self.qt_app.processEvents()

                self.assertTrue(window._startup_first_paint_seen)
                self.assertIs(window.center_stack.currentWidget(), window.review_page)
                usable = (
                    window.main_splitter.width()
                    - window.main_splitter.handleWidth() * (window.main_splitter.count() - 1)
                )
                sizes = window.main_splitter.sizes()
                self.assertEqual(len(sizes), 2)
                self.assertLessEqual(abs(sum(sizes) - usable), 2)
                self.assertGreaterEqual(sizes[0], 720)
                self.assertGreaterEqual(sizes[1], 352)
                self.assertLessEqual(sizes[1], 520)
            finally:
                window.close()
                self.qt_app.processEvents()


if __name__ == "__main__":
    unittest.main()
