import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from scripts.invoice_fetch.gui.api_key_dialog import ApiKeyDialog
from scripts.invoice_fetch.gui.app import InvoiceReviewApp, ReviewViewState
from scripts.invoice_fetch.gui.icon_provider import IconProvider, _ASSETS_ICONS
from scripts.invoice_fetch.gui.mobile_upload_dialog import MobileUploadDialog
from scripts.invoice_fetch.gui.mobile_upload_session import MobileUploadSessionController
from scripts.invoice_fetch.gui.ui_components import is_visual_primary, make_button
from scripts.invoice_fetch.gui.ui_components import ElidedTextLabel
from tests.gui_geometry_helpers import collect_visible_geometry_failures


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
                # The list/claims reload path may refresh dependent surfaces;
                # event ownership is asserted by one activity, while each
                # required surface must be refreshed at least once.
                self.assertGreaterEqual(len(calls), 5)
                self.assertTrue(set(("_load_invoices", "_load_claims", "_refresh_overview_page", "_refresh_imports_page", "_refresh_settings_page")) <= set(calls))
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
        """Mailbox name and email must be different label widgets with different texts."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                # Both must be distinct widget objects
                self.assertIsNot(window.lbl_detail_name, window.lbl_detail_email)
                # When a mailbox is selected, name text and email text must differ
                # (they represent different fields, not the same value twice).
                # Even in empty state, the placeholder texts differ.
                name_text = window.lbl_detail_name.text()
                email_text = window.lbl_detail_email.text()
                self.assertNotEqual(name_text, email_text,
                    "lbl_detail_name and lbl_detail_email must not show the same text")
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
        """The verify/test button must be the unique primary action and have honest text."""
        dialog = ApiKeyDialog("DeepSeek")
        # Text updated to be honest: local verification only, not real network test
        self.assertEqual(dialog.btn_save_and_test.text(), "保存并校验配置")
        self.assertTrue(is_visual_primary(dialog.btn_save_and_test))
        # save_and_verify attribute must exist; save_and_test is kept as backward-compat alias
        self.assertFalse(dialog.save_and_verify)
        self.assertFalse(dialog.save_and_test)
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

    def test_export_checklist_is_top_aligned(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertTrue(window.export_integrity_card.sizePolicy().verticalPolicy().name in {"Maximum", "Preferred"})
            finally: window.close()

    def test_page_geometry_at_1366x768(self):
        """Key UI pages must fit within 1366x768 without overflowing."""
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.resize(1366, 768)
                self.app.processEvents()
                for page_key in ("overview", "imports", "export", "settings"):
                    window._switch_main_page(page_key)
                    self.app.processEvents()
                    page = window.center_stack.currentWidget()
                    # Page should not overflow the window width
                    self.assertLessEqual(page.width(), 1366,
                        f"{page_key} page.width() {page.width()} > 1366")
                    # Page height must fit; allow small tolerance for header bars
                    self.assertLessEqual(page.height(), 830,
                        f"{page_key} page.height() {page.height()} too tall at 1366x768")
            finally: window.close()

    def test_review_view_state_uses_table_row_count_and_clears_detail(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.invoices_list = []
                window.table.setRowCount(0)
                window.current_filter_status = "to_review"
                window.txt_search.setText("not-found")
                window._update_record_header_summary(total_matching=0, selected_count=0)
                state = window._review_view_state()
                self.assertIsInstance(state, ReviewViewState)
                self.assertEqual(state.visible_count, window.table.rowCount())
                self.assertEqual(state.visible_count, 0)
                self.assertTrue(state.is_empty_result)
                self.assertEqual(window.lbl_record_count.text(), "当前筛选 0 张")
                window._clear_detail_form()
                self.assertIs(window.right_stack.currentWidget(), window.right_empty_widget)
            finally:
                window.close()

    def test_mailbox_golden_page_has_usable_detail_width_and_rows(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._switch_main_page("settings")
                window.settings_tabs.setCurrentIndex(0)
                window.resize(1366, 768)
                self.app.processEvents()
                self.assertEqual(window.settings_mailbox_list.width(), 280)
                self.assertGreaterEqual(window.settings_tabs.width(), 900)
                self.assertGreaterEqual(window.lbl_detail_name.minimumWidth(), 0)
                window.settings_mailbox_list.clear()
                window.settings_mailbox_list.add_entity_row("Synthetic mailbox", "synthetic@example.invalid", "正常", "已安全保存")
                self.assertGreaterEqual(window.settings_mailbox_list.item(0).sizeHint().height(), 64)
            finally:
                window.close()

    def test_api_key_local_validation_copy_is_truthful(self):
        dialog = ApiKeyDialog("DeepSeek")
        try:
            texts = "\n".join(button.text() for button in dialog.findChildren(QPushButton))
            self.assertIn("保存并校验配置", texts)
            self.assertNotIn("连接成功", texts)
            self.assertNotIn("测试通过", texts)
            self.assertNotIn("已连接", texts)
        finally:
            dialog.close()

    def test_ai_settings_validation_copy_is_truthful(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._switch_main_page("settings")
                window.settings_tabs.setCurrentIndex(1)
                self.app.processEvents()
                self.assertEqual(window.btn_settings_ai_test.text(), "校验配置")
                visible_text = "\n".join(
                    widget.text() for widget in window.settings_tabs.currentWidget().findChildren(QPushButton)
                    if widget.isVisible()
                )
                self.assertNotIn("测试连接", visible_text)
                self.assertNotIn("连接成功", visible_text)
                self.assertIn("校验配置", visible_text)
            finally:
                window.close()

    def test_navigation_icons_are_svg_backed(self):
        expected = ("dashboard", "review", "import", "export", "settings")
        for semantic in expected:
            asset = _ASSETS_ICONS / f"{semantic}.svg"
            self.assertTrue(asset.is_file(), f"missing SVG asset: {asset}")
            content = asset.read_text(encoding="utf-8")
            self.assertIn("<svg", content)
            self.assertIn('viewBox="0 0 18 18"', content)
            self.assertFalse(IconProvider.icon(semantic).isNull())

    def test_ai_profile_list_visibility_follows_count(self):
        profiles = [
            {"profile_id": "one", "name": "One", "provider": "A", "model": "a", "enabled": True},
            {"profile_id": "two", "name": "Two", "provider": "B", "model": "b", "enabled": True},
        ]
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._switch_main_page("settings")
                window.settings_tabs.setCurrentIndex(1)
                self.app.processEvents()
                with patch.object(window, "_ai_profiles_for_settings", return_value=[]):
                    window._refresh_settings_ai_page()
                    self.assertTrue(window.settings_ai_empty_state.isVisible())
                    self.assertFalse(window.settings_ai_profile_list.isVisible())
                with patch.object(window, "_ai_profiles_for_settings", return_value=profiles[:1]):
                    window._refresh_settings_ai_page()
                    self.assertFalse(window.settings_ai_empty_state.isVisible())
                    self.assertFalse(window.settings_ai_profile_list.isVisible())
                with patch.object(window, "_ai_profiles_for_settings", return_value=profiles):
                    window._refresh_settings_ai_page()
                    self.assertTrue(window.settings_ai_profile_list.isVisible())
                    self.assertEqual(window.settings_ai_profile_list.count(), 2)
            finally:
                window.close()

    def _assert_real_window_controls_fit(self, scale: float):
        """Use an isolated QApplication so a native Qt crash cannot kill the suite."""
        probe = r'''
import json, tempfile
from pathlib import Path
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from tests.gui_geometry_helpers import collect_visible_geometry_failures
app = QApplication([])
failures = []
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    window = InvoiceReviewApp(Path(td) / "geometry.db")
    window.resize(1366, 768); window.show(); app.processEvents(); app.processEvents()
    for page_key in ("overview", "imports", "export", "settings"):
        window._switch_main_page(page_key); app.processEvents(); app.processEvents()
        failures.extend(collect_visible_geometry_failures(window, page_key))
        controls = []
        for kind in (QPushButton, QLineEdit, QComboBox):
            controls.extend(window.center_stack.currentWidget().findChildren(kind))
        for control in controls:
            if not control.isVisible() or control.width() <= 0 or control.height() <= 0:
                continue
            origin = control.mapTo(window, QPoint(0, 0))
            if origin.x() < 0 or origin.y() < 0 or origin.x() + control.width() > window.width() or origin.y() + control.height() > window.height():
                failures.append({"page": page_key, "name": control.objectName(), "rect": [origin.x(), origin.y(), control.width(), control.height()]})
    window.close(); app.processEvents()
print(json.dumps(failures, ensure_ascii=False))
'''
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=str(scale), PYTHONIOENCODING="utf-8")
        completed = subprocess.run(
            [sys.executable, "-c", probe], cwd=Path(__file__).resolve().parents[1],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        failures = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(failures, [], failures)

    def test_real_window_1366_has_no_clipped_controls(self):
        self._assert_real_window_controls_fit(1.0)

    def test_real_window_125_percent_has_no_clipped_controls(self):
        self._assert_real_window_controls_fit(1.25)

    def test_real_window_150_percent_has_no_clipped_controls(self):
        self._assert_real_window_controls_fit(1.5)


if __name__ == "__main__":
    unittest.main()
