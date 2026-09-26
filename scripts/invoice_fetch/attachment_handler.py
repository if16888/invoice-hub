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
    extraction_warning: str = ""  # non-empty when the original archive needs manual review


# File extensions we care about
_INVOICE_EXTS = {".pdf", ".ofd"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".heic"}
_ALL_EXTS = _INVOICE_EXTS | _IMAGE_EXTS | {".zip"}
_ZIP_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_ZIP_MAX_FILES = 20

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


_WINDOWS_ILLEGAL = re.compile(r'[\\/:*?"<>|]')
_MAX_FILENAME_LEN = 180  # leave room for _1, _2 suffix and extension


def _safe_field(text: str, fallback: str, max_len: int = 20) -> str:
    """Sanitize a single field for inclusion in a filename segment."""
    text = str(text or "").strip()
    if not text:
        return fallback
    cleaned = _WINDOWS_ILLEGAL.sub("_", text)
    cleaned = re.sub(r"[_\s]+", "_", cleaned).strip("_")
    if not cleaned:
        return fallback
    return cleaned[:max_len]


def _format_amount_field(amount) -> str:
    """Format amount as '945.50'; return '金额待补全' if empty or invalid."""
    text = str(amount or "").strip()
    if not text:
        return "金额待补全"
    try:
        from decimal import Decimal, InvalidOperation
        return f"{Decimal(text):.2f}"
    except (ImportError, Exception):
        return text[:12] if text else "金额待补全"


def build_managed_attachment_name(
    *,
    original_name: str,
    invoice_date: str | None = None,
    expense_date: str | None = None,
    fallback_date: str | None = None,
    prefix_date: bool = True,
    # Extended fields for full-format naming
    category: str | None = None,
    total_amount: str | None = None,
    invoice_number: str | None = None,
    role: str | None = None,   # 原件 / 证明材料 / None (falls back to stem)
) -> str:
    """Build a unified, Windows-safe filename for a managed attachment.

    Short format (when category/amount/number all absent):
        YYYY-MM-DD_原文件名.ext

    Full format (when at least one of category/amount/number is provided):
        YYYY-MM-DD_消费类型_金额_发票号_原件.ext
        YYYY-MM-DD_消费类型_金额_发票号_证明材料.ext
    """
    # 1. Date Priority: expense_date -> invoice_date -> fallback_date -> unknown-date
    date_to_use = "unknown-date"
    for d in [expense_date, invoice_date, fallback_date]:
        if d:
            normalized = _normalize_export_date_prefix(d)
            if normalized and normalized != "unknown-date":
                date_to_use = normalized
                break

    # 2. Extract extension
    name_path = Path(original_name)
    ext = name_path.suffix.lower()

    # 3. Decide naming mode
    use_full_format = any(x is not None for x in [category, total_amount, invoice_number, role])

    if use_full_format:
        cat_part = _safe_field(category, "未分类", 16)
        amt_part = _format_amount_field(total_amount)
        num_part = _safe_field(invoice_number, "待补全", 24)
        role_part = _safe_field(role, "原件", 6) if role else "原件"
        stem = f"{cat_part}_{amt_part}_{num_part}_{role_part}"
    else:
        # Legacy mode: use original filename stem
        raw_stem = name_path.stem
        stem = _WINDOWS_ILLEGAL.sub("_", raw_stem)
        stem = re.sub(r"[_\s]+", "_", stem).strip("_")
        if not stem:
            stem = "file"

    # 4. Compose filename with optional date prefix
    if prefix_date:
        # Skip re-adding date prefix if it's already there
        if re.match(r"^\d{4}-\d{2}-\d{2}_", stem):
            filename = f"{stem}{ext}"
        else:
            filename = f"{date_to_use}_{stem}{ext}"
    else:
        filename = f"{stem}{ext}"

    # 5. Truncate if too long, preserving extension
    if len(filename) > _MAX_FILENAME_LEN:
        keep = _MAX_FILENAME_LEN - len(ext)
        filename = filename[:keep] + ext

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


