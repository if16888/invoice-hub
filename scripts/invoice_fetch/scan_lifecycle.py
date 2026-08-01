"""Cooperative mailbox scan lifecycle and redacted progress events."""

from __future__ import annotations

import threading
import time
import re
from dataclasses import dataclass, field
from uuid import uuid4

from .log_privacy import mask_email, sanitize_log_message


class ScanCancelled(Exception):
    """Raised at a safe operation boundary after the user requested cancel."""


class ScanStage:
    CONNECT = "connect"
    TLS = "tls"
    AUTHENTICATE = "authenticate"
    QUERY = "query"
    DOWNLOAD = "download"
    PARSE = "parse"
    SAVE = "save"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


DEFAULT_IMAP_TIMEOUTS = {
    "connect": 15.0,
    "tls": 20.0,
    "command": 30.0,
}


def new_scan_id() -> str:
    return uuid4().hex[:12]


class ScanControl:
    """Thread-safe cancellation token which can interrupt an active fetcher."""

    def __init__(self):
        self._cancelled = threading.Event()
        self._lock = threading.RLock()
        self._fetcher = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def register_fetcher(self, fetcher) -> None:
        with self._lock:
            self._fetcher = fetcher
            if self.cancelled:
                fetcher.cancel()

    def unregister_fetcher(self, fetcher) -> None:
        with self._lock:
            if self._fetcher is fetcher:
                self._fetcher = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            fetcher = self._fetcher
        if fetcher is not None:
            fetcher.cancel()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ScanCancelled("用户取消邮箱扫描")


@dataclass
class ScanProgress:
    scan_id: str
    mailbox: str = ""
    stage: str = ScanStage.CONNECT
    started_at: float = field(default_factory=time.monotonic)
    counts: dict[str, int] = field(default_factory=dict)
    reason: str = ""
    exception_type: str = ""

    def as_dict(self) -> dict:
        safe_reason = sanitize_log_message(self.reason)
        safe_reason = re.sub(
            r"(?i)\b(auth[_ -]?code|password|token|api[_ -]?key)\s*[:=]\s*\S+",
            r"\1=<redacted>",
            safe_reason,
        )
        return {
            "scan_id": self.scan_id,
            "mailbox": mask_email(self.mailbox),
            "stage": self.stage,
            "elapsed_ms": max(0, int((time.monotonic() - self.started_at) * 1000)),
            "counts": {str(k): int(v) for k, v in self.counts.items()},
            "reason": safe_reason,
            "exception_type": self.exception_type,
        }


def redacted_progress(
    scan_id: str,
    mailbox: str,
    stage: str,
    started_at: float,
    counts: dict | None = None,
    reason: str = "",
    exception_type: str = "",
) -> dict:
    return ScanProgress(
        scan_id=scan_id,
        mailbox=mailbox,
        stage=stage,
        started_at=started_at,
        counts=counts or {},
        reason=reason,
        exception_type=exception_type,
    ).as_dict()
