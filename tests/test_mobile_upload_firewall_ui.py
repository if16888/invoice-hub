import inspect
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QRect
from PySide6.QtWidgets import QApplication, QBoxLayout, QFormLayout

from scripts.invoice_fetch.gui.mobile_upload_session import (
    MobileUploadSessionController,
    MobileUploadSessionPanel,
    _MobileUploadStartWorker,
)
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.windows_firewall import FirewallState, FirewallStatus


class MobileUploadFirewallUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_panel(self, td: str):
        controller = MobileUploadSessionController(Path(td) / "invoices.db")
        panel = MobileUploadSessionPanel(controller)
        panel.show()
        self.app.processEvents()

        def cleanup():
            panel.close()
            panel.deleteLater()
            controller.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(cleanup)
        return controller, panel

    def activate(self, controller, panel):
        session = SimpleNamespace(
            upload_url="http://192.168.1.50:43210/u/synthetic-token",
            host="192.168.1.50",
            port=43210,
        )
        with patch.object(controller, "qr_png", return_value=b""):
            controller.started.emit(session)
        self.app.processEvents()

    @staticmethod
    def rect_in(widget, ancestor):
        return QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())

    def assert_active_geometry_contract(self, panel):
        page = panel.active_page
        qr = self.rect_in(panel.lbl_qr, page)
        url = self.rect_in(panel.txt_url, page)
        details = self.rect_in(panel._active_details, page)
        footer = QRect(panel._active_footer_layout.geometry())
        copy = self.rect_in(panel.btn_copy_url, page)
        change = self.rect_in(panel.btn_change_network, page)
        stop = self.rect_in(panel.btn_stop, page)
        regions = {
            "qr": qr,
            "url": url,
            "details": details,
            "footer": footer,
            "copy": copy,
            "change": change,
            "stop": stop,
        }
        for name, rect in regions.items():
            self.assertTrue(
                page.rect().contains(rect.topLeft())
                and page.rect().contains(rect.bottomRight()),
                f"{name} escaped active page: {rect} / {page.rect()}",
            )
        for left_name, left_rect in regions.items():
            for right_name, right_rect in regions.items():
                if left_name >= right_name:
                    continue
                if left_name == "url" and right_name in {"copy", "change", "stop"}:
                    continue
                if right_name == "url" and left_name in {"copy", "change", "stop"}:
                    continue
                if left_name == "footer" or right_name == "footer":
                    continue
                self.assertFalse(
                    left_rect.intersects(right_rect),
                    f"{left_name} intersects {right_name}: {left_rect} / {right_rect}",
                )
        self.assertGreaterEqual(url.top(), qr.bottom())
        self.assertEqual(change.center().y(), stop.center().y())

    def test_medium_imports_mobile_parent_owns_full_task_width_without_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "invoices.db")
            window.resize(1276, 875)
            window.show()
            window._switch_main_page("imports")
            window._set_import_source_selected("mobile")
            controller = window.mobile_upload_controller
            controller.host_options = [SimpleNamespace(label="WLAN", host="192.168.1.50")]
            session = SimpleNamespace(
                upload_url="http://192.168.1.50:43210/u/synthetic-review",
                host="192.168.1.50",
                port=43210,
            )
            with patch.object(controller, "qr_png", return_value=b""):
                controller.started.emit(session)
            self.app.processEvents()
            self.app.processEvents()
            self.app.processEvents()
            panel = window.mobile_upload_panel
            self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
            self.assertGreaterEqual(window.import_task_stack.width(), 840)
            self.assertGreaterEqual(panel.width(), 720)
            self.assertEqual(panel._active_body_layout.direction(), QBoxLayout.LeftToRight)
            self.assertEqual(panel._active_footer_layout.direction(), QBoxLayout.LeftToRight)
            self.assertTrue(panel._active_tech_details.isHidden())
            self.assert_active_geometry_contract(panel)

            panel._active_tech_toggle.click()
            self.app.processEvents()
            self.assertTrue(panel._active_tech_details.isVisible())
            self.assert_active_geometry_contract(panel)
            window.close()
            self.app.processEvents()
            window.deleteLater()
            self.app.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

    def test_medium_imports_mobile_geometry_survives_expanded_and_collapsed_sidebar(self):
        """Manual navigation choice must not shrink the active mobile task."""

        for nav_collapsed in (False, True):
            with self.subTest(nav_collapsed=nav_collapsed), tempfile.TemporaryDirectory() as td:
                window = InvoiceReviewApp(Path(td) / "invoices.db")
                try:
                    window.resize(1276, 875)
                    window.show()
                    # The initial show restores persisted preferences.  Apply
                    # the explicit user choice afterwards, matching the
                    # sidebar toggle's observable lifecycle.
                    window._nav_collapsed_manual = nav_collapsed
                    window._apply_workbench_metrics(1276, 875)
                    window._switch_main_page("imports")
                    window._set_import_source_selected("mobile")
                    controller = window.mobile_upload_controller
                    controller.host_options = [SimpleNamespace(label="WLAN", host="192.168.1.50")]
                    session = SimpleNamespace(
                        upload_url="http://192.168.1.50:43210/u/synthetic-review",
                        host="192.168.1.50",
                        port=43210,
                    )
                    with patch.object(controller, "qr_png", return_value=b""):
                        controller.started.emit(session)
                    for _ in range(3):
                        self.app.processEvents()

                    panel = window.mobile_upload_panel
                    expected_nav_width = 56 if nav_collapsed else 180
                    self.assertEqual(window.workbench_nav.width(), expected_nav_width)
                    self.assertEqual(window.imports_shell_layout.direction(), QBoxLayout.TopToBottom)
                    self.assertGreaterEqual(panel.width(), 720)
                    self.assertEqual(panel._active_body_layout.direction(), QBoxLayout.LeftToRight)
                    self.assert_active_geometry_contract(panel)
                finally:
                    window.close()
                    self.app.processEvents()
                    window.deleteLater()
                    self.app.sendPostedEvents(None, QEvent.DeferredDelete)
                    self.app.processEvents()

    def test_clicked_bool_is_not_forwarded_as_host(self):
        with tempfile.TemporaryDirectory() as td:
            controller, panel = self.make_panel(td)
            with patch.object(controller, "start") as start:
                panel.btn_start.click()
                panel.btn_retry.click()
            self.assertEqual(start.call_count, 2)
            start.assert_any_call()
            for call in start.call_args_list:
                self.assertEqual(call.args, ())
                self.assertEqual(call.kwargs, {})

    def test_start_worker_does_not_mutate_windows_firewall(self):
        source = inspect.getsource(_MobileUploadStartWorker.run)
        self.assertNotIn("clear_mobile_upload_dev_firewall_access", source)
        self.assertNotIn("request_mobile_upload_dev_firewall_access", source)
        self.assertNotIn("request_mobile_upload_firewall_access", source)

    def test_stop_does_not_clear_dev_firewall_rule(self):
        with tempfile.TemporaryDirectory() as td:
            controller, _panel = self.make_panel(td)
            server = SimpleNamespace(
                stop=lambda: None,
                drain_completed_upload_results=lambda: [],
            )
            controller.server = server
            controller.session = SimpleNamespace(port=43210)
            controller._dev_firewall_rule_active = True
            with patch(
                "scripts.invoice_fetch.windows_firewall.clear_mobile_upload_dev_firewall_access"
            ) as clear_rule, patch.object(controller, "refresh_firewall_status"):
                controller.stop()
            clear_rule.assert_not_called()
            self.assertIsNone(controller.server)
            self.assertIsNone(controller.session)

    def test_expired_session_stops_server_releases_state_and_prompts_restart(self):
        with tempfile.TemporaryDirectory() as td:
            controller, panel = self.make_panel(td)
            stopped = []
            server = SimpleNamespace(
                status=lambda: {
                    "expired": True,
                    "received": 0,
                    "failed": 0,
                    "import_failed": 0,
                },
                stop=lambda: stopped.append(True),
                drain_completed_upload_results=lambda: [],
            )
            controller.server = server
            controller.session = SimpleNamespace(port=43210)
            controller.session_expired.connect(lambda: None)

            controller.refresh_status()
            self.app.processEvents()

            self.assertEqual(stopped, [True])
            self.assertIsNone(controller.server)
            self.assertIsNone(controller.session)
            self.assertIs(panel.stack.currentWidget(), panel.idle_page)
            self.assertFalse(panel.lbl_idle_notice.isHidden())
            self.assertIn("二维码已过期", panel.lbl_idle_notice.text())
            self.assertEqual(panel.btn_start.text(), "重新生成二维码")

    def test_mobile_stats_use_business_outcome_labels(self):
        with tempfile.TemporaryDirectory() as td:
            _controller, panel = self.make_panel(td)
            panel._set_stats({
                "received": 5,
                "created": 4,
                "duplicate": 0,
                "business_duplicate": 1,
                "failed": 0,
                "import_failed": 0,
            })
            self.assertEqual(panel.lbl_stats.text(), "接收 5 · 新增 4 · 重复 1 · 失败 0")

    def test_active_qr_card_uses_vertical_contract_only_for_narrow_embedded_surface(self):
        with tempfile.TemporaryDirectory() as td:
            controller, panel = self.make_panel(td)
            self.activate(controller, panel)
            panel.resize(620, 900)
            self.app.processEvents()
            self.assertEqual(
                panel._active_body_layout.direction(),
                QBoxLayout.TopToBottom,
            )
            self.assertEqual(
                panel._active_details_form.rowWrapPolicy(),
                QFormLayout.WrapAllRows,
            )
            self.assertIsNone(panel._active_details_scroll)
            self.assertTrue(panel.lbl_service_address.wordWrap())
            self.assertTrue(panel.lbl_firewall_hint.wordWrap())
            panel.resize(900, 900)
            self.app.processEvents()
            self.assertEqual(
                panel._active_body_layout.direction(),
                QBoxLayout.LeftToRight,
            )
            self.assertEqual(
                panel._active_details_form.rowWrapPolicy(),
                QFormLayout.WrapLongRows,
            )

    def test_import_workspace_gives_active_mobile_main_area_desktop_width(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "invoices.db")
            window.resize(1366, 768)
            window.show()
            window._switch_main_page("imports")
            window._set_import_source_selected("mobile")
            try:
                controller = window.mobile_upload_controller
                controller.host_options = [SimpleNamespace(label="WLAN", host="192.168.1.50")]
                session = SimpleNamespace(
                    upload_url="http://192.168.1.50:43210/u/synthetic-review",
                    host="192.168.1.50",
                    port=43210,
                )
                with patch.object(controller, "qr_png", return_value=b""):
                    controller.started.emit(session)
                self.app.processEvents()
                self.app.processEvents()
                panel = window.mobile_upload_panel
                self.assertIsNone(panel._active_details_scroll)
                self.assertGreaterEqual(panel.width(), 720)
                self.assertEqual(panel._active_body_layout.direction(), QBoxLayout.LeftToRight)
                self.assertGreaterEqual(window.import_source_card.width(), 760)
                self.assertGreaterEqual(window.import_task_stack.width(), 760)
                self.assertTrue(panel._active_tech_details.isHidden())
                self.assertFalse(panel.lbl_service_address.isVisible())
                self.assertEqual(
                    panel.btn_change_network.geometry().center().y(),
                    panel.btn_stop.geometry().center().y(),
                )
                self.assertLess(
                    panel._active_footer_layout.geometry().top(),
                    panel.height(),
                )
                for label in (
                    panel.lbl_network_interface,
                    panel.lbl_lan_access_hint,
                    panel.lbl_firewall_hint,
                    panel.lbl_stats,
                ):
                    self.assertGreater(label.height(), 0)
            finally:
                window.close()
                self.app.processEvents()
                window.deleteLater()
                self.app.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()

    def test_firewall_allowed_does_not_confirm_lan_access(self):
        with tempfile.TemporaryDirectory() as td:
            controller, panel = self.make_panel(td)
            self.activate(controller, panel)
            panel._set_firewall_status(
                FirewallStatus(FirewallState.RULE_PRESENT, executable_path="InvoiceHub.exe")
            )
            panel._set_stats({
                "accepted": 0,
                "duplicate": 0,
                "failed": 0,
                "imported": 0,
                "active": True,
                "lan_client_access_confirmed": False,
                "last_lan_client_access_at": "",
                "local_self_check": "pass",
                "public_host": "192.168.1.50",
                "interface_name": "WLAN",
            })
            self.assertEqual(panel.lbl_firewall_state.text(), "已允许 · 仅私人网络")
            self.assertEqual(panel.lbl_lan_client_access.text(), "尚未确认")
            self.assertTrue(panel.lbl_lan_access_hint.isVisible())
            self.assertTrue(panel.btn_firewall_authorize.isHidden())

    def test_missing_and_dev_firewall_states_have_safe_fallbacks(self):
        with tempfile.TemporaryDirectory() as td:
            controller, panel = self.make_panel(td)
            self.activate(controller, panel)
            panel._set_firewall_status(FirewallStatus(FirewallState.RULE_MISSING))
            self.assertEqual(panel.lbl_firewall_state.text(), "未授权")
            self.assertFalse(panel.btn_firewall_authorize.isHidden())
            panel._set_firewall_status(
                FirewallStatus(FirewallState.SUPPORTED, development_mode=True)
            )
            self.assertEqual(panel.lbl_firewall_state.text(), "本次访问尚未允许")
            self.assertTrue(panel.btn_firewall_authorize.isHidden())

    def test_dev_firewall_button_requires_running_server_and_current_port(self):
        with tempfile.TemporaryDirectory() as td:
            controller, panel = self.make_panel(td)
            self.activate(controller, panel)
            panel._set_firewall_status(
                FirewallStatus(FirewallState.SUPPORTED, development_mode=True)
            )
            self.assertTrue(panel.btn_dev_firewall.isHidden())
            controller.server = SimpleNamespace(port=43210)
            controller.session = SimpleNamespace(port=43210)
            panel._set_dev_firewall_status(
                FirewallStatus(
                    FirewallState.RULE_MISSING,
                    development_mode=True,
                    rule_name="Invoice Hub Mobile Upload Dev Session",
                )
            )
            panel._set_firewall_status(
                FirewallStatus(FirewallState.SUPPORTED, development_mode=True)
            )
            self.assertFalse(panel.btn_dev_firewall.isHidden())
            self.assertTrue(panel.btn_dev_firewall.isEnabled())
            self.assertEqual(panel.btn_dev_firewall.text(), "允许本次访问")

    def test_stale_dev_rule_allows_direct_allow_action(self):
        with tempfile.TemporaryDirectory() as td:
            controller, panel = self.make_panel(td)
            controller.server = SimpleNamespace(port=43210)
            controller.session = SimpleNamespace(port=43210)
            panel._set_firewall_status(
                FirewallStatus(FirewallState.SUPPORTED, development_mode=True)
            )
            panel._set_dev_firewall_status(
                FirewallStatus(
                    FirewallState.RULE_PRESENT,
                    development_mode=True,
                    rule_name="Invoice Hub Mobile Upload Dev Session",
                    local_port="40000",
                    reason="stale development session port",
                )
            )
            self.assertTrue(panel.btn_dev_firewall.isEnabled())
            self.assertEqual(panel.btn_dev_firewall.text(), "允许本次访问")
            self.assertFalse(panel.btn_dev_firewall_cleanup.isHidden())
            self.assertEqual(panel.lbl_firewall_state.text(), "本次访问尚未允许")

    def test_current_dev_rule_is_not_equated_with_packaged_rule(self):
        with tempfile.TemporaryDirectory() as td:
            controller, panel = self.make_panel(td)
            controller.server = SimpleNamespace(port=43210)
            controller.session = SimpleNamespace(port=43210)
            panel._set_firewall_status(
                FirewallStatus(FirewallState.SUPPORTED, development_mode=True)
            )
            panel._set_dev_firewall_status(
                FirewallStatus(
                    FirewallState.RULE_PRESENT,
                    development_mode=True,
                    rule_name="Invoice Hub Mobile Upload Dev Session",
                    local_port="43210",
                )
            )
            self.assertEqual(panel.btn_dev_firewall.text(), "本次访问已允许")
            self.assertFalse(panel.btn_dev_firewall.isEnabled())
            self.assertEqual(panel.lbl_firewall_state.text(), "本次访问已允许")
            self.assertTrue(panel.btn_firewall_authorize.isHidden())


if __name__ == "__main__":
    unittest.main()
