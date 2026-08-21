import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QBoxLayout, QFormLayout

from scripts.invoice_fetch.gui.mobile_upload_session import (
    MobileUploadSessionController,
    MobileUploadSessionPanel,
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

    def test_active_qr_card_stacks_without_squeezing_details(self):
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

    def test_import_workspace_keeps_narrow_details_scrollable_and_footer_clear(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "invoices.db")
            window.resize(1366, 768)
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
            panel = window.mobile_upload_panel
            self.assertGreaterEqual(
                panel._active_details_scroll.geometry().top(),
                panel.lbl_qr.geometry().bottom(),
            )
            self.assertGreaterEqual(
                panel._active_footer_layout.geometry().top(),
                panel._active_details_scroll.geometry().bottom(),
            )
            self.assertGreater(panel._active_details.height(), panel._active_details_scroll.height())
            for label in (
                panel.lbl_service_address,
                panel.lbl_lan_access_hint,
                panel.lbl_firewall_hint,
                panel.lbl_stats,
            ):
                self.assertGreater(label.height(), 0)
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
            self.assertEqual(panel.lbl_firewall_state.text(), "开发运行模式")
            self.assertTrue(panel.btn_firewall_authorize.isHidden())


if __name__ == "__main__":
    unittest.main()
