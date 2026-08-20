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
        self._last_phone_access_at: datetime | None = None
        self._phone_access_confirmed = False
        self._local_self_check = "pending"
        self._local_self_check_error = ""

    def start(self) -> MobileUploadSession:
        if self._httpd:
            return self.session  # type: ignore[return-value]
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
            self._session_expired_logged = False
            self._last_request_at = None
            self._last_phone_access_at = None
            self._phone_access_confirmed = False
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
            _log.info(
                "[手机上传] server stop batch_id=<redacted>"
            )

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
                "phone_access_confirmed": self._phone_access_confirmed,
                "last_request_at": self._last_request_at.isoformat(timespec="seconds") if self._last_request_at else "",
                "last_phone_access_at": self._last_phone_access_at.isoformat(timespec="seconds") if self._last_phone_access_at else "",
            }

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
        """Check the selected public URL locally; never infer phone reachability."""
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
        self._last_request_at = now
        _log.info(
            "[手机上传] request method=%s client=%s path=%s status=%s",
            method,
            _redact_host(client),
            safe_path,
            status,
        )
        if (
            method == "GET"
            and path.startswith("/u/")
            and status == 200
            and not is_self_check
            and not _is_loopback_host(client)
        ):
            first_confirmation = not self._phone_access_confirmed
            self._phone_access_confirmed = True
            self._last_phone_access_at = now
            if first_confirmation:
                _log.info(
                    "[手机上传] network access confirmed client=%s at=%s",
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
        """Update the public URL host while keeping the running listener and token."""
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
            def log_message(self, fmt, *args):  # pragma: no cover - keep desktop logs quiet
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
    """Build sorted selectable IPv4 hosts for the QR upload URL."""
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
    """Write one safe diagnostic record per candidate considered for QR URLs."""
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
    title = "Invoice Hub 手机上传"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', sans-serif; background: #f5f6f8; color: #1a1a2e; line-height: 1.6; padding: 16px 16px 32px; }}
    main {{ max-width: 520px; margin: 0 auto; }}
    h1 {{ font-size: 20px; font-weight: 700; margin-bottom: 4px; }}
    .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; margin-bottom: 12px; }}

    /* WeChat tip banner */
    .wechat-tip {{ background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; display: none; }}
    .wechat-tip .tip-icon {{ display: inline-flex; width: 20px; height: 20px; border: 1px solid #B45309; border-radius: 50%; align-items: center; justify-content: center; margin-right: 6px; vertical-align: middle; color: #92400E; font-size: 12px; font-weight: 700; }}
    .wechat-tip .tip-icon::before {{ content: "i"; }}
    .wechat-tip .tip-text {{ font-size: 13px; color: #92400E; line-height: 1.5; }}

    /* Upload entries */
    .upload-entry {{ display: flex; align-items: center; background: #f9fafb; border: 1.5px dashed #d1d5db; border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; cursor: pointer; transition: border-color 0.2s, background 0.2s; position: relative; overflow: hidden; }}
    .upload-entry:active {{ background: #eff6ff; border-color: #93c5fd; }}
    .upload-entry .entry-icon {{ display: inline-flex; align-items: center; justify-content: center; width: 42px; height: 34px; border: 1px solid #BFDBFE; border-radius: 8px; background: #EFF6FF; color: #2563EB; font-size: 12px; font-weight: 700; letter-spacing: .04em; margin-right: 14px; flex-shrink: 0; }}
    .upload-entry .entry-title {{ font-size: 15px; font-weight: 600; color: #1e293b; }}
    .upload-entry .entry-desc {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
    .upload-entry input[type="file"] {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }}

    /* File confirmation list */
    .file-list {{ margin-top: 8px; }}
    .file-list-header {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; }}
    .file-list-header span {{ font-size: 14px; font-weight: 600; color: #374151; }}
    .file-list-clear {{ font-size: 13px; color: #2563EB; border: 1px solid #BFDBFE; border-radius: 7px; background: #EFF6FF; cursor: pointer; padding: 5px 8px; flex-shrink: 0; }}
    .file-list-clear:active {{ background: #DBEAFE; }}
    .file-item {{ display: flex; align-items: center; gap: 9px; padding: 8px 0; border-bottom: 1px solid #f3f4f6; min-width: 0; }}
    .file-thumb {{ width: 46px; height: 46px; border-radius: 7px; border: 1px solid #E5E7EB; background: #F8FAFC; color: #64748B; display: flex; align-items: center; justify-content: center; flex: 0 0 46px; font-size: 11px; font-weight: 700; }}
    .file-thumb img {{ width: 100%; height: 100%; border-radius: 6px; object-fit: cover; display: block; }}
    .file-meta {{ min-width: 0; flex: 1; }}
    .file-name {{ font-size: 13px; color: #334155; font-weight: 600; overflow-wrap: anywhere; }}
    .file-detail {{ font-size: 12px; color: #64748B; margin-top: 2px; }}
    .file-remove {{ font-size: 12px; color: #2563EB; border: 1px solid #CBD5E1; border-radius: 6px; background: #fff; cursor: pointer; padding: 5px 7px; flex: 0 0 auto; }}
    .file-remove:active {{ background: #F1F5F9; }}
    .selection-hint {{ font-size: 12px; color: #64748B; margin: 4px 0 8px; }}
    .no-files {{ font-size: 13px; color: #64748b; text-align: center; padding: 8px 0; }}

    /* Buttons */
    .btn-upload {{ width: 100%; padding: 14px; border: none; border-radius: 10px; background: #2563eb; color: #fff; font-size: 16px; font-weight: 700; cursor: pointer; transition: background 0.2s; }}
    .btn-upload:disabled {{ background: #93c5fd; cursor: not-allowed; }}
    .btn-upload:active:not(:disabled) {{ background: #1d4ed8; }}

    /* Result */
    #result {{ white-space: pre-wrap; font-size: 13px; color: #374151; min-height: 20px; }}
    .uploading {{ color: #2563eb; font-weight: 600; }}
    .result-success {{ color: #166534; }}
    .result-error {{ color: #B91C1C; }}

    /* Tips */
    .tips {{ font-size: 12px; color: #6b7280; line-height: 1.7; }}
    .tips li {{ margin-bottom: 4px; }}

    .batch-info {{ font-size: 13px; color: #6b7280; }}
    .batch-info strong {{ color: #374151; }}
    @media (max-width: 360px) {{
      body {{ padding: 12px 10px 24px; }}
      .card {{ padding: 13px; }}
      .upload-entry {{ padding: 12px; }}
      .upload-entry .entry-icon {{ width: 38px; margin-right: 10px; }}
      .upload-entry .entry-title {{ font-size: 14px; }}
      .file-remove {{ padding-left: 6px; padding-right: 6px; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <div class="card batch-info">
    <div>上传批次：<strong>{html.escape(session.batch_id)}</strong></div>
    <div>有效期至：{html.escape(session.expires_at.strftime("%Y-%m-%d %H:%M:%S"))}</div>
  </div>

  <div class="wechat-tip" id="wechatTip">
    <span class="tip-icon" aria-hidden="true"></span>
    <span class="tip-text">当前在微信内打开。为便于选择 PDF/OFD/下载文件，建议点击右上角 <strong>⋯</strong>，选择「在浏览器打开」。<br>上传图片/拍照可直接使用。</span>
  </div>

  <div class="card">
    <div class="upload-entry" id="entryFile">
      <div class="entry-icon" aria-hidden="true">PDF</div>
      <div>
        <div class="entry-title">选择 PDF/OFD/文件</div>
        <div class="entry-desc">适合电子发票、滴滴行程单、酒店水单、下载文件</div>
      </div>
      <input id="inputFile" type="file" multiple accept=".pdf,.ofd,application/pdf,application/octet-stream">
    </div>

    <div class="upload-entry" id="entryGallery">
      <div class="entry-icon" aria-hidden="true">IMG</div>
      <div>
        <div class="entry-title">选择相册图片</div>
        <div class="entry-desc">适合截图、照片、小票图片</div>
      </div>
      <input id="inputGallery" type="file" multiple accept="image/jpeg,image/png,image/heic,image/*">
    </div>

    <div class="upload-entry" id="entryCamera">
      <div class="entry-icon" aria-hidden="true">CAM</div>
      <div>
        <div class="entry-title">拍照上传</div>
        <div class="entry-desc">适合纸质票据、现场小票</div>
      </div>
      <input id="inputCamera" type="file" accept="image/*" capture="environment">
    </div>

    <div class="file-list" id="fileListSection" style="display:none;">
      <div class="file-list-header">
        <span id="fileCount">已选 0 个文件</span>
        <button class="file-list-clear" id="btnClear" type="button">清空重选</button>
      </div>
      <div class="selection-hint" id="selectionHint">已选文件会显示名称、类型和大小。</div>
      <div id="fileListItems"></div>
    </div>

    <button class="btn-upload" id="btnUpload" type="button" disabled>开始上传</button>
  </div>

  <div class="card">
    <div id="result" class="no-files" aria-live="polite">尚未选择文件。选中 PDF/OFD/图片后，这里会显示确认信息。</div>
  </div>

  <div class="card tips">
    <ul>
      <li>支持 pdf、ofd、jpg、jpeg、png、heic 格式。</li>
      <li>如果发票在微信聊天中，请先将文件保存到手机「文件/下载」目录，再通过上方入口选择。</li>
      <li>手机和电脑需要在同一 Wi-Fi / 局域网。</li>
      <li>如打不开页面，请回到电脑端扫码窗口切换正确 IP，或检查 Windows 防火墙是否允许专用网络访问。</li>
      <li>请勿上传与报销无关的私人照片。</li>
    </ul>
  </div>
</main>
<script>
(function() {{
  // WeChat in-app browser detection
  if (/MicroMessenger/i.test(navigator.userAgent)) {{
    document.getElementById('wechatTip').style.display = 'block';
  }}

  const inputFile = document.getElementById('inputFile');
  const inputGallery = document.getElementById('inputGallery');
  const inputCamera = document.getElementById('inputCamera');
  const fileListSection = document.getElementById('fileListSection');
  const fileListItems = document.getElementById('fileListItems');
  const fileCount = document.getElementById('fileCount');
  const selectionHint = document.getElementById('selectionHint');
  const btnClear = document.getElementById('btnClear');
  const btnUpload = document.getElementById('btnUpload');
  const result = document.getElementById('result');

  // Collect files from all inputs and show an explicit confirmation row.
  let pendingFiles = [];
  let previewUrls = [];
  let isUploading = false;

  function formatBytes(bytes) {{
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }}

  function fileKind(file) {{
    const name = (file.name || '').toLowerCase();
    if (name.endsWith('.pdf') || file.type === 'application/pdf') return 'PDF';
    if (name.endsWith('.ofd')) return 'OFD';
    if ((file.type || '').startsWith('image/')) return '图片';
    return '文件';
  }}

  function clearPreviews() {{
    previewUrls.forEach(function(url) {{ URL.revokeObjectURL(url); }});
    previewUrls = [];
  }}

  function collectFiles(input) {{
    for (const f of input.files) {{
      if (!pendingFiles.some(p => p.name === f.name && p.size === f.size && p.lastModified === f.lastModified)) {{
        pendingFiles.push(f);
      }}
    }}
    renderFileList();
  }}

  function removeFile(index) {{
    pendingFiles.splice(index, 1);
    renderFileList();
  }}

  function renderFileList() {{
    clearPreviews();
    if (pendingFiles.length === 0) {{
      fileListSection.style.display = 'none';
      btnUpload.disabled = true;
      return;
    }}
    fileListSection.style.display = 'block';
    btnUpload.disabled = isUploading;
    fileCount.textContent = '已选 ' + pendingFiles.length + ' 个文件' + (pendingFiles.length > 1 ? ' · 可多选上传' : '');
    selectionHint.textContent = pendingFiles.length === 1 ? '请确认这是要上传的文件。' : '请确认以下文件后再开始上传。';
    fileListItems.innerHTML = '';
    pendingFiles.forEach(function(f, index) {{
      const div = document.createElement('div');
      div.className = 'file-item';
      const kind = fileKind(f);
      const thumb = document.createElement('div');
      thumb.className = 'file-thumb';
      if (kind === '图片') {{
        const url = URL.createObjectURL(f);
        previewUrls.push(url);
        const image = document.createElement('img');
        image.src = url;
        image.alt = '图片预览：' + f.name;
        thumb.appendChild(image);
      }} else {{
        thumb.textContent = kind;
        thumb.setAttribute('aria-hidden', 'true');
      }}

      const meta = document.createElement('div');
      meta.className = 'file-meta';
      const name = document.createElement('div');
      name.className = 'file-name';
      name.textContent = f.name || '未命名文件';
      const detail = document.createElement('div');
      detail.className = 'file-detail';
      detail.textContent = kind + ' · ' + formatBytes(f.size);
      meta.appendChild(name);
      meta.appendChild(detail);

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'file-remove';
      remove.textContent = '移除';
      remove.setAttribute('aria-label', '移除 ' + (f.name || '文件'));
      remove.addEventListener('click', function() {{ removeFile(index); }});
      div.appendChild(thumb);
      div.appendChild(meta);
      div.appendChild(remove);
      fileListItems.appendChild(div);
    }});
  }}

  inputFile.addEventListener('change', function() {{ collectFiles(this); }});
  inputGallery.addEventListener('change', function() {{ collectFiles(this); }});
  inputCamera.addEventListener('change', function() {{ collectFiles(this); }});

  btnClear.addEventListener('click', function() {{
    pendingFiles = [];
    inputFile.value = '';
    inputGallery.value = '';
    inputCamera.value = '';
    renderFileList();
    result.textContent = '尚未选择文件。选中 PDF/OFD/图片后，这里会显示确认信息。';
    result.className = 'no-files';
  }});

  btnUpload.addEventListener('click', async function() {{
    if (pendingFiles.length === 0 || isUploading) {{
      result.textContent = '请先选择文件或拍照。';
      result.className = 'result-error';
      return;
    }}
    isUploading = true;
    btnUpload.disabled = true;
    result.textContent = '正在上传 ' + pendingFiles.length + ' 个文件...';
    result.className = 'uploading';
    try {{
      const data = new FormData();
      pendingFiles.forEach(function(f) {{ data.append('files', f); }});
      const response = await fetch('/api/upload/{html.escape(session.token)}', {{ method: 'POST', body: data }});
      let payload = {{}};
      try {{ payload = await response.json(); }} catch (_) {{ payload = {{}}; }}
      if (!response.ok) {{
        throw new Error(payload.message || ('HTTP ' + response.status));
      }}
      result.className = 'result-success';
      result.textContent = '上传完成\\n已接收：' + (payload.accepted || 0) + '\\n重复：' + (payload.duplicate || 0) + '\\n失败：' + (payload.failed || 0) + '\\n文件已交给桌面端处理。';
      // Reset for next batch
      pendingFiles = [];
      inputFile.value = '';
      inputGallery.value = '';
      inputCamera.value = '';
      renderFileList();
    }} catch (err) {{
      result.className = 'result-error';
      result.textContent = '上传失败：' + err.message;
      btnUpload.disabled = pendingFiles.length === 0;
    }} finally {{
      isUploading = false;
      btnUpload.disabled = pendingFiles.length === 0;
    }}
  }});
}})();
</script>
</body>
</html>"""
