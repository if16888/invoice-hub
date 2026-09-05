# -*- coding: utf-8 -*-
"""Background GUI workers extracted from the main GUI assembly module."""

from copy import deepcopy
from pathlib import Path
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from PySide6.QtCore import QThread, Signal

from .performance_probe import emit_performance_event
from ..redownload import (
    REDOWNLOAD_MODE_BATCH,
    REDOWNLOAD_MODE_DETAIL_LINK_RETRY,
    RedownloadInvoiceSnapshot,
)
from ..scan_lifecycle import ScanCancelled, ScanControl


@dataclass(frozen=True)
class MailboxConnectionTestRequest:
    """Immutable, non-UI input snapshot for one mailbox connection test."""

    request_id: int
    address: str
    auth_code: str
    server: str
    port: int


class MailboxConnectionTestWorker(QThread):
    """Run one IMAP login attempt outside the Qt GUI thread.

    The worker deliberately owns only the network operation.  It never
    touches widgets, settings, credentials storage, or application state.
    """

    success = Signal(object)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, request: MailboxConnectionTestRequest, parent=None):
        super().__init__(parent)
        self._request = request
        self.control = ScanControl()

    @property
    def request_id(self) -> int:
        return self._request.request_id if self._request is not None else -1

    def request_cancel(self):
        """Cooperatively cancel the active IMAP operation."""

        self.control.cancel()

    @staticmethod
    def _safe_error_text(error, secret: str) -> str:
        text = str(error or "")
        if secret:
            text = text.replace(secret, "<redacted>")
        return text

    def run(self):
        request = self._request
        fetcher = None
        outcome = "failure"
        error_text = ""
        try:
            # Import at execution time so importing the GUI worker module does
            # not perform any network setup and tests can replace MailFetcher.
            from ..mail_fetcher import MailFetcher

            self.control.raise_if_cancelled()
            fetcher = MailFetcher(
                address=request.address,
                auth_code=request.auth_code,
                server=request.server,
                port=request.port,
                control=self.control,
            )
            fetcher.connect()
            self.control.raise_if_cancelled()
            outcome = "success"
        except ScanCancelled:
            outcome = "cancelled"
        except Exception as exc:
            if self.control.cancelled:
                outcome = "cancelled"
            else:
                error_text = self._safe_error_text(exc, request.auth_code)
        finally:
            if fetcher is not None:
                try:
                    fetcher.disconnect()
                except Exception as exc:
                    if outcome == "success":
                        outcome = "failure"
                        error_text = self._safe_error_text(exc, request.auth_code)
            # Drop the worker's references as soon as the network operation is
            # complete.  The GUI receives only request_id/status-safe text.
            self._request = None

        if outcome == "success":
            self.success.emit(request.request_id)
        elif outcome == "cancelled":
            self.cancelled.emit()
        else:
            self.error.emit(error_text)


@dataclass(frozen=True)
class InvoiceRedownloadRequest:
    """Immutable request snapshot for one review-workbench redownload batch."""

    request_id: int
    invoice_snapshots: tuple[RedownloadInvoiceSnapshot, ...]
    db_path: Path
    runtime_dir: Path
    config: Mapping[str, object]
    mode: str = REDOWNLOAD_MODE_BATCH

    @classmethod
    def from_values(
        cls,
        request_id: int,
        invoice_snapshots,
        db_path: Path,
        runtime_dir: Path,
        config: Mapping[str, object],
        mode: str = REDOWNLOAD_MODE_BATCH,
    ) -> "InvoiceRedownloadRequest":
        # Convert at the boundary so the worker never receives QModelIndex,
        # QTableWidgetItem, a mutable GUI row, or a GUI-owned DB object.
        # RedownloadInvoiceSnapshot is frozen and contains only the fields
        # needed by the non-UI operation.
        snapshots = tuple(
            value
            if isinstance(value, RedownloadInvoiceSnapshot)
            else RedownloadInvoiceSnapshot.from_mapping(value)
            for value in invoice_snapshots
        )
        config_snapshot = deepcopy(dict(config or {}))
        return cls(
            request_id=int(request_id),
            invoice_snapshots=snapshots,
            db_path=Path(db_path),
            runtime_dir=Path(runtime_dir),
            config=MappingProxyType(config_snapshot),
            mode=str(mode or REDOWNLOAD_MODE_BATCH),
        )


