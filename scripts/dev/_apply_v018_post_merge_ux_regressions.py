from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    # Preserve the repository file's native CRLF/LF convention.  Path.read_text
    # uses universal-newline translation and would otherwise rewrite app.py in
    # full, turning a focused patch into a line-ending-only diff.
    with target.open("r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    old_native = old.replace("\n", newline)
    new_native = new.replace("\n", newline)
    count = text.count(old_native)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}")
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace(old_native, new_native, 1))


replace_once(
    "scripts/invoice_fetch/gui/app.py",
    """        content_row.addStretch(1)\n        content_row.addWidget(self.overview_content_host, 0, Qt.AlignTop)\n        content_row.addStretch(1)\n""",
    """        # Side gutters keep the dashboard centered, while the content host\n        # receives most of the available width. Giving the host zero stretch\n        # leaves it near its sizeHint even on a maximized window, which in turn\n        # forces the responsive task cards into a permanent single column.\n        content_row.addStretch(1)\n        content_row.addWidget(self.overview_content_host, 8, Qt.AlignTop)\n        content_row.addStretch(1)\n""",
)

replace_once(
    "scripts/invoice_fetch/gui/mobile_upload_session.py",
    """        controller.dev_firewall_action_finished.connect(self._dev_firewall_action_finished)\n        controller.failed.connect(self._show_error)\n        controller.stopped.connect(self.show_idle)\n        controller.session_expired.connect(self._show_expired)\n        controller.refresh_firewall_status()\n""",
    """        controller.dev_firewall_action_finished.connect(self._dev_firewall_action_finished)\n        controller.failed.connect(self._show_error)\n        controller.stopped.connect(self.show_idle)\n        controller.session_expired.connect(self._show_expired)\n        # Do not synchronously query Windows Firewall while constructing the\n        # hidden Imports page. The query shells out to PowerShell and can take\n        # several seconds on real Windows machines. Firewall status becomes\n        # authoritative when the user explicitly starts mobile upload.\n""",
)

replace_once(
    "scripts/invoice_fetch/gui/mobile_upload_session.py",
    '        self.lbl_idle_firewall = QLabel("Windows 防火墙：检查中")\n',
    '        self.lbl_idle_firewall = QLabel("Windows 防火墙：启动手机上传后检查")\n',
)

replace_once(
    "scripts/invoice_fetch/gui/hci_v1.py",
    '        ("to_review", "新票待确认", "warning"),\n',
    '        ("to_review", "待审核", "warning"),\n',
)

replace_once(
    "scripts/invoice_fetch/gui/hci_v1.py",
    '            counts["to_review"], "逐张确认，处理后自动进入下一张 →"\n',
    '            counts["to_review"], "所有尚未确认的发票 →"\n',
)

Path("tests/test_v018_post_merge_ux_regressions.py").write_text(
    '''from __future__ import annotations\n\nimport tempfile\nimport unittest\nfrom pathlib import Path\nfrom unittest.mock import patch\n\nfrom PySide6.QtWidgets import QApplication\n\nfrom scripts.invoice_fetch.gui import startup_lifecycle\nfrom scripts.invoice_fetch.gui.mobile_upload_session import (\n    MobileUploadSessionController,\n    MobileUploadSessionPanel,\n)\n\n\nclass V018PostMergeUxRegressionTests(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls):\n        cls.qt_app = QApplication.instance() or QApplication([])\n\n    def test_import_panel_construction_does_not_query_windows_firewall(self):\n        with tempfile.TemporaryDirectory(prefix="invoice-hub-import-no-firewall-") as td:\n            controller = MobileUploadSessionController(Path(td) / "invoices.db")\n            with patch.object(\n                controller,\n                "refresh_firewall_status",\n                side_effect=AssertionError("Imports construction must not query Windows Firewall"),\n            ):\n                panel = MobileUploadSessionPanel(controller)\n            try:\n                self.assertIn("启动手机上传后检查", panel.lbl_idle_firewall.text())\n            finally:\n                panel.close()\n                controller.shutdown(timeout_ms=50)\n                self.qt_app.processEvents()\n\n    def test_wide_dashboard_uses_available_width_and_four_task_columns(self):\n        with tempfile.TemporaryDirectory(prefix="invoice-hub-dashboard-wide-") as td:\n            window = startup_lifecycle.FirstPaintDeferredInvoiceReviewApp(\n                Path(td) / "startup.db",\n                splash=None,\n            )\n            try:\n                # Exercise layout geometry without relying on the hosted runner's\n                # physical desktop size. This is the same product viewport the\n                # responsive contract is intended to handle.\n                window.resize(1600, 900)\n                window._nav_collapsed_manual = True\n                window._apply_workbench_metrics(1600, 900)\n                window._switch_main_page("overview")\n                for _ in range(6):\n                    self.qt_app.processEvents()\n\n                self.assertGreaterEqual(window.overview_content_host.width(), 900)\n                self.assertEqual(window.hci_dashboard_task_cards_row.column_count(), 4)\n                self.assertEqual(\n                    window.hci_dashboard_task_cards["to_review"].lbl_title.text(),\n                    "待审核",\n                )\n                self.assertNotEqual(\n                    window.hci_dashboard_task_cards["to_review"].lbl_title.text(),\n                    "新票待确认",\n                )\n            finally:\n                window.close()\n                self.qt_app.processEvents()\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)
