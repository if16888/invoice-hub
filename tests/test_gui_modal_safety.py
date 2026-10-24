"""Regression tests for the test-suite modal-dialog safety net.

The guard under ``tests/__init__.py`` exists because ``unittest discover`` keeps
everything in one process: a leaked window can show a modal ``QMessageBox``
during a later test's ``processEvents()`` and block the whole run forever under
the offscreen platform.  These tests prove the replacement entry points return
immediately, record the call, and neutralise a GUI error path built on a
``MagicMock`` database.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

try:
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
except ImportError:  # pragma: no cover - data-only test environments
    QApplication = QDialog = QMessageBox = None

import tests as tests_package
from tests import (
    find_modal_dialog_calls,
    is_modal_guard_installed,
    original_modal_entry_points,
    reset_modal_dialog_calls,
    take_modal_dialog_calls,
)


@unittest.skipIf(QMessageBox is None, "PySide6 is not available")
class ModalGuardStaticEntryPointTests(unittest.TestCase):
    def setUp(self):
        reset_modal_dialog_calls()

    def test_message_box_statics_return_immediately_and_record_calls(self):
        self.assertTrue(is_modal_guard_installed())

        started = time.monotonic()
        critical = QMessageBox.critical(None, "错误", "synthetic failure")
        warning = QMessageBox.warning(None, "警告", "synthetic warning")
        information = QMessageBox.information(None, "提示", "synthetic info")
        elapsed = time.monotonic() - started

        # The real modal calls would block forever under offscreen Qt.
        self.assertLess(elapsed, 2.0)
        self.assertEqual(critical, QMessageBox.Ok)
        self.assertEqual(warning, QMessageBox.Ok)
        self.assertEqual(information, QMessageBox.Ok)

        calls = take_modal_dialog_calls()
        self.assertEqual(
            [call.name for call in calls],
            ["critical", "warning", "information"],
        )
        self.assertEqual(calls[0].title, "错误")
        self.assertEqual(calls[0].text, "synthetic failure")
        self.assertEqual(calls[2].text, "synthetic info")

    def test_question_defaults_to_cancel_and_is_recorded(self):
        reply = QMessageBox.question(None, "确认", "继续执行？")
        self.assertEqual(reply, QMessageBox.No)
        calls = find_modal_dialog_calls("question")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].text, "继续执行？")

    def test_original_entry_points_are_kept_for_debugging(self):
        originals = original_modal_entry_points()
        for key in (
            "QMessageBox.critical",
            "QMessageBox.warning",
            "QMessageBox.information",
            "QMessageBox.question",
            "QMessageBox.exec",
            "QDialog.exec",
        ):
            self.assertIn(key, originals)


@unittest.skipIf(QMessageBox is None, "PySide6 is not available")
class ModalGuardExecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def setUp(self):
        reset_modal_dialog_calls()

    def test_message_box_and_dialog_exec_do_not_run_a_modal_loop(self):
        box = QMessageBox()
        dialog = QDialog()
        try:
            started = time.monotonic()
            box_result = box.exec()
            dialog_result = dialog.exec()
            elapsed = time.monotonic() - started
        finally:
            box.deleteLater()
            dialog.deleteLater()
            self.app.processEvents()

        self.assertLess(elapsed, 2.0)
        self.assertEqual(box_result, QMessageBox.Ok)
        self.assertEqual(dialog_result, QDialog.Accepted)
        self.assertEqual(
            [call.name for call in take_modal_dialog_calls()],
            ["QMessageBox.exec", "QDialog.exec"],
        )


@unittest.skipIf(QMessageBox is None, "PySide6 is not available")
class ModalGuardGuiErrorPathTests(unittest.TestCase):
    """The exact contamination pattern that used to deadlock the full suite."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def test_deferred_init_with_broken_mock_db_returns_instead_of_blocking(self):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "invoices.db", splash=None)
            try:
                # Emulate the leaked-window contamination: a MagicMock where a
                # real InvoiceDB should be makes _load_invoices take its except
                # branch and try to show a modal critical dialog.
                window.db.close()
                broken_db = MagicMock()
                broken_db.is_open = True
                broken_db.count_review_invoices.side_effect = RuntimeError(
                    "'>' not supported between instances of 'MagicMock' and 'int'"
                )
                window.db = broken_db

                reset_modal_dialog_calls()
                started = time.monotonic()
                window._deferred_init()
                elapsed = time.monotonic() - started

                self.assertLess(elapsed, 10.0)
                critical_calls = find_modal_dialog_calls("critical")
                self.assertTrue(critical_calls)
                self.assertIn("加载发票失败", critical_calls[0].text)
            finally:
                # Never leave a magic-mock database or pending deferred work
                # behind for another test to trip over.
                window._deferred_init_done = True
                window.close()
                window.deleteLater()
                window.db = None
                self.app.processEvents()

    def test_guard_module_import_is_safe_without_pyside6(self):
        script = (
            "import sys\n"
            "sys.modules['PySide6'] = None\n"
            "import tests\n"
            "print('guard=', tests.is_modal_guard_installed())\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("guard= False", result.stdout)


if __name__ == "__main__":
    unittest.main()
