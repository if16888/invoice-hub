import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch import claim_export as claim_export_module
from scripts.invoice_fetch import review_status
from scripts.invoice_fetch.claim_export import export_claim_package
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


if __name__ == "__main__":
    unittest.main()
