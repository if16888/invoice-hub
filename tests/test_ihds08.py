import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QBoxLayout, QPushButton

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.mobile_upload_dialog import MobileUploadDialog


class IHDS08Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "invoices.db")
        window.show(); self.app.processEvents()
        return window

    def test_collapsed_nav_footer_is_icon_only(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.resize(1366, 768); self.app.processEvents()
                for button in (window.btn_shortcut_help, window.btn_collapse_nav):
                    self.assertEqual(button.text(), "")
                    self.assertEqual((button.width(), button.height()), (40, 40))
                    self.assertTrue(button.toolTip())
                    self.assertTrue(button.accessibleName())
                    self.assertFalse(button.icon().isNull())
            finally: window.close()

    def test_import_page_has_no_visible_mail_summary_strip(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertFalse(hasattr(window, "imports_summary_strip"))
            finally: window.close()

    def test_mobile_source_is_embedded_and_does_not_open_dialog(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                with patch.object(MobileUploadDialog, "exec", side_effect=AssertionError("modal opened")):
                    window._select_import_source("mobile")
                    self.app.processEvents()
                self.assertIs(window.import_task_stack.currentWidget(), window.import_mobile_task_card)
                self.assertFalse(window.mobile_upload_panel.isHidden())
                self.assertIs(window.mobile_upload_panel.stack.currentWidget(), window.mobile_upload_panel.idle_page)
            finally: window.close()

    def test_mobile_start_active_and_stop_idle(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                panel = window.mobile_upload_panel
                session = SimpleNamespace(upload_url="http://192.168.1.2:1234/u/test", host="192.168.1.2", port=1234)
                with patch.object(panel.controller, "qr_png", return_value=b""):
                    panel.controller.started.emit(session)
                self.assertIs(panel.stack.currentWidget(), panel.active_page)
                self.assertIn("/u/", panel.txt_url.text())
                panel.controller.stopped.emit()
                self.assertIs(panel.stack.currentWidget(), panel.idle_page)
            finally: window.close()

    def test_controller_is_shared_with_legacy_dialog(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            dialog = None
            try:
                with patch.object(window.mobile_upload_controller, "start", return_value=None):
                    with patch.object(MobileUploadDialog, "_start_server"):
                        dialog = MobileUploadDialog(window, window.db_path)
                self.assertIs(dialog.controller, window.mobile_upload_controller)
            finally:
                if dialog: dialog.close()
                window.close()

    def test_import_layout_adapts_below_1200(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._apply_workbench_metrics(1100, 800)
                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                self.assertEqual(window.import_task_stack.maximumWidth(), 16777215)
                window._apply_workbench_metrics(1600, 900)
                self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.LeftToRight)
                self.assertEqual(window.import_task_stack.maximumWidth(), 900)
            finally: window.close()

    def test_mobile_task_has_at_most_one_primary(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                primaries = [b for b in window.mobile_upload_panel.findChildren(QPushButton)
                             if b.isVisible() and b.property("class") == "PrimaryBtn"]
                self.assertLessEqual(len(primaries), 1)
            finally: window.close()

    def test_window_close_stops_mobile_before_database(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            order = []
            real_close = window.db.close
            try:
                window.mobile_upload_controller.timer.start()
                with patch.object(window.mobile_upload_controller, "shutdown", side_effect=lambda: order.append("mobile")), \
                     patch.object(window.db, "close", side_effect=lambda: (order.append("database"), real_close())[1]):
                    window.close(); self.app.processEvents()
                self.assertEqual(order, ["mobile", "database"])
            finally:
                if window.isVisible(): window.close()

    def test_mobile_timer_is_inactive_after_window_close(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            controller = window.mobile_upload_controller
            controller.timer.start()
            window.close(); self.app.processEvents()
            self.assertFalse(controller.timer.isActive())

    def test_mobile_upload_activity_uses_real_counts(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._mobile_upload_finished({"accepted": 4, "imported": 2, "duplicate": 1, "failed": 1})
                activity = window._import_activities[0]
                self.assertEqual((activity.added, activity.duplicates, activity.failed), (2, 1, 1))
            finally: window.close()

    def test_mobile_upload_does_not_create_zero_result_activity(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._mobile_upload_finished({"accepted": 0, "imported": 0, "duplicate": 0, "failed": 0})
                self.assertEqual(window._import_activities, [])
            finally: window.close()

    def test_legacy_dialog_close_does_not_stop_shared_session(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            with patch.object(MobileUploadDialog, "_start_server"):
                dialog = MobileUploadDialog(window, window.db_path)
            try:
                with patch.object(window.mobile_upload_controller, "stop") as stop:
                    dialog.close(); self.app.processEvents()
                    stop.assert_not_called()
            finally: window.close()

    def test_mobile_start_is_async_and_duplicate_click_is_ignored(self):
        from scripts.invoice_fetch.mobile_upload import UploadHostOption
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            controller = window.mobile_upload_controller
            def slow_hosts():
                time.sleep(0.25)
                return [UploadHostOption("127.0.0.1", "loopback", "Local", False, 0)]
            try:
                with patch("scripts.invoice_fetch.mobile_upload.enumerate_upload_hosts", side_effect=slow_hosts):
                    started_at = time.perf_counter()
                    controller.start()
                    first_thread = controller._start_thread
                    controller.start()
                    self.assertLess(time.perf_counter() - started_at, 0.15)
                    self.assertIs(controller._start_thread, first_thread)
                    controller.shutdown()
            finally: window.close()

    def test_runtime_activity_is_limited_to_three_visible_rows(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for value in range(5):
                    window._record_import_activity("local", added=value + 1)
                window._refresh_imports_page()
                self.assertEqual(window.import_recent_timeline.layout().count(), 3)
                self.assertEqual(window.import_mail_recent_card.lbl_title.text(), "本次运行")
            finally: window.close()

    def test_wide_import_workspace_is_centered_and_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.resize(1920, 1080)
                window._switch_main_page("imports")
                self.app.processEvents()
                self.assertLessEqual(window.imports_workspace_host.width(), 1440)
                page_center = window.imports_page.rect().center().x()
                host_center = window.imports_workspace_host.geometry().center().x()
                self.assertLess(abs(page_center - host_center), 30)
            finally: window.close()


if __name__ == "__main__":
    unittest.main()
