import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.invoice_fetch import services


class LocalZipIntegrityTests(unittest.TestCase):
    def _write_zip(self, path: Path, members: list[tuple[str, bytes]]) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, payload in members:
                zf.writestr(name, payload)

    def test_extract_local_zip_keeps_pdf_and_image_members(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "mixed.zip"
            self._write_zip(
                archive,
                [
                    ("invoice.pdf", b"%PDF-1.7\nsynthetic invoice"),
                    ("payment.png", b"\x89PNG\r\n\x1a\nsynthetic image"),
                ],
            )
            extracted = services._extract_local_zip(archive, root / "attachments")
            self.assertEqual({p.suffix.lower() for p in extracted}, {".pdf", ".png"})
            self.assertEqual(len(extracted), 2)

    def test_archive_over_member_limit_fails_closed_and_is_reconciled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            archive = source / "too-many.zip"
            self._write_zip(
                archive,
                [
                    (f"invoice-{index:02d}.pdf", b"%PDF-1.7\nsynthetic")
                    for index in range(21)
                ],
            )
            stats = services._import_local_directory(
                source,
                MagicMock(),
                MagicMock(),
                {},
                root / "attachments",
            )
            self.assertEqual(stats["failed"], 1)
            self.assertEqual(stats["archive_members_discovered"], 21)
            self.assertEqual(stats["archive_members_processed"], 0)
            self.assertEqual(stats["archive_members_unprocessed"], 21)
            self.assertEqual(stats["skipped"], 21)
            self.assertEqual(len(stats["skipped_details"]), 1)
            self.assertIn("超过安全上限", stats["skipped_details"][0]["reason"])

    def test_mixed_archive_routes_image_through_evidence_import(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            archive = source / "mixed.zip"
            self._write_zip(
                archive,
                [
                    ("invoice.pdf", b"%PDF-1.7\nsynthetic invoice"),
                    ("payment.png", b"\x89PNG\r\n\x1a\nsynthetic image"),
                ],
            )

            next_id = iter((101, 102))
            def result(status):
                return services.LocalImportItemResult(
                    status=status,
                    invoice_id=next(next_id),
                    created=True,
                    reviewable=True,
                )

            with patch.object(
                services,
                "_import_local_pdf",
                side_effect=lambda *args, **kwargs: result("added"),
            ) as pdf_import, patch.object(
                services,
                "_import_local_evidence",
                side_effect=lambda *args, **kwargs: result("pending_manual"),
            ) as image_import:
                stats = services._import_local_directory(
                    source,
                    MagicMock(),
                    MagicMock(),
                    {},
                    root / "attachments",
                )

            self.assertEqual(pdf_import.call_count, 1)
            self.assertEqual(image_import.call_count, 1)
            self.assertEqual(stats["added"], 1)
            self.assertEqual(stats["pending_manual"], 1)
            self.assertEqual(stats["archive_members_discovered"], 2)
            self.assertEqual(stats["archive_members_processed"], 2)
            self.assertEqual(stats["archive_members_unprocessed"], 0)
            self.assertEqual(stats["failed"], 0)


if __name__ == "__main__":
    unittest.main()
