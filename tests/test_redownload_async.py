import hashlib
import tempfile
import threading
import unittest
import sys
import importlib
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch import redownload as redownload_module
from scripts.invoice_fetch.redownload import (
    RedownloadInvoiceSnapshot,
    run_invoice_link_retry,
    run_invoice_redownload,
)
from scripts.invoice_fetch.gui.workers import InvoiceRedownloadRequest


def _fake_services_module(runtime_dir: Path):
    def classify(*_args, **_kwargs):
        return "其他", "", False

    def rename_by_invoice_code(
        file_path, _invoice_code, invoice_date, att_dir, **_kwargs
    ):
        destination_dir = Path(att_dir) / (invoice_date or "unknown_date")
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / Path(file_path).name
        Path(file_path).replace(destination)
        return str(destination.relative_to(runtime_dir))

    return SimpleNamespace(
        _classify=classify,
        _rename_by_invoice_code=rename_by_invoice_code,
    )


@contextmanager
def _patched_services(runtime_dir: Path):
    """Patch both import routes and restore the package attribute afterward."""

    fake_services = _fake_services_module(runtime_dir)
    package = importlib.import_module("scripts.invoice_fetch")
    module_name = "scripts.invoice_fetch.services"
    with patch.dict(sys.modules, {module_name: fake_services}), patch.object(
        package, "services", fake_services, create=True
    ):
        yield fake_services


