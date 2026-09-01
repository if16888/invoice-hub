from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from scripts.invoice_fetch import services
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.workers import LocalImportWorker
from scripts.invoice_fetch.scan_lifecycle import ScanControl


class LocalImportCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _source_dir(self, base: Path) -> Path:
        source_dir = base / "source"
        source_dir.mkdir()
        for name in ("A.pdf", "B.pdf", "C.pdf"):
            (source_dir / name).write_bytes(f"%PDF-{name}".encode("ascii"))
        return source_dir

    @staticmethod
    def _result(invoice_id: int):
        return services.LocalImportItemResult(
            status="added",
            invoice_id=invoice_id,
            created=True,
            reviewable=True,
        )

    def test_cancel_between_top_level_sources_keeps_completed_results(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source_dir = self._source_dir(base)
            runtime_dir = base / "runtime"
            att_dir = runtime_dir / "attachments"
            control = ScanControl()
            processed = []

            def process_source(source_name, *_args, **_kwargs):
                processed.append(source_name)
                if source_name == "B.pdf":
                    control.cancel()
                return self._result(len(processed))

            with patch.object(services, "RUNTIME_DIR", runtime_dir), patch.object(
                services, "_import_local_pdf", side_effect=process_source
            ):
                with InvoiceDB(base / "invoices.db") as db:
                    stats = services._import_local_directory(
                        source_dir,
                        db,
                        parser=Mock(),
                        categories={},
                        att_dir=att_dir,
                        scan_control=control,
                    )

            self.assertEqual(processed, ["A.pdf", "B.pdf"])
            self.assertTrue(stats["cancelled"])
            self.assertEqual(stats["added"], 2)
            self.assertEqual(stats["new_invoice_ids"], [1, 2])
            self.assertEqual(stats["failed"], 0)

    def test_cancel_before_first_source_processes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source_dir = self._source_dir(base)
            control = ScanControl()
            control.cancel()
            helper = Mock(return_value=self._result(1))

            with patch.object(services, "_import_local_pdf", helper):
                with InvoiceDB(base / "invoices.db") as db:
                    stats = services._import_local_directory(
                        source_dir,
                        db,
                        parser=Mock(),
                        categories={},
                        att_dir=base / "attachments",
                        scan_control=control,
                    )

            helper.assert_not_called()
            self.assertTrue(stats["cancelled"])
            self.assertEqual(stats["failed"], 0)
            self.assertEqual(stats["added"], 0)
            self.assertEqual(stats["new_invoice_ids"], [])

    def test_zip_is_one_boundary_and_finishes_all_extracted_members(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source_dir = base / "source"
            source_dir.mkdir()
            archive = source_dir / "bundle.zip"
            next_source = source_dir / "next.pdf"
            archive.write_bytes(b"zip placeholder")
            next_source.write_bytes(b"%PDF-next")
            control = ScanControl()
            extracted = [base / "member-1.pdf", base / "member-2.pdf"]
            processed = []

            def process_source(source_name, *_args, **_kwargs):
                processed.append(source_name)
                if len(processed) == 1:
                    control.cancel()
                return self._result(len(processed))

            with patch.object(services, "_extract_local_zip", return_value=extracted), patch.object(
                services, "_import_local_pdf", side_effect=process_source
            ):
                with InvoiceDB(base / "invoices.db") as db:
                    stats = services._import_local_directory(
                        source_dir,
                        db,
                        parser=Mock(),
                        categories={},
                        att_dir=base / "attachments",
                        scan_control=control,
                    )

            self.assertEqual(processed, ["bundle.zip", "bundle.zip"])
            self.assertTrue(stats["cancelled"])
            self.assertEqual(stats["added"], 2)
            self.assertEqual(stats["failed"], 0)

    def test_normal_wrapper_exports_once(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source_dir = base / "source"
            source_dir.mkdir()
            db_path = base / "invoices.db"
            stats = {"added": 1, "duplicates": 0, "conflicts": 0, "pending_manual": 0, "failed": 0}

            with patch.object(services, "_import_local_directory", return_value=stats) as operation, patch.object(
                services, "InvoiceParser", return_value=Mock()
            ), patch.object(services, "export_excel") as export:
                result = services.import_local_directory(source_dir, db_path)

            self.assertEqual(result, stats)
            operation.assert_called_once()
            self.assertIsNone(operation.call_args.kwargs["scan_control"])
            self.assertNotIn("cancelled", result)
            export.assert_called_once()

    def test_cancelled_wrapper_does_not_export(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source_dir = base / "source"
            source_dir.mkdir()
            db_path = base / "invoices.db"
            control = ScanControl()
            stats = {
                "added": 1,
                "duplicates": 0,
                "conflicts": 0,
                "pending_manual": 0,
                "failed": 0,
                "cancelled": True,
            }

            with patch.object(services, "_import_local_directory", return_value=stats) as operation, patch.object(
                services, "InvoiceParser", return_value=Mock()
            ), patch.object(services, "export_excel") as export:
                result = services.import_local_directory(
                    source_dir,
                    db_path,
                    scan_control=control,
                )

            self.assertTrue(result["cancelled"])
            self.assertIs(operation.call_args.kwargs["scan_control"], control)
            export.assert_not_called()

    def test_worker_reuses_control_and_emits_cancelled_finished_result(self):
        worker = LocalImportWorker(Path("source"), Path("invoices.db"))
        finished = []
        errors = []
        worker.finished.connect(finished.append)
        worker.error.connect(errors.append)
        observed = {}

        def fake_import(import_dir, db_path, *, scan_control):
            observed["import_dir"] = import_dir
            observed["db_path"] = db_path
            observed["control"] = scan_control
            scan_control.cancel()
            return {"added": 1, "failed": 0, "cancelled": True}

        with patch("scripts.invoice_fetch.services.import_local_directory", side_effect=fake_import):
            worker.run()

        self.assertIs(observed["control"], worker.control)
        self.assertEqual(observed["import_dir"], Path("source"))
        self.assertEqual(observed["db_path"], Path("invoices.db"))
        self.assertEqual(len(finished), 1)
        self.assertTrue(finished[0]["cancelled"])
        self.assertFalse(errors)

    def test_gui_renders_cancelled_import_without_error_dialog(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "gui.db", splash=None)
            window.show()
            self.app.processEvents()
            try:
                with patch.object(QMessageBox, "information") as information, patch.object(
                    QMessageBox, "critical"
                ) as critical:
                    window._import_local_finished(
                        {
                            "added": 1,
                            "duplicates": 0,
                            "conflicts": 0,
                            "pending_manual": 0,
                            "failed": 0,
                            "cancelled": True,
                            "new_invoice_ids": (),
                            "review_invoice_ids": (),
                        }
                    )

                information.assert_not_called()
                critical.assert_not_called()
                self.assertIn("已取消", window.statusBar().currentMessage())
            finally:
                window.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
