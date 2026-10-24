import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.invoice_fetch import redownload
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.redownload import RedownloadInvoiceSnapshot


class _FakeDB:
    def __init__(self, *, metadata_ok=True, file_ok=True, last_error=""):
        self.metadata_ok = metadata_ok
        self.file_ok = file_ok
        self.last_error = last_error
        self.closed = False
        self.file_updates = []
        self.metadata_updates = []
        self.original = {
            "id": 1,
            "invoice_number": "INV-001",
            "invoice_code": "CODE-001",
            "invoice_date": "2026-09-05",
            "expense_date": "2026-09-05",
            "date_source": "invoice_date",
            "amount": "10.00",
            "total_amount": "10.00",
            "seller_name": "Synthetic Seller",
            "buyer_name": "Synthetic Buyer",
            "invoice_type": "电子发票",
            "category": "交通",
            "has_extra": False,
            "extra_type": "",
            "missing_extra": False,
            "parse_success": True,
            "parse_note": "old",
            "item_name": "Synthetic Item",
            "attachment_path": "attachments/original.pdf",
            "file_hash": "old-hash",
        }

    def get_invoice(self, invoice_id):
        return dict(self.original) if int(invoice_id) == 1 else None

    def update_invoice_parsed_metadata(self, **kwargs):
        self.metadata_updates.append(dict(kwargs))
        return self.metadata_ok

    def update_invoice_file_paths(self, invoice_id, **kwargs):
        self.file_updates.append((int(invoice_id), dict(kwargs)))
        return self.file_ok

    def update_invoice_missing_fields(self, *args, **kwargs):
        return {"updated_fields": ["parse_note"], "skipped_fields": []}

    def close(self):
        self.closed = True


class _FakeDownloader:
    def __init__(self, download_dir, suffix=".pdf", content=b"synthetic"):
        self.download_dir = Path(download_dir)
        self.suffix = suffix
        self.content = content
        self.last_download_diagnostics = {}
        self.closed = False

    def _download_url(self, *_args):
        self.download_dir.mkdir(parents=True, exist_ok=True)
        path = self.download_dir / f"raw{self.suffix}"
        path.write_bytes(self.content)
        return SimpleNamespace(file_path=str(path), parse_note="")

    def close(self):
        self.closed = True


class _FakeParser:
    def __init__(self, *, parse_success=True):
        self.parse_success = parse_success

    def parse_pdf(self, _path):
        return SimpleNamespace(
            parse_success=self.parse_success,
            parse_note="synthetic parse failure" if not self.parse_success else "",
            invoice_number="INV-NEW",
            invoice_code="CODE-NEW",
            invoice_date="2026-09-05",
            expense_date="2026-09-05",
            date_source="invoice_date",
            amount="10.00",
            total_amount="10.00",
            seller_name="Synthetic Seller",
            buyer_name="Synthetic Buyer",
            invoice_type="电子发票",
            item_name="Synthetic Item",
        )


def _snapshot(url="https://example.invalid/invoice", *, mail_uid=None):
    return RedownloadInvoiceSnapshot(
        invoice_id=1,
        download_url=url,
        mail_uid=mail_uid,
        mail_date="2026-09-05",
        invoice_date="2026-09-05",
        expense_date="2026-09-05",
        invoice_number="INV-001",
        invoice_code="CODE-001",
        category="交通",
        total_amount="10.00",
    )


