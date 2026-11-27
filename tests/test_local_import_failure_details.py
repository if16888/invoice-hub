"""Desktop-only per-source failures use synthetic files and real result controls."""

import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPlainTextEdit

from scripts.invoice_fetch import services
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp, LocalImportFailuresDialog
from scripts.invoice_fetch.invoice_parser import InvoiceInfo
from scripts.invoice_fetch.mobile_upload import public_upload_result
from scripts.invoice_fetch.scan_lifecycle import ScanControl
from tests import original_modal_entry_points


class LocalImportFailureDetailsTests(unittest.TestCase):
    def test_mixed_import_reports_distinct_paths_only_when_desktop_requests_them(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "selected"
            runtime = Path(td) / "runtime"
            for folder in ("north", "south"):
                (root / folder).mkdir(parents=True)
                (root / folder / "same.zip").write_bytes(b"synthetic invalid zip")
            (root / "invoice.pdf").write_bytes(b"%PDF-1.4 synthetic")
            (root / "manual.ofd").write_bytes(b"synthetic pending material")
            parser = Mock()
            parser.parse_pdf.return_value = InvoiceInfo(
                invoice_number="SYNTHETIC-LOCAL-1", invoice_date="2026-10-01",
                expense_date="2026-10-01", total_amount="10.00", seller_name="Synthetic Seller",
                parse_success=True,
            )
            with patch.object(services, "RUNTIME_DIR", runtime), InvoiceDB(runtime / "invoices.db") as db:
                stats = services._import_local_directory(root, db, parser, {}, runtime / "attachments",
                                                         include_desktop_failure_details=True)
                ordinary = services._import_local_directory(root, db, parser, {}, runtime / "attachments")
            self.assertEqual((stats["added"], stats["pending_manual"], stats["failed"]), (1, 1, 2))
            self.assertEqual(len(stats["new_invoice_ids"]), 2)
            self.assertEqual(stats["review_invoice_ids"], stats["new_invoice_ids"])
            self.assertEqual([detail["source"] for detail in stats["failure_details"]],
                             ["north/same.zip", "south/same.zip"])
            self.assertTrue(all("压缩包损坏" in detail["reason"] for detail in stats["failure_details"]))
            self.assertNotIn("failure_details", ordinary)
            self.assertEqual(ordinary["failed"], 2)
            self.assertNotIn("north/same.zip", repr(ordinary))
            public = public_upload_result({"imported": stats})
            self.assertNotIn("failure_details", public)
            self.assertNotIn("north/same.zip", repr(public))

    def test_external_drop_uses_absolute_local_paths(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            first, second = base / "a" / "same.zip", base / "b" / "same.zip"
            for path in (first, second):
                path.parent.mkdir()
                path.write_bytes(b"synthetic invalid zip")
            stats = services._import_local_directory(first.parent, Mock(), Mock(), {}, base / "attachments",
                                                     file_paths=(first, second), allow_external_file_paths=True,
                                                     include_desktop_failure_details=True)
            self.assertEqual(stats["failed"], 2)
            self.assertEqual({detail["source"] for detail in stats["failure_details"]},
                             {str(first.resolve()), str(second.resolve())})

    def test_fixed_failure_reasons_do_not_echo_exception_text(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "selected"
            source.mkdir()
            private = "SYNTHETIC PRIVATE EXCEPTION TEXT /private/with space/path.pdf"
            exceptions = {
                "a.pdf": (PermissionError(private), "无法访问文件"),
                "b.pdf": (FileNotFoundError(private), "文件不存在"),
                "c.pdf": (sqlite3.OperationalError(private), "本地数据库操作失败"),
                "d.pdf": (RuntimeError(private), "文件处理失败"),
                "e.pdf": (OSError(private), "文件读取或保存失败"),
            }
            for name in exceptions:
                (source / name).write_bytes(b"%PDF synthetic")

            def fail(name, *_args, **_kwargs):
                raise exceptions[name][0]

            with patch.object(services, "_import_local_pdf", side_effect=fail), self.assertLogs("invoice_fetch", "WARNING") as logs:
                stats = services._import_local_directory(source, Mock(), Mock(), {}, base / "attachments",
                                                         include_desktop_failure_details=True)
            self.assertEqual(stats["failed"], len(exceptions))
            for detail in stats["failure_details"]:
                self.assertIn(exceptions[detail["source"]][1], detail["reason"])
            self.assertNotIn(private, repr(stats))
            self.assertNotIn("SYNTHETIC PRIVATE EXCEPTION TEXT", "\n".join(logs.output))
            self.assertIn("PermissionError", "\n".join(logs.output))

    def test_archive_limits_add_one_failure_detail_without_changing_member_counts(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "selected"
            source.mkdir()
            archive = source / "too-many.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                for index in range(21):
                    zf.writestr(f"invoice-{index}.pdf", b"%PDF synthetic")
            stats = services._import_local_directory(source, Mock(), Mock(), {}, base / "attachments",
                                                     include_desktop_failure_details=True)
            self.assertEqual(stats["failed"], 1)
            self.assertEqual(len(stats["failure_details"]), 1)
            self.assertEqual(stats["archive_members_discovered"], 21)
            self.assertEqual(stats["archive_members_unprocessed"], 21)
            self.assertEqual(stats["archive_members_processed"], 0)
            self.assertEqual(stats["skipped"], 21)
            self.assertIn(stats["skipped_details"][0]["reason"], stats["failure_details"][0]["reason"])
            self.assertIn("拆分", stats["failure_details"][0]["reason"])
            with patch.object(services, "_inspect_local_zip", return_value=(1, services._LOCAL_ZIP_MAX_BYTES + 1)), patch.object(
                services, "_extract_local_zip"
            ) as extract:
                oversized = services._import_local_directory(source, Mock(), Mock(), {}, base / "attachments",
                                                             include_desktop_failure_details=True)
            extract.assert_not_called()
            self.assertEqual(oversized["failed"], 1)
            self.assertEqual(len(oversized["failure_details"]), 1)
            self.assertIn("超过 50 MB", oversized["failure_details"][0]["reason"])

    def test_cancelled_batch_only_retains_completed_failures(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "selected"
            source.mkdir()
            for name in ("a.pdf", "b.pdf", "c.pdf"):
                (source / name).write_bytes(b"%PDF synthetic")
            control = ScanControl()
            processed = []

            def process(name, *_args, **_kwargs):
                processed.append(name)
                if name == "a.pdf":
                    raise PermissionError("synthetic private reason")
                control.cancel()
                raise services.ScanCancelled("已取消")

            with patch.object(services, "_import_local_pdf", side_effect=process):
                stats = services._import_local_directory(source, Mock(), Mock(), {}, base / "attachments",
                                                         scan_control=control, include_desktop_failure_details=True)
            self.assertEqual(processed, ["a.pdf", "b.pdf"])
            self.assertTrue(stats["cancelled"])
            self.assertEqual(stats["failed"], 1)
            self.assertEqual([detail["source"] for detail in stats["failure_details"]], ["a.pdf"])


class LocalImportFailureGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _open_real_details(self, window):
        # Restore the actual nested Qt modal just for this dialog; the
        # suite-wide guard remains installed for unrelated warnings.
        real_exec = original_modal_entry_points().get("QDialog.exec", QDialog.exec)
        texts, errors = [], []

        def execute(dialog):
            def inspect_dialog():
                try:
                    self.assertIs(QApplication.activeModalWidget(), dialog)
                    self.assertEqual(dialog.windowTitle(), "本地导入失败明细")
                    self.assertTrue(dialog.details.isReadOnly())
                    self.assertIsInstance(dialog.details, QPlainTextEdit)
                    texts.append(dialog.details.toPlainText())
                except BaseException as error:
                    errors.append(error)
                finally:
                    dialog.reject()

            timer = QTimer(dialog)
            timer.setSingleShot(True)
            timer.timeout.connect(inspect_dialog)
            timer.start(0)
            try:
                return real_exec(dialog)
            finally:
                timer.stop()

        button = window.btn_import_recent_failures
        self.assertTrue(button.isVisible())
        with patch.object(LocalImportFailuresDialog, "exec", execute):
            QTest.mouseClick(button, Qt.LeftButton)
        if errors:
            raise errors[0]
        self.assertEqual(len(texts), 1)
        return texts[0]

    def test_latest_mixed_all_failed_cancelled_and_successful_batches(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "invoices.db", splash=None)
            try:
                window._deferred_init()
                window.resize(1200, 800)
                window.show()
                window._switch_main_page("imports")
                window._set_import_source_selected("local")
                self.app.processEvents()
                invoice_ids = [window.db.insert_invoice({"invoice_number": f"SYNTHETIC-{index}",
                                                         "review_status": "to_review"}) for index in (1, 2)]
                reason = "压缩包损坏。请重新获取原始压缩包。"
                with patch.object(QMessageBox, "information") as completion:
                    window._import_local_finished({
                        "added": 1, "pending_manual": 1, "failed": 2,
                        "new_invoice_ids": invoice_ids, "review_invoice_ids": invoice_ids,
                        "failure_details": [{"source": f"{folder}/<b>same</b>.zip", "reason": reason}
                                            for folder in ("north", "south")],
                    })
                    summary = completion.call_args.args[-1]
                self.assertIn("真正失败: 2", summary)
                self.assertIn("查看失败明细", summary)
                self.assertNotIn("north/", summary)
                self.assertEqual(window._import_activities[0].review_invoice_ids, tuple(invoice_ids))
                self.assertNotIn("north/", repr(window._import_activities[0]))
                self.assertEqual(window.btn_import_recent_review.text(), "处理新增 2 张")
                self.assertEqual(window.btn_import_recent_failures.text(), "查看失败明细（2）")
                detail = self._open_real_details(window)
                self.assertIn("north/<b>same</b>.zip", detail)
                self.assertIn("south/<b>same</b>.zip", detail)
                self.assertIn(reason, detail)
                self.assertNotIn("north/", window.txt_log.toPlainText())

                with patch.object(QMessageBox, "information"):
                    window._import_local_finished({"failed": 1, "failure_details": [{"source": "only.zip", "reason": reason}]})
                self.assertTrue(window.btn_import_recent_review.isHidden())
                self.assertEqual(window.btn_import_recent_failures.text(), "查看失败明细（1）")
                detail = self._open_real_details(window)
                self.assertIn("only.zip", detail)
                self.assertNotIn("north/", detail)
                self.assertEqual(window._import_activities[1].local_failure_details, ())

                with patch.object(QMessageBox, "information") as completion:
                    window._import_local_finished({"cancelled": True, "failed": 1,
                                                   "failure_details": [{"source": "completed.zip", "reason": reason}]})
                    completion.assert_not_called()
                self.assertEqual(window._import_activities[0].status, "cancelled")
                detail = self._open_real_details(window)
                self.assertIn("completed.zip", detail)
                self.assertNotIn("only.zip", detail)

                with patch.object(QMessageBox, "information"):
                    window._import_local_finished({"added": 0, "failed": 0, "failure_details": []})
                self.assertTrue(window.btn_import_recent_failures.isHidden())
                self.assertTrue(all(not activity.local_failure_details for activity in window._import_activities))
            finally:
                window.close()
                window.deleteLater()
                QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()

    def test_failure_dialog_is_scrollable_plain_text(self):
        text = "\n\n".join(f"失败文件 {index}\n目录/" + "<b>文件</b>" * 60 + ".zip\n请重新获取文件。" for index in range(40))
        dialog = LocalImportFailuresDialog(None, text, 40)
        try:
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.details.toPlainText(), text)
            self.assertEqual(dialog.details.lineWrapMode(), QPlainTextEdit.WidgetWidth)
            self.assertEqual(dialog.details.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
            self.assertGreater(dialog.details.verticalScrollBar().maximum(), 0)
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
