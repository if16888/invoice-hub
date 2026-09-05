import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.invoice_fetch import redownload
from tests.test_redownload_consistency import _FakeDB, _FakeDownloader, _snapshot


class _RaisingFileDB(_FakeDB):
    def update_invoice_file_paths(self, invoice_id, **kwargs):
        self.file_updates.append((int(invoice_id), dict(kwargs)))
        raise RuntimeError("synthetic file persistence failure")


class RedownloadConsistencyContractTests(unittest.TestCase):
    def test_detail_retry_db_exception_removes_new_managed_file(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            db = _RaisingFileDB()
            downloader_ns = SimpleNamespace(
                LinkDownloader=lambda download_dir: _FakeDownloader(download_dir)
            )

            with patch.object(redownload, "InvoiceDB", return_value=db), \
                 patch.object(redownload, "_link_downloader", downloader_ns), \
                 patch.object(
                     redownload._attachment_handler,
                     "build_managed_attachment_name",
                     return_value="managed.pdf",
                 ):
                result = redownload.run_invoice_link_retry(
                    _snapshot(),
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                )

            self.assertFalse(result["success"])
            self.assertEqual(
                [p for p in (runtime / "attachments").rglob("*") if p.is_file()],
                [],
            )
            self.assertTrue(db.closed)

    def test_detail_retry_successful_reuse_preserves_preexisting_file(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            dest_dir = runtime / "attachments" / "2026-09-05"
            dest_dir.mkdir(parents=True)
            existing = dest_dir / "managed.pdf"
            existing.write_bytes(b"synthetic")

            db = _FakeDB(file_ok=True)
            downloader_ns = SimpleNamespace(
                LinkDownloader=lambda download_dir: _FakeDownloader(
                    download_dir,
                    content=b"synthetic",
                )
            )

            with patch.object(redownload, "InvoiceDB", return_value=db), \
                 patch.object(redownload, "_link_downloader", downloader_ns), \
                 patch.object(
                     redownload._attachment_handler,
                     "build_managed_attachment_name",
                     return_value="managed.pdf",
                 ):
                result = redownload.run_invoice_link_retry(
                    _snapshot(),
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                )

            self.assertTrue(result["success"])
            self.assertTrue(existing.exists())
            self.assertEqual(existing.read_bytes(), b"synthetic")
            self.assertEqual(
                [p for p in (runtime / "attachments").rglob("*") if p.is_file()],
                [existing],
            )

    def test_unsupported_direct_download_keeps_metadata_refreshed_contract(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            db = _FakeDB(metadata_ok=True, file_ok=True)
            downloader_ns = SimpleNamespace(
                LinkDownloader=lambda download_dir: _FakeDownloader(
                    download_dir,
                    suffix=".txt",
                    content=b"synthetic text attachment",
                )
            )

            def rename(file_path, _code, _date, att_dir, **_kwargs):
                dest_dir = Path(att_dir) / "2026-09-05"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / "managed.txt"
                os.replace(file_path, dest)
                return os.path.relpath(dest, runtime)

            with patch.object(redownload, "InvoiceDB", return_value=db), \
                 patch.object(redownload, "_link_downloader", downloader_ns), \
                 patch.object(redownload._invoice_parser, "InvoiceParser", return_value=object()), \
                 patch.object(redownload._attachment_handler, "AttachmentHandler", return_value=object()), \
                 patch("scripts.invoice_fetch.services._classify", return_value=("交通", "", False)), \
                 patch("scripts.invoice_fetch.services._rename_by_invoice_code", side_effect=rename):
                result = redownload.run_invoice_redownload(
                    [_snapshot()],
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                    config={},
                )

            self.assertEqual(result["success_count"], 1)
            self.assertEqual(result["buckets"]["metadata_refreshed"], 1)
            self.assertEqual(
                result["invoice_results"],
                ({"invoice_id": 1, "status": "metadata_refreshed"},),
            )
            self.assertTrue(
                (runtime / "attachments" / "2026-09-05" / "managed.txt").exists()
            )
            self.assertFalse(db.metadata_updates[-1]["parse_success"])
            self.assertIn("不支持的文件类型", db.metadata_updates[-1]["parse_note"])


if __name__ == "__main__":
    unittest.main()
