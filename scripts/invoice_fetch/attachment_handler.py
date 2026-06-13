"""Attachment extraction — pull PDF / OFD / image files from MIME messages."""

from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from dataclasses import dataclass
from email.header import decode_header
from email.message import Message
from pathlib import Path

from .log_privacy import mask_filename

_log = logging.getLogger(__name__)


@dataclass
class Attachment:
    """Metadata for a single extracted attachment."""

    file_path: str          # absolute path where the file was saved
    original_name: str      # decoded MIME filename
    content_type: str
    size: int
    is_invoice: bool = False
    is_extra: bool = False  # water bill / trip record


# File extensions we care about
_INVOICE_EXTS = {".pdf", ".ofd"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".heic"}
_ALL_EXTS = _INVOICE_EXTS | _IMAGE_EXTS | {".zip"}

# Invoice-ish filename keywords
_INVOICE_NAME_KW = ["发票", "invoice", "fapiao", "einvoice"]
_EXTRA_NAME_KW = [
    "水单", "folio", "行程", "行程单", "行程记录", "用车明细", "费用明细",
    "支付凭证", "支付截图", "交易记录", "订单明细", "订单截图", "明细",
    "trip", "itinerary", "ride", "ride_detail", "detail", "statement", "bill"
]


def _ext_priority(ext: str) -> int:
    if ext == ".pdf":
        return 1
    if ext in _IMAGE_EXTS:
        return 2
    if ext == ".ofd":
        return 3
    if ext == ".zip":
        return 4
    return 99


def _decode_filename(part: Message) -> str:
    """Best-effort decode of a MIME attachment filename."""
    raw = part.get_filename()
    if raw is None:
        return ""
    pieces = decode_header(raw)
    decoded = []
    for content, charset in pieces:
        if isinstance(content, bytes):
            for enc in [charset or "utf-8", "utf-8", "gbk", "gb2312", "gb18030"]:
                try:
                    decoded.append(content.decode(enc))
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                decoded.append(content.decode("utf-8", errors="replace"))
        else:
            decoded.append(str(content))
    return "".join(decoded).strip()


def _safe_name(name: str, max_len: int = 80) -> str:
    """Sanitize a filename for Windows."""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"[_\s]+", "_", name).strip("_")
    return name[:max_len] if len(name) > max_len else name


def _normalize_export_date_prefix(raw_value: str) -> str:
    from datetime import datetime
    text = str(raw_value or "").strip()
    if not text:
        return "unknown-date"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return "unknown-date"


def build_managed_attachment_name(
    *,
    original_name: str,
    invoice_date: str | None = None,
    expense_date: str | None = None,
    fallback_date: str | None = None,
    prefix_date: bool = True,
) -> str:
    """Build a unified, Windows-safe filename for a managed attachment.

    YYYY-MM-DD_原文件名.ext
    """
    # 1. Date Priority: expense_date -> invoice_date -> fallback_date -> unknown-date
    date_to_use = None
    for d in [expense_date, invoice_date, fallback_date]:
        if d:
            normalized = _normalize_export_date_prefix(d)
            if normalized and normalized != "unknown-date":
                date_to_use = normalized
                break
    if not date_to_use:
        date_to_use = "unknown-date"

    # 2. Extract stem and extension
    name_path = Path(original_name)
    stem = name_path.stem
    ext = name_path.suffix.lower()

    # 3. Clean Windows illegal characters
    clean_stem = re.sub(r'[\\/:*?"<>|]', "_", stem)
    clean_stem = re.sub(r"[_\s]+", "_", clean_stem).strip("_")

    if not clean_stem:
        clean_stem = "file"

    # 4. Check if YYYY-MM-DD_ is already present
    if prefix_date:
        if re.match(r"^\d{4}-\d{2}-\d{2}_", clean_stem):
            filename = f"{clean_stem}{ext}"
        else:
            filename = f"{date_to_use}_{clean_stem}{ext}"
    else:
        filename = f"{clean_stem}{ext}"

    return filename



def _payload_matches_extension(payload: bytes, ext: str) -> bool:
    """Return whether file bytes match the claimed safe extension."""
    if ext == ".pdf":
        return payload.startswith(b"%PDF-")
    if ext in {".zip", ".ofd"}:
        return payload.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    if ext == ".png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return payload.startswith(b"\xff\xd8\xff")
    if ext == ".bmp":
        return payload.startswith(b"BM")
    if ext == ".heic":
        return len(payload) >= 12 and payload[4:8] == b"ftyp"
    return False


