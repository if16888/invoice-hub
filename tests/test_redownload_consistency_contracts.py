import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts.invoice_fetch import redownload
from tests.test_redownload_consistency import _FakeDB, _FakeDownloader, _snapshot


class _RaisingFileDB(_FakeDB):
    def update_invoice_file_paths(self, invoice_id, **kwargs):
        self.file_updates.append((int(invoice_id), dict(kwargs)))
        raise RuntimeError("synthetic file persistence failure")


class RedownloadConsistencyContractTests(unittest.TestCase):
    def test_compensation_failure_logs_instead_of_raising_name_error(self):
        db = _FakeDB()

        def raising_update(**_kwargs):
            raise RuntimeError("synthetic compensation failure")

        db.update_invoice_parsed_metadata = raising_update
        with self.assertLogs("invoice_fetch.redownload", level="ERROR") as logs:
            redownload._restore_invoice_state(db, db.original)
        self.assertIn("compensation failed", " ".join(logs.output))

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

    def test_detail_retry_collision_preserves_preexisting_file(self):
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

            collision_copy = dest_dir / "managed_1.pdf"
            self.assertTrue(result["success"])
            self.assertTrue(existing.exists())
            self.assertEqual(existing.read_bytes(), b"synthetic")
            self.assertTrue(collision_copy.exists())
            self.assertEqual(collision_copy.read_bytes(), b"synthetic")
            self.assertEqual(
                sorted(p.name for p in dest_dir.iterdir() if p.is_file()),
                ["managed.pdf", "managed_1.pdf"],
            )

    def test_detail_retry_never_overwrites_when_all_collision_names_are_taken(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            dest_dir = runtime / "attachments" / "2026-09-05"
            dest_dir.mkdir(parents=True)
            reserved = [dest_dir / "managed.pdf"]
            for name in reserved:
                name.write_bytes(b"original-managed")
            for number in range(1, 100):
                candidate = dest_dir / f"managed_{number}.pdf"
                candidate.write_bytes(b"original-numbered")
                reserved.append(candidate)

            db = _FakeDB(file_ok=True)
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

            self.assertTrue(result["success"])
            # Every pre-existing original is untouched byte for byte.
            self.assertEqual(
                (dest_dir / "managed.pdf").read_bytes(), b"original-managed"
            )
            for candidate in reserved[1:]:
                self.assertEqual(candidate.read_bytes(), b"original-numbered")
            names = {p.name for p in dest_dir.iterdir() if p.is_file()}
            created = names - {candidate.name for candidate in reserved}
            self.assertEqual(len(created), 1)
            created_name = created.pop()
            self.assertTrue(created_name.startswith("managed_"))
            self.assertTrue(created_name.endswith(".pdf"))
            self.assertEqual(
                (dest_dir / created_name).read_bytes(), b"synthetic"
            )

    def test_failed_email_download_with_metadata_update_is_counted_as_failure(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td)
            db = _FakeDB()
            downloader = _FakeDownloader(runtime / "attachments")
            downloader.last_download_diagnostics = {"attempted": 1, "failed": 1}
            namespace = SimpleNamespace(LinkDownloader=lambda **kwargs: downloader)
            with patch.object(redownload, "InvoiceDB", return_value=db), \
                 patch.object(redownload, "_link_downloader", namespace), \
                 patch.object(redownload._config, "get_email_accounts", return_value=[]), \
                 patch.object(redownload._credentials, "has_auth_code", return_value=True), \
                 patch.object(redownload._credentials, "get_auth_code", return_value="synthetic-code"), \
                 patch.object(redownload._mail_fetcher, "MailFetcher", return_value=MagicMock()), \
                 patch.object(redownload._invoice_parser, "IsolatedInvoiceParser", return_value=SimpleNamespace()), \
                 patch.object(redownload._attachment_handler, "AttachmentHandler", return_value=object()), \
                 patch("scripts.invoice_fetch.services._handle_pending_email", return_value=SimpleNamespace(status="metadata_refreshed")):
                result = redownload.run_invoice_redownload(
                    [_snapshot(url="", mail_uid=1)], runtime / "invoices.db",
                    runtime_dir=runtime, config={"email": {"address": "synthetic@example.invalid"}},
                )
            self.assertEqual(result["buckets"]["download_failed"], 1)
            self.assertEqual(result["failed_count"], 1)
            self.assertEqual(result["buckets"]["metadata_refreshed"], 0)

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
                 patch.object(redownload._invoice_parser, "IsolatedInvoiceParser", return_value=SimpleNamespace()), \
                 patch.object(redownload._attachment_handler, "AttachmentHandler", return_value=object()), \
                 patch("scripts.invoice_fetch.services._classify", return_value=("交通", "", False)), \
                 patch("scripts.invoice_fetch.services._rename_by_invoice_code", side_effect=rename):
                result = redownload.run_invoice_redownload(
                    [_snapshot()],
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                    config={},
                )

            self.assertEqual(result["success_count"], 0)
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


    def test_detail_retry_parse_note_failure_keeps_success_result(self):
        """A best-effort note update must not turn a persisted retry into failure."""
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"

            class _RaisingMissingFieldsDB(_FakeDB):
                def update_invoice_missing_fields(self, *args, **kwargs):
                    raise RuntimeError("synthetic parse note failure")

            class _Downloader:
                def __init__(self, download_dir):
                    self.download_dir = Path(download_dir)

                def _download_url(self, *_args):
                    self.download_dir.mkdir(parents=True, exist_ok=True)
                    source = self.download_dir / "raw.pdf"
                    source.write_bytes(b"%PDF-1.4 synthetic")
                    return SimpleNamespace(
                        file_path=str(source),
                        parse_note="synthetic note",
                    )

                def close(self):
                    return None

            db = _RaisingMissingFieldsDB(file_ok=True)
            with patch.object(
                redownload, "InvoiceDB", return_value=db
            ), patch.object(
                redownload,
                "_link_downloader",
                SimpleNamespace(LinkDownloader=_Downloader),
            ), patch.object(
                redownload._attachment_handler,
                "build_managed_attachment_name",
                return_value="managed.pdf",
            ), self.assertLogs(
                "invoice_fetch.redownload", level="WARNING"
            ) as logs:
                result = redownload.run_invoice_link_retry(
                    _snapshot(),
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                )

            self.assertTrue(result["success"])
            self.assertEqual(result["completed_count"], 1)
            self.assertEqual(result["failure_detail"], "")
            self.assertEqual(len(db.file_updates), 1)
            managed = runtime / "attachments" / "2026-09-05" / "managed.pdf"
            self.assertTrue(managed.exists())
            self.assertGreater(managed.stat().st_size, 0)
            self.assertIn("parse note update failed", " ".join(logs.output))

    def test_direct_download_failure_detail_redacts_paths_and_url_tokens(self):
        synthetic_path = r"C:\Users\synthetic-alice\AppData\invoice.pdf"
        token_url = "http://192.168.50.20:8765/u/synthetic-upload-token-7f3a"
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            db = _FakeDB()

            class _FailingDownloader:
                def __init__(self, download_dir):
                    self.download_dir = download_dir

                def _download_url(self, *_args):
                    raise OSError(
                        f"permission denied {synthetic_path} {token_url}"
                    )

                def close(self):
                    return None

            logs: list[str] = []
            with patch.object(redownload, "InvoiceDB", return_value=db), \
                    patch.object(
                        redownload,
                        "_link_downloader",
                        SimpleNamespace(LinkDownloader=_FailingDownloader),
                    ), patch.object(
                        redownload._invoice_parser,
                        "IsolatedInvoiceParser",
                        return_value=SimpleNamespace(),
                    ), patch.object(
                        redownload._attachment_handler,
                        "AttachmentHandler",
                        return_value=object(),
                    ):
                result = redownload.run_invoice_redownload(
                    [_snapshot(url="https://example.test/a.pdf")],
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                    config={},
                    log_callback=logs.append,
                )

            self.assertEqual(result["buckets"]["download_failed"], 1)
            combined = repr(result) + " ".join(logs)
            self.assertNotIn("synthetic-alice", combined)
            self.assertNotIn("synthetic-upload-token-7f3a", combined)
            self.assertNotIn(r"C:\Users", combined)
            self.assertIn("链接下载异常", " ".join(result["failure_details"]))

    def test_imap_fallback_value_error_detail_is_redacted(self):
        synthetic_path = r"C:\Users\synthetic-alice\Documents\invoice.pdf"
        token_url = "http://192.168.50.20:8765/u/synthetic-upload-token-7f3a"
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            db = _FakeDB()
            fetcher_cm = MagicMock()
            with patch.object(redownload, "InvoiceDB", return_value=db), \
                    patch.object(
                        redownload,
                        "_link_downloader",
                        SimpleNamespace(
                            LinkDownloader=lambda **_kwargs: SimpleNamespace(
                                _download_url=lambda *_a: None,
                                close=lambda: None,
                                last_download_diagnostics={},
                            )
                        ),
                    ), patch.object(
                        redownload._invoice_parser,
                        "IsolatedInvoiceParser",
                        return_value=SimpleNamespace(),
                    ), patch.object(
                        redownload._attachment_handler,
                        "AttachmentHandler",
                        return_value=object(),
                    ), patch.object(
                        redownload._config, "get_email_accounts", return_value=[]
                    ), patch.object(
                        redownload._credentials, "has_auth_code", return_value=True
                    ), patch.object(
                        redownload._credentials,
                        "get_auth_code",
                        return_value="synthetic-code",
                    ), patch.object(
                        redownload._mail_fetcher, "MailFetcher", return_value=fetcher_cm
                    ), patch(
                        "scripts.invoice_fetch.services._handle_pending_email",
                        side_effect=ValueError(
                            f"bad payload {synthetic_path} {token_url}"
                        ),
                    ):
                result = redownload.run_invoice_redownload(
                    [_snapshot(url="", mail_uid=42)],
                    runtime / "invoices.db",
                    runtime_dir=runtime,
                    config={"email": {"address": "synthetic@example.invalid"}},
                )

            self.assertEqual(result["buckets"]["download_failed"], 1)
            combined = repr(result)
            self.assertNotIn("synthetic-alice", combined)
            self.assertNotIn("synthetic-upload-token-7f3a", combined)
            self.assertNotIn(r"C:\Users", combined)
            self.assertIn("重新读取邮件失败", combined)


if __name__ == "__main__":
    unittest.main()
