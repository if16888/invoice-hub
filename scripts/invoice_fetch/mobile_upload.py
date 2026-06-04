"""Temporary LAN upload service for phone-to-desktop invoice intake."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
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
from urllib.parse import urlparse

from .config import RUNTIME_DIR


ALLOWED_UPLOAD_EXTS = {".pdf", ".ofd", ".png", ".jpg", ".jpeg", ".heic"}
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024


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

        self.session: MobileUploadSession | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._files: list[dict] = []
        self._stats = {"accepted": 0, "duplicate": 0, "failed": 0, "imported": 0}

    def start(self) -> MobileUploadSession:
        if self._httpd:
            return self.session  # type: ignore[return-value]

        token = secrets.token_urlsafe(18)
        now = datetime.now()
        batch_id = f"mobile_{now:%Y%m%d_%H%M%S}_{token[:6]}"
        session_dir = self.runtime_dir / "inbox" / "mobile_upload" / f"{now:%Y-%m-%d}" / batch_id
        original_dir = session_dir / "original"
        original_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = session_dir / "manifest.json"
        expires_at = now + timedelta(seconds=self.ttl_seconds)

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
        self._write_manifest()

        self._thread = threading.Thread(target=self._httpd.serve_forever, name="InvoiceHubMobileUpload", daemon=True)
        self._thread.start()
        return self.session

    def stop(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def is_token_valid(self, token: str) -> bool:
        return bool(self.session and token == self.session.token and datetime.now() <= self.session.expires_at and self._httpd)

    def status(self) -> dict:
        with self._lock:
            return {
                **self._stats,
                "active": bool(self._httpd),
                "batch_id": self.session.batch_id if self.session else "",
                "upload_url": self.session.upload_url if self.session else "",
                "expires_at": self.session.expires_at.isoformat(timespec="seconds") if self.session else "",
            }

    def set_public_host(self, host: str) -> MobileUploadSession:
        """Update the public URL host while keeping the running listener and token."""
        host = (host or "").strip()
        if not host:
            raise ValueError("host is required")
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
                    if self.import_on_upload and self.db_path:
                        restored = self._restore_deleted_invoice_by_hash(digest)
                        if restored:
                            record["reason"] = "sha256_already_uploaded_restored_deleted_record"
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

            self._stats["accepted"] += accepted_now
            self._stats["duplicate"] += duplicate_now
            self._stats["failed"] += failed_now
            self._write_manifest()

        imported = 0
        if accepted_paths and self.import_on_upload and self.db_path:
            imported = self._import_accepted_files()
            with self._lock:
                imported_count = (
                    imported.get("added", 0) +
                    imported.get("conflicts", 0) +
                    imported.get("pending_manual", 0) +
                    imported.get("duplicates", 0)
                ) if isinstance(imported, dict) else imported
                self._stats["imported"] += imported_count
                self._write_manifest()

        return {
            "accepted": accepted_now,
            "duplicate": duplicate_now,
            "failed": failed_now,
            "imported": imported,
            "batch_id": self.session.batch_id,
        }

    def _restore_deleted_invoice_by_hash(self, file_hash: str) -> bool:
        if not self.db_path or not file_hash:
            return False
        from .db import InvoiceDB

        with InvoiceDB(self.db_path) as db:
            existing = db.find_invoice_by_file_hash(file_hash, include_deleted=True)
            if not existing or int(existing.get("is_deleted") or 0) != 1:
                return False
            return db.restore_invoice(existing["id"])

    def _import_accepted_files(self) -> int:
        if not self.session or not self.db_path:
            return 0
        from .services import import_local_directory
        from .db import InvoiceDB

        imported = import_local_directory(self.session.original_dir, self.db_path)
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

            def do_GET(self):
                parsed = urlparse(self.path)
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
                token = _token_from_path(urlparse(self.path).path, "/api/upload/")
                if not token or not owner.is_token_valid(token):
                    self._send_text(403, "Upload link expired or invalid.")
                    return

                content_length = int(self.headers.get("Content-Length") or "0")
                if content_length > owner.max_total_bytes:
                    self._send_text(413, "Upload is too large.")
                    return
                body = self.rfile.read(content_length)
                files = _parse_multipart_upload(body, self.headers.get("Content-Type", ""))
                result = owner.save_uploads(files)
                self._send_json(200, result)

            def _send_html(self, status: int, body: str):
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def _send_json(self, status: int, payload: dict):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def _send_text(self, status: int, body: str):
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
    .wechat-tip .tip-icon {{ font-size: 18px; margin-right: 6px; vertical-align: middle; }}
    .wechat-tip .tip-text {{ font-size: 13px; color: #92400E; line-height: 1.5; }}

    /* Upload entries */
    .upload-entry {{ display: flex; align-items: center; background: #f9fafb; border: 1.5px dashed #d1d5db; border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; cursor: pointer; transition: border-color 0.2s, background 0.2s; position: relative; overflow: hidden; }}
    .upload-entry:active {{ background: #eff6ff; border-color: #93c5fd; }}
    .upload-entry .entry-icon {{ font-size: 28px; margin-right: 14px; flex-shrink: 0; }}
    .upload-entry .entry-title {{ font-size: 15px; font-weight: 600; color: #1e293b; }}
    .upload-entry .entry-desc {{ font-size: 12px; color: #64748b; margin-top: 2px; }}
    .upload-entry input[type="file"] {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }}

    /* File list */
    .file-list {{ margin-top: 8px; }}
    .file-list-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
    .file-list-header span {{ font-size: 14px; font-weight: 600; color: #374151; }}
    .file-list-clear {{ font-size: 13px; color: #dc2626; border: none; background: none; cursor: pointer; padding: 4px 8px; }}
    .file-item {{ font-size: 13px; color: #4b5563; padding: 4px 0; border-bottom: 1px solid #f3f4f6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .no-files {{ font-size: 13px; color: #9ca3af; text-align: center; padding: 8px 0; }}

    /* Buttons */
    .btn-upload {{ width: 100%; padding: 14px; border: none; border-radius: 10px; background: #2563eb; color: #fff; font-size: 16px; font-weight: 700; cursor: pointer; transition: background 0.2s; }}
    .btn-upload:disabled {{ background: #93c5fd; cursor: not-allowed; }}
    .btn-upload:active:not(:disabled) {{ background: #1d4ed8; }}

    /* Result */
    #result {{ white-space: pre-wrap; font-size: 13px; color: #374151; min-height: 20px; }}
    .uploading {{ color: #2563eb; font-weight: 600; }}

    /* Tips */
    .tips {{ font-size: 12px; color: #6b7280; line-height: 1.7; }}
    .tips li {{ margin-bottom: 4px; }}

    .batch-info {{ font-size: 13px; color: #6b7280; }}
    .batch-info strong {{ color: #374151; }}
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
    <span class="tip-icon">💡</span>
    <span class="tip-text">当前在微信内打开。为便于选择 PDF/OFD/下载文件，建议点击右上角 <strong>⋯</strong>，选择「在浏览器打开」。<br>上传图片/拍照可直接使用。</span>
  </div>

  <div class="card">
    <div class="upload-entry" id="entryFile">
      <div class="entry-icon">📄</div>
      <div>
        <div class="entry-title">选择 PDF/OFD/文件</div>
        <div class="entry-desc">适合电子发票、滴滴行程单、酒店水单、下载文件</div>
      </div>
      <input id="inputFile" type="file" multiple accept=".pdf,.ofd,application/pdf,application/octet-stream">
    </div>

    <div class="upload-entry" id="entryGallery">
      <div class="entry-icon">🖼️</div>
      <div>
        <div class="entry-title">选择相册图片</div>
        <div class="entry-desc">适合截图、照片、小票图片</div>
      </div>
      <input id="inputGallery" type="file" multiple accept="image/jpeg,image/png,image/heic,image/*">
    </div>

    <div class="upload-entry" id="entryCamera">
      <div class="entry-icon">📷</div>
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
      <div id="fileListItems"></div>
    </div>

    <button class="btn-upload" id="btnUpload" type="button" disabled>开始上传</button>
  </div>

  <div class="card">
    <div id="result" class="no-files">选择文件后点击「开始上传」。</div>
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
  const btnClear = document.getElementById('btnClear');
  const btnUpload = document.getElementById('btnUpload');
  const result = document.getElementById('result');

  // Collect files from all inputs
  let pendingFiles = [];

  function collectFiles(input) {{
    for (const f of input.files) {{
      // Avoid exact duplicates by name+size
      if (!pendingFiles.some(p => p.name === f.name && p.size === f.size)) {{
        pendingFiles.push(f);
      }}
    }}
    renderFileList();
  }}

  function renderFileList() {{
    if (pendingFiles.length === 0) {{
      fileListSection.style.display = 'none';
      btnUpload.disabled = true;
      return;
    }}
    fileListSection.style.display = 'block';
    btnUpload.disabled = false;
    fileCount.textContent = '已选 ' + pendingFiles.length + ' 个文件';
    fileListItems.innerHTML = '';
    pendingFiles.forEach(function(f) {{
      const div = document.createElement('div');
      div.className = 'file-item';
      div.textContent = f.name;
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
    result.textContent = '选择文件后点击「开始上传」。';
    result.className = 'no-files';
  }});

  btnUpload.addEventListener('click', async function() {{
    if (pendingFiles.length === 0) {{
      result.textContent = '请先选择文件或拍照。';
      return;
    }}
    btnUpload.disabled = true;
    result.textContent = '正在上传 ' + pendingFiles.length + ' 个文件...';
    result.className = 'uploading';
    try {{
      const data = new FormData();
      pendingFiles.forEach(function(f) {{ data.append('files', f); }});
      const response = await fetch('/api/upload/{html.escape(session.token)}', {{ method: 'POST', body: data }});
      const payload = await response.json();
      result.className = '';
      result.textContent = '✅ 成功：' + payload.accepted + '\\n🔁 重复：' + payload.duplicate + '\\n❌ 失败：' + payload.failed;
      // Reset for next batch
      pendingFiles = [];
      inputFile.value = '';
      inputGallery.value = '';
      inputCamera.value = '';
      renderFileList();
    }} catch (err) {{
      result.className = '';
      result.textContent = '上传失败: ' + err.message;
      btnUpload.disabled = false;
    }}
  }});
}})();
</script>
</body>
</html>"""