class RedownloadServiceTests(unittest.TestCase):
    def _seed_invoice(self, db_path: Path, **overrides) -> int:
        payload = {
            "invoice_number": "INV-OLD",
            "invoice_date": "2026-06-01",
            "total_amount": "10.00",
            "seller_name": "Seller",
            "buyer_name": "Buyer",
            "mail_date": "2026-06-01",
            "mail_subject": "subject",
            "mail_sender": "sender@example.com",
            "attachment_path": "",
            "download_url": "",
            "review_status": "to_review",
        }
        payload.update(overrides)
        with InvoiceDB(db_path) as db:
            invoice_id = db.insert_invoice(payload)
        self.assertIsNotNone(invoice_id)
        return int(invoice_id)

    def test_bucket_mapping_preserves_the_legacy_five_bucket_contract(self):
        expected = {
            "file_restored": "file_restored",
            "metadata_refreshed": "metadata_refreshed",
            "manual_required": "metadata_refreshed",
            "recorded": "metadata_refreshed",
            "duplicate": "duplicate_only",
            "no_candidate_link": "no_candidate_link",
            "download_failed": "download_failed",
            "parse_failed": "download_failed",
            "": "download_failed",
        }
        for raw_status, bucket in expected.items():
            self.assertEqual(
                redownload_module._bucket_redownload_status(raw_status), bucket
            )

    def test_cancel_between_items_leaves_later_items_untouched(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "redownload.db"
            ids = [self._seed_invoice(db_path, invoice_number=f"INV-{n}") for n in range(3)]
            control_progress = []

            def progress(value):
                control_progress.append(value)
                if value["processed"] == 1:
                    control.cancel()

            from scripts.invoice_fetch.scan_lifecycle import ScanControl

            control = ScanControl()
            fake_downloader_module = SimpleNamespace(LinkDownloader=lambda **_kwargs: SimpleNamespace(close=lambda: None))
            with patch.object(redownload_module, "_link_downloader", fake_downloader_module):
                result = run_invoice_redownload(
                    [{"id": invoice_id} for invoice_id in ids],
                    db_path,
                    runtime_dir=Path(temp_dir) / "runtime",
                    scan_control=control,
                    progress_callback=progress,
                )

            self.assertTrue(result["cancelled"])
            self.assertEqual(result["completed_count"], 1)
            self.assertEqual([item["invoice_id"] for item in result["invoice_results"]], [ids[0]])
            self.assertEqual(result["buckets"]["no_candidate_link"], 1)
            self.assertEqual(sum(result["buckets"].values()), 1)
            self.assertEqual(len(control_progress), 2)  # item completion + final cancelled event

    def test_direct_ofd_restore_runs_in_service_and_updates_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "redownload.db"
            invoice_id = self._seed_invoice(
                db_path,
                invoice_number="OFD-1",
                download_url="https://example.test/invoice.ofd",
                mail_uid=100,
            )
            source = root / "download.ofd"
            source.write_bytes(b"OFD content")

            class FakeDownloader:
                last_download_diagnostics = {}

                def __init__(self, download_dir):
                    self.download_dir = Path(download_dir)

                def _download_url(self, *args):
                    return SimpleNamespace(file_path=str(source))

                def close(self):
                    return None

            class ParserMustNotRun:
                def parse_pdf(self, path):
                    raise AssertionError(f"PDF parser must not parse OFD: {path}")

            with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
                    patch.object(redownload_module._invoice_parser, "InvoiceParser", ParserMustNotRun), \
                    _patched_services(root / "runtime"):
                result = run_invoice_redownload(
                    [{"id": invoice_id, "download_url": "https://example.test/invoice.ofd", "invoice_number": "OFD-1"}],
                    db_path,
                    runtime_dir=root / "runtime",
                )

            self.assertEqual(result["buckets"]["metadata_refreshed"], 1)
            with InvoiceDB(db_path) as db:
                row = db.get_invoice(invoice_id)
            self.assertTrue(row["attachment_path"].endswith(".ofd"))
            self.assertTrue((root / "runtime" / row["attachment_path"]).exists())
            self.assertIn("OFD 原件已恢复", row["parse_note"])

    def test_detail_link_retry_keeps_unparseable_pdf_and_never_uses_imap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "redownload.db"
            invoice_id = self._seed_invoice(
                db_path,
                invoice_number="DETAIL-1",
                invoice_date="2026-06-01",
                expense_date="2026-06-02",
                download_url="https://example.test/detail.pdf",
                mail_uid=404,
            )
            source = root / "official-original.pdf"
            payload = b"%PDF-1.4 downloadable but unsupported by parser"
            source.write_bytes(payload)
            calls = []
            instances = []

            class FakeDownloader:
                def __init__(self, download_dir):
                    instances.append(self)
                    self.download_dir = Path(download_dir)

                def _download_url(self, *args):
                    calls.append(args)
                    return SimpleNamespace(
                        file_path=str(source),
                        parse_note="链接文件格式暂不支持解析",
                    )

                def close(self):
                    self.closed = True

            class ParserMustNotRun:
                def __init__(self, *args, **kwargs):
                    raise AssertionError("detail retry must not create an invoice parser")

            class MailFetcherMustNotRun:
                def __init__(self, *args, **kwargs):
                    raise AssertionError("detail retry must not use IMAP fallback")

            with patch.object(
                redownload_module,
                "_link_downloader",
                SimpleNamespace(LinkDownloader=FakeDownloader),
            ), patch.object(
                redownload_module._invoice_parser, "InvoiceParser", ParserMustNotRun
            ), patch.object(
                redownload_module._mail_fetcher, "MailFetcher", MailFetcherMustNotRun
            ):
                result = run_invoice_link_retry(
                    {
                        "id": invoice_id,
                        "download_url": "https://example.test/detail.pdf",
                        "mail_uid": 404,
                        "invoice_number": "DETAIL-1",
                        "invoice_date": "2026-06-01",
                        "expense_date": "2026-06-02",
                        "total_amount": "10.00",
                        "category": "办公",
                    },
                    db_path,
                    runtime_dir=root / "runtime",
                )

            self.assertTrue(result["success"])
            self.assertEqual(result["mode"], "detail_link_retry")
            self.assertEqual(result["completed_count"], 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "https://example.test/detail.pdf")
            self.assertTrue(instances[0].closed)
            self.assertFalse(source.exists())
            with InvoiceDB(db_path) as db:
                row = db.get_invoice(invoice_id)
            attachment = Path(row["attachment_path"])
            self.assertTrue(attachment.as_posix().startswith("attachments/"))
            stored_file = root / "runtime" / attachment
            self.assertTrue(stored_file.exists())
            self.assertEqual(row["file_hash"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(row["parse_note"], "链接文件格式暂不支持解析")

    def test_direct_pdf_parse_and_metadata_update_use_worker_owned_db(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "redownload.db"
            invoice_id = self._seed_invoice(
                db_path,
                invoice_number="PDF-OLD",
                download_url="https://example.test/invoice.pdf",
                mail_uid=101,
            )
            source = root / "download.pdf"
            source.write_bytes(b"%PDF-1.4 test")

            class FakeDownloader:
                last_download_diagnostics = {}

                def __init__(self, download_dir):
                    self.download_dir = Path(download_dir)

                def _download_url(self, *args):
                    return SimpleNamespace(file_path=str(source))

                def close(self):
                    return None

            class FakeParser:
                def parse_pdf(self, path):
                    return SimpleNamespace(
                        parse_success=True,
                        parse_note="",
                        invoice_code="CODE-1",
                        invoice_number="PDF-NEW",
                        invoice_date="2026-06-02",
                        amount="10.00",
                        total_amount="10.00",
                        seller_name="Seller New",
                        buyer_name="Buyer",
                        invoice_type="电子发票",
                        item_name="",
                        expense_date="2026-06-02",
                        date_source="invoice_date",
                    )

            with patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
                    patch.object(redownload_module._invoice_parser, "InvoiceParser", FakeParser), \
                    _patched_services(root / "runtime"), \
                    patch("scripts.invoice_fetch.redownload.InvoiceDB", wraps=InvoiceDB) as db_factory:
                result = run_invoice_redownload(
                    [{"id": invoice_id, "download_url": "https://example.test/invoice.pdf", "invoice_number": "PDF-OLD"}],
                    db_path,
                    runtime_dir=root / "runtime",
                )

            self.assertEqual(result["buckets"]["file_restored"], 1)
            self.assertEqual(db_factory.call_count, 1)
            self.assertEqual(Path(db_factory.call_args.args[0]), db_path)
            with InvoiceDB(db_path) as db:
                row = db.get_invoice(invoice_id)
            self.assertEqual(row["invoice_number"], "PDF-NEW")
            self.assertEqual(row["seller_name"], "Seller New")

    def test_partial_failure_continues_and_commits_each_invoice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "redownload.db"
            ids = [
                self._seed_invoice(
                    db_path,
                    invoice_number=f"OLD-{suffix}",
                    download_url=f"https://example.test/{suffix}.pdf",
                )
                for suffix in ("A", "B", "C")
            ]
            files = {}
            for suffix in ("A", "C"):
                source = root / f"{suffix}.pdf"
                source.write_bytes(b"%PDF-1.4 test")
                files[suffix] = source

            class FakeDownloader:
                last_download_diagnostics = {}

                def __init__(self, download_dir):
                    self.download_dir = Path(download_dir)
                    self.closed = False

                def _download_url(self, _url, _mail_uid, invoice_id, _mail_date):
                    suffix = {ids[0]: "A", ids[1]: "B", ids[2]: "C"}[invoice_id]
                    if suffix == "B":
                        raise RuntimeError("controlled link failure")
                    return SimpleNamespace(file_path=str(files[suffix]))

                def close(self):
                    self.closed = True

            class FakeParser:
                def parse_pdf(self, path):
                    suffix = Path(path).stem
                    return SimpleNamespace(
                        parse_success=True,
                        parse_note="",
                        invoice_code=f"CODE-{suffix}",
                        invoice_number=f"NEW-{suffix}",
                        invoice_date="2026-06-02",
                        amount="10.00",
                        total_amount="10.00",
                        seller_name=f"Seller {suffix}",
                        buyer_name="Buyer",
                        invoice_type="电子发票",
                        item_name="",
                        expense_date="2026-06-02",
                        date_source="invoice_date",
                    )

            snapshots = [
                {
                    "id": invoice_id,
                    "download_url": f"https://example.test/{suffix}.pdf",
                    "invoice_number": f"OLD-{suffix}",
                }
                for invoice_id, suffix in zip(ids, ("A", "B", "C"))
            ]
            with patch.object(
                redownload_module,
                "_link_downloader",
                SimpleNamespace(LinkDownloader=FakeDownloader),
            ), patch.object(redownload_module._invoice_parser, "InvoiceParser", FakeParser), _patched_services(
                root / "runtime"
            ):
                result = run_invoice_redownload(
                    snapshots,
                    db_path,
                    runtime_dir=root / "runtime",
                )

            self.assertEqual(result["completed_count"], 3)
            self.assertEqual(result["success_count"], 2)
            self.assertEqual(result["failed_count"], 1)
            self.assertEqual(
                result["invoice_results"],
                (
                    {"invoice_id": ids[0], "status": "file_restored"},
                    {"invoice_id": ids[1], "status": "download_failed"},
                    {"invoice_id": ids[2], "status": "file_restored"},
                ),
            )
            self.assertEqual(
                result["buckets"],
                {
                    "file_restored": 2,
                    "metadata_refreshed": 0,
                    "duplicate_only": 0,
                    "download_failed": 1,
                    "no_candidate_link": 0,
                },
            )
            with InvoiceDB(db_path) as db:
                rows = {row["id"]: row for row in db.list_invoices(include_deleted=True)}
            self.assertEqual(rows[ids[0]]["invoice_number"], "NEW-A")
            self.assertEqual(rows[ids[2]]["invoice_number"], "NEW-C")
            self.assertEqual(rows[ids[1]]["attachment_path"], "")

    def test_duplicate_only_bucket_requires_a_valid_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            existing = runtime / "attachments" / "2026-06-01" / "existing.pdf"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"existing")
            db_path = root / "redownload.db"
            invoice_id = self._seed_invoice(
                db_path,
                invoice_number="DUP-1",
                attachment_path="attachments/2026-06-01/existing.pdf",
                mail_uid=303,
            )

            class FakeDownloader:
                last_download_diagnostics = {}

                def __init__(self, download_dir):
                    self.download_dir = download_dir

                def _download_url(self, *_args):
                    return None

                def close(self):
                    return None

            class FakeMailFetcher:
                def __init__(self, **_kwargs):
                    self.exited = False

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    self.exited = True

            with _patched_services(runtime) as patched_services, patch.object(
                redownload_module,
                "_link_downloader",
                SimpleNamespace(LinkDownloader=FakeDownloader),
            ), patch.object(
                redownload_module._mail_fetcher, "MailFetcher", FakeMailFetcher
            ), patch.object(
                redownload_module._credentials, "has_auth_code", return_value=True
            ), patch.object(
                redownload_module._credentials, "get_auth_code", return_value="temporary"
            ):
                patched_services._handle_pending_email = lambda **_kwargs: SimpleNamespace(
                    status="duplicate"
                )
                result = run_invoice_redownload(
                    [{"id": invoice_id, "mail_uid": 303}],
                    db_path,
                    runtime_dir=runtime,
                    config={"email": {"address": "user@example.com"}},
                )

            self.assertEqual(result["buckets"]["duplicate_only"], 1)
            self.assertEqual(result["buckets"]["download_failed"], 0)
            self.assertEqual(result["failed_count"], 0)

    def test_request_is_a_value_snapshot_not_a_gui_row(self):
        row = {
            "id": 41,
            "download_url": "https://example.test/a.pdf",
            "mail_uid": 404,
            "mail_subject": "original subject",
        }
        config = {"search": {"folder": "INBOX"}}
        request = InvoiceRedownloadRequest.from_values(
            7,
            [row],
            Path("invoice.db"),
            Path("runtime"),
            config,
        )
        row["download_url"] = "https://example.test/changed.pdf"
        row["mail_subject"] = "changed subject"
        config["search"]["folder"] = "Archive"

        snapshot = request.invoice_snapshots[0]
        self.assertIsInstance(snapshot, RedownloadInvoiceSnapshot)
        self.assertEqual(snapshot.invoice_id, 41)
        self.assertEqual(snapshot.download_url, "https://example.test/a.pdf")
        self.assertEqual(snapshot.mail_subject, "original subject")
        self.assertEqual(request.config["search"]["folder"], "INBOX")
        with self.assertRaises(FrozenInstanceError):
            snapshot.invoice_id = 99

    def test_db_factory_is_called_inside_operation_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "redownload.db"
            self._seed_invoice(db_path, invoice_number="THREAD-1")
            main_thread = threading.get_ident()
            created_on = []
            operation_thread = []
            original_db = redownload_module.InvoiceDB

            class FakeDownloader:
                def __init__(self, download_dir):
                    self.download_dir = download_dir

                def close(self):
                    return None

            def db_factory(path):
                created_on.append(threading.get_ident())
                return original_db(path)

            result_holder = []

            def operation():
                operation_thread.append(threading.get_ident())
                result_holder.append(
                    run_invoice_redownload(
                        [{"id": 1}],
                        db_path,
                        runtime_dir=root / "runtime",
                    )
                )

            with patch.object(
                redownload_module, "InvoiceDB", side_effect=db_factory
            ), patch.object(
                redownload_module,
                "_link_downloader",
                SimpleNamespace(LinkDownloader=FakeDownloader),
            ):
                thread = threading.Thread(target=operation)
                thread.start()
                thread.join()

            self.assertEqual(len(result_holder), 1)
            self.assertEqual(created_on, operation_thread)
            self.assertNotEqual(created_on[0], main_thread)
            self.assertEqual(result_holder[0]["buckets"]["no_candidate_link"], 1)

    def test_mail_fallback_failure_does_not_return_auth_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "redownload.db"
            invoice_id = self._seed_invoice(db_path, invoice_number="MAIL-1", mail_uid=202)
            secret = "temporary-auth-secret"
            logs = []

            class FakeDownloader:
                def __init__(self, download_dir):
                    self.download_dir = download_dir

                def _download_url(self, *args):
                    return None

                def close(self):
                    return None

            class FailingMailFetcher:
                def __init__(self, **kwargs):
                    self.secret = kwargs.get("auth_code")
                    self.exited = False

                def __enter__(self):
                    raise RuntimeError(f"provider rejected {self.secret}")

                def __exit__(self, *_args):
                    self.exited = True

            fetchers = []

            def make_failing_fetcher(**kwargs):
                fetcher = FailingMailFetcher(**kwargs)
                fetchers.append(fetcher)
                return fetcher

            with _patched_services(root / "runtime") as fake_services, \
                    patch.object(redownload_module, "_link_downloader", SimpleNamespace(LinkDownloader=FakeDownloader)), \
                    patch.object(redownload_module._credentials, "has_auth_code", return_value=True), \
                    patch.object(redownload_module._credentials, "get_auth_code", return_value=secret), \
                    patch.object(redownload_module._mail_fetcher, "MailFetcher", make_failing_fetcher):
                fake_services._handle_pending_email = lambda **_kwargs: None
                result = run_invoice_redownload(
                    [{"id": invoice_id, "mail_uid": 202}],
                    db_path,
                    runtime_dir=root / "runtime",
                    config={"email": {"address": "user@example.com"}},
                    log_callback=logs.append,
                )

            self.assertNotIn(secret, repr(result))
            self.assertNotIn(secret, " ".join(logs))
            self.assertEqual(result["buckets"]["download_failed"], 1)
            self.assertTrue(fetchers[0].exited)

    def test_playwright_owner_is_closed_when_parser_setup_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "redownload.db"
            self._seed_invoice(db_path, invoice_number="CLEANUP-1")
            instances = []

            class FakeDownloader:
                def __init__(self, download_dir):
                    self.download_dir = download_dir
                    self.closed = False
                    instances.append(self)

                def close(self):
                    self.closed = True

            class ParserSetupFailure:
                def __init__(self):
                    raise RuntimeError("controlled parser setup failure")

            with patch.object(
                redownload_module,
                "_link_downloader",
                SimpleNamespace(LinkDownloader=FakeDownloader),
            ), patch.object(
                redownload_module._invoice_parser, "InvoiceParser", ParserSetupFailure
            ):
                with self.assertRaises(RuntimeError):
                    run_invoice_redownload(
                        [{"id": 1}],
                        db_path,
                        runtime_dir=root / "runtime",
                    )

            self.assertEqual(len(instances), 1)
            self.assertTrue(instances[0].closed)


class RedownloadWorkerEventLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtCore import QCoreApplication
        except ImportError as exc:
            raise unittest.SkipTest(f"Skipping Qt worker tests: {exc}")
        cls._qt = QCoreApplication.instance() or QCoreApplication([])

    def test_worker_does_not_block_event_loop_while_operation_is_pending(self):
        from PySide6.QtCore import QTimer
        from scripts.invoice_fetch.gui.workers import InvoiceRedownloadRequest, InvoiceRedownloadWorker

        started = threading.Event()
        release = threading.Event()
        ticks = []

        def controlled_operation(*args, **kwargs):
            started.set()
            release.wait()
            return {
                "requested_count": 1,
                "completed_count": 1,
                "success_count": 1,
                "failed_count": 0,
                "cancelled": False,
                "buckets": {"file_restored": 1},
                "invoice_results": ({"invoice_id": 1, "status": "file_restored"},),
                "failure_details": (),
            }

        request = InvoiceRedownloadRequest.from_values(1, [{"id": 1}], Path("worker.db"), Path("runtime"), {})
        worker = InvoiceRedownloadWorker(request)
        worker.result.connect(lambda _result: ticks.append("result"))
        with patch("scripts.invoice_fetch.redownload.run_invoice_redownload", controlled_operation):
            worker.start()
            self.assertTrue(started.wait(2))
            QTimer.singleShot(0, lambda: ticks.append("timer"))
            self._qt.processEvents()
            self.assertIn("timer", ticks)

            release.set()
            worker.wait()
            self._qt.processEvents()
            self.assertIn("result", ticks)
        worker.deleteLater()

    def test_worker_fatal_error_signal_does_not_forward_exception_text(self):
        from scripts.invoice_fetch.gui.workers import InvoiceRedownloadRequest, InvoiceRedownloadWorker

        secret = "credential-that-must-not-cross-worker-boundary"
        request = InvoiceRedownloadRequest.from_values(
            2, [{"id": 1}], Path("worker.db"), Path("runtime"), {}
        )
        worker = InvoiceRedownloadWorker(request)
        errors = []
        worker.error.connect(errors.append)

        with patch(
            "scripts.invoice_fetch.redownload.run_invoice_redownload",
            side_effect=RuntimeError(secret),
        ):
            worker.start()
            worker.wait()
            self._qt.processEvents()

        self.assertEqual(errors, ["重新下载失败，请稍后重试。"])
        self.assertNotIn(secret, repr(errors))
        worker.deleteLater()

    def test_window_close_defers_while_redownload_worker_is_blocked(self):
        try:
            from PySide6.QtCore import QThread, QTimer
            from PySide6.QtGui import QCloseEvent
            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
            from shiboken6 import isValid
        except ImportError as exc:
            self.skipTest(f"Skipping Qt window test: {exc}")

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "shutdown.db"
            window = InvoiceReviewApp(db_path, splash=None, startup_probe=True)
            started = threading.Event()
            release = threading.Event()
            cancel_called = threading.Event()

            class BlockedWorker(QThread):
                def run(self):
                    started.set()
                    release.wait()

                def request_cancel(self):
                    cancel_called.set()

            worker = BlockedWorker(window)
            window._redownload_worker = worker
            window._redownload_request_id = 1
            self.assertTrue(window._try_begin_data_operation("重新下载发票", notify=False))
            worker.finished.connect(lambda: window._redownload_thread_done(1))
            worker.start()
            self.assertTrue(started.wait(2))

            try:
                close_event = QCloseEvent()
                window.closeEvent(close_event)
                self.assertFalse(close_event.isAccepted())
                self.assertTrue(cancel_called.is_set())
                self.assertTrue(worker.isRunning())
                self.assertTrue(window.db.is_open)

                timer_ticks = []
                QTimer.singleShot(0, lambda: timer_ticks.append(True))
                self._qt.processEvents()
                self.assertEqual(timer_ticks, [True])

                release.set()
                worker.wait()
                for _ in range(3):
                    self._qt.processEvents()

                self.assertIsNone(window._redownload_worker)
                self.assertFalse(window.db.is_open)
                self.assertEqual(window._data_operation_gate.owner, "")
            finally:
                release.set()
                if isValid(worker) and worker.isRunning():
                    worker.wait()
                if isValid(window) and window.db.is_open:
                    window.db.close()
                if isValid(window):
                    window.deleteLater()
                self._qt.processEvents()


class RedownloadGuiBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping Qt GUI boundary tests: {exc}")
        try:
            cls._qt = QApplication.instance() or QApplication([])
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping Qt GUI boundary tests: {exc}")

    def _make_window(self):
        try:
            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"Skipping Qt GUI boundary tests: {exc}")

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "gui-redownload.db"
        with InvoiceDB(db_path) as db:
            first_id = db.insert_invoice(
                {
                    "invoice_number": "A",
                    "invoice_date": "2026-06-01",
                    "total_amount": "10.00",
                    "seller_name": "Seller A",
                    "download_url": "https://example.test/a.pdf",
                    "review_status": "to_review",
                }
            )
            second_id = db.insert_invoice(
                {
                    "invoice_number": "B",
                    "invoice_date": "2026-06-02",
                    "total_amount": "20.00",
                    "seller_name": "Seller B",
                    "download_url": "https://example.test/b.pdf",
                    "review_status": "to_review",
                }
            )

        with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value={}):
            window = InvoiceReviewApp(db_path, splash=None)
        window._deferred_init()
        self._qt.processEvents()

        def cleanup():
            try:
                from shiboken6 import isValid
            except ImportError:
                isValid = lambda _object: True
            worker = getattr(window, "_redownload_worker", None)
            if worker is not None and isValid(worker) and worker.isRunning():
                worker.request_cancel()
                worker.wait()
            if isValid(window) and getattr(window, "db", None) is not None and window.db.is_open:
                window.db.close()
            if isValid(window):
                window.close()
                window.deleteLater()
            self._qt.processEvents()

        self.addCleanup(cleanup)
        return window, int(first_id), int(second_id)

    @staticmethod
    def _result(requested_count=2):
        return {
            "requested_count": requested_count,
            "completed_count": requested_count,
            "success_count": requested_count,
            "failed_count": 0,
            "cancelled": False,
            "buckets": {
                "file_restored": requested_count,
                "metadata_refreshed": 0,
                "duplicate_only": 0,
                "download_failed": 0,
                "no_candidate_link": 0,
            },
            "invoice_results": (),
            "failure_details": (),
        }

    def test_handler_returns_to_event_loop_and_repeated_start_reuses_worker(self):
        from PySide6.QtCore import QTimer
        from scripts.invoice_fetch import redownload as redownload_module

        window, _first_id, _second_id = self._make_window()
        window.table.selectRow(0)
        started = threading.Event()
        release = threading.Event()

        def controlled_operation(*_args, **_kwargs):
            started.set()
            release.wait()
            return self._result(requested_count=1)

        timer_ticks = []
        with patch.object(
            redownload_module, "run_invoice_redownload", side_effect=controlled_operation
        ) as operation, patch("PySide6.QtWidgets.QMessageBox.information"):
            worker = window._redownload_selected_invoices()
            self.assertIsNotNone(worker)
            self.assertTrue(started.wait(2))
            self.assertIs(window._redownload_selected_invoices(), worker)
            self.assertEqual(operation.call_count, 1)

            QTimer.singleShot(0, lambda: timer_ticks.append(True))
            self._qt.processEvents()
            self.assertEqual(timer_ticks, [True])

            release.set()
            worker.wait()
            self._qt.processEvents()
            self.assertIsNone(window._redownload_worker)

    def test_completion_refresh_keeps_the_new_selection(self):
        from scripts.invoice_fetch import redownload as redownload_module

        window, _first_id, second_id = self._make_window()
        first_row = window._row_for_invoice_id(_first_id)
        second_row = window._row_for_invoice_id(second_id)
        self.assertGreaterEqual(first_row, 0)
        self.assertGreaterEqual(second_row, 0)
        window._apply_single_row_selection(first_row)
        release = threading.Event()

        def controlled_operation(*_args, **_kwargs):
            release.wait()
            return self._result(requested_count=1)

        with patch.object(
            redownload_module, "run_invoice_redownload", side_effect=controlled_operation
        ), patch("PySide6.QtWidgets.QMessageBox.information"):
            worker = window._redownload_selected_invoices()
            window._apply_single_row_selection(second_row)
            # Reproduce the Windows regression: the live table selection is B
            # while the cached detail object still points to A.
            window.current_invoice = window._invoice_by_id(_first_id)
            release.set()
            worker.wait()
            self._qt.processEvents()

        selected_rows = window.table.selectionModel().selectedRows()
        self.assertEqual([index.row() for index in selected_rows], [second_row])
        selected_invoice_ids = [window.invoices_list[index.row()]["id"] for index in selected_rows]
        self.assertEqual(selected_invoice_ids, [second_id])
        self.assertIsNotNone(window.current_invoice)
        self.assertEqual(window.current_invoice["id"], second_id)
        self.assertEqual(window.txt_number.text(), "B")

    def test_detail_retry_uses_current_invoice_only_with_multiple_selection(self):
        from PySide6.QtCore import QItemSelectionModel
        from PySide6.QtWidgets import QAbstractItemView
        from scripts.invoice_fetch import redownload as redownload_module

        window, first_id, second_id = self._make_window()
        window.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        first_row = window._row_for_invoice_id(first_id)
        second_row = window._row_for_invoice_id(second_id)
        self.assertGreaterEqual(first_row, 0)
        self.assertGreaterEqual(second_row, 0)
        window._apply_single_row_selection(second_row)
        window.table.selectionModel().select(
            window.table.model().index(first_row, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )
        window.current_invoice = window._invoice_by_id(second_id)
        captured = []

        def controlled_detail(snapshot, *_args, **_kwargs):
            captured.append(snapshot)
            return {
                "mode": "detail_link_retry",
                "invoice_id": second_id,
                "requested_count": 1,
                "completed_count": 1,
                "success": True,
                "cancelled": False,
            }

        with patch.object(
            redownload_module, "run_invoice_link_retry", side_effect=controlled_detail
        ), patch.object(
            redownload_module,
            "run_invoice_redownload",
            side_effect=AssertionError("detail retry must not invoke batch operation"),
        ), patch("PySide6.QtWidgets.QMessageBox.information"):
            worker = window._retry_download_link()
            self.assertIsNotNone(worker)
            worker.wait()
            self._qt.processEvents()

        self.assertEqual([snapshot.invoice_id for snapshot in captured], [second_id])
        self.assertNotEqual(captured[0].invoice_id, first_id)
        self.assertIsNone(window._redownload_worker)

    def test_detail_retry_returns_to_event_loop_while_downloader_is_blocked(self):
        from PySide6.QtCore import QTimer
        from scripts.invoice_fetch import redownload as redownload_module
        try:
            from shiboken6 import isValid
        except ImportError:
            isValid = lambda _object: True

        window, _first_id, second_id = self._make_window()
        window.table.selectRow(1)
        started = threading.Event()
        release = threading.Event()
        timer_ticks = []
        worker = None

        def controlled_detail(*_args, **_kwargs):
            started.set()
            release.wait()
            return {
                "mode": "detail_link_retry",
                "invoice_id": second_id,
                "requested_count": 1,
                "completed_count": 1,
                "success": True,
                "cancelled": False,
            }

        try:
            with patch.object(
                redownload_module, "run_invoice_link_retry", side_effect=controlled_detail
            ), patch("PySide6.QtWidgets.QMessageBox.information"):
                worker = window._retry_download_link()
                self.assertTrue(started.wait(2))
                QTimer.singleShot(0, lambda: timer_ticks.append(True))
                self._qt.processEvents()
                self.assertEqual(timer_ticks, [True])
                release.set()
                worker.wait()
                self._qt.processEvents()
        finally:
            release.set()
            if worker is not None and isValid(worker) and worker.isRunning():
                worker.wait()


if __name__ == "__main__":
    unittest.main()
