import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch import claim_export as claim_export_module
from scripts.invoice_fetch import review_status
from scripts.invoice_fetch.claim_export import (
    export_claim_package,
    inspect_invoice_materials,
    inspect_materials_for_invoices,
    inspect_original_attachment,
    summarize_extra_material_issues,
    verify_export_manifest,
)
from scripts.invoice_fetch.db import InvoiceDB


class ClaimExportOriginalIntegrityTests(unittest.TestCase):
    def _create_claim(
        self,
        root: Path,
        *,
        attachment_path: str,
        invoice_number: str = "ORIGINAL-001",
        extra_paths: list[str] | None = None,
    ) -> tuple[Path, Path, int]:
        project_root = root / "project"
        runtime_dir = project_root / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        db_path = runtime_dir / "invoices.db"
        extra_paths = list(extra_paths or [])

        with InvoiceDB(db_path) as db:
            claim_id = db.create_claim_group("Original Integrity")
            invoice_id = db.insert_invoice({
                "invoice_number": invoice_number,
                "total_amount": "100.00",
                "seller_name": "Synthetic Seller",
                "invoice_date": "2026-09-07",
                "category": "交通",
                "review_status": review_status.APPROVED,
                "attachment_path": attachment_path,
                "has_extra": bool(extra_paths),
                "extra_type": "水单" if extra_paths else "",
                "missing_extra": False,
                "extra_paths": json.dumps(extra_paths, ensure_ascii=False),
            })
            db.add_invoice_to_claim(claim_id, invoice_id)

        return project_root, runtime_dir, claim_id

    def _assert_no_current_partial_package(self, export_root: Path) -> None:
        if not export_root.exists():
            return
        self.assertEqual(
            [path for path in export_root.iterdir() if path.name != "historical-success"],
            [],
        )

    def test_complete_export_succeeds_only_with_materialized_original(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                attachment_path="attachments/original.pdf",
            )
            original_path = runtime_dir / "attachments/original.pdf"
            original_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.write_bytes(b"synthetic invoice original")
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
                copied_path = manifest["items"][0]["copied_attachment_path"]
                self.assertTrue(copied_path)
                self.assertTrue((export_dir / copied_path).is_file())
                self.assertEqual(len(manifest["files"]), 3)
                self.assertTrue(any(entry["path"] == manifest["spreadsheet"] for entry in manifest["files"]))
                self.assertTrue(verify_export_manifest(export_dir)["valid"])
                self.assertEqual(len(db.list_export_runs(claim_id)), 1)

    def test_empty_original_path_blocks_complete_export(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                attachment_path="",
                invoice_number="EMPTY-ORIGINAL",
            )
            export_root = project_root / "exports"

            with InvoiceDB(runtime_dir / "invoices.db") as db:
                with self.assertRaisesRegex(
                    ValueError,
                    "发票号 EMPTY-ORIGINAL的发票原件复制失败或已不可用",
                ) as ctx:
                    export_claim_package(
                        db,
                        claim_id,
                        project_root,
                        runtime_dir,
                        export_root=export_root,
                    )
                self.assertNotIn(str(runtime_dir), str(ctx.exception))
                self.assertEqual(db.list_export_runs(claim_id), [])
                self._assert_no_current_partial_package(export_root)

    def test_zero_byte_original_is_unavailable_during_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, _ = self._create_claim(
                Path(td),
                attachment_path="attachments/empty.xml",
                invoice_number="EMPTY-BYTES",
            )
            empty_path = runtime_dir / "attachments/empty.xml"
            empty_path.parent.mkdir(parents=True, exist_ok=True)
            empty_path.write_bytes(b"")

            result = inspect_original_attachment(
                {"attachment_path": "attachments/empty.xml"},
                runtime_dir,
            )
            self.assertFalse(result["available"])
            self.assertEqual(result["reason"], "empty")
            self.assertEqual(
                summarize_extra_material_issues(
                    [{"attachment_path": "attachments/empty.xml"}],
                    runtime_dir,
                )["missing_attachment"],
                1,
            )
            self.assertEqual(project_root.name, "project")

    def test_zero_byte_original_blocks_complete_export(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                attachment_path="attachments/empty.xml",
                invoice_number="EMPTY-BYTES-EXPORT",
            )
            empty_path = runtime_dir / "attachments/empty.xml"
            empty_path.parent.mkdir(parents=True, exist_ok=True)
            empty_path.write_bytes(b"")
            export_root = project_root / "exports"

            with InvoiceDB(runtime_dir / "invoices.db") as db:
                with self.assertRaisesRegex(
                    ValueError,
                    "发票号 EMPTY-BYTES-EXPORT的发票原件复制失败或已不可用",
                ) as ctx:
                    export_claim_package(
                        db,
                        claim_id,
                        project_root,
                        runtime_dir,
                        export_root=export_root,
                    )
                self.assertNotIn(str(runtime_dir), str(ctx.exception))
                self.assertEqual(db.list_export_runs(claim_id), [])
                self._assert_no_current_partial_package(export_root)
    def test_missing_or_directory_original_blocks_complete_export(self):
        for case_name, create_directory in (("missing", False), ("directory", True)):
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as td:
                project_root, runtime_dir, claim_id = self._create_claim(
                    Path(td),
                    attachment_path="attachments/original.pdf",
                    invoice_number=f"ORIGINAL-{case_name.upper()}",
                )
                source_path = runtime_dir / "attachments/original.pdf"
                if create_directory:
                    source_path.mkdir(parents=True, exist_ok=True)
                export_root = project_root / "exports"

                with InvoiceDB(runtime_dir / "invoices.db") as db:
                    with self.assertRaisesRegex(ValueError, "发票原件复制失败或已不可用"):
                        export_claim_package(
                            db,
                            claim_id,
                            project_root,
                            runtime_dir,
                            export_root=export_root,
                        )
                    self.assertEqual(db.list_export_runs(claim_id), [])
                    self._assert_no_current_partial_package(export_root)

    def test_original_copy_race_cleans_current_attempt_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                attachment_path="attachments/original.pdf",
                invoice_number="RACE-001",
            )
            source_path = runtime_dir / "attachments/original.pdf"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"synthetic invoice original")
            export_root = project_root / "exports"
            historical_dir = export_root / "historical-success"
            historical_dir.mkdir(parents=True, exist_ok=True)
            historical_marker = historical_dir / "manifest.json"
            historical_marker.write_text("historical package", encoding="utf-8")

            with InvoiceDB(runtime_dir / "invoices.db") as db, patch.object(
                claim_export_module.shutil,
                "copy2",
                side_effect=FileNotFoundError("source disappeared after preflight"),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "发票号 RACE-001的发票原件复制失败或已不可用",
                ):
                    export_claim_package(
                        db,
                        claim_id,
                        project_root,
                        runtime_dir,
                        export_root=export_root,
                    )
                self.assertEqual(db.list_export_runs(claim_id), [])

            self.assertTrue(historical_marker.is_file())
            self.assertEqual(historical_marker.read_text(encoding="utf-8"), "historical package")
            self._assert_no_current_partial_package(export_root)

    def test_zero_byte_copy_result_fails_closed_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                attachment_path="attachments/original.xml",
                invoice_number="COPY-EMPTY-001",
            )
            source_path = runtime_dir / "attachments/original.xml"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"synthetic invoice original")
            export_root = project_root / "exports"
            historical_dir = export_root / "historical-success"
            historical_dir.mkdir(parents=True, exist_ok=True)
            historical_marker = historical_dir / "manifest.json"
            historical_marker.write_text("historical package", encoding="utf-8")

            def copy_as_empty(_src, dest, *args, **kwargs):
                Path(dest).write_bytes(b"")

            with InvoiceDB(runtime_dir / "invoices.db") as db, patch.object(
                claim_export_module.shutil,
                "copy2",
                side_effect=copy_as_empty,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "发票号 COPY-EMPTY-001的发票原件复制失败或已不可用",
                ) as ctx:
                    export_claim_package(
                        db,
                        claim_id,
                        project_root,
                        runtime_dir,
                        export_root=export_root,
                    )
                self.assertNotIn(str(runtime_dir), str(ctx.exception))
                self.assertEqual(db.list_export_runs(claim_id), [])

            self.assertTrue(historical_marker.is_file())
            self.assertEqual(historical_marker.read_text(encoding="utf-8"), "historical package")
            self._assert_no_current_partial_package(export_root)
    def test_original_and_supplementary_material_must_both_copy(self):
        with tempfile.TemporaryDirectory() as td:
            project_root, runtime_dir, claim_id = self._create_claim(
                Path(td),
                attachment_path="attachments/original.pdf",
                extra_paths=["attachments/evidence.pdf"],
            )
            for relative_path in ("attachments/original.pdf", "attachments/evidence.pdf"):
                path = runtime_dir / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic export material")

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
                self.assertTrue((export_dir / item["copied_attachment_path"]).is_file())
                self.assertEqual(len(item["copied_extra_paths"]), 1)
                self.assertTrue((export_dir / item["copied_extra_paths"][0]).is_file())
                self.assertEqual(manifest["integrity"]["algorithm"], "sha256")
                self.assertEqual(len(manifest["files"]), 4)
                self.assertEqual(len(item["file_integrity"]), 2)
                self.assertTrue(verify_export_manifest(export_dir)["valid"])

                tampered = export_dir / item["copied_extra_paths"][0]
                tampered.write_bytes(tampered.read_bytes() + b"tampered")
                verification = verify_export_manifest(export_dir)
                self.assertFalse(verification["valid"])
                self.assertTrue(any("sha256 mismatch" in error for error in verification["errors"]))


