"""Regression tests for P1-3 (flat workspace) and P1-7 (export hierarchy)."""

import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


_QAPP = None


class P1StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, directory):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        window = InvoiceReviewApp(Path(directory) / "p1s.db", splash=None)
        window.resize(1440, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        return window

    def test_workspace_uses_matching_table_and_preview_surfaces(self):
        from scripts.invoice_fetch.gui.styles import APP_STYLESHEET

        self.assertIn("QSplitter#WorkbenchMainSplitter::handle", APP_STYLESHEET)
        from scripts.invoice_fetch.gui.ui.qss import build_qss

        shared_rule = build_qss().split("QFrame#ReviewPageBar, QFrame#InvoiceTableCard, QFrame#PreviewPanel", 1)[1].split("}", 1)[0]
        self.assertIn("border-radius: 12px", shared_rule)
        self.assertIn("background: #FFFFFF", shared_rule)

        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertEqual(window.preview_panel.objectName(), "PreviewPanel")
                self.assertEqual(window.main_splitter.objectName(), "WorkbenchMainSplitter")
                self.assertEqual(window.main_splitter.handleWidth(), 12)
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_export_hierarchy_has_one_command_bar_and_neutral_zero(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._window(td)
            try:
                self.assertEqual(
                    window.export_group_card.body_layout.indexOf(window.btn_edit_claim_reason),
                    -1,
                )
                self.assertEqual(
                    window.export_group_card.body_layout.indexOf(window.btn_export_filename),
                    -1,
                )
                more_texts = [a.text() for a in window.export_group_more_menu.actions()]
                self.assertIn("编辑报销信息", more_texts)
                self.assertIn("导出文件名模板", more_texts)
                self.assertEqual(window.btn_export_create_group.property("variant"), "primary")
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def _assert_export_compatibility_buttons(self, window):
        for button in (window.btn_edit_claim_reason, window.btn_export_filename):
            self.assertIs(button.parentWidget(), window.export_group_card)
            self.assertTrue(button.isHidden())
            self.assertFalse(button.isVisible())
            self.assertFalse(button.isWindow())
            self.assertNotIn(button, self.app.topLevelWidgets())
            self.assertEqual(window.export_group_card.body_layout.indexOf(button), -1)

    def test_export_refresh_keeps_compatibility_buttons_hidden_without_disabling_more_actions(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox
        from scripts.invoice_fetch import config
        from scripts.invoice_fetch.gui import app as app_module
        from scripts.invoice_fetch.gui.claim_reason_dialog import ClaimReasonDialog

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"reimbursement": {"buyer_name": "Synthetic buyer"},
                                               "email_accounts": []}), encoding="utf-8")
            # The real filename save must never resolve the source checkout's
            # config.json. Both application and config roots are synthetic.
            with patch.object(config, "PROJECT_ROOT", root), patch.object(app_module, "PROJECT_ROOT", root):
                window = self._window(td)
                try:
                    window._deferred_init()
                    QTest.mouseClick(window.workbench_nav_buttons["export"], Qt.LeftButton)
                    self.app.processEvents()
                    self.assertIs(window.center_stack.currentWidget(), window.export_page)
                    self._assert_export_compatibility_buttons(window)
                    self.assertEqual(window.export_group_list.count(), 0)
                    actions = {action.text(): action for action in window.export_group_more_menu.actions()}
                    edit = actions["编辑报销信息"]
                    filename = actions["导出文件名模板"]
                    self.assertTrue(edit.isEnabled() and filename.isEnabled())
                    edit.trigger()
                    self.assertIn("请先选择报销组", window.statusBar().currentMessage())

                    # This is a global setting even when there is no group.
                    # The QAction opens the original handler, not a legacy
                    # button; only the modal's text result is controlled.
                    with patch.object(QInputDialog, "getText", return_value=("{部门}_{姓名}.xlsx", True)) as dialog:
                        filename.trigger()
                    dialog.assert_called_once()
                    saved = json.loads(config_path.read_text(encoding="utf-8"))
                    self.assertEqual(saved["reimbursement"]["filename_template"], "{部门}_{姓名}.xlsx")
                    self.assertEqual(saved["reimbursement"]["buyer_name"], "Synthetic buyer")

                    claim_id = window.db.create_claim_group("Synthetic group", reason_detail="Original reason")
                    for n in range(20):
                        invoice_id = window.db.insert_invoice({"invoice_number": f"SYNTH-{n:03d}",
                            "invoice_date": "2026-11-01", "total_amount": "10.00", "seller_name": "Synthetic supplier",
                            "review_status": "to_review"})
                        self.assertTrue(window.db.add_invoice_to_claim(claim_id, invoice_id))
                    window._load_claims(selected_claim_id=claim_id)
                    for _ in range(2):
                        window._refresh_export_page()
                        self.app.processEvents()
                        self._assert_export_compatibility_buttons(window)
                        self.assertEqual(window.export_group_list.currentItem().data(Qt.UserRole), claim_id)
                    self.assertEqual(window.export_invoice_list.count(), 20)

                    def save_reason(dialog):
                        dialog.fields["reason_detail"].setText("Updated synthetic reason")
                        return QDialog.Accepted

                    with patch.object(ClaimReasonDialog, "exec", save_reason):
                        edit.trigger()
                    self.assertEqual(window.db.get_claim_group(claim_id)["reason_detail"], "Updated synthetic reason")
                    window.db._conn.execute("UPDATE claim_groups SET status='exported' WHERE id=?", (claim_id,))
                    window.db._conn.commit()
                    window._refresh_export_page()
                    self._assert_export_compatibility_buttons(window)
                    self.assertFalse(window.btn_edit_claim_reason.isEnabled())
                    self.assertTrue(edit.isEnabled())
                    # The locked group's menu action must still explain the
                    # lock. Routing through the disabled legacy button would
                    # silently do nothing instead.
                    with patch.object(QMessageBox, "information") as notice:
                        edit.trigger()
                    notice.assert_called_once()
                    self.assertIn("已锁定", notice.call_args.args[1])
                    self.assertEqual(window.db.get_claim_group(claim_id)["reason_detail"], "Updated synthetic reason")
                    before = config_path.read_bytes()
                    with patch.object(QInputDialog, "getText", return_value=("ignored.xlsx", False)) as dialog:
                        filename.trigger()
                    dialog.assert_called_once()
                    self.assertEqual(config_path.read_bytes(), before)

                    QTest.mouseClick(window.workbench_nav_buttons["review"], Qt.LeftButton)
                    QTest.mouseClick(window.workbench_nav_buttons["export"], Qt.LeftButton)
                    self.app.processEvents()
                    self._assert_export_compatibility_buttons(window)
                finally:
                    window.close()
                    self.app.processEvents()
                    self.assertFalse(window.db.is_open)
                    window.deleteLater()
                    self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_normal_desktop_export_closes_and_exits_its_real_event_loop(self):
        for count in (20, 50):
            with self.subTest(invoices=count), tempfile.TemporaryDirectory(prefix="ih-export-lifecycle-") as td:
                root = Path(td)
                for name in ("runtime", "config", "data", "cache", "qt"):
                    (root / name).mkdir(mode=0o700)
                runtime = root / "runtime"
                (runtime / "workbench.ini").write_text("[migration]\nlegacy_qsettings_v1=true\n", encoding="utf-8")
                env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "INVOICE_HUB_DISABLE_MODAL_GUARD": "1",
                       "INVOICE_HUB_RUNTIME_DIR": str(runtime), "INVOICE_HUB_TEST_MODE": "1",
                       "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
                       "XDG_CACHE_HOME": str(root / "cache"), "XDG_RUNTIME_DIR": str(root / "qt"),
                       "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring", "PYTHONIOENCODING": "utf-8"}
                for key in ("INVOICE_HUB_STARTUP_PROBE", "INVOICE_HUB_STARTUP_PROBE_FILE", "PYTHONOPTIMIZE"):
                    env.pop(key, None)
                result = subprocess.run([sys.executable, "-m", "tests.test_ui_p1_structure", "--export-lifecycle-child", str(count)],
                                        cwd=Path(__file__).resolve().parents[1], env=env,
                                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
                evidence = result.stdout + "\n" + result.stderr
                self.assertEqual(result.returncode, 0, evidence)
                line = next((line for line in result.stdout.splitlines() if line.startswith("EXPORT_LIFECYCLE_RESULT=")), None)
                self.assertIsNotNone(line, evidence)
                report = json.loads(line.split("=", 1)[1])
                self.assertEqual(report["visible_export_members"], count)
                self.assertTrue(report["close_accepted"] and report["database_closed"] and report["last_window_closed"])
                self.assertFalse(report["watchdog"])
                self.assertEqual(report["event_loop_code"], 0)
                self.assertEqual(report["visible_after_close"], [])
                self.assertEqual(report["visible_after_loop"], [])
                self.assertTrue(report["compatibility_buttons_owned_hidden"])


def _export_lifecycle_child(count):
    """Observe the shipping launcher; success only comes from its natural exit."""
    import runpy
    import time
    import traceback

    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from scripts.invoice_fetch import config

    runtime = Path(os.environ["INVOICE_HUB_RUNTIME_DIR"])
    config.PROJECT_ROOT = runtime  # never read or write a source checkout's config.json
    (runtime / "config.json").write_text('{"email_accounts": [], "reimbursement": {}}', encoding="utf-8")
    from scripts.invoice_fetch.db import InvoiceDB
    from scripts.invoice_fetch.gui import startup_lifecycle

    with InvoiceDB(runtime / "invoices.db") as db:
        claim_id = db.create_claim_group("Synthetic group")
        for n in range(count):
            invoice_id = db.insert_invoice({"invoice_number": f"SYNTH-{n:03d}", "invoice_date": "2026-11-01",
                "total_amount": "10.00", "seller_name": "Synthetic supplier", "review_status": "to_review"})
            assert db.add_invoice_to_claim(claim_id, invoice_id)
    assert not db.is_open

    report = {"watchdog": False, "last_window_closed": False}
    references = {}
    original_reveal = startup_lifecycle.reveal_startup_window

    def visible_top_levels(qt):
        return [getattr(widget, "text", lambda: widget.__class__.__name__)()
                for widget in qt.topLevelWidgets() if widget.isVisible()]

    def reveal(window, splash):
        original_reveal(window, splash)
        qt = QApplication.instance()
        references.update(qt=qt, window=window)  # retain wrappers through app.exec() return
        assert qt.quitOnLastWindowClosed()
        qt.lastWindowClosed.connect(lambda: report.update(last_window_closed=True))
        deadline = time.monotonic() + 12

        def fail_watchdog():
            report["watchdog"] = True
            qt.exit(7)  # diagnostic failure only; never force a successful exit

        def drive():
            try:
                if not window._deferred_init_done or not window._startup_first_paint_seen:
                    assert time.monotonic() < deadline, "normal desktop did not finish initial load"
                    QTimer.singleShot(10, drive)
                    return
                assert window.workbench_nav_buttons["export"].isVisible()
                QTest.mouseClick(window.workbench_nav_buttons["export"], Qt.LeftButton)
                qt.processEvents()
                assert window._current_page_key() == "export"
                assert window.export_group_list.currentItem().data(Qt.UserRole) == claim_id
                report["visible_export_members"] = window.export_invoice_list.count()
                assert report["visible_export_members"] == count
                window._refresh_export_page()
                qt.processEvents()
                report["visible_before_close"] = visible_top_levels(qt)
                report["compatibility_buttons_owned_hidden"] = all(
                    button.parentWidget() is window.export_group_card and button.isHidden() and not button.isWindow()
                    for button in (window.btn_edit_claim_reason, window.btn_export_filename))
                # Record the bug without rejecting it before real close: the
                # old process must actually stay alive with its stray windows.
                QTimer.singleShot(7000, fail_watchdog)
                report["close_accepted"] = window.close()
                report["database_closed"] = not window.db.is_open
                report["visible_after_close"] = visible_top_levels(qt)
            except BaseException:
                traceback.print_exc()
                qt.exit(8)

        QTimer.singleShot(0, drive)

    launcher = Path(__file__).resolve().parents[1] / "scripts/invoice_fetch_desktop.py"
    sys.argv = [str(launcher)]
    code = 1
    with patch.object(startup_lifecycle, "reveal_startup_window", reveal):
        try:
            runpy.run_path(str(launcher), run_name="__main__")
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    report["event_loop_code"] = code
    qt = references.get("qt")
    report["visible_after_loop"] = visible_top_levels(qt) if qt is not None else None
    print("EXPORT_LIFECYCLE_RESULT=" + json.dumps(report, ensure_ascii=False), flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--export-lifecycle-child":
        _export_lifecycle_child(int(sys.argv[2]))
    else:
        unittest.main()