class InvoiceRedownloadWorker(QThread):
    """Run one non-UI invoice redownload batch in its own thread."""

    progress = Signal(dict)
    log = Signal(str)
    result = Signal(object)
    error = Signal(str)
    cancelled = Signal(object)

    def __init__(self, request: InvoiceRedownloadRequest, parent=None):
        super().__init__(parent)
        self.request = request
        self.control = ScanControl()

    @property
    def request_id(self) -> int:
        return int(self.request.request_id) if self.request is not None else -1

    def request_cancel(self):
        """Stop before the next invoice and interrupt active IMAP fetches."""

        self.control.cancel()

    @staticmethod
    def _safe_error_text(_error) -> str:
        """Return a useful but secret-independent fatal error message."""

        # The request deliberately contains no credential.  A transport or
        # provider exception can nevertheless echo one, so do not forward
        # arbitrary exception text through a queued GUI signal.
        return "重新下载失败，请稍后重试。"

    def run(self):
        request = self.request
        if request is None:
            return
        try:
            from ..redownload import run_invoice_link_retry, run_invoice_redownload

            if request.mode == REDOWNLOAD_MODE_DETAIL_LINK_RETRY:
                if len(request.invoice_snapshots) != 1:
                    raise ValueError("detail link retry requires exactly one invoice")
                payload = run_invoice_link_retry(
                    request.invoice_snapshots[0],
                    request.db_path,
                    runtime_dir=request.runtime_dir,
                    config=request.config,
                    scan_control=self.control,
                    log_callback=self.log.emit,
                    progress_callback=self.progress.emit,
                )
            else:
                payload = run_invoice_redownload(
                    request.invoice_snapshots,
                    request.db_path,
                    runtime_dir=request.runtime_dir,
                    config=request.config,
                    scan_control=self.control,
                    log_callback=self.log.emit,
                    progress_callback=self.progress.emit,
                )
            if payload.get("cancelled"):
                self.cancelled.emit(payload)
            else:
                self.result.emit(payload)
        except ScanCancelled:
            self.cancelled.emit(
                {
                    "mode": request.mode,
                    "invoice_id": request.invoice_snapshots[0].invoice_id
                    if request.invoice_snapshots
                    else None,
                    "requested_count": len(request.invoice_snapshots),
                    "completed_count": 0,
                    "cancelled": True,
                    "buckets": {},
                    "invoice_results": (),
                    "failure_details": (),
                }
            )
        except Exception as exc:
            if self.control.cancelled:
                self.cancelled.emit(
                    {
                        "mode": request.mode,
                        "invoice_id": request.invoice_snapshots[0].invoice_id
                        if request.invoice_snapshots
                        else None,
                        "requested_count": len(request.invoice_snapshots),
                        "completed_count": 0,
                        "cancelled": True,
                        "buckets": {},
                        "invoice_results": (),
                        "failure_details": (),
                    }
                )
            else:
                self.error.emit(self._safe_error_text(exc))
        finally:
            # Release the immutable snapshot (including any config reference)
            # as soon as the operation exits.  The native QThread finished
            # signal remains available to the owning window for cleanup.
            self.request = None


class ExportMigrationWorker(QThread):
    """Move legacy install-local exports without delaying UI construction."""

    progress = Signal(dict)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, source: Path, destination: Path, parent=None):
        super().__init__(parent)
        self.source = Path(source)
        self.destination = Path(destination)
        self.result = None

    def run(self):
        try:
            from ..export_paths import migrate_legacy_exports

            self.result = migrate_legacy_exports(
                self.source,
                self.destination,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(self.result)
        except Exception as e:
            self.error.emit(str(e))


class LocalImportWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, import_dir: Path, db_path: Path):
        super().__init__()
        self.import_dir = import_dir
        self.db_path = db_path
        self.control = ScanControl()

    def request_cancel(self):
        """Request a cooperative stop before the next source file."""

        self.control.cancel()

    def run(self):
        try:
            from ..services import import_local_directory

            stats = import_local_directory(
                self.import_dir,
                self.db_path,
                scan_control=self.control,
            )
            completed_at = time.perf_counter()
            result = dict(stats)
            result["_performance_t0_monotonic"] = completed_at
            outcome = "cancelled" if result.get("cancelled") else "success"
            emit_performance_event("local_import", "T0_worker_done", outcome=outcome)
            self.finished.emit(result)
        except ScanCancelled:
            completed_at = time.perf_counter()
            emit_performance_event("local_import", "T0_worker_done", outcome="cancelled")
            self.finished.emit(
                {
                    "cancelled": True,
                    "_performance_t0_monotonic": completed_at,
                }
            )
        except Exception as e:
            emit_performance_event("local_import", "T0_worker_done", outcome="error")
            self.error.emit(str(e))


class EmailScanWorker(QThread):
    log = Signal(str)
    stage = Signal(dict)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, db_path: Path, selected_keys: list[str] | None = None):
        super().__init__()
        self.db_path = db_path
        self.selected_keys = selected_keys
        self.summary_logs = []
        from ..scan_lifecycle import ScanControl
        self.control = ScanControl()

    def request_cancel(self):
        self.control.cancel()

    def run(self):
        try:
            from ..services import scan_email_and_download

            def gui_log(msg: str):
                self.summary_logs.append(str(msg or ""))
                self.log.emit(msg)

            res = scan_email_and_download(
                db_path=self.db_path,
                log_callback=gui_log,
                selected_keys=self.selected_keys,
                scan_control=self.control,
                progress_callback=self.stage.emit,
            )
            completed_at = time.perf_counter()
            emit_performance_event("mail_complete", "T0_worker_done", outcome="success")
            result = dict(res)
            result["_performance_t0_monotonic"] = completed_at
            self.finished.emit(result)
        except Exception as e:
            from ..scan_lifecycle import ScanCancelled
            if isinstance(e, ScanCancelled):
                completed_at = time.perf_counter()
                emit_performance_event("mail_complete", "T0_worker_done", outcome="cancelled")
                self.finished.emit(
                    {
                        "cancelled": True,
                        "reason": str(e),
                        "_performance_t0_monotonic": completed_at,
                    }
                )
            else:
                emit_performance_event("mail_complete", "T0_worker_done", outcome="error")
                self.error.emit(str(e))
