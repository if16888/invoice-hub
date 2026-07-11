import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from scripts.invoice_fetch.gui.api_key_dialog import ApiKeyDialog
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.mobile_upload_dialog import MobileUploadDialog
from scripts.invoice_fetch.gui.mobile_upload_session import MobileUploadSessionController
from scripts.invoice_fetch.gui.ui_components import is_visual_primary, make_button
from scripts.invoice_fetch.gui.ui_components import AdaptiveButton, ElidedTextLabel


class IHDS09Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "ihds09.db")
        window.show(); self.app.processEvents()
        return window

    def test_all_mobile_entries_open_embedded_task(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                with patch.object(MobileUploadDialog, "exec", side_effect=AssertionError("legacy dialog reached")):
                    for entry in (window.action_import_mobile, window.action_mobile_upload):
                        window._switch_main_page("review")
                        entry.trigger(); self.app.processEvents()
                        self.assertIs(window.center_stack.currentWidget(), window.imports_page)
                        self.assertEqual(window._selected_import_source, "mobile")
                    window._mobile_upload_clicked(); self.app.processEvents()
                    self.assertEqual(window._selected_import_source, "mobile")
            finally: window.close()

    def test_legacy_mobile_dialog_is_not_reachable(self):
        import inspect
        source = inspect.getsource(InvoiceReviewApp._mobile_upload_clicked)
        self.assertNotIn("MobileUploadDialog", source)
        self.assertNotIn("exec", source)

    def test_app_handles_upload_event_once(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                calls = []
                for name in ("_load_invoices", "_load_claims", "_refresh_overview_page", "_refresh_imports_page", "_refresh_settings_page"):
                    setattr(window, name, lambda n=name: calls.append(n))
                window.mobile_upload_controller.upload_received.emit({
                    "batch_id": "batch-1", "accepted": 1, "imported": 1,
                    "duplicate": 0, "failed": 0,
                })
                self.app.processEvents()
                self.assertEqual(len(window._import_activities), 1)
                self.assertEqual(len(calls), 5)
            finally: window.close()

    def test_mobile_panel_has_idle_starting_active_error_states(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                panel = window.mobile_upload_panel
                self.assertEqual(panel.stack.count(), 4)
                panel.controller.starting.emit(); self.assertIs(panel.stack.currentWidget(), panel.starting_page)
                panel.controller.failed.emit("端口不可用"); self.assertIs(panel.stack.currentWidget(), panel.error_page)
                self.assertIn("端口不可用", panel.lbl_error.text())
            finally: window.close()

    def test_mobile_start_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                panel = window.mobile_upload_panel
                panel.controller.failed.emit("未找到可用网络")
                self.assertTrue(panel.error_page.isVisibleTo(panel))
                self.assertIn("未找到可用网络", panel.lbl_error.text())
            finally: window.close()

    def test_mobile_activity_updates_same_batch(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._mobile_upload_finished({"batch_id": "same", "accepted": 1, "imported": 1})
                window._mobile_upload_finished({"batch_id": "same", "accepted": 3, "imported": 3})
                self.assertEqual(len(window._import_activities), 1)
                self.assertEqual(window._import_activities[0].added, 3)
            finally: window.close()

    def test_mobile_network_selection_matches_session_host(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                controller = window.mobile_upload_controller
                controller.host_options = [
                    SimpleNamespace(label="Virtual", host="172.16.0.1"),
                    SimpleNamespace(label="WLAN", host="192.168.1.9"),
                ]
                session = SimpleNamespace(host="192.168.1.9", port=8080, upload_url="http://192.168.1.9:8080/u/x")
                with patch.object(controller, "qr_png", return_value=b""):
                    controller.started.emit(session)
                self.assertEqual(window.mobile_upload_panel.combo_upload_host.currentData(), session.host)
            finally: window.close()

    def test_shutdown_waits_for_start_thread(self):
        controller = MobileUploadSessionController(Path("unused.db"))
        thread = MagicMock()
        thread.isRunning.return_value = True
        thread.wait.return_value = False
        controller._start_thread = thread
        self.assertFalse(controller.shutdown(timeout_ms=1))
        thread.wait.assert_called_once_with(1)

    def test_database_closes_after_mobile_shutdown(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            order = []
            real_close = window.db.close
            try:
                with patch.object(window.mobile_upload_controller, "shutdown", side_effect=lambda: (order.append("mobile"), True)[1]), \
                     patch.object(window.db, "close", side_effect=lambda: (order.append("db"), real_close())[1]):
                    window.close(); self.app.processEvents()
                self.assertEqual(order, ["mobile", "db"])
            finally:
                if window.isVisible(): window.close()

    def test_visual_primary_helper_recognizes_variant_and_emphasis(self):
        variant = make_button("Variant", variant="primary")
        emphasis = QPushButton("Emphasis"); emphasis.setProperty("emphasis", "primary")
        secondary = make_button("Secondary", variant="secondary")
        self.assertTrue(is_visual_primary(variant))
        self.assertTrue(is_visual_primary(emphasis))
        self.assertFalse(is_visual_primary(secondary))

    def test_page_archetypes_use_shared_layout_contracts(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertEqual(window.overview_page.property("pageArchetype"), "dashboard")
                self.assertEqual(window.review_page.property("pageArchetype"), "workspace")
                self.assertEqual(window.imports_page.property("pageArchetype"), "task_flow")
                self.assertEqual(window.export_page.property("pageArchetype"), "task_flow")
                self.assertEqual(window.settings_page.property("pageArchetype"), "settings")
            finally: window.close()

    def test_settings_content_is_centered_and_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.resize(1920, 1080); window._switch_main_page("settings"); self.app.processEvents()
                self.assertLessEqual(window.settings_tabs.width(), 1120)
                self.assertLess(abs(window.settings_page.rect().center().x() - window.settings_tabs.geometry().center().x()), 40)
            finally: window.close()

    def test_mailbox_page_uses_master_detail_without_summary(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertEqual(window.settings_mailbox_list.width(), 280)
                self.assertFalse(hasattr(window, "stat_box_overview"))
                self.assertTrue(hasattr(window, "lbl_detail_email"))
            finally: window.close()

    def test_api_key_uses_custom_dialog_and_show_hide(self):
        dialog = ApiKeyDialog("DeepSeek")
        self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Password)
        dialog.btn_show_hide.setChecked(True)
        self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Normal)
        self.assertTrue(is_visual_primary(dialog.btn_save_and_test))
        self.assertFalse(is_visual_primary(dialog.btn_save))
        dialog.close()

    def test_primary_pages_have_at_most_one_visual_primary(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for page in (window.overview_page, window.imports_page, window.export_page, window.settings_page):
                    visible = [b for b in page.findChildren(QPushButton) if b.isVisible() and is_visual_primary(b)]
                    self.assertLessEqual(len(visible), 1)
            finally: window.close()

    def test_mailbox_page_uses_master_detail(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertEqual(window.settings_mailbox_list.width(), 280)
                self.assertTrue(hasattr(window, "lbl_detail_server"))
                self.assertTrue(hasattr(window, "lbl_settings_mailbox_scan_result"))
            finally: window.close()

    def test_mailbox_page_has_no_visible_summary_strip(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try: self.assertFalse(hasattr(window, "stat_box_overview"))
            finally: window.close()

    def test_mailbox_identity_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                detail_values = [window.lbl_detail_name, window.lbl_detail_email]
                self.assertEqual(len({id(label) for label in detail_values}), 2)
            finally: window.close()

    def test_mailbox_has_one_contextual_primary(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                buttons = [window.btn_settings_mailbox_add_credential, window.btn_settings_mailbox_scan]
                self.assertLessEqual(sum(is_visual_primary(button) for button in buttons), 1)
            finally: window.close()

    def test_provider_picker_only_exists_in_add_flow(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertEqual(len(window.btn_settings_mailbox_add.menu().actions()), 5)
                self.assertFalse(hasattr(window, "v11_preset_buttons"))
            finally: window.close()

    def test_ai_single_profile_has_no_profile_list(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try: self.assertFalse(window.settings_ai_profile_list.isVisible())
            finally: window.close()

    def test_ai_single_profile_has_no_summary_duplication(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try: self.assertFalse(hasattr(window, "settings_ai_summary_strip"))
            finally: window.close()

    def test_api_key_uses_custom_dialog(self):
        import inspect
        source = inspect.getsource(InvoiceReviewApp._configure_settings_ai_key)
        self.assertIn("ApiKeyDialog", source)
        self.assertNotIn("QInputDialog", source)

    def test_api_key_dialog_supports_show_hide(self):
        dialog = ApiKeyDialog("DeepSeek")
        dialog.btn_show_hide.setChecked(True); self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Normal)
        dialog.btn_show_hide.setChecked(False); self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Password)
        dialog.close()

    def test_api_key_dialog_has_save_and_test(self):
        dialog = ApiKeyDialog("DeepSeek")
        self.assertEqual(dialog.btn_save_and_test.text(), "保存并测试")
        self.assertTrue(is_visual_primary(dialog.btn_save_and_test))
        dialog.close()

    def test_wide_page_primary_is_not_full_width(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.resize(1920, 1080); window._switch_main_page("export"); self.app.processEvents()
                self.assertLess(window.btn_run_export_page.width(), window.export_integrity_card.width())
            finally: window.close()

    def test_visible_nav_uses_unified_icons(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for key in ("overview", "review", "imports", "export", "settings"):
                    self.assertFalse(window.workbench_nav_buttons[key].icon().isNull())
            finally: window.close()

    def test_no_visible_nav_uses_emoji(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for key in ("overview", "review", "imports", "export", "settings"):
                    self.assertNotRegex(window.workbench_nav_buttons[key].text(), r"[\U0001F300-\U0001FAFF]")
            finally: window.close()

    def test_long_values_have_tooltips(self):
        value = "very-long-value-" * 20
        label = ElidedTextLabel(value)
        self.assertEqual(label.toolTip(), value)

    def _assert_adaptive_button_at_scale(self, scale):
        button = AdaptiveButton("保存并测试")
        font = button.font(); font.setPointSizeF(max(9.0, font.pointSizeF()) * scale); button.setFont(font)
        button.refresh_adaptive_width()
        self.assertGreaterEqual(button.minimumWidth(), button.fontMetrics().horizontalAdvance(button.text()) + 28)

    def test_controls_do_not_clip_at_125_percent(self):
        self._assert_adaptive_button_at_scale(1.25)

    def test_controls_do_not_clip_at_150_percent(self):
        self._assert_adaptive_button_at_scale(1.5)

    def test_export_checklist_is_top_aligned(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertTrue(window.export_integrity_card.sizePolicy().verticalPolicy().name in {"Maximum", "Preferred"})
            finally: window.close()


if __name__ == "__main__":
    unittest.main()
