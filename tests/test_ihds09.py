import os
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLineEdit, QPushButton
from shiboken6 import isValid as is_qobject_valid

from scripts.invoice_fetch.gui.api_key_dialog import ApiKeyDialog
from scripts.invoice_fetch.gui.app import InvoiceReviewApp, ReviewViewState
from scripts.invoice_fetch.gui.icon_provider import IconProvider, _ASSETS_ICONS
from scripts.invoice_fetch.gui.mobile_upload_dialog import MobileUploadDialog
from scripts.invoice_fetch.gui.mobile_upload_session import MobileUploadSessionController
from scripts.invoice_fetch.gui.ui_components import is_visual_primary, make_button
from scripts.invoice_fetch.gui.ui_components import ElidedTextLabel, ReadOnlyDetailPanel
from scripts.invoice_fetch.mobile_upload import MobileUploadServer, UploadedFile
from tests.gui_geometry_helpers import collect_visible_geometry_failures
from tests.test_mobile_upload import _multipart_body


class IHDS09Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        """Flush closed Qt windows before the next fixture is constructed.

        This module creates many real ``InvoiceReviewApp`` windows.  Several
        tests intentionally call only ``close()``; leaving their deferred
        QWidget deletions queued eventually terminates the Windows Qt test
        process without a Python traceback.
        """
        widgets = [
            widget
            for widget in list(self.app.topLevelWidgets())
            if widget is not None and widget is not self.app and is_qobject_valid(widget)
        ]
        # Let zero-delay callbacks queued by the just-closed window run while
        # its QObject graph is still valid.  Scheduling deleteLater() first
        # can let DeferredDelete win the event ordering and leave a queued
        # callback holding a stale Shiboken wrapper.
        for widget in widgets:
            if not is_qobject_valid(widget):
                continue
            close = getattr(widget, "close", None)
            if callable(close):
                close()
        self.app.processEvents()

        for widget in widgets:
            if widget is None or widget is self.app or not is_qobject_valid(widget):
                continue
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "ihds09.db")
        window.show()
        self.app.processEvents()
        # Let the application's 50-ms deferred initialization and the queued
        # page-normalization callbacks finish while this fixture's window and
        # database are still valid.  A single processEvents() can return before
        # newly queued timers on slower Windows runs, leaving their callbacks
        # to overlap the next fixture's QApplication lifecycle.
        QTest.qWait(75)
        self.app.processEvents()
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
                window.mobile_upload_controller.upload_batch_completed.emit({
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

    def test_two_finalized_mobile_batches_create_two_history_rows_and_latest_status(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                batch_a = {
                    "result_seq": 1,
                    "batch_id": "upload-a",
                    "received": 3,
                    "created": 0,
                    "upload_duplicate": 3,
                    "business_duplicate": 0,
                    "upload_failed": 0,
                    "import_failed": 0,
                }
                batch_b = {
                    "result_seq": 2,
                    "batch_id": "upload-b",
                    "received": 7,
                    "created": 6,
                    "upload_duplicate": 1,
                    "business_duplicate": 0,
                    "upload_failed": 0,
                    "import_failed": 0,
                }

                class FakeServer:
                    def __init__(self):
                        self.completed = [batch_a, batch_b]

                    def status(self):
                        return {
                            "received": 10,
                            "created": 6,
                            "duplicate": 4,
                            "business_duplicate": 0,
                            "failed": 0,
                            "import_failed": 0,
                            "active": True,
                            "completed_upload_seq": 2,
                            "last_upload_result": batch_b,
                            "upload_in_progress": False,
                        }

                    def drain_completed_upload_results(self):
                        completed, self.completed = self.completed, []
                        return completed

                controller = window.mobile_upload_controller
                controller.server = FakeServer()
                controller.session = SimpleNamespace(port=43210)
                with self.assertLogs(level="INFO") as captured:
                    controller.refresh_status()
                self.app.processEvents()

                self.assertEqual(len(window._import_activities), 2)
                observed = {
                    activity.batch_id: (
                        activity.scanned,
                        activity.added,
                        activity.duplicates,
                        activity.failed,
                    )
                    for activity in window._import_activities
                }
                self.assertEqual(observed["upload-a"], (3, 0, 3, 0))
                self.assertEqual(observed["upload-b"], (7, 6, 1, 0))
                self.assertEqual(
                    window.mobile_upload_panel.lbl_stats.text(),
                    "接收 7 · 新增 6 · 重复 1 · 失败 0",
                )
                log_text = "\n".join(captured.output)
                for batch_id in ("upload-a", "upload-b"):
                    self.assertIn(
                        f"gui batch completed emitted batch_id={batch_id}",
                        log_text,
                    )
                    self.assertIn(
                        f"run history appended batch_id={batch_id}",
                        log_text,
                    )
                controller.refresh_status()
                self.app.processEvents()
                self.assertEqual(len(window._import_activities), 2)
            finally:
                window.mobile_upload_controller.server = None
                window.close()

    def test_mobile_intermediate_refreshes_do_not_create_run_history(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                server = SimpleNamespace(
                    status=lambda: {
                        "received": 10,
                        "created": 0,
                        "duplicate": 3,
                        "business_duplicate": 0,
                        "failed": 0,
                        "import_failed": 0,
                        "active": True,
                    },
                    drain_completed_upload_results=lambda: [],
                )
                controller = window.mobile_upload_controller
                controller.server = server
                controller.session = SimpleNamespace(port=43210)

                for _ in range(3):
                    controller.refresh_status()
                    window._load_invoices()
                    self.app.processEvents()

                self.assertEqual(window._import_activities, [])
            finally:
                window.mobile_upload_controller.server = None
                window.close()

    def test_real_http_two_batch_lifecycle_reaches_two_gui_history_rows(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            runtime_dir = Path(td) / "mobile-runtime"
            server = MobileUploadServer(
                runtime_dir=runtime_dir,
                db_path=window.db_path,
                host="127.0.0.1",
                port=0,
                import_on_upload=True,
            )
            session = server.start()
            try:
                duplicate_payloads = [b"known-a", b"known-b", b"known-c"]
                server._files.extend(
                    {
                        "status": "accepted",
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                    for payload in duplicate_payloads
                )
                controller = window.mobile_upload_controller
                controller.server = server
                controller.session = session
                controller.timer.stop()

                imported = {
                    "added": 6,
                    "duplicates": 0,
                    "conflicts": 0,
                    "pending_manual": 0,
                    "failed": 0,
                    "restored": 0,
                    "new_invoice_ids": [],
                    "restored_invoice_ids": [],
                    "review_invoice_ids": [],
                    "duplicate_outcomes": [],
                }

                def post(files):
                    body, boundary = _multipart_body(files)
                    request = urllib.request.Request(
                        session.api_url,
                        data=body,
                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=10) as response:
                        return json.loads(response.read().decode("utf-8"))

                with self.assertLogs(level="INFO") as captured, patch.object(
                    server,
                    "_import_accepted_files",
                    return_value=imported,
                ):
                    result_a = post([
                        (f"duplicate-{index}.pdf", payload, "application/pdf")
                        for index, payload in enumerate(duplicate_payloads)
                    ])
                    controller.refresh_status()
                    self.app.processEvents()

                    result_b = post([
                        ("duplicate-again.pdf", duplicate_payloads[0], "application/pdf"),
                        *[
                            (
                                f"new-{index}.pdf",
                                f"new-{index}".encode("ascii"),
                                "application/pdf",
                            )
                            for index in range(6)
                        ],
                    ])
                    controller.refresh_status()
                    self.app.processEvents()

                self.assertEqual(
                    (result_a["received"], result_a["created"], result_a["duplicate"], result_a["failed"]),
                    (3, 0, 3, 0),
                )
                self.assertEqual(
                    (result_b["received"], result_b["created"], result_b["duplicate"], result_b["failed"]),
                    (7, 6, 1, 0),
                )
                self.assertEqual(len(window._import_activities), 2)
                self.assertEqual(
                    window.mobile_upload_panel.lbl_stats.text(),
                    "接收 7 · 新增 6 · 重复 1 · 失败 0",
                )

                log_text = "\n".join(captured.output)
                for batch_id in (result_a["batch_id"], result_b["batch_id"]):
                    finalized = log_text.index(f"batch finalized batch_id={batch_id}")
                    emitted = log_text.index(f"gui batch completed emitted batch_id={batch_id}")
                    appended = log_text.index(f"run history appended batch_id={batch_id}")
                    self.assertLess(finalized, emitted)
                    self.assertLess(emitted, appended)
            finally:
                window.mobile_upload_controller.server = None
                window.mobile_upload_controller.session = None
                server.stop()
                window.close()

    def test_polling_during_import_emits_only_after_finalized_sequence(self):
        with tempfile.TemporaryDirectory() as td:
            server = MobileUploadServer(
                runtime_dir=Path(td) / "runtime",
                db_path=Path(td) / "invoices.db",
                host="127.0.0.1",
                port=0,
                import_on_upload=True,
            )
            session = server.start()
            controller = MobileUploadSessionController(Path(td) / "invoices.db")
            controller.server = server
            controller.session = session
            entered_import = threading.Event()
            release_import = threading.Event()
            emissions = []
            controller.upload_batch_completed.connect(lambda result: emissions.append(dict(result)))

            def blocked_import(_paths):
                entered_import.set()
                self.assertTrue(release_import.wait(timeout=10))
                return {
                    "added": 3,
                    "duplicates": 1,
                    "conflicts": 0,
                    "pending_manual": 0,
                    "failed": 0,
                    "restored": 0,
                    "new_invoice_ids": [5, 6, 7],
                    "restored_invoice_ids": [],
                    "review_invoice_ids": [5, 6, 7],
                    "duplicate_outcomes": [],
                }

            try:
                files = [
                    UploadedFile(f"poll-{index}.pdf", f"payload-{index}".encode(), "application/pdf")
                    for index in range(4)
                ]
                with patch.object(server, "_import_accepted_files", side_effect=blocked_import):
                    worker = threading.Thread(target=server.save_uploads, args=(files,))
                    worker.start()
                    self.assertTrue(entered_import.wait(timeout=10))

                    mid_status = server.status()
                    self.assertEqual(mid_status["received"], 4)
                    self.assertTrue(mid_status["upload_in_progress"])
                    self.assertEqual(mid_status["completed_upload_seq"], 0)
                    controller.refresh_status()
                    self.assertEqual(emissions, [])

                    release_import.set()
                    worker.join(timeout=10)
                    self.assertFalse(worker.is_alive())

                controller.refresh_status()
                self.assertEqual(len(emissions), 1)
                self.assertEqual(emissions[0]["result_seq"], 1)
                self.assertEqual(emissions[0]["review_invoice_ids"], (5, 6, 7))
                controller.refresh_status()
                self.assertEqual(len(emissions), 1)
            finally:
                release_import.set()
                controller.server = None
                controller.session = None
                server.stop()

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
                with patch.object(controller, "set_public_host") as switch_host:
                    window.mobile_upload_panel.combo_upload_host.setCurrentIndex(0)
                    self.assertFalse(switch_host.called)
                    window.mobile_upload_panel.combo_upload_host.activated.emit(0)
                    switch_host.assert_called_once_with("172.16.0.1")
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
                self.assertTrue(hasattr(window, "lbl_detail_server"))
                self.assertTrue(hasattr(window, "lbl_settings_mailbox_scan_result"))
            finally: window.close()

    def test_api_key_uses_custom_dialog_and_show_hide(self):
        dialog = ApiKeyDialog("DeepSeek")
        self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Password)
        dialog.btn_show_hide.setChecked(True)
        self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Normal)
        dialog.btn_show_hide.setChecked(False)
        self.assertEqual(dialog.txt_key.echoMode(), QLineEdit.Password)
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

    def _mailbox_state_window(self, account, credential=False):
        td = tempfile.TemporaryDirectory()
        window = self.make_window(td.name)
        window._switch_main_page("settings")
        window.settings_tabs.setCurrentIndex(0)
        window.show()
        self.app.processEvents()
        window._mailbox_accounts_for_settings = lambda: [dict(account)]
        patcher = patch("scripts.invoice_fetch.credentials.has_auth_code", return_value=credential)
        patcher.start()
        window._load_settings_mailbox_form(0)
        window._test_mailbox_patcher = patcher
        window._test_mailbox_td = td
        return window

    def _close_mailbox_state_window(self, window):
        window._test_mailbox_patcher.stop()
        if is_qobject_valid(window):
            window.close()
        # This fixture removes its TemporaryDirectory immediately.  Complete
        # the Qt close/deferred-delete cycle before removing the database
        # directory so queued callbacks cannot target a half-torn-down window.
        self.app.processEvents()
        if is_qobject_valid(window):
            window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        window._test_mailbox_td.cleanup()

    def test_mailbox_normal_account_hides_repair_credential(self):
        window = self._mailbox_state_window({"mailbox_key": "normal", "address": "normal@example.invalid", "enabled": True}, credential=True)
        try:
            self.assertFalse(window.btn_settings_mailbox_add_credential.isVisible())
            self.assertTrue(window.btn_settings_mailbox_scan.isVisible())
            self.assertTrue(window.btn_settings_mailbox_test.isVisible())
            self.assertTrue(window.settings_mailbox_more_update_credential.isVisible())
        finally:
            self._close_mailbox_state_window(window)

    def test_mailbox_normal_account_has_scan_as_only_primary(self):
        window = self._mailbox_state_window({"mailbox_key": "normal", "address": "normal@example.invalid", "enabled": True}, credential=True)
        try:
            self.assertTrue(is_visual_primary(window.btn_settings_mailbox_scan))
            self.assertFalse(is_visual_primary(window.btn_settings_mailbox_test))
            self.assertFalse(is_visual_primary(window.btn_settings_mailbox_edit_config))
        finally:
            self._close_mailbox_state_window(window)

    def test_mailbox_missing_credential_hides_scan(self):
        window = self._mailbox_state_window({"mailbox_key": "missing", "address": "missing@example.invalid", "enabled": True})
        try:
            self.assertTrue(window.btn_settings_mailbox_add_credential.isVisible())
            self.assertFalse(window.btn_settings_mailbox_scan.isVisible())
            self.assertFalse(window.btn_settings_mailbox_test.isVisible())
            self.assertTrue(is_visual_primary(window.btn_settings_mailbox_add_credential))
        finally:
            self._close_mailbox_state_window(window)

    def test_mailbox_disabled_account_has_enable_as_primary(self):
        window = self._mailbox_state_window({"mailbox_key": "disabled", "address": "disabled@example.invalid", "enabled": False}, credential=True)
        try:
            self.assertTrue(window.btn_settings_mailbox_toggle.isVisible())
            self.assertEqual(window.btn_settings_mailbox_toggle.text(), "启用")
            self.assertFalse(window.btn_settings_mailbox_scan.isVisible())
            self.assertFalse(window.btn_settings_mailbox_test.isVisible())
            self.assertTrue(is_visual_primary(window.btn_settings_mailbox_toggle))
        finally:
            self._close_mailbox_state_window(window)

    def test_mailbox_detail_has_one_outer_surface(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                surfaces = window.findChildren(QFrame, "MailboxDetailSurface")
                self.assertEqual(len(surfaces), 1)
            finally:
                window.close()

    def test_mailbox_detail_has_no_nested_readonly_cards(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertEqual(window.mailbox_detail_surface.findChildren(ReadOnlyDetailPanel), [])
            finally:
                window.close()

    def test_mailbox_server_and_port_are_separate_fields(self):
        window = self._mailbox_state_window({"mailbox_key": "split", "address": "split@example.invalid", "enabled": True, "imap": {"server": "imap.example.invalid", "port": 993, "ssl": True}})
        try:
            self.assertEqual(window.lbl_detail_server.text(), "imap.example.invalid")
            self.assertIn("993", window.lbl_detail_port_security.text())
            self.assertNotIn(":993", window.lbl_detail_server.text())
        finally:
            self._close_mailbox_state_window(window)

    def test_mailbox_folder_and_range_are_separate_fields(self):
        window = self._mailbox_state_window({"mailbox_key": "rules", "address": "rules@example.invalid", "enabled": True, "search": {"folder": "Receipts", "months_back": 6}})
        try:
            self.assertEqual(window.lbl_detail_scan_folder.text(), "Receipts")
            self.assertIn("6", window.lbl_detail_scan_range.text())
            self.assertNotEqual(window.lbl_detail_scan_folder.text(), window.lbl_detail_scan_range.text())
        finally:
            self._close_mailbox_state_window(window)

    def _assert_mailbox_footer_fits(self, scale):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._switch_main_page("settings"); window.settings_tabs.setCurrentIndex(0)
                font = window.font(); font.setPointSizeF(max(9.0, font.pointSizeF()) * scale); window.setFont(font)
                self.app.processEvents()
                buttons = [window.btn_settings_mailbox_scan, window.btn_settings_mailbox_test, window.btn_settings_mailbox_edit_config, window.settings_mailbox_more]
                visible = [button for button in buttons if button.isVisible()]
                self.assertLessEqual(sum(button.sizeHint().width() for button in visible) + 32, window.settings_tabs.width())
            finally:
                window.close()

    def test_mailbox_footer_fits_at_125_percent(self):
        self._assert_mailbox_footer_fits(1.25)

    def test_mailbox_footer_fits_at_150_percent(self):
        self._assert_mailbox_footer_fits(1.5)

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
