import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.invoice_fetch import claim_export as claim_export_module
from scripts.invoice_fetch import review_status
from scripts.invoice_fetch.claim_export import (
    export_claim_package,
    inspect_extra_material,
)
from scripts.invoice_fetch.db import InvoiceDB


class ExportMaterialPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication

            cls.qt_app = QApplication.instance() or QApplication([])
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"PySide6 is not available: {exc}")

    def _create_claim(self, root: Path, rows: list[dict]) -> tuple[Path, Path, int]:
        project_root = root / "project"
        runtime_dir = project_root / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        db_path = runtime_dir / "invoices.db"

        with InvoiceDB(db_path) as db:
            claim_id = db.create_claim_group("Synthetic Material Preflight")
            for index, row in enumerate(rows, start=1):
                attachment_path = row.get("attachment_path", f"attachments/invoice-{index}.pdf")
                extra_paths = row.get("extra_paths", [])
                payload = {
                    "invoice_number": row.get("invoice_number", f"SYN-{index}"),
                    "total_amount": row.get("total_amount", "100.00"),
                    "seller_name": row.get("seller_name", "Synthetic Seller"),
                    "invoice_date": "2026-08-05",
                    "category": "交通",
                    "review_status": row.get("review_status", review_status.APPROVED),
                    "attachment_path": attachment_path,
                    "has_extra": row.get("has_extra", False),
                    "extra_type": row.get("extra_type", ""),
                    "missing_extra": row.get("missing_extra", False),
                    "extra_paths": json.dumps(extra_paths, ensure_ascii=False),
                }
                invoice_id = db.insert_invoice(payload)
                db.add_invoice_to_claim(claim_id, invoice_id)

        for index, row in enumerate(rows, start=1):
            attachment_path = row.get("attachment_path", f"attachments/invoice-{index}.pdf")
            files_to_create = list(row.get("files", []))
            if row.get("create_attachment", True) and attachment_path:
                files_to_create.insert(0, attachment_path)
            for relative_path in files_to_create:
                if not relative_path:
                    continue
                path = runtime_dir / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic evidence")

        return project_root, runtime_dir, claim_id

    def _assert_no_partial_package(self, export_root: Path) -> None:
        if export_root.exists():
            self.assertEqual(list(export_root.iterdir()), [])

    def test_missing_extra_is_reported_by_shared_integrity_judgement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_root, runtime_dir, _ = self._create_claim(
                root,
                [{"missing_extra": True}],
            )
            result = inspect_extra_material(
                {"missing_extra": True, "extra_paths": [], "has_extra": False, "extra_type": ""},
                runtime_dir,
            )
            self.assertTrue(result["missing_extra"])
            self.assertFalse(result["unavailable_extra"])
            self.assertEqual(project_root.name, "project")

    def test_gui_preflight_blocks_missing_extra_and_shows_specific_row(self):
        from scripts.invoice_fetch.gui import app as app_module
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [{"missing_extra": True, "create_attachment": False}],
            )
            with patch.object(app_module, "PROJECT_ROOT", project_root), patch.object(
                app_module, "RUNTIME_DIR", runtime_dir
            ):
                window = InvoiceReviewApp(runtime_dir / "invoices.db", splash=None)
                try:
                    window._deferred_init()
                    self.qt_app.processEvents()
                    stats = window._claim_export_preflight_stats(claim_id)
                    self.assertEqual(stats["missing_extra"], 1)
                    self.assertEqual(stats["unavailable_extra"], 0)
                    self.assertIn("缺补充材料：1 张", window._format_claim_export_preflight_text(stats))

                    window._refresh_export_page()
                    window.export_group_list.setCurrentRow(0)
                    window._sync_export_claim_selection()
                    self.assertFalse(window.btn_run_export_page.isEnabled())
                    self.assertEqual(window.export_check_missing_extra.lbl_value.text(), "1 张")
                    self.assertIn("缺补充材料 1 张", window.lbl_export_action_hint.text())
                finally:
                    if getattr(window, "db", None) is not None:
                        window.db.close()
                    window.close()
                    window.deleteLater()
                    self.qt_app.processEvents()

    def test_gui_export_action_rechecks_material_before_export(self):
        from scripts.invoice_fetch.gui import app as app_module
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [{"missing_extra": True, "create_attachment": False}],
            )
            export_root = project_root / "exports"
            with patch.object(app_module, "PROJECT_ROOT", project_root), patch.object(
                app_module, "RUNTIME_DIR", runtime_dir
            ):
                window = InvoiceReviewApp(runtime_dir / "invoices.db", splash=None)
                try:
                    window._deferred_init()
                    window.combo_claims.clear()
                    window.combo_claims.addItem("Synthetic Material Preflight", claim_id)
                    window.combo_claims.setCurrentIndex(0)

                    approved_button = Mock()
                    include_button = Mock()
                    cancel_button = Mock()
                    with patch("scripts.invoice_fetch.gui.app.QMessageBox") as message_box:
                        message_box.return_value.addButton.side_effect = [
                            approved_button,
                            include_button,
                            cancel_button,
                        ]
                        message_box.return_value.clickedButton.return_value = approved_button
                        window._export_claim_package()

                        message_box.warning.assert_called_once()
                        warning_args = message_box.warning.call_args.args
                        self.assertEqual(warning_args[1], "导出已阻断")
                        self.assertIn("缺补充材料 1 张", warning_args[2])
                    self.assertFalse(export_root.exists())
                    self.assertEqual(window.db.list_export_runs(claim_id), [])
                finally:
                    if getattr(window, "db", None) is not None:
                        window.db.close()
                    window.close()
                    window.deleteLater()
                    self.qt_app.processEvents()

    def test_gui_mixed_status_keeps_approved_only_entry_and_blocks_pending_scope(self):
        from scripts.invoice_fetch.gui import app as app_module
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [
                    {
                        "invoice_number": "APPROVED-COMPLETE",
                        "review_status": review_status.APPROVED,
                        "missing_extra": False,
                        "create_attachment": False,
                    },
                    {
                        "invoice_number": "PENDING-MISSING",
                        "review_status": review_status.TO_REVIEW,
                        "missing_extra": True,
                        "create_attachment": False,
                    },
                ],
            )
            with patch.object(app_module, "PROJECT_ROOT", project_root), patch.object(
                app_module, "RUNTIME_DIR", runtime_dir
            ):
                window = InvoiceReviewApp(runtime_dir / "invoices.db", splash=None)
                try:
                    window._deferred_init()
                    self.qt_app.processEvents()
                    window._refresh_export_page()
                    window.export_group_list.setCurrentRow(0)
                    window._sync_export_claim_selection()

                    self.assertTrue(window.btn_run_export_page.isEnabled())
                    self.assertEqual(window.export_check_missing_extra.lbl_value.text(), "1 张")
                    self.assertIn("已通过发票可导出", window.lbl_export_action_hint.text())

                    window.combo_claims.clear()
                    window.combo_claims.addItem("Synthetic Material Preflight", claim_id)
                    window.combo_claims.setCurrentIndex(0)

                    approved_button = Mock()
                    include_button = Mock()
                    cancel_button = Mock()
                    with patch("scripts.invoice_fetch.gui.app.QMessageBox") as message_box, patch(
                        "scripts.invoice_fetch.claim_export.export_claim_package",
                        side_effect=RuntimeError("synthetic approved-only handoff"),
                    ) as exporter:
                        message_box.return_value.addButton.side_effect = [
                            approved_button,
                            include_button,
                            cancel_button,
                        ]
                        message_box.return_value.clickedButton.return_value = approved_button
                        window._export_claim_package()

                        exporter.assert_called_once()
                        self.assertFalse(exporter.call_args.kwargs["include_to_review"])
                        message_box.warning.assert_not_called()

                    approved_button = Mock()
                    include_button = Mock()
                    cancel_button = Mock()
                    with patch("scripts.invoice_fetch.gui.app.QMessageBox") as message_box, patch(
                        "scripts.invoice_fetch.claim_export.export_claim_package",
                    ) as exporter:
                        message_box.return_value.addButton.side_effect = [
                            approved_button,
                            include_button,
                            cancel_button,
                        ]
                        message_box.return_value.clickedButton.return_value = include_button
                        window._export_claim_package()

                        exporter.assert_not_called()
                        message_box.warning.assert_called_once()
                        warning_args = message_box.warning.call_args.args
                        self.assertEqual(warning_args[1], "导出已阻断")
                        self.assertIn("缺补充材料 1 张", warning_args[2])
                finally:
                    if getattr(window, "db", None) is not None:
                        window.db.close()
                    window.close()
                    window.deleteLater()
                    self.qt_app.processEvents()

    def test_direct_export_rejects_missing_extra_before_side_effects(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [{"missing_extra": True}],
            )
            export_root = project_root / "exports"
            with InvoiceDB(runtime_dir / "invoices.db") as db:
                with self.assertRaisesRegex(ValueError, "缺补充材料 1 张") as ctx:
                    export_claim_package(
                        db,
                        claim_id,
                        project_root,
                        runtime_dir,
                        export_root=export_root,
                    )
                self.assertNotIn(str(runtime_dir), str(ctx.exception))
                self.assertFalse(export_root.exists())
                self.assertEqual(db.list_export_runs(claim_id), [])

    def test_ordinary_invoice_with_empty_extra_paths_exports(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [{"missing_extra": False, "has_extra": False, "extra_type": "", "extra_paths": []}],
            )
            export_root = project_root / "exports"
            with InvoiceDB(runtime_dir / "invoices.db") as db:
                export_dir = export_claim_package(
                    db,
                    claim_id,
                    project_root,
                    runtime_dir,
                    export_root=export_root,
                )
                manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["item_count"], 1)
                self.assertEqual(manifest["items"][0]["extra_paths"], [])
                self.assertEqual(len(db.list_export_runs(claim_id)), 1)

    def test_valid_extra_path_exports_and_is_in_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [{
                    "missing_extra": False,
                    "has_extra": True,
                    "extra_type": "水单",
                    "extra_paths": [
                        "attachments/evidence.pdf",
                        "attachments/evidence-2.pdf",
                    ],
                    "files": [
                        "attachments/evidence.pdf",
                        "attachments/evidence-2.pdf",
                    ],
                }],
            )
            with InvoiceDB(runtime_dir / "invoices.db") as db:
                export_dir = export_claim_package(
                    db,
                    claim_id,
                    project_root,
                    runtime_dir,
                    export_root=project_root / "exports",
                )
                manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
                item = manifest["items"][0]
                self.assertEqual(len(item["copied_extra_paths"]), 2)
                self.assertTrue(
                    all((export_dir / copied_path).is_file() for copied_path in item["copied_extra_paths"])
                )
                self.assertEqual(len(db.list_export_runs(claim_id)), 1)

    def test_declared_missing_extra_path_blocks_export_without_run(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [{
                    "missing_extra": False,
                    "has_extra": True,
                    "extra_type": "水单",
                    "extra_paths": ["attachments/not-found.pdf"],
                }],
            )
            export_root = project_root / "exports"
            with InvoiceDB(runtime_dir / "invoices.db") as db:
                with self.assertRaisesRegex(ValueError, "补充材料不可用 1 张"):
                    export_claim_package(
                        db,
                        claim_id,
                        project_root,
                        runtime_dir,
                        export_root=export_root,
                    )
                self.assertFalse(export_root.exists())
                self.assertEqual(db.list_export_runs(claim_id), [])

    def test_extra_file_disappearing_after_preflight_cleans_partial_package(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [{
                    "missing_extra": False,
                    "has_extra": True,
                    "extra_type": "水单",
                    "extra_paths": ["attachments/evidence.pdf"],
                    "files": ["attachments/evidence.pdf"],
                }],
            )
            evidence_path = runtime_dir / "attachments/evidence.pdf"
            export_root = project_root / "exports"
            original_summary = claim_export_module.summarize_extra_material_issues

            def inspect_then_remove(invoices, inspected_runtime_dir):
                result = original_summary(invoices, inspected_runtime_dir)
                evidence_path.unlink()
                return result

            with InvoiceDB(runtime_dir / "invoices.db") as db:
                with patch.object(
                    claim_export_module,
                    "summarize_extra_material_issues",
                    side_effect=inspect_then_remove,
                ), patch.object(
                    claim_export_module,
                    "export_excel",
                ) as export_excel_mock, patch.object(
                    claim_export_module.json,
                    "dump",
                ) as manifest_dump_mock:
                    with self.assertRaisesRegex(ValueError, "补充材料复制失败或已不可用") as ctx:
                        export_claim_package(
                            db,
                            claim_id,
                            project_root,
                            runtime_dir,
                            export_root=export_root,
                        )
                export_excel_mock.assert_not_called()
                manifest_dump_mock.assert_not_called()
                self.assertNotIn(str(runtime_dir), str(ctx.exception))
                self.assertEqual(db.list_export_runs(claim_id), [])
                self._assert_no_partial_package(export_root)

    def test_extra_copy_oserror_is_sanitized_and_preserves_historical_exports(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [{
                    "missing_extra": False,
                    "has_extra": True,
                    "extra_type": "水单",
                    "extra_paths": ["attachments/evidence.pdf"],
                    "files": ["attachments/evidence.pdf"],
                }],
            )
            evidence_path = runtime_dir / "attachments/evidence.pdf"
            export_root = project_root / "exports"
            historical_dir = export_root / "historical-success"
            historical_dir.mkdir(parents=True)
            historical_marker = historical_dir / "manifest.json"
            historical_marker.write_text("synthetic history", encoding="utf-8")
            original_copy2 = claim_export_module.shutil.copy2

            def copy_with_evidence_failure(src, dst, *args, **kwargs):
                if Path(src) == evidence_path:
                    raise OSError(f"copy failed: {evidence_path}")
                return original_copy2(src, dst, *args, **kwargs)

            with InvoiceDB(runtime_dir / "invoices.db") as db:
                with patch.object(
                    claim_export_module.shutil,
                    "copy2",
                    side_effect=copy_with_evidence_failure,
                ), patch.object(
                    claim_export_module,
                    "export_excel",
                ) as export_excel_mock, patch.object(
                    claim_export_module.json,
                    "dump",
                ) as manifest_dump_mock:
                    with self.assertRaisesRegex(ValueError, "补充材料复制失败或已不可用") as ctx:
                        export_claim_package(
                            db,
                            claim_id,
                            project_root,
                            runtime_dir,
                            export_root=export_root,
                        )
                export_excel_mock.assert_not_called()
                manifest_dump_mock.assert_not_called()
                self.assertNotIn(str(runtime_dir), str(ctx.exception))
                self.assertEqual(db.list_export_runs(claim_id), [])
                self.assertTrue(historical_marker.is_file())
                self.assertEqual(list(export_root.iterdir()), [historical_dir])

    def test_excel_quality_and_manifest_failures_clean_current_export_only(self):
        failure_cases = (
            ("excel", "export_excel"),
            ("quality", "_generate_quality_report"),
            ("manifest", "json.dump"),
        )
        for label, target in failure_cases:
            with self.subTest(stage=label), tempfile.TemporaryDirectory() as td:
                project_root, runtime_dir, claim_id = self._create_claim(
                    Path(td),
                    [{"missing_extra": False, "has_extra": False, "extra_paths": []}],
                )
                export_root = project_root / "exports"
                with InvoiceDB(runtime_dir / "invoices.db") as db:
                    if target == "json.dump":
                        failure_patch = patch.object(
                            claim_export_module.json,
                            "dump",
                            side_effect=OSError("synthetic manifest failure"),
                        )
                    else:
                        failure_patch = patch.object(
                            claim_export_module,
                            target,
                            side_effect=OSError(f"synthetic {label} failure"),
                        )
                    with failure_patch, self.assertRaises(OSError):
                        export_claim_package(
                            db,
                            claim_id,
                            project_root,
                            runtime_dir,
                            export_root=export_root,
                        )
                    self.assertEqual(db.list_export_runs(claim_id), [])
                    self._assert_no_partial_package(export_root)

    def test_mixed_claim_is_blocked_when_one_invoice_lacks_extra(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [
                    {"invoice_number": "VALID-1"},
                    {"invoice_number": "VALID-2"},
                    {"invoice_number": "MISSING-1", "missing_extra": True},
                ],
            )
            export_root = project_root / "exports"
            with InvoiceDB(runtime_dir / "invoices.db") as db:
                with self.assertRaisesRegex(ValueError, "缺补充材料 1 张"):
                    export_claim_package(
                        db,
                        claim_id,
                        project_root,
                        runtime_dir,
                        export_root=export_root,
                    )
                self.assertFalse(export_root.exists())
                self.assertEqual(db.list_export_runs(claim_id), [])

    def test_include_to_review_material_check_preserves_status_range(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                [
                    {"invoice_number": "APPROVED"},
                    {
                        "invoice_number": "PENDING-MISSING",
                        "review_status": review_status.TO_REVIEW,
                        "missing_extra": True,
                    },
                ],
            )
            with InvoiceDB(runtime_dir / "invoices.db") as db:
                approved_only_dir = export_claim_package(
                    db,
                    claim_id,
                    project_root,
                    runtime_dir,
                    include_to_review=False,
                    export_root=project_root / "approved-only",
                )
                approved_manifest = json.loads(
                    (approved_only_dir / "manifest.json").read_text(encoding="utf-8")
                )
                self.assertEqual(approved_manifest["item_count"], 1)

                with self.assertRaisesRegex(ValueError, "缺补充材料 1 张"):
                    export_claim_package(
                        db,
                        claim_id,
                        project_root,
                        runtime_dir,
                        include_to_review=True,
                        export_root=project_root / "include-pending",
                    )
                self.assertEqual(len(db.list_export_runs(claim_id)), 1)


if __name__ == "__main__":
    unittest.main()
