import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.services import _scan_mailboxes_with_db
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.workers import EmailScanWorker
from scripts.invoice_fetch.mail_fetcher import MailFetcher, _TimedIMAP4SSL
from scripts.invoice_fetch.scan_lifecycle import (
    ScanCancelled,
    ScanControl,
    ScanStage,
    redacted_progress,
)


QT_APP = QApplication.instance() or QApplication([])


class ScanLifecycleTests(unittest.TestCase):

    def test_progress_is_stageful_and_redacted(self):
        event = redacted_progress(
            "scan123",
            "alice@example.com",
            ScanStage.DOWNLOAD,
            time.monotonic() - 0.25,
            {"processed": 2},
            reason="download failed",
            exception_type="TimeoutError",
        )
        self.assertEqual(event["scan_id"], "scan123")
        self.assertNotEqual(event["mailbox"], "alice@example.com")
        self.assertEqual(event["stage"], "download")
        self.assertGreaterEqual(event["elapsed_ms"], 200)
        self.assertEqual(event["counts"], {"processed": 2})
        self.assertEqual(event["exception_type"], "TimeoutError")

    def test_progress_reason_redacts_credentials_and_invoice_numbers(self):
        event = redacted_progress(
            "scan123",
            "alice@example.com",
            ScanStage.FAILED,
            time.monotonic(),
            reason="auth_code=one-time-secret invoice=1234567890123456",
        )
        self.assertNotIn("one-time-secret", event["reason"])
        self.assertNotIn("1234567890123456", event["reason"])

    def test_cancel_closes_active_network_socket_and_raises(self):
        control = ScanControl()
        fetcher = MailFetcher("alice@example.com", "secret", control=control)
        sock = Mock()
        fetcher._active_socket = sock
        control.cancel()
        sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        sock.close.assert_called_once_with()
        with self.assertRaises(ScanCancelled):
            control.raise_if_cancelled()

    def test_connect_timeout_is_separate_from_tls_and_command_timeout(self):
        with patch("scripts.invoice_fetch.mail_fetcher._TimedIMAP4SSL") as imap:
            imap.return_value.login.return_value = ("OK", [b"logged in"])
            fetcher = MailFetcher(
                "alice@example.com",
                "secret",
                server="imap.example.test",
                port=993,
                timeouts={"connect": 3, "tls": 7, "command": 11},
            )
            fetcher.connect()
            kwargs = imap.call_args.kwargs
            self.assertEqual(kwargs["connect_timeout"], 3)
            self.assertEqual(kwargs["tls_timeout"], 7)
            self.assertEqual(kwargs["command_timeout"], 11)
            self.assertIn("stage_callback", kwargs)
            fetcher.disconnect()

    def _timed_socket_object(self, stage_callback, context):
        obj = _TimedIMAP4SSL.__new__(_TimedIMAP4SSL)
        obj.host = "imap.example.test"
        obj.port = 993
        obj.ssl_context = context
        obj._connect_timeout = 3
        obj._tls_timeout = 7
        obj._command_timeout = 11
        obj._socket_callback = None
        obj._stage_callback = stage_callback
        return obj

    def test_connect_and_tls_callbacks_are_emitted_at_real_operation_boundaries(self):
        raw = Mock()
        tls = Mock()
        context = Mock()
        events = []
        context.wrap_socket.side_effect = lambda *_args, **_kwargs: (
            events.append("tls-wrap"),
            tls,
        )[1]

        def create_connection(*_args):
            events.append("tcp-connect")
            return raw

        obj = self._timed_socket_object(
            lambda stage: events.append(stage),
            context,
        )
        with patch(
            "scripts.invoice_fetch.mail_fetcher.socket.create_connection",
            side_effect=create_connection,
        ):
            self.assertIs(obj._create_socket(None), tls)

        self.assertEqual(
            events,
            [ScanStage.CONNECT, "tcp-connect", ScanStage.TLS, "tls-wrap"],
        )

    def test_tcp_connect_failure_leaves_connect_as_last_stage(self):
        stages = []
        context = Mock()
        obj = self._timed_socket_object(stages.append, context)
        with patch(
            "scripts.invoice_fetch.mail_fetcher.socket.create_connection",
            side_effect=OSError("tcp blocked"),
        ), self.assertRaises(OSError):
            obj._create_socket(None)
        self.assertEqual(stages, [ScanStage.CONNECT])

    def test_tls_wrap_failure_leaves_tls_as_last_stage(self):
        raw = Mock()
        context = Mock()
        context.wrap_socket.side_effect = OSError("tls blocked")
        stages = []
        obj = self._timed_socket_object(stages.append, context)
        with patch(
            "scripts.invoice_fetch.mail_fetcher.socket.create_connection",
            return_value=raw,
        ), self.assertRaises(OSError):
            obj._create_socket(None)
        self.assertEqual(stages, [ScanStage.CONNECT, ScanStage.TLS])

    def test_authenticate_callback_is_immediately_before_login(self):
        events = []
        connection = Mock()
        connection.login.side_effect = lambda *_args: events.append("login")
        fetcher = MailFetcher(
            "alice@example.com",
            "secret",
            progress_callback=lambda stage: events.append(stage),
        )

        def new_connection():
            fetcher._notify_stage(ScanStage.CONNECT)
            fetcher._notify_stage(ScanStage.TLS)
            events.append("connection-ready")
            return connection

        fetcher._new_connection = new_connection
        fetcher.connect()
        self.assertEqual(
            events,
            [
                ScanStage.CONNECT,
                ScanStage.TLS,
                "connection-ready",
                ScanStage.AUTHENTICATE,
                "login",
            ],
        )
        fetcher.disconnect()

    def test_header_scan_reports_throttled_progress_counters(self):
        class HeaderConnection:
            def select(self, _folder, readonly=True):
                return "OK", [b"55"]

            def search(self, *_args):
                return "OK", [b" " .join(str(i).encode() for i in range(1, 56))]

            def fetch(self, mid, _query):
                uid = int(mid)
                date = "01-Jan-2020" if uid == 2 else "01-Jul-2026"
                metadata = f'UID {uid} INTERNALDATE "{date} 00:00:00 +0000"'.encode()
                headers = (
                    b"Subject: invoice\r\n"
                    b"From: sender@example.com\r\n"
                    b"Date: Tue, 01 Jul 2026 00:00:00 +0000\r\n\r\n"
                )
                return "OK", [(metadata, headers)]

        events = []
        fetcher = MailFetcher(
            "alice@example.com",
            "secret",
            progress_callback=lambda stage, counts=None: events.append(
                (stage, counts or {})
            ),
        )
        fetcher._conn = HeaderConnection()
        headers = fetcher.scan_headers(months_back=12, known_uids={1})

        progress = [counts for stage, counts in events if stage == ScanStage.QUERY and counts]
        self.assertGreaterEqual(len(progress), 3)
        self.assertEqual(
            set(progress[-1]),
            {"processed", "total", "headers", "known_skipped", "old_skipped", "errors"},
        )
        self.assertEqual(progress[-1]["processed"], 55)
        self.assertEqual(progress[-1]["total"], 55)
        self.assertEqual(progress[-1]["headers"], 53)
        self.assertEqual(progress[-1]["known_skipped"], 1)
        self.assertEqual(progress[-1]["old_skipped"], 1)
        self.assertEqual(progress[-1]["errors"], 0)

    def test_cancellation_stops_first_mailbox_before_database_write(self):
        class FakeNetwork:
            def __init__(self):
                self.closed = False

            def cancel(self):
                self.closed = True

        class FakeFetcher:
            instances = []

            def __init__(self, *, control, progress_callback, **_kwargs):
                self.control = control
                self.progress_callback = progress_callback
                self.network = FakeNetwork()
                self.control.register_fetcher(self)
                self.instances.append(self)

            def __enter__(self):
                self.progress_callback(ScanStage.CONNECT)
                return self

            def __exit__(self, *_args):
                self.disconnect()

            def cancel(self):
                self.network.cancel()

            def disconnect(self):
                self.network.cancel()
                self.control.unregister_fetcher(self)

            def scan_headers(self, **_kwargs):
                self.progress_callback(
                    ScanStage.QUERY,
                    {
                        "processed": 1,
                        "total": 10,
                        "headers": 1,
                        "known_skipped": 0,
                        "old_skipped": 0,
                        "errors": 0,
                    },
                )
                self.control.cancel()
                self.control.raise_if_cancelled()

        accounts = [
            {
                "address": "first@example.com",
                "mailbox_key": "first@example.com",
                "enabled": True,
                "provider": "qq",
                "imap": {"server": "imap.example.test", "port": 993},
                "search": {"folder": "INBOX", "months_back": 3},
            },
            {
                "address": "second@example.com",
                "mailbox_key": "second@example.com",
                "enabled": True,
                "provider": "qq",
                "imap": {"server": "imap.example.test", "port": 993},
                "search": {"folder": "INBOX", "months_back": 3},
            },
        ]
        progress_events = []
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "invoices.db"
            db = InvoiceDB(db_path)
            try:
                with patch(
                    "scripts.invoice_fetch.services.get_email_accounts",
                    return_value=accounts,
                ), patch(
                    "scripts.invoice_fetch.services.get_auth_code",
                    return_value="secret",
                ), patch(
                    "scripts.invoice_fetch.services.MailFetcher",
                    FakeFetcher,
                ), patch(
                    "scripts.invoice_fetch.services._run_classify",
                    return_value={},
                ):
                    with self.assertRaises(ScanCancelled):
                        _scan_mailboxes_with_db(
                            db=db,
                            db_path=db_path,
                            cfg={"email_accounts": accounts},
                            scan_only=True,
                            no_ai=True,
                            progress_callback=progress_events.append,
                            scan_control=ScanControl(),
                        )

                self.assertEqual(len(FakeFetcher.instances), 1)
                self.assertTrue(FakeFetcher.instances[0].network.closed)
                self.assertEqual(db.get_all_email_uids(), set())
                integrity = db._conn.execute("PRAGMA integrity_check").fetchone()[0]
                self.assertEqual(integrity, "ok")
                self.assertEqual(
                    progress_events[-1]["stage"],
                    ScanStage.CANCELLED,
                )
            finally:
                db.close()

    def test_worker_returns_cancelled_and_gui_cleanup_restores_controls(self):
        active_network = {}

        def fake_scan(**kwargs):
            class ActiveNetwork:
                def __init__(self):
                    self.closed = False

                def cancel(self):
                    self.closed = True

            network = ActiveNetwork()
            active_network["value"] = network
            kwargs["scan_control"].register_fetcher(network)
            kwargs["progress_callback"](
                {
                    "stage": ScanStage.QUERY,
                    "counts": {"processed": 1, "total": 2},
                }
            )
            kwargs["scan_control"].cancel()
            kwargs["scan_control"].raise_if_cancelled()

        app = QCoreApplication.instance() or QCoreApplication([])
        worker = EmailScanWorker(Path("cancel-integration.db"))
        finished = []
        errors = []
        worker.finished.connect(finished.append)
        worker.error.connect(errors.append)
        with patch(
            "scripts.invoice_fetch.services.scan_email_and_download",
            side_effect=fake_scan,
        ):
            worker.start()
            deadline = time.monotonic() + 5
            while worker.isRunning() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            worker.wait(1000)
            app.processEvents()

        self.assertFalse(worker.isRunning())
        self.assertFalse(errors)
        self.assertEqual(len(finished), 1)
        self.assertTrue(finished[0]["cancelled"])
        self.assertTrue(active_network["value"].closed)

        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        with tempfile.TemporaryDirectory() as tmp:
            window = InvoiceReviewApp(Path(tmp) / "gui-cancel.db", splash=None)
            try:
                window._refresh_imports_page()
                trigger = window.btn_import_scan_default
                window.scan_worker = type(
                    "FinishedWorker",
                    (),
                    {
                        "_trigger_btn": trigger,
                        "isRunning": lambda _self: False,
                    },
                )()
                window._scan_started_at = time.monotonic()
                window.btn_import_scan_default.setEnabled(False)
                window.btn_import_scan_selected.setEnabled(False)
                window.btn_import_scan_cancel.setVisible(True)
                window.btn_import_scan_cancel.setEnabled(False)
                window._finish_scan_ui(cancelled=True)
                self.assertTrue(window.btn_import_scan_default.isEnabled())
                self.assertTrue(window.btn_import_scan_selected.isEnabled())
                self.assertFalse(window.btn_import_scan_cancel.isVisible())
                self.assertIn("已取消", window.lbl_import_scan_status.text())
            finally:
                window.close()

    def test_cancelled_scan_does_not_turn_into_download_failure(self):
        control = ScanControl()
        control.cancel()
        with self.assertRaises(ScanCancelled):
            control.raise_if_cancelled()


if __name__ == "__main__":
    unittest.main()
