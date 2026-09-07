import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch import review_status
from scripts.invoice_fetch.claim_export import export_claim_package
from scripts.invoice_fetch.db import InvoiceDB


class ClaimExportStatusErrorBoundaryTests(unittest.TestCase):
    def _create_materialized_claim(self, root: Path, invoice_number: str):
        project_root = root / "project"
        runtime_dir = project_root / "runtime"
        source_path = root / "private-person" / "invoices" / "original.pdf"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"synthetic invoice original")
        db_path = runtime_dir / "invoices.db"

        with InvoiceDB(db_path) as db:
            claim_id = db.create_claim_group("Status Error Boundary")
            invoice_id = db.insert_invoice(
                {
                    "invoice_number": invoice_number,
                    "total_amount": "100.00",
                    "seller_name": "Synthetic Seller",
                    "invoice_date": "2026-09-07",
                    "category": "交通",
                    "review_status": review_status.APPROVED,
                    "attachment_path": str(source_path),
                }
            )
            db.add_invoice_to_claim(claim_id, invoice_id)

        export_root = project_root / "exports"
        historical_dir = export_root / "historical-success"
        historical_dir.mkdir(parents=True, exist_ok=True)
        historical_marker = historical_dir / "manifest.json"
        historical_marker.write_text("historical package", encoding="utf-8")
        return project_root, runtime_dir, claim_id, source_path, export_root, historical_marker

    def _assert_failed_attempt_is_transactional(
        self,
        db: InvoiceDB,
        claim_id: int,
        export_root: Path,
        historical_marker: Path,
    ) -> None:
        self.assertEqual(db.list_export_runs(claim_id), [])
        self.assertTrue(historical_marker.is_file())
        self.assertEqual(
            historical_marker.read_text(encoding="utf-8"),
            "historical package",
        )
        self.assertEqual(
            [path for path in export_root.iterdir() if path.name != "historical-success"],
            [],
        )

    def test_source_status_oserror_is_sanitized_and_cleans_current_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            (
                project_root,
                runtime_dir,
                claim_id,
                source_path,
                export_root,
                historical_marker,
            ) = self._create_materialized_claim(Path(td), "STATUS-SOURCE-001")

            real_exists = Path.exists

            def injected_exists(path: Path) -> bool:
                if path == source_path:
                    raise PermissionError(13, "Permission denied", str(source_path))
                return real_exists(path)

            with InvoiceDB(runtime_dir / "invoices.db") as db, patch.object(
                Path,
                "exists",
                new=injected_exists,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "发票号 STATUS-SOURCE-001的发票原件复制失败或已不可用",
                ) as ctx:
                    export_claim_package(
                        db,
                        claim_id,
                        project_root,
                        runtime_dir,
                        export_root=export_root,
                    )

                message = str(ctx.exception)
                self.assertNotIn(str(source_path), message)
                self.assertNotIn(str(Path(td)), message)
                self._assert_failed_attempt_is_transactional(
                    db,
                    claim_id,
                    export_root,
                    historical_marker,
                )

    def test_destination_status_oserror_is_sanitized_and_cleans_current_attempt(self):
        for mode in ("destination", "collision_candidate"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                (
                    project_root,
                    runtime_dir,
                    claim_id,
                    source_path,
                    export_root,
                    historical_marker,
                ) = self._create_materialized_claim(Path(td), f"STATUS-{mode.upper()}")

                real_exists = Path.exists

                def injected_exists(path: Path) -> bool:
                    if path == source_path:
                        return real_exists(path)
                    if path.parent.name == "attachments" and path.name == "2026-09-07_original.pdf":
                        if mode == "destination":
                            raise PermissionError(13, "Permission denied", str(path))
                        return True
                    if (
                        mode == "collision_candidate"
                        and path.parent.name == "attachments"
                        and path.name == "2026-09-07_original_1.pdf"
                    ):
                        raise PermissionError(13, "Permission denied", str(path))
                    return real_exists(path)

                invoice_number = f"STATUS-{mode.upper()}"
                with InvoiceDB(runtime_dir / "invoices.db") as db, patch.object(
                    Path,
                    "exists",
                    new=injected_exists,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        rf"发票号 {invoice_number}的发票原件复制失败或已不可用",
                    ) as ctx:
                        export_claim_package(
                            db,
                            claim_id,
                            project_root,
                            runtime_dir,
                            export_root=export_root,
                        )

                    message = str(ctx.exception)
                    self.assertNotIn(str(source_path), message)
                    self.assertNotIn(str(export_root), message)
                    self.assertNotIn(str(Path(td)), message)
                    self._assert_failed_attempt_is_transactional(
                        db,
                        claim_id,
                        export_root,
                        historical_marker,
                    )


if __name__ == "__main__":
    unittest.main()