class MaterialInspectionParallelTests(unittest.TestCase):
    """The batch preflight must stay exact while reading files in parallel."""

    def _build_batch(self, runtime_dir: Path, count: int = 12):
        attachments = runtime_dir / "attachments"
        attachments.mkdir(parents=True, exist_ok=True)
        invoices = []
        for index in range(count):
            if index % 4 == 0:
                # present and non-empty
                target = attachments / f"ok-{index}.pdf"
                target.write_bytes(b"%PDF-1.4 synthetic")
                invoices.append({"id": index, "attachment_path": f"attachments/{target.name}"})
            elif index % 4 == 1:
                # configured but missing
                invoices.append({"id": index, "attachment_path": f"attachments/gone-{index}.pdf"})
            elif index % 4 == 2:
                # present but zero bytes
                target = attachments / f"empty-{index}.pdf"
                target.write_bytes(b"")
                invoices.append({"id": index, "attachment_path": f"attachments/{target.name}"})
            else:
                # original fine, supplemental material missing
                target = attachments / f"with-extra-{index}.pdf"
                target.write_bytes(b"%PDF-1.4 synthetic")
                invoices.append(
                    {
                        "id": index,
                        "attachment_path": f"attachments/{target.name}",
                        "extra_paths": json.dumps([f"attachments/missing-extra-{index}.pdf"]),
                    }
                )
        return invoices

    def test_parallel_summary_matches_per_invoice_inspection(self):
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            invoices = self._build_batch(runtime_dir, count=12)

            summary = summarize_extra_material_issues(invoices, runtime_dir)

            per_invoice = [inspect_invoice_materials(invoice, runtime_dir) for invoice in invoices]
            self.assertEqual(summary["missing_attachment"], sum(
                1 for result in per_invoice if not result["attachment_available"]
            ))
            self.assertEqual(summary["missing_extra"], sum(
                1 for result in per_invoice if result["missing_extra"]
            ))
            self.assertEqual(summary["unavailable_extra"], sum(
                1 for result in per_invoice if result["unavailable_extra"]
            ))
            # 3 missing + 3 zero-byte originals; 3 invoices have a missing extra file.
            self.assertEqual(summary["missing_attachment"], 6)
            self.assertEqual(summary["unavailable_extra"], 3)

    def test_parallel_results_keep_input_order(self):
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            attachments = runtime_dir / "attachments"
            attachments.mkdir(parents=True)
            invoices = []
            for index in range(8):
                name = f"ordered-{index}.pdf"
                (attachments / name).write_bytes(b"x" if index % 2 == 0 else b"")
                invoices.append({"id": index, "attachment_path": f"attachments/{name}"})

            results = inspect_materials_for_invoices(invoices, runtime_dir)

            self.assertEqual(len(results), len(invoices))
            self.assertEqual(
                [result["attachment_available"] for result in results],
                [True, False] * 4,
            )

    def test_concurrent_batch_inspection_is_thread_safe(self):
        with tempfile.TemporaryDirectory() as td:
            runtime_dir = Path(td)
            invoices = self._build_batch(runtime_dir, count=40)
            expected = summarize_extra_material_issues(invoices, runtime_dir)

            results = []
            errors = []

            def worker():
                try:
                    results.append(summarize_extra_material_issues(invoices, runtime_dir))
                except Exception as exc:  # pragma: no cover - failure path
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)

            self.assertEqual(errors, [])
            self.assertEqual(len(results), 4)
            for result in results:
                self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
