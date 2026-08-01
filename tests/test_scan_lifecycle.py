import socket
import time
from unittest.mock import Mock, patch

import pytest

from scripts.invoice_fetch.mail_fetcher import MailFetcher, _TimedIMAP4SSL
from scripts.invoice_fetch.scan_lifecycle import (
    ScanCancelled,
    ScanControl,
    ScanStage,
    redacted_progress,
)


def test_progress_is_stageful_and_redacted():
    event = redacted_progress(
        "scan123",
        "alice@example.com",
        ScanStage.DOWNLOAD,
        time.monotonic() - 0.25,
        {"processed": 2},
        reason="download failed",
        exception_type="TimeoutError",
    )
    assert event["scan_id"] == "scan123"
    assert event["mailbox"] != "alice@example.com"
    assert event["stage"] == "download"
    assert event["elapsed_ms"] >= 200
    assert event["counts"] == {"processed": 2}
    assert event["exception_type"] == "TimeoutError"


def test_progress_reason_redacts_credentials_and_invoice_numbers():
    event = redacted_progress(
        "scan123",
        "alice@example.com",
        ScanStage.FAILED,
        time.monotonic(),
        reason="auth_code=one-time-secret invoice=1234567890123456",
    )
    assert "one-time-secret" not in event["reason"]
    assert "1234567890123456" not in event["reason"]


def test_cancel_closes_active_network_socket_and_raises():
    control = ScanControl()
    fetcher = MailFetcher("alice@example.com", "secret", control=control)
    sock = Mock()
    fetcher._active_socket = sock
    control.cancel()
    sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
    sock.close.assert_called_once_with()
    with pytest.raises(ScanCancelled):
        control.raise_if_cancelled()


def test_connect_timeout_is_separate_from_tls_and_command_timeout():
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
        assert kwargs["connect_timeout"] == 3
        assert kwargs["tls_timeout"] == 7
        assert kwargs["command_timeout"] == 11
        fetcher.disconnect()


def test_timed_socket_applies_tls_then_read_timeout():
    raw = Mock()
    tls = Mock()
    context = Mock()
    context.wrap_socket.return_value = tls
    obj = _TimedIMAP4SSL.__new__(_TimedIMAP4SSL)
    obj.host = "imap.example.test"
    obj.port = 993
    obj.ssl_context = context
    obj._connect_timeout = 3
    obj._tls_timeout = 7
    obj._command_timeout = 11
    obj._socket_callback = None
    with patch("scripts.invoice_fetch.mail_fetcher.socket.create_connection", return_value=raw) as create:
        assert obj._create_socket(None) is tls
    create.assert_called_once_with(("imap.example.test", 993), 3)
    raw.settimeout.assert_called_once_with(7)
    tls.settimeout.assert_called_once_with(11)


def test_cancelled_scan_does_not_turn_into_download_failure():
    control = ScanControl()
    control.cancel()
    with pytest.raises(ScanCancelled):
        control.raise_if_cancelled()
