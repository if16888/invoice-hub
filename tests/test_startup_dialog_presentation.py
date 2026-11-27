"""Fresh-process regression tests for the startup dialog-presentation boundary."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


class StartupDialogPresentationTests(unittest.TestCase):
    def run_child(self, mode):
        with tempfile.TemporaryDirectory(prefix="invoice-hub-dialog-startup-") as temp:
            root = Path(temp)
            runtime = root / "runtime"
            runtime.mkdir()
            (root / "qt").mkdir(mode=0o700)
            (runtime / "workbench.ini").write_text("[migration]\nlegacy_qsettings_v1=true\n", encoding="utf-8")
            env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "INVOICE_HUB_DISABLE_MODAL_GUARD": "1",
                   "INVOICE_HUB_RUNTIME_DIR": str(runtime), "XDG_CONFIG_HOME": str(root / "config"),
                   "XDG_DATA_HOME": str(root / "data"), "XDG_CACHE_HOME": str(root / "cache"),
                   "XDG_RUNTIME_DIR": str(root / "qt"),
                   "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring", "PYTHONIOENCODING": "utf-8"}
            env.pop("INVOICE_HUB_STARTUP_PROBE", None)
            env.pop("INVOICE_HUB_STARTUP_PROBE_FILE", None)
            env.pop("PYTHONOPTIMIZE", None)  # the fresh-process assertions must stay active
            result = subprocess.run([sys.executable, "-m", "tests.test_startup_dialog_presentation", mode],
                                    cwd=Path(__file__).resolve().parents[1], env=env,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
            self.assertIn("STARTUP_DIALOG_PRESENTATION=PASS", result.stdout)

    def test_real_desktop_installs_after_construction_and_preserves_first_dialogs(self):
        self.run_child("--desktop-child")

    def test_construction_exception_still_installs_presentation_before_propagating(self):
        self.run_child("--failure-child")


def _child(mode):
    import runpy
    import time
    import traceback
    from unittest.mock import patch

    from PySide6.QtCore import QEvent, QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QInputDialog, QLineEdit, QMessageBox

    from scripts.invoice_fetch import config
    from scripts.invoice_fetch.db import InvoiceDB
    from scripts.invoice_fetch.gui import app as app_module, dialog_shell, startup_lifecycle

    runtime = Path(os.environ["INVOICE_HUB_RUNTIME_DIR"])
    # Source-mode config resolution must not read a developer's real config.json.
    config.PROJECT_ROOT = runtime
    db_path = runtime / "invoices.db"

    if mode == "--failure-child":
        qt = QApplication([])
        captured = []

        def fail(window):
            captured.append(window)
            assert not hasattr(qt, "_desktop_dialog_presentation")
            raise RuntimeError("Synthetic construction failure")

        with patch.object(app_module.InvoiceReviewApp, "_init_ui", fail):
            try:
                app_module.InvoiceReviewApp(db_path)
            except RuntimeError as error:
                assert str(error) == "Synthetic construction failure"
            else:
                raise AssertionError("Expected construction failure")
        assert hasattr(qt, "_desktop_dialog_presentation")
        captured[0].db.close()
        captured[0].deleteLater()
        print("STARTUP_DIALOG_PRESENTATION=PASS", flush=True)
        return

    with InvoiceDB(db_path) as db:
        invoice_id = db.insert_invoice({"invoice_number": "SYNTHETIC-STARTUP", "invoice_date": "2026-11-01",
                                        "seller_name": "Synthetic supplier", "total_amount": "10.00",
                                        "review_status": "to_review"})

    premature = []
    phases = []
    watcher = None

    class BeforeInstallWatcher(QObject):
        def eventFilter(self, target, event):
            if (event.type() == QEvent.Show and isinstance(target, QDialog)
                    and not hasattr(QApplication.instance(), "_desktop_dialog_presentation")):
                premature.append(type(target).__name__)
                QTimer.singleShot(0, target.reject)
            return False

    real_progress = app_module.StartupSplash.show_message
    real_init_ui = app_module.InvoiceReviewApp._init_ui
    real_reveal = startup_lifecycle.reveal_startup_window

    def progress(splash, message, progress_val=None):
        nonlocal watcher
        qt = QApplication.instance()
        if watcher is None:
            watcher = BeforeInstallWatcher(qt)
            qt.installEventFilter(watcher)
        if progress_val == 70:
            assert not hasattr(qt, "_desktop_dialog_presentation")
            phases.append("splash-layout-progress")
        return real_progress(splash, message, progress_val)

    def init_ui(window):
        qt = QApplication.instance()
        assert not hasattr(qt, "_desktop_dialog_presentation")
        real_init_ui(window)
        assert not hasattr(qt, "_desktop_dialog_presentation")
        phases.append("ui-complete")

    def reveal(window, splash):
        qt = QApplication.instance()
        assert phases == ["splash-layout-progress", "ui-complete"]
        handler = qt._desktop_dialog_presentation
        assert not premature, premature
        real_reveal(window, splash)
        qt.setQuitOnLastWindowClosed(False)
        deadline = time.monotonic() + 12

        def check_shell(dialog):
            assert dialog.property("dialogStyle") == "desktop"
            assert dialog.accessibleName() == dialog.windowTitle()
            assert dialog.isModal() and dialog.parentWidget() is window
            available = dialog.screen().availableGeometry()
            # QInputDialog's native layout may reset maximumWidth after Show;
            # the existing contract is that the presented dialog fits.
            assert dialog.width() <= max(240, available.width() - 32)
            assert dialog.height() <= max(240, available.height() - 48)

        def run_modal(trigger, interact):
            errors, observed = [], []
            timer = QTimer(window)

            def reply():
                dialog = qt.activeModalWidget()
                if dialog is None:
                    return
                timer.stop()
                observed.append(dialog)
                try:
                    check_shell(dialog)
                    interact(dialog)
                    assert not dialog.isVisible()
                except BaseException as exc:
                    errors.append(exc)
                    dialog.reject()

            timer.timeout.connect(reply)
            timer.start(10)
            try:
                trigger()
            finally:
                timer.stop()
            if errors:
                raise errors[0]
            assert len(observed) == 1

        def drive():
            try:
                if not window._deferred_init_done:
                    assert time.monotonic() < deadline, "Desktop initial load did not complete"
                    QTimer.singleShot(10, drive)
                    return
                assert window._startup_first_paint_seen
                row = window._row_for_invoice_id(invoice_id)
                assert row >= 0
                window.table.selectRow(row)
                qt.processEvents()
                panel = window._detail_panel
                assert panel.btn_inline_more.isVisible()
                assert panel.action_inline_delete in panel.btn_inline_more.menu().actions()
                assert panel.action_inline_delete.isEnabled()

                def cancel_delete(box):
                    assert isinstance(box, QMessageBox)
                    yes, no = box.button(QMessageBox.Yes), box.button(QMessageBox.No)
                    assert "是" in yes.text() and "否" in no.text()
                    assert box.defaultButton() is no
                    QTest.keyClick(box, Qt.Key_Return)
                    assert box.clickedButton() is no

                run_modal(panel.action_inline_delete.trigger, cancel_delete)
                assert window.db.get_invoice(invoice_id) is not None
                assert not window.db.get_invoice(invoice_id)["is_deleted"]

                window.workbench_nav_buttons["export"].click()
                qt.processEvents()
                assert window.btn_export_create_group.isVisible()

                def cancel_input(dialog):
                    assert isinstance(dialog, QInputDialog)
                    buttons = dialog.findChild(QDialogButtonBox)
                    ok, cancel = buttons.button(QDialogButtonBox.Ok), buttons.button(QDialogButtonBox.Cancel)
                    assert "确定" in ok.text() and "取消" in cancel.text()
                    assert ok.isDefault() and cancel.x() < ok.x()
                    field = dialog.findChild(QLineEdit)
                    # Offscreen Qt may not grant OS-level focus to a freshly
                    # opened modal; its own designated focus widget still must
                    # be the input, not a confirmation button.
                    assert dialog.focusWidget() is field
                    field.setText("Unsubmitted synthetic group")
                    QTest.keyClick(field, Qt.Key_Escape)

                run_modal(window.btn_export_create_group.click, cancel_input)
                assert window.db.list_claim_groups() == []
                assert qt._desktop_dialog_presentation is handler and not premature
                window.close()
                print("STARTUP_DIALOG_PRESENTATION=PASS", flush=True)
                qt.exit(0)
            except BaseException:
                traceback.print_exc()
                window.close()
                qt.exit(1)

        QTimer.singleShot(0, drive)

    with patch.object(app_module.StartupSplash, "show_message", progress), \
            patch.object(app_module.InvoiceReviewApp, "_init_ui", init_ui), \
            patch.object(startup_lifecycle, "reveal_startup_window", reveal):
        # Normal no-argument desktop launcher, not the reduced legacy probe.
        launcher = Path(__file__).resolve().parents[1] / "scripts/invoice_fetch_desktop.py"
        sys.argv = [str(launcher)]
        runpy.run_path(str(launcher), run_name="__main__")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in {"--desktop-child", "--failure-child"}:
        _child(sys.argv[1])
    else:
        unittest.main()
