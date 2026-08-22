"""Temporary LAN upload service for phone-to-desktop invoice intake."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
import socket
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

from .config import RUNTIME_DIR
from .log_privacy import sanitize_log_message


_log = logging.getLogger("invoice_fetch.mobile_upload")


ALLOWED_UPLOAD_EXTS = {".pdf", ".ofd", ".png", ".jpg", ".jpeg", ".heic"}
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024

_PDFJS_ASSET_ROOT = Path(__file__).resolve().parent / "web_assets" / "pdfjs"
_PDFJS_ASSET_PREFIX = "/assets/pdfjs/"
_PDFJS_ALLOWED_ROOTS = {"pdf.min.mjs", "pdf.worker.min.mjs", "cmaps", "standard_fonts"}
_PDFJS_CONTENT_TYPES = {
    ".mjs": "text/javascript; charset=utf-8",
    ".bcmap": "application/octet-stream",
    ".pfb": "application/octet-stream",
    ".ttf": "font/ttf",
}


def _redact_host(host: object) -> str:
    """Keep logs useful for LAN diagnosis without recording a full address."""
    value = str(host or "").strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return "<redacted>"
    if address.version == 4:
        parts = value.split(".")
        return ".".join(parts[:2] + ["x", "xxx"])
    return "<ipv6:redacted>"


def _redact_request_path(path: object) -> str:
    """Drop query strings and replace every session token path segment."""
    value = urlparse(str(path or "")).path or "/"
    for prefix in ("/u/", "/api/upload/", "/api/status/"):
        if value.startswith(prefix):
            return f"{prefix}<redacted>"
    return value


def _safe_log_reason(reason: object, token: str = "") -> str:
    value = str(reason or "").replace(token, "<redacted>") if token else str(reason or "")
    value = sanitize_log_message(value)
    value = re.sub(r"https?://\S+", "<url:redacted>", value)
    return value[:240] or "unknown"


def _resolve_pdfjs_asset(path: str) -> Path | None:
    """Resolve only the vendored PDF.js files, never arbitrary local paths."""
    if not str(path or "").startswith(_PDFJS_ASSET_PREFIX):
        return None
    relative = str(path)[len(_PDFJS_ASSET_PREFIX):].replace("\\", "/")
    parts = tuple(part for part in relative.split("/") if part)
    if not parts or parts[0] not in _PDFJS_ALLOWED_ROOTS:
        return None
    candidate = (_PDFJS_ASSET_ROOT.joinpath(*parts)).resolve(strict=False)
    try:
        candidate.relative_to(_PDFJS_ASSET_ROOT.resolve(strict=False))
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@dataclass(frozen=True)
class UploadHostOption:
    host: str
    interface_name: str
    label: str
    is_virtual: bool
    priority: int


@dataclass(frozen=True)
class UploadedFile:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class MobileUploadSession:
    token: str
    batch_id: str
    host: str
    port: int
    base_url: str
    upload_url: str
    api_url: str
    expires_at: datetime
    session_dir: Path
    original_dir: Path
    manifest_path: Path


class MobileUploadServer:
    """Small HTTP server used by the desktop app for one LAN upload session."""

    def __init__(
        self,
        *,
        runtime_dir: Path = RUNTIME_DIR,
        db_path: Path | None = None,
        host: str | None = None,
        bind_host: str = "0.0.0.0",
        port: int = 0,
        ttl_seconds: int = 600,
        max_file_bytes: int = MAX_FILE_BYTES,
        max_total_bytes: int = MAX_TOTAL_BYTES,
        import_on_upload: bool = False,
        interface_name: str = "",
        network_priority: int = 50,
        network_virtual: bool = False,
        local_host_addresses: Iterable[str] | None = None,
    ):
        self.runtime_dir = Path(runtime_dir)
        self.db_path = Path(db_path) if db_path else None
        self.host = host or get_lan_ip()
        self.bind_host = bind_host
        self.port = port
        self.ttl_seconds = ttl_seconds
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.import_on_upload = import_on_upload
        self.interface_name = str(interface_name or "")
        self.network_priority = int(network_priority)
        self.network_virtual = bool(network_virtual)

        self.session: MobileUploadSession | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._files: list[dict] = []
        self._stats = {"accepted": 0, "duplicate": 0, "failed": 0, "imported": 0}
        self._session_expired_logged = False
        self._last_request_at: datetime | None = None
        self._last_lan_client_access_at: datetime | None = None
        self._lan_client_access_confirmed = False
        configured_addresses = local_host_addresses if local_host_addresses is not None else ()
        self._configured_local_host_addresses = {
            address
            for address in (_normalize_ipv4_address(item) for item in configured_addresses)
            if address
        }
        self._local_host_addresses = _collect_local_host_addresses(
            (*self._configured_local_host_addresses, self.host)
        )
        self._local_self_check = "pending"
        self._local_self_check_error = ""

    def start(self) -> MobileUploadSession:
        if self._httpd:
            return self.session  # type: ignore[return-value]
        self.refresh_local_host_addresses()
        _log.info(
            "[手机上传] selected network interface=%s public_host=%s bind_host=%s",
            self.interface_name or "<fallback>",
            _redact_host(self.host),
            self.bind_host,
        )
        token = secrets.token_urlsafe(18)
        now = datetime.now()
        batch_id = f"mobile_{now:%Y%m%d_%H%M%S}_{token[:6]}"
        session_dir = self.runtime_dir / "inbox" / "mobile_upload" / f"{now:%Y-%m-%d}" / batch_id
        original_dir = session_dir / "original"
        manifest_path = session_dir / "manifest.json"
        expires_at = now + timedelta(seconds=self.ttl_seconds)

        try:
            original_dir.mkdir(parents=True, exist_ok=True)
            handler = self._make_handler()
            self._httpd = ThreadingHTTPServer((self.bind_host, self.port), handler)
            actual_port = int(self._httpd.server_address[1])
            self.port = actual_port
            base_url = f"http://{self.host}:{actual_port}"
            self.session = MobileUploadSession(
                token=token,
                batch_id=batch_id,
                host=self.host,
                port=actual_port,
                base_url=base_url,
                upload_url=f"{base_url}/u/{token}",
                api_url=f"{base_url}/api/upload/{token}",
                expires_at=expires_at,
                session_dir=session_dir,
                original_dir=original_dir,
                manifest_path=manifest_path,
            )
            with self._lock:
                self._session_expired_logged = False
                self._last_request_at = None
                self._last_lan_client_access_at = None
                self._lan_client_access_confirmed = False
                self._local_self_check = "pending"
                self._local_self_check_error = ""
            self._write_manifest()

            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                name="InvoiceHubMobileUpload",
                daemon=True,
            )
            self._thread.start()
            _log.info(
                "[手机上传] server started bind=%s:%s public=%s:%s expires_at=%s token=<redacted>",
                self.bind_host,
                actual_port,
                _redact_host(self.host),
                actual_port,
                expires_at.isoformat(timespec="seconds"),
            )
            _log.info(
                "[手机上传] qr generated host=%s port=%s path=/u/<redacted>",
                _redact_host(self.host),
                actual_port,
            )
            return self.session
        except Exception as exc:
            _log.info(
                "[手机上传] server start failed exception_type=%s reason=%s",
                type(exc).__name__,
                _safe_log_reason(exc, token),
            )
            httpd = self._httpd
            self._httpd = None
            if httpd is not None:
                try:
                    httpd.server_close()
                except Exception:
                    pass
            self.session = None
            raise

    def stop(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        if httpd is not None:
            _log.info("[手机上传] server stop batch_id=<redacted>")

    def is_token_valid(self, token: str) -> bool:
        if not self.session or not self._httpd or token != self.session.token:
            return False
        now = datetime.now()
        if now > self.session.expires_at:
            if not self._session_expired_logged:
                self._session_expired_logged = True
                _log.info(
                    "[手机上传] session expired batch_id=<redacted> expires_at=%s",
                    self.session.expires_at.isoformat(timespec="seconds"),
                )
            return False
        return True

    def status(self) -> dict:
        with self._lock:
            return {
                **self._stats,
                "active": bool(self._httpd),
                "batch_id": self.session.batch_id if self.session else "",
                "upload_url": self.session.upload_url if self.session else "",
                "expires_at": self.session.expires_at.isoformat(timespec="seconds") if self.session else "",
                "interface_name": self.interface_name,
                "public_host": self.host,
                "bind_host": self.bind_host,
                "network_virtual": self.network_virtual,
                "network_priority": self.network_priority,
                "local_self_check": self._local_self_check,
                "local_self_check_error": self._local_self_check_error,
                "lan_client_access_confirmed": self._lan_client_access_confirmed,
                "last_request_at": self._last_request_at.isoformat(timespec="seconds") if self._last_request_at else "",
                "last_lan_client_access_at": self._last_lan_client_access_at.isoformat(timespec="seconds") if self._last_lan_client_access_at else "",
            }

    def refresh_local_host_addresses(self) -> set[str]:
        addresses = _collect_local_host_addresses(
            (*self._configured_local_host_addresses, self.host)
        )
        with self._lock:
            self._local_host_addresses = addresses
        return set(addresses)

    def set_network_metadata(
        self,
        *,
        interface_name: str = "",
        priority: int = 50,
        is_virtual: bool = False,
    ) -> None:
        self.interface_name = str(interface_name or "")
        self.network_priority = int(priority)
        self.network_virtual = bool(is_virtual)

    def run_local_self_check(self, timeout: float = 1.5) -> bool:
        session = self.session
        if session is None or self._httpd is None:
            self._local_self_check = "fail"
            self._local_self_check_error = "server_not_running"
            return False
        try:
            request = urllib_request.Request(
                session.upload_url,
                headers={"User-Agent": "InvoiceHub/LocalSelfCheck", "X-InvoiceHub-Self-Check": "1"},
            )
            with urllib_request.urlopen(request, timeout=timeout) as response:
                status = int(response.status)
            self._local_self_check = "pass" if status == 200 else "fail"
            self._local_self_check_error = "" if status == 200 else f"http_{status}"
            _log.info("[手机上传] local self-check result=%s status=%s", self._local_self_check, status)
        except urllib_error.HTTPError as exc:
            self._local_self_check = "fail"
            self._local_self_check_error = f"http_{exc.code}"
            _log.info("[手机上传] local self-check result=fail status=%s", exc.code)
        except Exception as exc:
            self._local_self_check = "fail"
            self._local_self_check_error = _safe_log_reason(exc, session.token)
            _log.info(
                "[手机上传] local self-check result=fail exception_type=%s reason=%s",
                type(exc).__name__,
                self._local_self_check_error,
            )
        return self._local_self_check == "pass"

    def _record_request(
        self,
        method: str,
        path: str,
        client: str,
        status: int,
        *,
        is_self_check: bool = False,
    ) -> None:
        now = datetime.now()
        safe_path = _redact_request_path(path)
        confirmation_log = False
        normalized_client = _normalize_ipv4_address(client)
        with self._lock:
            self._last_request_at = now
            valid_upload_page = (
                self.session is not None
                and _token_from_path(path, "/u/") == self.session.token
            )
            if (
                method == "GET"
                and valid_upload_page
                and status == 200
                and not is_self_check
                and bool(normalized_client)
                and normalized_client not in self._local_host_addresses
            ):
                confirmation_log = not self._lan_client_access_confirmed
                self._lan_client_access_confirmed = True
                self._last_lan_client_access_at = now
        _log.info(
            "[手机上传] request method=%s client=%s path=%s status=%s",
            method,
            _redact_host(client),
            safe_path,
            status,
        )
        if confirmation_log:
            _log.info(
                "[手机上传] LAN client access confirmed client=%s at=%s",
                _redact_host(client),
                now.strftime("%H:%M:%S"),
            )

    def _log_upload_result(self, result: dict) -> None:
        imported = result.get("imported", 0)
        if isinstance(imported, dict):
            imported = sum(int(imported.get(key, 0) or 0) for key in ("added", "conflicts", "pending_manual", "duplicates"))
        _log.info(
            "[手机上传] upload result accepted=%s duplicate=%s failed=%s imported=%s",
            int(result.get("accepted", 0) or 0),
            int(result.get("duplicate", 0) or 0),
            int(result.get("failed", 0) or 0),
            int(imported or 0),
        )

    def set_public_host(self, host: str) -> MobileUploadSession:
        host = (host or "").strip()
        if not host:
            raise ValueError("host is required")
        old_host = self.host
        self.host = host
        if not self.session:
            raise RuntimeError("mobile upload server has not been started")

        base_url = f"http://{host}:{self.session.port}"
        self.session = replace(
            self.session,
            host=host,
            base_url=base_url,
            upload_url=f"{base_url}/u/{self.session.token}",
            api_url=f"{base_url}/api/upload/{self.session.token}",
        )
        self.refresh_local_host_addresses()
        self._write_manifest()
        self._local_self_check = "pending"
        self._local_self_check_error = ""
        _log.info(
            "[手机上传] network changed old_public_host=%s new_public_host=%s bind_host=%s",
            _redact_host(old_host),
            _redact_host(host),
            self.bind_host,
        )
        return self.session

    def save_uploads(self, files: Iterable[UploadedFile]) -> dict:
        if not self.session:
            raise RuntimeError("mobile upload server has not been started")

        accepted_now = 0
        duplicate_now = 0
        failed_now = 0
        total_bytes = 0
        known_hashes = self._known_hashes()
        accepted_paths: list[Path] = []
        duplicate_records_by_hash: dict[str, list[dict]] = {}

        with self._lock:
            for item in files:
                original_name = item.filename or "upload.bin"
                content = item.content or b""
                total_bytes += len(content)
                record = {
                    "source": "mobile_qr",
                    "batch_id": self.session.batch_id,
                    "original_filename": original_name,
                    "stored_path": "",
                    "sha256": "",
                    "size_bytes": len(content),
                    "mime_type": item.content_type or mimetypes.guess_type(original_name)[0] or "",
                    "status": "failed",
                    "reason": "",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }

                ext = Path(original_name).suffix.lower()
                if ext not in ALLOWED_UPLOAD_EXTS:
                    record["reason"] = "unsupported_file_type"
                    failed_now += 1
                    self._files.append(record)
                    continue
                if len(content) > self.max_file_bytes:
                    record["reason"] = "file_too_large"
                    failed_now += 1
                    self._files.append(record)
                    continue
                if total_bytes > self.max_total_bytes:
                    record["reason"] = "total_upload_too_large"
                    failed_now += 1
                    self._files.append(record)
                    continue

                digest = hashlib.sha256(content).hexdigest()
                record["sha256"] = digest
                if digest in known_hashes:
                    record["status"] = "duplicate"
                    record["reason"] = "sha256_already_uploaded"
                    duplicate_now += 1
                    duplicate_records_by_hash.setdefault(digest, []).append(record)
                    self._files.append(record)
                    continue

                dest = _unique_path(self.session.original_dir / _safe_upload_name(original_name))
                dest.write_bytes(content)
                record["stored_path"] = _runtime_relative(dest, self.runtime_dir)
                record["status"] = "accepted"
                accepted_now += 1
                known_hashes.add(digest)
                accepted_paths.append(dest)
                self._files.append(record)

            if duplicate_records_by_hash and self.import_on_upload and self.db_path:
                restored_hashes = self._restore_deleted_invoices_by_hashes(
                    set(duplicate_records_by_hash)
                )
                for digest in restored_hashes:
                    for record in duplicate_records_by_hash.get(digest, []):
                        record["reason"] = "sha256_already_uploaded_restored_deleted_record"

            self._stats["accepted"] += accepted_now
            self._stats["duplicate"] += duplicate_now
            self._stats["failed"] += failed_now
            self._write_manifest()

        imported = 0
        if accepted_paths and self.import_on_upload and self.db_path:
            imported = self._import_accepted_files(accepted_paths)
            with self._lock:
                imported_count = (
                    imported.get("added", 0) +
                    imported.get("conflicts", 0) +
                    imported.get("pending_manual", 0) +
                    imported.get("duplicates", 0)
                ) if isinstance(imported, dict) else imported
                self._stats["imported"] += imported_count
                self._write_manifest()

        result = {
            "accepted": accepted_now,
            "duplicate": duplicate_now,
            "failed": failed_now,
            "imported": imported,
            "batch_id": self.session.batch_id,
        }
        self._log_upload_result(result)
        return result

    def _restore_deleted_invoices_by_hashes(self, file_hashes: set[str]) -> set[str]:
        if not self.db_path or not file_hashes:
            return set()
        from .db import InvoiceDB

        with InvoiceDB(self.db_path) as db:
            return db.restore_deleted_invoices_by_file_hashes(file_hashes)

    def _import_accepted_files(self, accepted_paths: Iterable[Path]) -> int:
        if not self.session or not self.db_path:
            return 0
        from .services import import_local_directory
        from .db import InvoiceDB

        imported = import_local_directory(
            self.session.original_dir,
            self.db_path,
            file_paths=accepted_paths,
        )
        hash_to_subject = {
            item["sha256"]: f"手机上传: {item['original_filename']}"
            for item in self._files
            if item.get("status") == "accepted" and item.get("sha256")
        }
        with InvoiceDB(self.db_path) as db:
            db.update_invoice_source_by_hashes(hash_to_subject, "mobile_qr")
        return imported

    def _known_hashes(self) -> set[str]:
        hashes = {item.get("sha256", "") for item in self._files if item.get("sha256") and item.get("status") == "accepted"}
        upload_root = self.runtime_dir / "inbox" / "mobile_upload"
        if upload_root.exists():
            for manifest in upload_root.rglob("manifest.json"):
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for item in data.get("files", []):
                    if item.get("status") == "accepted" and item.get("sha256"):
                        hashes.add(item["sha256"])
        return hashes

    def _write_manifest(self) -> None:
        if not self.session:
            return
        payload = {
            "source": "mobile_qr",
            "batch_id": self.session.batch_id,
            "token_expires_at": self.session.expires_at.isoformat(timespec="seconds"),
            "session_dir": _runtime_relative(self.session.session_dir, self.runtime_dir),
            "stats": dict(self._stats),
            "files": list(self._files),
        }
        self.session.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _make_handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def _begin_request(self):
                parsed = urlparse(self.path)
                self._request_path = parsed.path or "/"
                self._request_self_check = self.headers.get("X-InvoiceHub-Self-Check") == "1"
                self._request_logged = False
                return parsed

            def _log_response(self, status: int):
                if self._request_logged:
                    return
                self._request_logged = True
                owner._record_request(
                    self.command,
                    getattr(self, "_request_path", urlparse(self.path).path),
                    self.client_address[0],
                    status,
                    is_self_check=bool(getattr(self, "_request_self_check", False)),
                )

            def do_GET(self):
                parsed = self._begin_request()
                asset = _resolve_pdfjs_asset(parsed.path)
                if asset is not None:
                    self._send_asset(200, asset)
                    return

                token = _token_from_path(parsed.path, "/u/")
                if token:
                    if not owner.is_token_valid(token):
                        self._send_text(403, "Upload link expired or invalid.")
                        return
                    self._send_html(200, _upload_page(owner.session))  # type: ignore[arg-type]
                    return

                status_token = _token_from_path(parsed.path, "/api/status/")
                if status_token:
                    if not owner.is_token_valid(status_token):
                        self._send_text(403, "Upload link expired or invalid.")
                        return
                    self._send_json(200, owner.status())
                    return

                self._send_text(404, "Not found.")

            def do_POST(self):
                parsed = self._begin_request()
                token = _token_from_path(parsed.path, "/api/upload/")
                if not token or not owner.is_token_valid(token):
                    self._send_text(403, "Upload link expired or invalid.")
                    return

                try:
                    content_length = int(self.headers.get("Content-Length") or "0")
                except ValueError:
                    self._send_text(400, "Invalid content length.")
                    return
                if content_length > owner.max_total_bytes:
                    self._send_text(413, "Upload is too large.")
                    return
                body = self.rfile.read(content_length)
                files = _parse_multipart_upload(body, self.headers.get("Content-Type", ""))
                try:
                    result = owner.save_uploads(files)
                except Exception:
                    _log.info("[手机上传] upload processing failed exception_type=server_error")
                    self._send_text(500, "Upload processing failed.")
                    return
                self._send_json(200, result)

            def _send_html(self, status: int, body: str):
                self._log_response(status)
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def _send_json(self, status: int, payload: dict):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._log_response(status)
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def _send_text(self, status: int, body: str):
                self._log_response(status)
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def _send_asset(self, status: int, path: Path):
                try:
                    body = path.read_bytes()
                except OSError:
                    self._send_text(404, "Not found.")
                    return
                self._log_response(status)
                self.send_response(status)
                self.send_header(
                    "Content-Type",
                    _PDFJS_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                )
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


_VIRTUAL_ADAPTER_MARKERS = (
    "docker",
    "wsl",
    "hyper-v",
    "hyperv",
    "vethernet",
    "virtualbox",
    "vmware",
    "tailscale",
    "vpn",
)


def _is_loopback_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(str(host or "")).is_loopback
    except ValueError:
        return False


def _is_usable_ipv4(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(str(host))
    except ValueError:
        return False
    return addr.version == 4 and not addr.is_loopback and not addr.is_link_local and not addr.is_unspecified


def _is_virtual_adapter(interface_name: str) -> bool:
    name = (interface_name or "").lower()
    return any(marker in name for marker in _VIRTUAL_ADAPTER_MARKERS)


def _host_priority(interface_name: str, host: str) -> int:
    name = (interface_name or "").lower()
    priority = 50
    if any(marker in name for marker in ("wi-fi", "wifi", "wlan", "wireless")):
        priority = 0
    elif "ethernet" in name or "以太网" in name:
        priority = 10
    if _is_virtual_adapter(interface_name):
        priority += 1000
    return priority


def build_upload_host_options(raw_addresses: Iterable[tuple[str, str]]) -> list[UploadHostOption]:
    seen: set[str] = set()
    options: list[UploadHostOption] = []
    for interface_name, host in raw_addresses:
        host = str(host or "").strip()
        if not host or host in seen or not _is_usable_ipv4(host):
            continue
        seen.add(host)
        is_virtual = _is_virtual_adapter(interface_name)
        priority = _host_priority(interface_name, host)
        label_prefix = interface_name or "Network"
        virtual_suffix = " (虚拟网卡)" if is_virtual else ""
        options.append(UploadHostOption(
            host=host,
            interface_name=interface_name,
            label=f"{label_prefix} - {host}{virtual_suffix}",
            is_virtual=is_virtual,
            priority=priority,
        ))
    options.sort(key=lambda item: (item.priority, item.host))
    return options


def log_upload_host_candidates(options: Iterable[UploadHostOption]) -> None:
    for option in options:
        _log.info(
            "[手机上传] network candidate interface=%s host=%s virtual=%s priority=%s",
            option.interface_name or "<unnamed>",
            _redact_host(option.host),
            str(option.is_virtual).lower(),
            option.priority,
        )


def enumerate_upload_hosts() -> list[UploadHostOption]:
    raw: list[tuple[str, str]] = []
    try:
        from PySide6.QtNetwork import QNetworkInterface

        for iface in QNetworkInterface.allInterfaces():
            name = iface.humanReadableName() or iface.name() or ""
            for entry in iface.addressEntries():
                raw.append((name, entry.ip().toString()))
    except Exception:
        raw = []

    if not raw:
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                raw.append((hostname, info[4][0]))
        except OSError:
            raw = []

    return build_upload_host_options(raw)


def _normalize_ipv4_address(value: object) -> str:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return ""
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return str(address) if address.version == 4 else ""


def _collect_local_host_addresses(extra: Iterable[str] = ()) -> set[str]:
    addresses = {"127.0.0.1"}
    for value in extra:
        normalized = _normalize_ipv4_address(value)
        if normalized:
            addresses.add(normalized)
    try:
        addresses.update(
            normalized
            for option in enumerate_upload_hosts()
            if (normalized := _normalize_ipv4_address(option.host))
        )
    except Exception:
        pass
    return addresses


def get_lan_ip() -> str:
    options = enumerate_upload_hosts()
    if options:
        return options[0].host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


def _token_from_path(path: str, prefix: str) -> str:
    if path.startswith(prefix):
        return path[len(prefix):].strip("/")
    return ""


def _safe_upload_name(name: str, max_len: int = 100) -> str:
    base = Path(name.replace("\\", "/")).name or "upload"
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in base)
    safe = safe.strip("._") or "upload"
    if len(safe) > max_len:
        stem = Path(safe).stem[: max_len - len(Path(safe).suffix)]
        safe = f"{stem}{Path(safe).suffix}"
    return safe


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{datetime.now():%H%M%S%f}{path.suffix}")


def _runtime_relative(path: Path, runtime_dir: Path) -> str:
    try:
        return os.path.relpath(str(path), runtime_dir)
    except ValueError:
        return str(path)


def _parse_multipart_upload(body: bytes, content_type: str) -> list[UploadedFile]:
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        return []
    boundary = match.group("boundary").strip('"').encode("utf-8")
    files: list[UploadedFile] = []
    for raw_part in body.split(b"--" + boundary):
        part = raw_part.strip()
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].strip()
        if b"\r\n\r\n" not in part:
            continue
        header_blob, content = part.split(b"\r\n\r\n", 1)
        content = content.rstrip(b"\r\n")
        headers = header_blob.decode("utf-8", errors="replace")
        filename_match = re.search(r'filename="(?P<filename>[^"]*)"', headers)
        if not filename_match:
            continue
        type_match = re.search(r"Content-Type:\s*(?P<type>[^\r\n]+)", headers, re.IGNORECASE)
        files.append(UploadedFile(
            filename=filename_match.group("filename"),
            content=content,
            content_type=type_match.group("type").strip() if type_match else "application/octet-stream",
        ))
    return files


def _upload_page(session: MobileUploadSession) -> str:
    remaining_seconds = max(0, int((session.expires_at - datetime.now()).total_seconds()))
    remaining_minutes = max(1, (remaining_seconds + 59) // 60)
    expiry_hint = f"链接约 {remaining_minutes} 分钟后失效"
    page = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Invoice Hub</title>
  <style>
    :root { color-scheme: light; --blue:#2563eb; --blue-dark:#1d4ed8; --ink:#172033; --muted:#64748b; --line:#e2e8f0; --surface:#fff; --canvas:#f4f7fb; --danger:#b91c1c; --success:#166534; }
    *, *::before, *::after { box-sizing:border-box; }
    html { min-width:320px; background:var(--canvas); }
    body { margin:0; min-width:320px; min-height:100vh; overflow-x:hidden; background:var(--canvas); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB",sans-serif; line-height:1.45; padding:16px 14px calc(24px + env(safe-area-inset-bottom)); }
    body.modal-open { overflow:hidden; }
    button, label { touch-action:manipulation; }
    button:focus-visible, label:focus-within { outline:3px solid #93c5fd; outline-offset:2px; }
    main { width:100%; max-width:560px; margin:0 auto; padding-bottom:4px; }
    .page-header { margin:2px 2px 14px; }
    h1 { margin:0; font-size:24px; line-height:1.2; letter-spacing:-.02em; }
    .host-line { margin-top:5px; color:var(--muted); font-size:14px; overflow-wrap:anywhere; }
    .host-line strong { color:#334155; font-weight:650; }
    .session-meta { display:flex; flex-wrap:wrap; gap:5px 12px; margin-top:9px; color:#94a3b8; font-size:11px; }
    .surface { margin-bottom:12px; padding:14px; background:var(--surface); border:1px solid var(--line); border-radius:14px; box-shadow:0 2px 8px rgba(15,23,42,.035); }
    h2 { margin:0; font-size:16px; line-height:1.3; }
    .section-note { margin:5px 0 11px; color:var(--muted); font-size:12px; }

    .wechat-tip { display:none; margin:0 0 12px; padding:9px 11px; color:#854d0e; background:#fffbeb; border:1px solid #fde68a; border-radius:10px; cursor:pointer; text-align:left; }
    .wechat-tip.is-visible { display:block; }
    .wechat-summary { display:flex; align-items:center; justify-content:space-between; gap:8px; font-size:13px; font-weight:650; line-height:1.35; }
    .wechat-summary .arrow { flex:0 0 auto; font-size:19px; line-height:1; }
    .wechat-details { margin-top:7px; padding-top:7px; border-top:1px solid #fcd34d; font-size:12px; font-weight:400; line-height:1.55; }

    .source-actions { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }
    .source-action { position:relative; display:flex; min-width:0; min-height:54px; flex-direction:column; align-items:center; justify-content:center; gap:2px; padding:6px 3px; color:#1e3a8a; background:#eff6ff; border:1px solid #bfdbfe; border-radius:10px; cursor:pointer; text-align:center; }
    .source-action:active { background:#dbeafe; border-color:#93c5fd; }
    .source-action input[type=file] { position:absolute; width:1px; height:1px; opacity:0; pointer-events:none; }
    .entry-icon { display:inline-flex; flex:0 0 auto; width:22px; height:22px; align-items:center; justify-content:center; border:1px solid #93c5fd; border-radius:6px; color:#1d4ed8; background:#fff; font-size:8px; font-weight:800; letter-spacing:.02em; }
    .entry-title { min-width:0; max-width:100%; font-size:13px; font-weight:700; line-height:1.15; overflow-wrap:anywhere; }
    .source-note { margin:10px 1px 0; color:var(--muted); font-size:11px; text-align:center; }

    .pending-section[hidden], .upload-bar[hidden], #result[hidden], .preview-modal[hidden], .wechat-details[hidden] { display:none; }
    .pending-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:8px; }
    .clear-button { min-height:40px; padding:7px 10px; color:#1d4ed8; background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; font-size:12px; cursor:pointer; }
    .selection-hint { margin:-1px 0 9px; color:var(--muted); font-size:12px; }
    .file-list { display:grid; gap:8px; }
    .file-card { display:grid; grid-template-columns:76px minmax(0,1fr) auto; gap:10px; align-items:center; min-width:0; padding:9px; border:1px solid #e2e8f0; border-radius:11px; background:#fbfdff; }
    .file-preview { display:flex; width:76px; height:76px; align-items:center; justify-content:center; overflow:hidden; padding:0; color:#1d4ed8; background:#eff6ff; border:1px solid #bfdbfe; border-radius:9px; cursor:pointer; }
    .file-preview:disabled { cursor:wait; opacity:.78; }
    .file-preview img { display:block; width:100%; height:100%; object-fit:cover; }
    .file-preview .pdf-thumb { width:100%; height:100%; object-fit:contain; background:#fff; }
    .file-preview-label { padding:4px; color:#475569; font-size:11px; font-weight:700; line-height:1.2; }
    .file-preview-error { padding:4px; color:var(--danger); font-size:11px; line-height:1.25; }
    .file-meta { min-width:0; }
    .file-detail { color:#475569; font-size:12px; line-height:1.35; overflow-wrap:anywhere; }
    .file-name { display:-webkit-box; overflow:hidden; color:#1e293b; font-size:13px; font-weight:700; line-height:1.35; overflow-wrap:anywhere; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
    .file-note { margin-top:4px; color:#b45309; font-size:11px; line-height:1.35; overflow-wrap:anywhere; }
    .remove-button, .review-button { min-height:40px; padding:7px 9px; border-radius:8px; font-size:12px; cursor:pointer; white-space:nowrap; }
    .remove-button { color:#1d4ed8; background:#fff; border:1px solid #cbd5e1; }
    .review-button { margin-top:6px; color:#1d4ed8; background:#eff6ff; border:1px solid #bfdbfe; }
    .remove-button:active, .review-button:active, .clear-button:active { background:#dbeafe; }

    .upload-bar { position:sticky; bottom:0; z-index:5; display:flex; align-items:center; gap:10px; min-height:64px; margin:0 auto 12px; padding:10px 10px calc(10px + env(safe-area-inset-bottom)); background:rgba(255,255,255,.96); border:1px solid #cbd5e1; border-radius:13px; box-shadow:0 -5px 18px rgba(15,23,42,.10); backdrop-filter:blur(8px); }
    .upload-summary { min-width:0; flex:1; color:#334155; font-size:13px; font-weight:650; overflow-wrap:anywhere; }
    .btn-upload { flex:0 0 auto; min-width:92px; min-height:44px; padding:9px 14px; color:#fff; background:var(--blue); border:0; border-radius:9px; font-size:15px; font-weight:750; cursor:pointer; }
    .btn-upload:active:not(:disabled) { background:var(--blue-dark); }
    .btn-upload:disabled { color:#dbeafe; background:#93c5fd; cursor:not-allowed; }

    #result { margin-bottom:12px; padding:11px 13px; white-space:pre-wrap; border-radius:10px; font-size:13px; line-height:1.5; }
    #result.uploading { color:#1d4ed8; background:#eff6ff; border:1px solid #bfdbfe; }
    #result.result-success { color:var(--success); background:#f0fdf4; border:1px solid #bbf7d0; }
    #result.result-error { color:var(--danger); background:#fef2f2; border:1px solid #fecaca; }
    .tips { color:#64748b; font-size:12px; line-height:1.65; }
    .tips summary { color:#475569; cursor:pointer; font-weight:650; }
    .tips ul { margin:8px 0 0 18px; }
    .tips li { margin-bottom:4px; }

    .preview-modal { position:fixed; inset:0; z-index:20; display:flex; align-items:stretch; justify-content:center; padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom); background:rgba(15,23,42,.72); }
    .preview-sheet { display:flex; width:min(100%,620px); min-height:100%; flex-direction:column; background:#0f172a; color:#f8fafc; }
    .preview-header { display:flex; min-height:58px; align-items:center; gap:9px; padding:8px 12px; border-bottom:1px solid #334155; }
    .preview-back { min-height:42px; padding:7px 8px; color:#dbeafe; background:transparent; border:0; font-size:15px; cursor:pointer; }
    .preview-title { min-width:0; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; font-weight:650; }
    .preview-page-indicator { flex:0 0 auto; color:#cbd5e1; font-size:12px; }
    .preview-stage { position:relative; display:flex; min-height:0; flex:1; align-items:center; justify-content:center; overflow:auto; padding:14px 10px; }
    .preview-stage canvas { display:block; max-width:100%; height:auto; background:#fff; box-shadow:0 3px 12px rgba(0,0,0,.25); }
    .preview-stage img { display:block; max-width:100%; max-height:100%; object-fit:contain; }
    .preview-loading, .preview-error { padding:20px; color:#cbd5e1; text-align:center; font-size:13px; }
    .preview-error { color:#fecaca; }
    .preview-footer { display:flex; gap:10px; padding:10px 12px calc(10px + env(safe-area-inset-bottom)); border-top:1px solid #334155; }
    .preview-nav { flex:1; min-height:44px; color:#e0f2fe; background:#1e40af; border:1px solid #60a5fa; border-radius:9px; font-size:14px; cursor:pointer; }
    .preview-nav:disabled { color:#64748b; background:#1e293b; border-color:#334155; cursor:not-allowed; }
    @media (max-width:360px) {
      body { padding-left:10px; padding-right:10px; }
      .surface { padding:12px; }
      .file-card { grid-template-columns:64px minmax(0,1fr) auto; gap:7px; padding:8px; }
      .file-preview { width:64px; height:64px; }
      .remove-button, .review-button { padding-left:7px; padding-right:7px; }
      .upload-summary { font-size:12px; }
      .btn-upload { min-width:82px; padding-left:10px; padding-right:10px; }
    }
  </style>
</head>
<body data-upload-state="EMPTY">
<main>
  <header class="page-header">
    <h1>Invoice Hub</h1>
    <div class="host-line">上传到电脑 · <strong>__HOST__</strong></div>
    <div class="session-meta"><span>__EXPIRY_HINT__</span></div>
  </header>

  <div class="wechat-tip" id="wechatTip" role="button" tabindex="0" aria-expanded="false">
    <div class="wechat-summary"><span>微信内 PDF 选择受限，建议在浏览器打开</span><span class="arrow" aria-hidden="true">›</span></div>
    <div class="wechat-details" id="wechatDetails" hidden>点击微信右上角「⋯」，选择「在浏览器打开」。图片/拍照可以继续在微信内使用；需要选择 PDF/OFD 时请使用系统浏览器。</div>
  </div>

  <section class="surface source-section" aria-labelledby="sourceTitle">
    <h2 id="sourceTitle">添加材料</h2>
    <p class="section-note">选择来源后，文件会先留在手机本地，确认无误再上传。</p>
    <div class="source-actions">
      <label class="source-action upload-entry" id="entryFile" aria-label="选择 PDF/OFD/文件">
        <span class="entry-icon" aria-hidden="true">文件</span><span class="entry-title">选择文件</span>
        <input id="inputFile" type="file" multiple accept=".pdf,.ofd,application/pdf,application/octet-stream">
      </label>
      <label class="source-action upload-entry" id="entryGallery" aria-label="选择相册图片">
        <span class="entry-icon" aria-hidden="true">相册</span><span class="entry-title">相册</span>
        <input id="inputGallery" type="file" multiple accept="image/jpeg,image/png,image/heic,image/*">
      </label>
      <label class="source-action upload-entry" id="entryCamera" aria-label="拍照上传">
        <span class="entry-icon" aria-hidden="true">拍照</span><span class="entry-title">拍照</span>
        <input id="inputCamera" type="file" accept="image/*" capture="environment">
      </label>
    </div>
    <p class="source-note">支持 PDF、OFD、JPG、JPEG、PNG、HEIC</p>
  </section>

  <section class="surface pending-section" id="pendingSection" hidden aria-labelledby="pendingTitle">
    <div class="pending-heading">
      <h2 id="pendingTitle">待上传 · 0</h2>
      <button class="clear-button" id="btnClear" type="button">清空重选</button>
    </div>
    <p class="selection-hint" id="selectionHint">文件仍保留在手机本地。</p>
    <div class="file-list" id="fileListItems"></div>
  </section>

  <div id="result" hidden role="status" aria-live="polite"></div>

  <div class="upload-bar" id="uploadBar" hidden>
    <span class="upload-summary" id="uploadSummary">已选 0 个</span>
    <button class="btn-upload" id="btnUpload" type="button" disabled>上传</button>
  </div>

  <details class="surface tips">
    <summary>使用提示</summary>
    <ul>
      <li>PDF 会在手机本地读取页数并生成第一页预览，不会在点击上传前发送到电脑。</li>
      <li>PDF 预览默认适应屏幕宽度，可使用浏览器/系统手势放大检查金额、号码和税号。</li>
      <li>OFD 手机浏览器暂不支持内容预览，上传后可在 Invoice Hub 中查看。</li>
      <li>如果发票在微信聊天中，请先保存到手机「文件/下载」，或在微信内点击「在浏览器打开」。</li>
      <li>手机和电脑需要在同一 Wi-Fi / 局域网；打不开时请检查 Windows 防火墙专用网络权限。</li>
      <li>请勿上传与报销无关的私人照片。</li>
    </ul>
  </details>
</main>

<div class="preview-modal" id="previewModal" hidden>
  <div class="preview-sheet" role="dialog" aria-modal="true" aria-labelledby="previewTitle">
    <header class="preview-header">
      <button class="preview-back" id="previewBack" type="button">‹ 返回</button>
      <span class="preview-title" id="previewTitle">文件预览</span>
      <span class="preview-page-indicator" id="previewPageIndicator">1 / 1</span>
    </header>
    <div class="preview-stage" id="previewStage">
      <div class="preview-loading" id="previewLoading" hidden>正在生成预览…</div>
      <div class="preview-error" id="previewError" hidden>无法预览，但仍可移除/重新选择。</div>
      <canvas id="previewCanvas" hidden></canvas>
      <img id="previewImage" alt="" hidden>
    </div>
    <footer class="preview-footer" id="previewFooter">
      <button class="preview-nav" id="previewPrev" type="button">上一页</button>
      <button class="preview-nav" id="previewNext" type="button">下一页</button>
    </footer>
  </div>
</div>

<script type="module">
const PDFJS_BASE = "/assets/pdfjs/";
const PDFJS_CMAP_URL = PDFJS_BASE + "cmaps/";
const PDFJS_FONT_URL = PDFJS_BASE + "standard_fonts/";
const UPLOAD_URL = "/api/upload/__TOKEN__";
const STATES = Object.freeze(["EMPTY", "SELECTED", "PREVIEWING", "UPLOADING", "SUCCESS", "PARTIAL", "FAILURE"]);

const inputFile = document.getElementById("inputFile");
const inputGallery = document.getElementById("inputGallery");
const inputCamera = document.getElementById("inputCamera");
const wechatTip = document.getElementById("wechatTip");
const wechatDetails = document.getElementById("wechatDetails");
const pendingSection = document.getElementById("pendingSection");
const pendingTitle = document.getElementById("pendingTitle");
const fileListItems = document.getElementById("fileListItems");
const selectionHint = document.getElementById("selectionHint");
const btnClear = document.getElementById("btnClear");
const uploadBar = document.getElementById("uploadBar");
const uploadSummary = document.getElementById("uploadSummary");
const btnUpload = document.getElementById("btnUpload");
const result = document.getElementById("result");
const previewModal = document.getElementById("previewModal");
const previewBack = document.getElementById("previewBack");
const previewTitle = document.getElementById("previewTitle");
const previewPageIndicator = document.getElementById("previewPageIndicator");
const previewStage = document.getElementById("previewStage");
const previewLoading = document.getElementById("previewLoading");
const previewError = document.getElementById("previewError");
const previewCanvas = document.getElementById("previewCanvas");
const previewImage = document.getElementById("previewImage");
const previewFooter = document.getElementById("previewFooter");
const previewPrev = document.getElementById("previewPrev");
const previewNext = document.getElementById("previewNext");

let uploadState = "EMPTY";
let pendingFiles = [];
let isUploading = false;
let pdfJsPromise = null;
let activePreview = null;
let activePreviewPage = 1;
let renderSerial = 0;

function setState(next) {
  if (!STATES.includes(next)) throw new Error("Unknown upload state");
  uploadState = next;
  document.body.dataset.uploadState = next;
}

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function fileKind(file) {
  const name = (file.name || "").toLowerCase();
  if (name.endsWith(".pdf") || file.type === "application/pdf") return "PDF";
  if (name.endsWith(".ofd")) return "OFD";
  if ((file.type || "").startsWith("image/")) return "图片";
  return "文件";
}

function fileKey(file) {
  return [file.name || "", file.size || 0, file.lastModified || 0, file.type || ""].join("\u0000");
}

function displayFileName(name) {
  const value = name || "未命名文件";
  const dot = value.lastIndexOf(".");
  const extension = dot > 0 ? value.slice(dot) : "";
  if (value.length <= 36) return value;
  const stem = extension ? value.slice(0, -extension.length) : value;
  const headLength = Math.max(8, 36 - extension.length - 1);
  return stem.slice(0, headLength) + "…" + extension;
}

function setResult(kind, message) {
  result.hidden = false;
  result.className = kind;
  result.textContent = message;
}

function clearResult() {
  result.hidden = true;
  result.textContent = "";
  result.className = "";
}

function hasPreviewBlocker() {
  return pendingFiles.some((record) => record.previewState === "loading" || record.previewState === "error");
}

function canUpload() {
  return pendingFiles.length > 0 && !isUploading && !hasPreviewBlocker();
}

function destroyRecord(record) {
  if (record.imageUrl) URL.revokeObjectURL(record.imageUrl);
  if (record.pdfDocument && record.pdfDocument.destroy) {
    try { record.pdfDocument.destroy(); } catch (_) { /* already released */ }
  }
}

function updateSelectionUi() {
  const count = pendingFiles.length;
  pendingSection.hidden = count === 0;
  uploadBar.hidden = count === 0;
  if (count === 0) {
    btnUpload.disabled = true;
    return;
  }
  const totalBytes = pendingFiles.reduce((sum, record) => sum + record.file.size, 0);
  pendingTitle.textContent = "待上传 · " + count;
  uploadSummary.textContent = "已选 " + count + " 个 · " + formatBytes(totalBytes);
  btnUpload.textContent = count > 1 ? "上传 " + count + " 个" : "上传";
  btnUpload.disabled = !canUpload();
  if (hasPreviewBlocker()) {
    selectionHint.textContent = pendingFiles.some((record) => record.previewState === "error")
      ? "有 PDF 无法预览，请移除后重新选择；预览失败不会静默上传。"
      : "正在生成 PDF 首页预览，完成内容确认后才可上传。";
  } else {
    selectionHint.textContent = "文件仍保留在手机本地；点击缩略图可查看完整内容。";
  }
}

function makePreviewButton(record) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "file-preview";
  button.setAttribute("aria-label", "预览 " + (record.file.name || "文件"));
  if (record.kind === "图片" && record.imageUrl) {
    const image = document.createElement("img");
    image.src = record.imageUrl;
    image.alt = "图片预览：" + (record.file.name || "文件");
    button.appendChild(image);
  } else if (record.kind === "PDF" && record.thumbnailUrl) {
    const image = document.createElement("img");
    image.className = "pdf-thumb";
    image.src = record.thumbnailUrl;
    image.alt = "PDF 第一页预览：" + (record.file.name || "文件");
    button.appendChild(image);
  } else if (record.previewState === "error") {
    const label = document.createElement("span");
    label.className = "file-preview-error";
    label.textContent = "无法预览";
    button.appendChild(label);
  } else {
    const label = document.createElement("span");
    label.className = "file-preview-label";
    label.textContent = record.previewState === "loading" ? "读取中…" : record.kind;
    button.appendChild(label);
  }
  button.disabled = record.previewState === "loading";
  if (record.kind !== "OFD") {
    button.addEventListener("click", () => openPreview(record));
  } else {
    button.disabled = true;
    button.setAttribute("aria-label", "OFD 暂不支持手机预览");
  }
  return button;
}

function renderFileList() {
  fileListItems.replaceChildren();
  pendingFiles.forEach((record, index) => {
    const card = document.createElement("article");
    card.className = "file-card";
    card.dataset.fileKind = record.kind;
    const preview = makePreviewButton(record);
    const meta = document.createElement("div");
    meta.className = "file-meta";
    const detail = document.createElement("div");
    detail.className = "file-detail";
    let detailText = record.kind + " · " + formatBytes(record.file.size);
    if (record.kind === "PDF") {
      detailText = record.pageCount ? "PDF · " + record.pageCount + " 页 · " + formatBytes(record.file.size) : "PDF · 正在读取页数 · " + formatBytes(record.file.size);
    }
    detail.textContent = detailText;
    const name = document.createElement("div");
    name.className = "file-name";
    const fullName = record.file.name || "未命名文件";
    name.textContent = displayFileName(fullName);
    name.title = fullName;
    name.setAttribute("aria-label", fullName);
    meta.appendChild(detail);
    meta.appendChild(name);
    if (record.kind === "OFD") {
      const note = document.createElement("div");
      note.className = "file-note";
      note.textContent = "手机浏览器暂不支持内容预览，上传后可在 Invoice Hub 中查看。";
      meta.appendChild(note);
    } else if (record.kind === "PDF" && record.previewState === "error") {
      const note = document.createElement("div");
      note.className = "file-note";
      note.textContent = "无法预览，但仍可移除/重新选择。";
      meta.appendChild(note);
    }
    if (record.kind === "PDF" && record.previewState === "ready") {
      const review = document.createElement("button");
      review.type = "button";
      review.className = "review-button";
      review.textContent = "查看 PDF";
      review.addEventListener("click", () => openPreview(record));
      meta.appendChild(review);
    } else if (record.kind === "图片") {
      const review = document.createElement("button");
      review.type = "button";
      review.className = "review-button";
      review.textContent = "查看图片";
      review.addEventListener("click", () => openPreview(record));
      meta.appendChild(review);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-button";
    remove.textContent = "移除";
    remove.setAttribute("aria-label", "移除 " + (record.file.name || "文件"));
    remove.addEventListener("click", () => removeFile(index));
    card.appendChild(preview);
    card.appendChild(meta);
    card.appendChild(remove);
    fileListItems.appendChild(card);
  });
  updateSelectionUi();
}

async function getPdfJs() {
  if (!pdfJsPromise) {
    pdfJsPromise = import(PDFJS_BASE + "pdf.min.mjs").then((pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_BASE + "pdf.worker.min.mjs";
      return pdfjs;
    });
  }
  return pdfJsPromise;
}

async function preparePdf(record) {
  record.previewState = "loading";
  renderFileList();
  try {
    const pdfjs = await getPdfJs();
    const loadingTask = pdfjs.getDocument({
      data: await record.file.arrayBuffer(),
      cMapUrl: PDFJS_CMAP_URL,
      cMapPacked: true,
      standardFontDataUrl: PDFJS_FONT_URL,
    });
    record.pdfDocument = await loadingTask.promise;
    record.pageCount = record.pdfDocument.numPages;
    const page = await record.pdfDocument.getPage(1);
    const viewport = page.getViewport({ scale: 1 });
    const scale = Math.min(1, 86 / Math.max(viewport.width, 1));
    const canvas = document.createElement("canvas");
    const thumbViewport = page.getViewport({ scale });
    canvas.width = Math.ceil(thumbViewport.width);
    canvas.height = Math.ceil(thumbViewport.height);
    await page.render({ canvasContext: canvas.getContext("2d"), viewport: thumbViewport }).promise;
    record.thumbnailUrl = canvas.toDataURL("image/jpeg", .82);
    record.previewState = "ready";
  } catch (error) {
    record.previewState = "error";
    record.previewError = error instanceof Error ? error.message : "PDF preview failed";
  }
  renderFileList();
}

function collectFiles(input) {
  const incoming = Array.from(input.files || []);
  const newRecords = [];
  incoming.forEach((file) => {
    const key = fileKey(file);
    if (!pendingFiles.some((record) => record.key === key)) {
      const kind = fileKind(file);
      const record = {
        file,
        key,
        kind,
        previewState: kind === "PDF" ? "loading" : "ready",
        pageCount: kind === "图片" ? 1 : null,
        imageUrl: kind === "图片" ? URL.createObjectURL(file) : "",
        thumbnailUrl: "",
        pdfDocument: null,
        previewError: "",
      };
      pendingFiles.push(record);
      newRecords.push(record);
    }
  });
  if (newRecords.length === 0) return;
  setState("SELECTED");
  clearResult();
  renderFileList();
  newRecords.filter((record) => record.kind === "PDF").forEach(preparePdf);
}

function removeFile(index) {
  const record = pendingFiles[index];
  if (!record) return;
  if (activePreview === record) closePreview();
  destroyRecord(record);
  pendingFiles.splice(index, 1);
  if (pendingFiles.length === 0) setState("EMPTY");
  renderFileList();
}

function resetSelection() {
  pendingFiles.forEach(destroyRecord);
  pendingFiles = [];
  inputFile.value = "";
  inputGallery.value = "";
  inputCamera.value = "";
  setState("EMPTY");
  renderFileList();
  clearResult();
}

function showPreviewError() {
  previewLoading.hidden = true;
  previewCanvas.hidden = true;
  previewImage.hidden = true;
  previewError.hidden = false;
  previewPageIndicator.textContent = "—";
}

async function renderPdfPage(record, pageNumber) {
  if (!record.pdfDocument || activePreview !== record) return;
  const serial = ++renderSerial;
  activePreviewPage = pageNumber;
  previewLoading.hidden = false;
  previewError.hidden = true;
  previewCanvas.hidden = true;
  previewImage.hidden = true;
  previewPageIndicator.textContent = pageNumber + " / " + record.pageCount;
  previewPrev.disabled = pageNumber <= 1;
  previewNext.disabled = pageNumber >= record.pageCount;
  try {
    const page = await record.pdfDocument.getPage(pageNumber);
    const baseViewport = page.getViewport({ scale: 1 });
    const maxWidth = Math.max(280, previewStage.clientWidth - 24);
    const scale = Math.min(2.5, maxWidth / Math.max(baseViewport.width, 1));
    const viewport = page.getViewport({ scale });
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    previewCanvas.width = Math.ceil(viewport.width * dpr);
    previewCanvas.height = Math.ceil(viewport.height * dpr);
    previewCanvas.style.width = Math.ceil(viewport.width) + "px";
    previewCanvas.style.height = Math.ceil(viewport.height) + "px";
    const context = previewCanvas.getContext("2d", { alpha: false });
    context.fillStyle = "#fff";
    context.fillRect(0, 0, previewCanvas.width, previewCanvas.height);
    await page.render({
      canvasContext: context,
      viewport,
      transform: dpr === 1 ? null : [dpr, 0, 0, dpr, 0, 0],
    }).promise;
    if (serial !== renderSerial || activePreview !== record) return;
    previewLoading.hidden = true;
    previewCanvas.hidden = false;
  } catch (_) {
    if (serial !== renderSerial) return;
    record.previewState = "error";
    showPreviewError();
    updateSelectionUi();
  }
}

function openPreview(record) {
  if (record.kind === "OFD") return;
  activePreview = record;
  activePreviewPage = 1;
  setState("PREVIEWING");
  previewModal.hidden = false;
  document.body.classList.add("modal-open");
  previewTitle.textContent = record.file.name || "文件预览";
  previewTitle.title = record.file.name || "文件预览";
  previewImage.hidden = true;
  previewCanvas.hidden = true;
  previewError.hidden = true;
  previewLoading.hidden = false;
  previewFooter.hidden = record.kind !== "PDF" || record.previewState !== "ready";
  if (record.kind === "图片") {
    previewLoading.hidden = true;
    previewImage.src = record.imageUrl;
    previewImage.alt = "图片预览：" + (record.file.name || "文件");
    previewImage.hidden = false;
    previewPageIndicator.textContent = "1 / 1";
    previewPrev.disabled = true;
    previewNext.disabled = true;
  } else if (record.previewState === "ready") {
    renderPdfPage(record, 1);
  } else {
    showPreviewError();
  }
}

function closePreview() {
  renderSerial++;
  previewModal.hidden = true;
  document.body.classList.remove("modal-open");
  activePreview = null;
  setState(pendingFiles.length ? "SELECTED" : "EMPTY");
}

function toggleWechatTip() {
  const expanded = wechatTip.getAttribute("aria-expanded") === "true";
  wechatTip.setAttribute("aria-expanded", String(!expanded));
  wechatDetails.hidden = expanded;
  wechatTip.classList.toggle("is-expanded", !expanded);
}

inputFile.addEventListener("change", () => collectFiles(inputFile));
inputGallery.addEventListener("change", () => collectFiles(inputGallery));
inputCamera.addEventListener("change", () => collectFiles(inputCamera));
btnClear.addEventListener("click", resetSelection);
wechatTip.addEventListener("click", toggleWechatTip);
wechatTip.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleWechatTip(); }
});
previewBack.addEventListener("click", closePreview);
previewPrev.addEventListener("click", () => {
  if (activePreview && activePreview.kind === "PDF" && activePreviewPage > 1) renderPdfPage(activePreview, activePreviewPage - 1);
});
previewNext.addEventListener("click", () => {
  if (activePreview && activePreview.kind === "PDF" && activePreviewPage < activePreview.pageCount) renderPdfPage(activePreview, activePreviewPage + 1);
});
window.addEventListener("resize", () => {
  if (activePreview && activePreview.kind === "PDF" && !previewModal.hidden) renderPdfPage(activePreview, activePreviewPage);
});

btnUpload.addEventListener("click", async () => {
  if (!canUpload()) {
    if (hasPreviewBlocker()) setResult("result-error", "请先完成 PDF 预览检查；无法预览的 PDF 请移除后重新选择。");
    return;
  }
  isUploading = true;
  setState("UPLOADING");
  updateSelectionUi();
  setResult("uploading", "正在上传 " + pendingFiles.length + " 个文件…");
  try {
    const data = new FormData();
    pendingFiles.forEach((record) => data.append("files", record.file, record.file.name));
    const response = await fetch(UPLOAD_URL, { method: "POST", body: data });
    let payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) throw new Error(payload.message || ("HTTP " + response.status));
    const failed = Number(payload.failed || 0);
    const accepted = Number(payload.accepted || 0);
    const duplicate = Number(payload.duplicate || 0);
    setState(failed > 0 ? "PARTIAL" : "SUCCESS");
    setResult(failed > 0 ? "result-error" : "result-success", failed > 0
      ? "部分上传完成\\n已接收：" + accepted + "\\n重复：" + duplicate + "\\n失败：" + failed + "\\n请检查桌面端结果。"
      : "上传完成\\n已接收：" + accepted + "\\n重复：" + duplicate + "\\n文件已交给桌面端处理。");
    pendingFiles.forEach(destroyRecord);
    pendingFiles = [];
    inputFile.value = "";
    inputGallery.value = "";
    inputCamera.value = "";
    renderFileList();
  } catch (error) {
    setState("FAILURE");
    setResult("result-error", "上传失败：" + (error instanceof Error ? error.message : "网络错误"));
  } finally {
    isUploading = false;
    updateSelectionUi();
  }
});

if (/MicroMessenger/i.test(navigator.userAgent)) wechatTip.classList.add("is-visible");
setState("EMPTY");
updateSelectionUi();
</script>
</body>
</html>"""
    return (
        page.replace("__HOST__", html.escape(str(session.host), quote=True))
        .replace("__EXPIRY_HINT__", html.escape(expiry_hint, quote=True))
        .replace("__TOKEN__", html.escape(str(session.token), quote=True))
    )