class RedownloadConsistencyTests(unittest.TestCase):
    def test_rollback_deletes_only_file_created_after_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "attachments"
            root.mkdir()
            old = root / "old.pdf"
            old.write_bytes(b"old")
            before = redownload._snapshot_attachment_files(root)
            new = root / "new.pdf"
            new.write_bytes(b"new")

            self.assertTrue(
                redownload._rollback_created_attachment(
                    new,
                    attachments_root=root,
                    preexisting_files=before,
                )
            )
            self.assertFalse(new.exists())
            self.assertTrue(old.exists())
            self.assertFalse(
                redownload._rollback_created_attachment(
                    old,
                    attachments_root=root,
                    preexisting_files=before,
                )
            )
            self.assertTrue(old.exists())

    def test_rollback_refuses_path_outside_attachment_root(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "attachments"
            root.mkdir()
            outside = base / "do-not-delete.pdf"
            outside.write_bytes(b"keep")
            self.assertFalse(
                redownload._rollback_created_attachment(
                    outside,
                    attachments_root=root,
                    preexisting_files=set(),
                )
            )
            self.assertTrue(outside.exists())

    def test_detail_retry_db_failure_removes_new_managed_file(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            db = _FakeDB(file_ok=False)
            downloader_ns = SimpleNamespace(
                LinkDownloader=lambda download_dir: _FakeDownloader(download_dir)
            )
            with patch.object(redownload, "InvoiceDB", return_value=db), \
                 patch.object(redownload, "_link_downloader", downloader_ns), \
                 patch.object(redownload._attachment_handler, "build_managed_attachment_name", return_value="managed.pdf"):
                result = redownload.run_invoice_link_retry(
                    _snapshot(),
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                )

            self.assertFalse(result["success"])
            files = [p for p in (runtime / "attachments").rglob("*") if p.is_file()]
            self.assertEqual(files, [])
            self.assertTrue(db.closed)

    def test_pdf_unique_conflict_removes_new_file(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            db = _FakeDB(metadata_ok=False, last_error="unique_conflict")
            downloader_ns = SimpleNamespace(
                LinkDownloader=lambda download_dir: _FakeDownloader(download_dir)
            )

            def rename(file_path, _code, _date, att_dir, **_kwargs):
                dest_dir = Path(att_dir) / "2026-09-05"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / "managed.pdf"
                os.replace(file_path, dest)
                return os.path.relpath(dest, runtime)

            with patch.object(redownload, "InvoiceDB", return_value=db), \
                 patch.object(redownload, "_link_downloader", downloader_ns), \
                 patch.object(redownload._invoice_parser, "IsolatedInvoiceParser", return_value=_FakeParser()), \
                 patch.object(redownload._attachment_handler, "AttachmentHandler", return_value=object()), \
                 patch("scripts.invoice_fetch.services._classify", return_value=("交通", "", False)), \
                 patch("scripts.invoice_fetch.services._rename_by_invoice_code", side_effect=rename):
                result = redownload.run_invoice_redownload(
                    [_snapshot()],
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                    config={},
                )

            self.assertEqual(result["buckets"]["download_failed"], 1)
            self.assertEqual(
                [p for p in (runtime / "attachments").rglob("*") if p.is_file()],
                [],
            )

    def test_pdf_unique_conflict_preserves_reused_preexisting_file(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            dest_dir = runtime / "attachments" / "2026-09-05"
            dest_dir.mkdir(parents=True)
            existing = dest_dir / "managed.pdf"
            existing.write_bytes(b"synthetic")
            db = _FakeDB(metadata_ok=False, last_error="unique_conflict")
            downloader_ns = SimpleNamespace(
                LinkDownloader=lambda download_dir: _FakeDownloader(download_dir, content=b"synthetic")
            )

            def reuse(file_path, _code, _date, _att_dir, **_kwargs):
                Path(file_path).unlink()
                return os.path.relpath(existing, runtime)

            with patch.object(redownload, "InvoiceDB", return_value=db), \
                 patch.object(redownload, "_link_downloader", downloader_ns), \
                 patch.object(redownload._invoice_parser, "IsolatedInvoiceParser", return_value=_FakeParser()), \
                 patch.object(redownload._attachment_handler, "AttachmentHandler", return_value=object()), \
                 patch("scripts.invoice_fetch.services._classify", return_value=("交通", "", False)), \
                 patch("scripts.invoice_fetch.services._rename_by_invoice_code", side_effect=reuse):
                result = redownload.run_invoice_redownload(
                    [_snapshot()],
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                    config={},
                )

            self.assertEqual(result["buckets"]["download_failed"], 1)
            self.assertTrue(existing.exists())
            self.assertEqual(existing.read_bytes(), b"synthetic")

    def test_pdf_success_keeps_existing_status_bucket_contract(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            db = _FakeDB(metadata_ok=True, file_ok=True)
            downloader_ns = SimpleNamespace(
                LinkDownloader=lambda download_dir: _FakeDownloader(download_dir)
            )

            def rename(file_path, _code, _date, att_dir, **_kwargs):
                dest_dir = Path(att_dir) / "2026-09-05"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / "managed.pdf"
                os.replace(file_path, dest)
                return os.path.relpath(dest, runtime)

            with patch.object(redownload, "InvoiceDB", return_value=db), \
                 patch.object(redownload, "_link_downloader", downloader_ns), \
                 patch.object(redownload._invoice_parser, "IsolatedInvoiceParser", return_value=_FakeParser()), \
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
            self.assertEqual(result["buckets"]["file_restored"], 1)
            self.assertEqual(result["invoice_results"], ({"invoice_id": 1, "status": "file_restored"},))
            self.assertTrue((runtime / "attachments" / "2026-09-05" / "managed.pdf").exists())

    def test_is_file_valid_and_openable_rejects_zero_byte_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            empty = root / "empty.pdf"
            empty.write_bytes(b"")
            usable = root / "usable.pdf"
            usable.write_bytes(b"%PDF-1.4 synthetic")
            directory = root / "dir"
            directory.mkdir()

            self.assertFalse(redownload._is_file_valid_and_openable(empty))
            self.assertFalse(redownload._is_file_valid_and_openable(root / "missing.pdf"))
            self.assertFalse(redownload._is_file_valid_and_openable(directory))
            self.assertFalse(redownload._is_file_valid_and_openable(None))
            self.assertTrue(redownload._is_file_valid_and_openable(usable))

    def test_failed_attachment_persist_restores_metadata_and_tax_fields(self):
        """A rejected parse must not leave its tax fields on the old invoice."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "runtime"
            db_path = root / "invoices.db"
            with InvoiceDB(db_path) as db:
                invoice_id = int(db.insert_invoice({
                    "invoice_number": "OLD-INV",
                    "invoice_code": "OLD-CODE",
                    "invoice_date": "2026-06-01",
                    "expense_date": "2026-06-01",
                    "date_source": "invoice_date",
                    "amount": "9.99",
                    "total_amount": "10.00",
                    "seller_name": "Old Seller",
                    "buyer_name": "Old Buyer",
                    "invoice_type": "电子发票",
                    "category": "交通",
                    "category_source": "manual",
                    "item_name": "Old Item",
                    "buyer_tax_id": "OLD-TAX-ID",
                    "tax_amount": "1.23",
                    "tax_rate": "6%",
                    "parse_success": True,
                    "parse_note": "old note",
                    "attachment_path": "attachments/2026-06-01/old.pdf",
                    "file_hash": "old-hash",
                    "review_status": "to_review",
                    "download_url": "https://example.test/old.pdf",
                }))
            with InvoiceDB(db_path) as db:
                before = dict(db.get_invoice(invoice_id))

            class _FailingFileDB(InvoiceDB):
                def update_invoice_file_paths(self, invoice_id, **kwargs):
                    return False

            class _NewParser:
                def parse_pdf(self, _path):
                    return SimpleNamespace(
                        parse_success=True,
                        parse_note="",
                        invoice_code="NEW-CODE",
                        invoice_number="NEW-INV",
                        invoice_date="2026-06-02",
                        amount="20.00",
                        total_amount="20.00",
                        seller_name="New Seller",
                        buyer_name="New Buyer",
                        invoice_type="电子发票",
                        item_name="New Item",
                        expense_date="2026-06-02",
                        date_source="invoice_date",
                        buyer_tax_id="NEW-TAX-ID",
                        tax_amount="2.34",
                        tax_rate="13%",
                    )

            class _Downloader:
                def __init__(self, download_dir):
                    self.download_dir = Path(download_dir)

                def _download_url(self, *_args):
                    source = root / "raw.pdf"
                    source.write_bytes(b"%PDF-1.4 synthetic")
                    return SimpleNamespace(file_path=str(source), parse_note="")

                def close(self):
                    return None

            def rename(file_path, _code, _date, att_dir, **_kwargs):
                dest_dir = Path(att_dir) / "2026-06-02"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / "managed.pdf"
                os.replace(file_path, dest)
                return os.path.relpath(dest, runtime)

            with patch.object(
                redownload, "InvoiceDB", side_effect=lambda path: _FailingFileDB(path)
            ), patch.object(
                redownload, "_link_downloader", SimpleNamespace(LinkDownloader=_Downloader)
            ), patch.object(
                redownload._invoice_parser, "IsolatedInvoiceParser", _NewParser
            ), patch.object(
                redownload._attachment_handler, "AttachmentHandler", return_value=object()
            ), patch(
                "scripts.invoice_fetch.services._classify",
                return_value=("交通", "", False),
            ), patch(
                "scripts.invoice_fetch.services._rename_by_invoice_code",
                side_effect=rename,
            ):
                result = redownload.run_invoice_redownload(
                    [_snapshot(url="https://example.test/old.pdf")],
                    db_path,
                    runtime_dir=runtime,
                    config={},
                )

            self.assertEqual(result["buckets"]["download_failed"], 1)
            self.assertEqual(
                [p for p in (runtime / "attachments").rglob("*") if p.is_file()],
                [],
            )
            with InvoiceDB(db_path) as db:
                after = dict(db.get_invoice(invoice_id))

            for key in (
                "invoice_number",
                "invoice_code",
                "invoice_date",
                "amount",
                "total_amount",
                "seller_name",
                "buyer_name",
                "invoice_type",
                "category",
                "category_source",
                "item_name",
                "attachment_path",
                "file_hash",
                "parse_note",
                "review_status",
            ):
                self.assertEqual(after[key], before[key], f"{key} was not restored")
            # Tax columns are COALESCE-updated; compensation must write the
            # original values explicitly or the rejected parse leaks into them.
            self.assertEqual(after["buyer_tax_id"], "OLD-TAX-ID")
            self.assertEqual(after["tax_amount"], "1.23")
            self.assertEqual(after["tax_rate"], "6%")
            self.assertEqual(after["download_url"], before["download_url"])

    def test_redownload_source_has_no_direct_connection_access(self):
        source = Path(redownload.__file__).read_text(encoding="utf-8")
        self.assertNotIn("db._conn", source)


if __name__ == "__main__":
    unittest.main()