def _read_zip_member_limited(zf: zipfile.ZipFile, member, max_bytes: int) -> bytes | None:
    """Read one member without trusting ZIP metadata to bound decompressed bytes."""
    chunks = []
    size = 0
    with zf.open(member) as stream:
        while True:
            chunk = stream.read(min(64 * 1024, max_bytes - size + 1))
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > max_bytes:
                return None
            chunks.append(chunk)


class AttachmentHandler:
    """Extract and classify attachments from a MIME message."""

    def __init__(self, base_dir: str | Path):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def extract(self, msg: Message, mail_uid: int,
                date_str: str = "") -> list[Attachment]:
        """Walk *msg* parts, prioritizing standalone invoices and always processing ZIPs.

        Among standalone invoice candidates, priority is PDF > Images > OFD. ZIP archives
        are processed independently so a top-level PDF cannot hide bundled evidence.
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

        # A ZIP is a container, not an alternate representation of a standalone invoice.
        # Process every one even when a higher-priority PDF is attached to the same email.
        selected_ids = {id(c) for c in to_extract}
        to_extract.extend(
            c for c in candidates
            if c["ext"] == ".zip" and id(c) not in selected_ids
        )

        # 3. Extract and save the chosen ones
        for c in to_extract:
            part = c["part"]
            payload = part.get_payload(decode=True)
            filename = c["filename"]
            ext = c["ext"]

            if ext == ".zip":
                archive_payload = payload or b""
                if not _payload_matches_extension(archive_payload, ext):
                    warning = "邮件 ZIP 格式无效或内容与扩展名不符，已保留压缩包，请人工检查。"
                    results.append(self._save_problem_archive(
                        date_dir, filename, c["ct"], archive_payload, warning, date_str
                    ))
                    _log.warning("  邮件 ZIP 格式无效，已保留待人工检查: %s", mask_filename(filename))
                    continue

                warning = ""
                staged_members: list[tuple[str, int, bytes, bool, bool]] = []
                try:
                    with zipfile.ZipFile(io.BytesIO(archive_payload)) as zf:
                        eligible = []
                        total_size = 0
                        for member in zf.infolist():
                            if member.is_dir():
                                continue
                            inner_name = Path(member.filename.replace("\\", "/")).name
                            inner_ext = os.path.splitext(inner_name)[1].lower()
                            if inner_ext not in (_ALL_EXTS - {".zip"}):
                                continue
                            if member.file_size < 0:
                                warning = "邮件 ZIP 文件大小信息无效，已保留压缩包，请人工检查。"
                                break
                            eligible.append((member, inner_name, inner_ext))
                            total_size += member.file_size
                            if len(eligible) > _ZIP_MAX_FILES:
                                warning = (
                                    f"邮件 ZIP 超过安全展开限制（最多 {_ZIP_MAX_FILES} 个文件、"
                                    f"总解压 {_ZIP_MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MiB），"
                                    "已保留压缩包，请人工检查。"
                                )
                                break
                            if total_size > _ZIP_MAX_UNCOMPRESSED_BYTES:
                                warning = (
                                    f"邮件 ZIP 超过安全展开限制（最多 {_ZIP_MAX_FILES} 个文件、"
                                    f"总解压 {_ZIP_MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MiB），"
                                    "已保留压缩包，请人工检查。"
                                )
                                break

                        if not warning and not eligible:
                            warning = "邮件 ZIP 中没有可识别的 PDF、OFD 或图片，已保留压缩包，请人工检查。"

                        if not warning:
                            actual_total_size = 0
                            for member, inner_name, inner_ext in eligible:
                                inner_payload = _read_zip_member_limited(
                                    zf, member, _ZIP_MAX_UNCOMPRESSED_BYTES - actual_total_size
                                )
                                if inner_payload is None:
                                    warning = (
                                        f"邮件 ZIP 超过安全展开限制（最多 {_ZIP_MAX_FILES} 个文件、"
                                        f"总解压 {_ZIP_MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MiB），"
                                        "已保留压缩包，请人工检查。"
                                    )
                                    break
                                actual_total_size += len(inner_payload)
                                if len(inner_payload) != member.file_size:
                                    warning = "邮件 ZIP 内容不完整或超出安全展开限制，已保留压缩包，请人工检查。"
                                    break
                                if not _payload_matches_extension(inner_payload, inner_ext):
                                    warning = "邮件 ZIP 内文件格式校验失败，已保留压缩包，请人工检查。"
                                    break

                                inner_lower = inner_name.lower()
                                member_has_invoice_name = any(
                                    k in inner_lower for k in _INVOICE_NAME_KW
                                )
                                member_is_extra = any(k in inner_lower for k in _EXTRA_NAME_KW)
                                # Explicit invoice filenames inside an archive take
                                # precedence over a broad parent name such as 明细.zip.
                                is_extra = member_is_extra or (
                                    c["is_ext"] and not member_has_invoice_name
                                )
                                is_invoice = (
                                    inner_ext in _INVOICE_EXTS or member_has_invoice_name
                                ) and not is_extra
                                staged_members.append((
                                    inner_name, len(inner_payload), inner_payload,
                                    is_invoice, is_extra,
                                ))
                except Exception:
                    # No extracted member is written until the archive has passed every check.
                    warning = "邮件 ZIP 无法安全读取，已保留压缩包，请人工检查。"
                    _log.warning("  邮件 ZIP 读取失败，已保留待人工检查: %s", mask_filename(filename))

                if warning:
                    results.append(self._save_problem_archive(
                        date_dir, filename, c["ct"], archive_payload, warning, date_str
                    ))
                    _log.warning("  邮件 ZIP 未完整展开，已保留待人工检查: %s", mask_filename(filename))
                    continue

                written_paths: list[Path] = []
                extracted: list[Attachment] = []
                try:
                    for inner_name, size, inner_payload, is_invoice, is_extra in staged_members:
                        combined_name = f"{os.path.splitext(filename)[0]}_{inner_name}"
                        dest = self._write_unique_file(
                            date_dir, combined_name, inner_payload, date_str
                        )
                        written_paths.append(dest)
                        extracted.append(Attachment(
                            file_path=str(dest),
                            original_name=inner_name,
                            content_type="application/octet-stream",
                            size=size,
                            is_invoice=is_invoice,
                            is_extra=is_extra,
                        ))
                except OSError:
                    for written_path in written_paths:
                        try:
                            written_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                    warning = "邮件 ZIP 解压文件无法安全保存，已保留压缩包，请人工检查。"
                    results.append(self._save_problem_archive(
                        date_dir, filename, c["ct"], archive_payload, warning, date_str
                    ))
                    _log.warning("  邮件 ZIP 保存失败，已保留待人工检查: %s", mask_filename(filename))
                    continue

                results.extend(extracted)
                for att in extracted:
                    _log.info("  附件(解压): %s (%d bytes) %s",
                              mask_filename(att.original_name), att.size,
                              "[发票]" if att.is_invoice else ("[附加材料]" if att.is_extra else ""))
                continue

            if not payload:
                continue
            if not _payload_matches_extension(payload, ext):
                _log.warning("  Attachment content does not match extension, skipped: %s", mask_filename(filename))
                continue
            dest = self._write_unique_file(date_dir, filename, payload, date_str)

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

    def _write_unique_file(
        self, date_dir: Path, original_name: str, payload: bytes, date_str: str
    ) -> Path:
        safe_name = build_managed_attachment_name(
            original_name=original_name,
            fallback_date=date_str,
        )
        base = Path(safe_name)
        attempt = 0
        while True:
            candidate_name = (
                f"{base.stem}_{attempt}{base.suffix}" if attempt else safe_name
            )
            dest = date_dir / candidate_name
            try:
                with dest.open("xb") as stream:
                    stream.write(payload)
                return dest
            except FileExistsError:
                attempt += 1
            except OSError:
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
                raise

    def _save_problem_archive(
        self,
        date_dir: Path,
        filename: str,
        content_type: str,
        payload: bytes,
        warning: str,
        date_str: str,
    ) -> Attachment:
        dest = self._write_unique_file(date_dir, filename, payload, date_str)
        return Attachment(
            file_path=str(dest),
            original_name=filename,
            content_type=content_type,
            size=len(payload),
            extraction_warning=warning,
        )