class AttachmentHandler:
    """Extract and classify attachments from a MIME message."""

    def __init__(self, base_dir: str | Path):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def extract(self, msg: Message, mail_uid: int,
                date_str: str = "") -> list[Attachment]:
        """Walk *msg* parts and save attachments to disk based on priority.

        Priority: PDF > Images > OFD > ZIP.
        Files are saved under ``<base_dir>/<date_str>/``.
        """
        results: list[Attachment] = []

        date_dir = self._base / (date_str or "unknown_date")
        date_dir.mkdir(parents=True, exist_ok=True)

        # 1. Collect all valid candidates
        candidates = []
        parts = list(msg.walk()) if msg.is_multipart() else [msg]
        for idx, part in enumerate(parts):
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" not in cd and ct in ("text/plain", "text/html"):
                continue

            # Some mail clients send attachments without explicitly saying "attachment"
            # but we'll stick to basic check: if it's an image/pdf, it might be inline.
            # Usually we require a filename.
            filename = _decode_filename(part)
            if not filename and "attachment" not in cd:
                continue
            if not filename:
                filename = f"attachment_{mail_uid}_{idx}"

            ext = os.path.splitext(filename)[1].lower()
            if ext not in _ALL_EXTS:
                continue

            name_lower = filename.lower()
            is_ext = any(k in name_lower for k in _EXTRA_NAME_KW)
            is_inv = (ext in _INVOICE_EXTS or any(k in name_lower for k in _INVOICE_NAME_KW)) and not is_ext

            candidates.append({
                "part": part,
                "filename": filename,
                "ext": ext,
                "is_inv": is_inv,
                "is_ext": is_ext,
                "ct": ct
            })

        if not candidates:
            return results

        # 2. Filter candidates by priority
        to_extract = []

        # Always extract extra files (water bills, etc)
        extras = [c for c in candidates if c["is_ext"]]
        to_extract.extend(extras)

        # For invoices, find the best priority
        invoices = [c for c in candidates if c["is_inv"] and not c["is_ext"]]
        if not invoices:
            # Fallback: treat all non-extra candidates as potential invoices
            # Priority will still ensure PDF > IMG > OFD > ZIP
            fallback_invs = [c for c in candidates if not c["is_ext"]]
            invoices = fallback_invs

        if invoices:
            best_prio = min(_ext_priority(c["ext"]) for c in invoices)
            best_invoices = [c for c in invoices if _ext_priority(c["ext"]) == best_prio]
            to_extract.extend(best_invoices)

        # 3. Extract and save the chosen ones
        for c in to_extract:
            part = c["part"]
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            filename = c["filename"]
            ext = c["ext"]
            if not _payload_matches_extension(payload, ext):
                _log.warning("  Attachment content does not match extension, skipped: %s", mask_filename(filename))
                continue
            if ext == ".zip":
                try:
                    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                        total_size = 0
                        file_count = 0
                        for member in zf.infolist():
                            if member.is_dir():
                                continue
                            inner_name = Path(member.filename).name
                            inner_ext = os.path.splitext(inner_name)[1].lower()
                            if inner_ext not in (_ALL_EXTS - {".zip"}):
                                continue
                            # Safety: limit total unzipped size and file count
                            total_size += member.file_size
                            file_count += 1
                            if total_size > 50 * 1024 * 1024:  # 50 MB
                                _log.warning("  ⚠️ ZIP 解压内容过大 (>50MB)，停止提取: %s", mask_filename(filename))
                                break
                            if file_count > 20:
                                _log.warning("  ⚠️ ZIP 内文件过多 (>20)，停止提取: %s", mask_filename(filename))
                                break
                            inner_payload = zf.read(member)
                            if not _payload_matches_extension(inner_payload, inner_ext):
                                _log.warning("  ZIP inner file content does not match extension, skipped: %s", mask_filename(inner_name))
                                continue
                            inner_combined_name = f"{os.path.splitext(filename)[0]}_{inner_name}"
                            inner_safe = build_managed_attachment_name(
                                original_name=inner_combined_name,
                                fallback_date=date_str,
                            )
                            dest = date_dir / inner_safe
                            if dest.exists():
                                stem = dest.stem
                                for n in range(1, 100):
                                    candidate = date_dir / f"{stem}_{n}{inner_ext}"
                                    if not candidate.exists():
                                        dest = candidate
                                        break
                            dest.write_bytes(inner_payload)
                            inner_lower = inner_name.lower()
                            is_ext = any(k in inner_lower for k in _EXTRA_NAME_KW)
                            is_inv = (inner_ext in _INVOICE_EXTS or any(k in inner_lower for k in _INVOICE_NAME_KW)) and not is_ext
                            results.append(Attachment(
                                file_path=str(dest),
                                original_name=inner_name,
                                content_type="application/octet-stream",
                                size=len(inner_payload),
                                is_invoice=is_inv,
                                is_extra=is_ext,
                            ))
                            _log.info("  附件(解压): %s (%d bytes) %s",
                                      mask_filename(inner_name), len(inner_payload),
                                      "[发票]" if is_inv else ("[附加材料]" if is_ext else ""))
                    continue
                except zipfile.BadZipFile:
                    _log.info("  ZIP 附件不是有效压缩包，跳过: %s", mask_filename(filename))
                    continue
            safe = build_managed_attachment_name(
                original_name=filename,
                fallback_date=date_str,
            )
            dest = date_dir / safe

            # Avoid overwriting
            if dest.exists():
                stem = dest.stem
                for n in range(1, 100):
                    candidate = date_dir / f"{stem}_{n}{ext}"
                    if not candidate.exists():
                        dest = candidate
                        break

            dest.write_bytes(payload)

            att = Attachment(
                file_path=str(dest),
                original_name=filename,
                content_type=c["ct"],
                size=len(payload),
                is_invoice=c["is_inv"],
                is_extra=c["is_ext"],
            )
            results.append(att)
            _log.info("  附件: %s (%d bytes) %s",
                      mask_filename(filename), len(payload),
                      "[发票]" if c["is_inv"] else ("[附加材料]" if c["is_ext"] else ""))

        return results
