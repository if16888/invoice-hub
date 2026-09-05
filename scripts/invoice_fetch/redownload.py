"""Non-GUI invoice redownload application workflow.

The review workbench owns the request and result presentation, while this
module owns the potentially slow link/IMAP, parser, filesystem, and SQLite
operations.  It intentionally keeps the existing redownload decision tree
and outcome buckets intact; the only new boundary is that callers provide an
immutable invoice snapshot and a database path.
"""

from __future__ import annotations

import os
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from . import credentials as _credentials
from . import config as _config
from . import invoice_parser as _invoice_parser
from . import mail_fetcher as _mail_fetcher
from . import attachment_handler as _attachment_handler

try:
    from . import link_downloader as _link_downloader
except ImportError:
    # Keep the application module importable on minimal/headless installs;
    # the worker reports the missing optional downloader dependency when the
    # operation actually starts.
    _link_downloader = None
from .db import InvoiceDB
from .log_privacy import mask_email, sanitize_log_message
from .scan_lifecycle import ScanCancelled, ScanControl

RUNTIME_DIR = _config.RUNTIME_DIR

REDOWNLOAD_MODE_BATCH = "batch_redownload"
REDOWNLOAD_MODE_DETAIL_LINK_RETRY = "detail_link_retry"


REDOWNLOAD_BUCKETS = (
    "file_restored",
    "metadata_refreshed",
    "duplicate_only",
    "download_failed",
    "no_candidate_link",
)


@dataclass(frozen=True)
class RedownloadInvoiceSnapshot:
    """Minimal immutable invoice input required by the redownload workflow."""

    invoice_id: int
    download_url: str = ""
    mail_uid: int | None = None
    mail_date: str = ""
    invoice_date: str = ""
    expense_date: str = ""
    mailbox_key: str = "legacy"
    mail_subject: str = ""
    mail_sender: str = ""
    invoice_type: str = ""
    has_extra: bool = False
    invoice_code: str = ""
    invoice_number: str = ""
    category: str = ""
    total_amount: str = ""
    attachment_path: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "RedownloadInvoiceSnapshot":
        raw_uid = value.get("mail_uid")
        try:
            mail_uid = int(raw_uid) if raw_uid not in (None, "") else None
        except (TypeError, ValueError):
            mail_uid = None
        raw_id = value.get("invoice_id", value.get("id", 0))
        try:
            invoice_id = int(raw_id or 0)
        except (TypeError, ValueError):
            invoice_id = 0
        return cls(
            invoice_id=invoice_id,
            download_url=str(value.get("download_url") or ""),
            mail_uid=mail_uid,
            mail_date=str(value.get("mail_date") or ""),
            invoice_date=str(value.get("invoice_date") or ""),
            expense_date=str(value.get("expense_date") or ""),
            mailbox_key=str(value.get("mailbox_key") or "legacy"),
            mail_subject=str(value.get("mail_subject") or ""),
            mail_sender=str(value.get("mail_sender") or ""),
            invoice_type=str(value.get("invoice_type") or ""),
            has_extra=bool(value.get("has_extra") or False),
            invoice_code=str(value.get("invoice_code") or ""),
            invoice_number=str(value.get("invoice_number") or ""),
            category=str(value.get("category") or ""),
            total_amount=str(value.get("total_amount") or ""),
            attachment_path=str(value.get("attachment_path") or ""),
        )


def _bucket_redownload_status(status: str) -> str:
    if status == "file_restored":
        return "file_restored"
    if status in {"metadata_refreshed", "manual_required", "recorded"}:
        return "metadata_refreshed"
    if status == "duplicate":
        return "duplicate_only"
    if status == "no_candidate_link":
        return "no_candidate_link"
    return "download_failed"


def _resolve_stored_attachment(raw_path: str, runtime_dir: Path) -> Path | None:
    """Resolve a stored attachment path without importing GUI helpers."""

    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path

    runtime_dir = Path(runtime_dir)
    project_root = runtime_dir.parent
    candidates = [
        runtime_dir / path,
        runtime_dir / "attachments" / path,
        project_root / path,
        project_root / "runtime" / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    filename = path.name
    if filename:
        for root in (
            runtime_dir / "attachments",
            runtime_dir,
            project_root / "runtime" / "attachments",
        ):
            if not root.exists():
                continue
            matches = [item for item in root.rglob(filename) if item.is_file()]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1 and len(path.parts) >= 2:
                suffix = Path(*path.parts[-2:])
                suffix_matches = [item for item in matches if str(item).endswith(str(suffix))]
                if len(suffix_matches) == 1:
                    return suffix_matches[0]
                return matches[0]
    return candidates[0]


def _is_file_valid_and_openable(path: Path | None) -> bool:
    if not path:
        return False
    try:
        if not path.exists():
            return False
        with path.open("rb") as handle:
            handle.read(10)
        return True
    except Exception:
        return False


def _safe_failure(text: object, secrets: Iterable[object] = ()) -> str:
    rendered = str(text or "")
    for secret in secrets:
        secret_text = str(secret or "")
        if secret_text:
            rendered = rendered.replace(secret_text, "<redacted>")
    return sanitize_log_message(rendered)


def _emit_log(callback: Callable[[str], object] | None, message: object) -> None:
    safe = _safe_failure(message)
    if callback is not None:
        callback(safe)


def _emit_progress(
    callback: Callable[[dict], object] | None,
    *,
    processed: int,
    total: int,
    invoice_id: int | None = None,
    status: str = "processing",
    cancelled: bool = False,
) -> None:
    if callback is None:
        return
    callback(
        {
            "processed": int(processed),
            "total": int(total),
            "invoice_id": int(invoice_id) if invoice_id is not None else None,
            "status": str(status or "processing"),
            "cancelled": bool(cancelled),
        }
    )


def _coerce_snapshots(
    snapshots: Iterable[RedownloadInvoiceSnapshot | Mapping[str, object]],
) -> tuple[RedownloadInvoiceSnapshot, ...]:
    result = []
    for item in snapshots:
        if isinstance(item, RedownloadInvoiceSnapshot):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(RedownloadInvoiceSnapshot.from_mapping(item))
        else:
            raise TypeError("redownload snapshots must be mappings")
    return tuple(result)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8192):
            digest.update(chunk)
    return digest.hexdigest()


def _detail_date_directory(snapshot: RedownloadInvoiceSnapshot) -> str:
    raw_date = snapshot.invoice_date or snapshot.mail_date or "unknown_date"
    return raw_date[:10] if "-" in raw_date else "unknown_date"


def _snapshot_attachment_files(attachments_root: Path) -> set[Path] | None:
    """Capture the only provenance that permits later rollback deletion.

    ``None`` means provenance could not be established. Rollback must fail
    closed in that state rather than assuming the directory was empty.
    """

    root = Path(attachments_root)
    if not root.exists():
        return set()
    try:
        return {path.resolve() for path in root.rglob("*") if path.is_file()}
    except OSError:
        return None


def _rollback_created_attachment(
    path: str | Path | None,
    *,
    attachments_root: Path,
    preexisting_files: set[Path] | None,
) -> bool:
    """Delete only a file proven to have been created by this attempt."""

    if not path or preexisting_files is None:
        return False
    try:
        candidate = Path(path).resolve()
        root = Path(attachments_root).resolve()
        if candidate in preexisting_files:
            return False
        if candidate != root and root not in candidate.parents:
            return False
        if not candidate.is_file():
            return False
        candidate.unlink()
        return True
    except OSError:
        return False


def _restore_invoice_state(db: InvoiceDB, original: Mapping[str, object] | None) -> None:
    """Best-effort compensation after a multi-step DB write fails."""

    if not original:
        return
    invoice_id = int(original.get("id") or original.get("invoice_id") or 0)
    if invoice_id <= 0:
        return
    try:
        db.update_invoice_parsed_metadata(
            invoice_id=invoice_id,
            invoice_number=str(original.get("invoice_number") or ""),
            invoice_code=str(original.get("invoice_code") or ""),
            invoice_date=str(original.get("invoice_date") or ""),
            amount=str(original.get("amount") or ""),
            total_amount=str(original.get("total_amount") or ""),
            seller_name=str(original.get("seller_name") or ""),
            buyer_name=str(original.get("buyer_name") or ""),
            invoice_type=str(original.get("invoice_type") or ""),
            category=str(original.get("category") or ""),
            has_extra=bool(original.get("has_extra")),
            extra_type=str(original.get("extra_type") or ""),
            missing_extra=bool(original.get("missing_extra")),
            parse_success=bool(original.get("parse_success")),
            parse_note=str(original.get("parse_note") or ""),
            item_name=str(original.get("item_name") or ""),
            expense_date=str(original.get("expense_date") or ""),
            date_source=str(original.get("date_source") or ""),
        )
        db.update_invoice_file_paths(
            invoice_id,
            attachment_path=str(original.get("attachment_path") or ""),
            file_hash=str(original.get("file_hash") or ""),
        )
    except Exception:
        pass


def _persist_attachment_reference(
    db: InvoiceDB,
    *,
    invoice_id: int,
    attachment_path: str,
    file_hash: str | None = None,
    original: Mapping[str, object] | None = None,
) -> bool:
    """Persist an attachment through the public DB API and compensate on failure."""

    try:
        updated = db.update_invoice_file_paths(
            invoice_id,
            attachment_path=attachment_path,
            file_hash=file_hash,
        )
    except Exception:
        updated = False
    if updated:
        return True
    if original is not None:
        _restore_invoice_state(db, original)
    return False


def _update_unparsed_direct_download(
    db: InvoiceDB,
    *,
    original: Mapping[str, object] | None,
    attachment_path: str,
    parse_note: str,
) -> bool:
    """Preserve business fields while recording a non-parsed direct download."""

    if not original:
        return False
    invoice_id = int(original.get("id") or original.get("invoice_id") or 0)
    if invoice_id <= 0:
        return False
    try:
        metadata_updated = db.update_invoice_parsed_metadata(
            invoice_id=invoice_id,
            invoice_number=str(original.get("invoice_number") or ""),
            invoice_code=str(original.get("invoice_code") or ""),
            invoice_date=str(original.get("invoice_date") or ""),
            amount=str(original.get("amount") or ""),
            total_amount=str(original.get("total_amount") or ""),
            seller_name=str(original.get("seller_name") or ""),
            buyer_name=str(original.get("buyer_name") or ""),
            invoice_type=str(original.get("invoice_type") or ""),
            category=str(original.get("category") or ""),
            has_extra=bool(original.get("has_extra")),
            extra_type=str(original.get("extra_type") or ""),
            missing_extra=bool(original.get("missing_extra")),
            parse_success=False,
            parse_note=parse_note,
            item_name=str(original.get("item_name") or ""),
            expense_date=str(original.get("expense_date") or ""),
            date_source=str(original.get("date_source") or ""),
        )
    except Exception:
        metadata_updated = False
    if not metadata_updated:
        return False
    if _persist_attachment_reference(
        db,
        invoice_id=invoice_id,
        attachment_path=attachment_path,
        original=original,
    ):
        return True
    _restore_invoice_state(db, original)
    return False


def run_invoice_link_retry(
    snapshot: RedownloadInvoiceSnapshot | Mapping[str, object],
    db_path: str | Path,
    *,
    runtime_dir: str | Path = RUNTIME_DIR,
    config: Mapping[str, object] | None = None,
    scan_control: ScanControl | None = None,
    log_callback: Callable[[str], object] | None = None,
    progress_callback: Callable[[dict], object] | None = None,
) -> dict:
    """Retry the current detail invoice's direct link without parsing or IMAP.

    This deliberately mirrors the legacy ``_retry_download_link`` contract:
    only the requested invoice is touched, a successful PDF/OFD download is
    retained even when no parser is available, and only attachment path/hash
    plus the downloader's parse note are written back to the existing row.
    """

    del config  # Kept in the common worker signature; detail retry uses no config data.
    item = _coerce_snapshots([snapshot])[0]
    total = 1
    control = scan_control or ScanControl()
    runtime_dir = Path(runtime_dir)
    attachments_root = runtime_dir / "attachments"
    downloader = None
    db = None
    downloaded = None
    final_path: Path | None = None
    preexisting_files: set[Path] | None = set()
    persisted = False

    def result(*, success: bool, cancelled: bool = False, failure_detail: str = "") -> dict:
        return {
            "mode": REDOWNLOAD_MODE_DETAIL_LINK_RETRY,
            "invoice_id": int(item.invoice_id),
            "requested_count": total,
            "completed_count": 1 if success else 0,
            "success": bool(success),
            "cancelled": bool(cancelled),
            "failure_detail": _safe_failure(failure_detail) if failure_detail else "",
        }

    try:
        control.raise_if_cancelled()
        if item.invoice_id <= 0:
            return result(success=False, failure_detail="无效发票记录")
        if not item.download_url.strip():
            return result(success=False, failure_detail="没有可用的直接下载链接")

        link_downloader = _link_downloader
        if link_downloader is None:
            from . import link_downloader

        db = InvoiceDB(db_path)
        original_invoice = db.get_invoice(item.invoice_id)
        downloader = link_downloader.LinkDownloader(
            download_dir=attachments_root,
        )
        date_dir_name = _detail_date_directory(item)
        preexisting_files = _snapshot_attachment_files(attachments_root)
        _emit_progress(
            progress_callback,
            processed=0,
            total=total,
            invoice_id=item.invoice_id,
            status="detail_link_retry",
        )
        downloaded = downloader._download_url(
            item.download_url,
            item.mail_uid or 0,
            999,
            date_dir_name,
        )
        # The downloader call is the active, non-interruptible boundary.  Do
        # not begin file moves or DB writes after a cancellation has arrived.
        control.raise_if_cancelled()
        if not downloaded or not downloaded.file_path:
            return result(success=False, failure_detail="未能从链接获取官方 PDF/OFD")

        source_path = Path(downloaded.file_path)
        if not source_path.is_file():
            return result(success=False, failure_detail="下载文件不存在")

        destination_dir = attachments_root / date_dir_name
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_name = _attachment_handler.build_managed_attachment_name(
            original_name=source_path.name,
            invoice_date=item.invoice_date,
            expense_date=item.expense_date,
            fallback_date=item.mail_date,
            category=item.category,
            total_amount=item.total_amount,
            invoice_number=item.invoice_number,
            role="原件",
        )
        extension = source_path.suffix.lower()
        if not destination_name.lower().endswith(extension):
            destination_name = f"{Path(destination_name).stem}{extension}"

        destination_path = destination_dir / destination_name
        if destination_path.resolve() != source_path.resolve():
            if destination_path.exists():
                stem = destination_path.stem
                for number in range(1, 100):
                    candidate = destination_dir / f"{stem}_{number}{extension}"
                    if not candidate.exists():
                        destination_path = candidate
                        break
            shutil.move(str(source_path), str(destination_path))
        final_path = destination_path

        file_hash = _sha256_file(destination_path)
        relative_path = f"attachments/{date_dir_name}/{destination_path.name}"
        if not _persist_attachment_reference(
            db,
            invoice_id=item.invoice_id,
            attachment_path=relative_path,
            file_hash=file_hash,
            original=original_invoice,
        ):
            _rollback_created_attachment(
                destination_path,
                attachments_root=attachments_root,
                preexisting_files=preexisting_files,
            )
            return result(success=False, failure_detail="附件路径写入失败")
        persisted = True
        parse_note = getattr(downloaded, "parse_note", None)
        if parse_note:
            db.update_invoice_missing_fields(
                item.invoice_id,
                {"parse_note": parse_note},
                only_if_empty=False,
            )

        _emit_log(log_callback, f"✅ [重新下载] 发票 ID {item.invoice_id} 原件下载并关联成功")
        _emit_progress(
            progress_callback,
            processed=1,
            total=total,
            invoice_id=item.invoice_id,
            status="file_restored",
        )
        return result(success=True)
    except ScanCancelled:
        if not persisted:
            rollback_path = final_path
            if rollback_path is None and downloaded is not None and getattr(downloaded, "file_path", None):
                rollback_path = Path(downloaded.file_path)
            _rollback_created_attachment(
                rollback_path,
                attachments_root=attachments_root,
                preexisting_files=preexisting_files,
            )
        _emit_progress(
            progress_callback,
            processed=0,
            total=total,
            invoice_id=item.invoice_id,
            status="cancelled",
            cancelled=True,
        )
        return result(success=False, cancelled=True)
    except Exception as exc:
        if not persisted:
            rollback_path = final_path
            if rollback_path is None and downloaded is not None and getattr(downloaded, "file_path", None):
                rollback_path = Path(downloaded.file_path)
            _rollback_created_attachment(
                rollback_path,
                attachments_root=attachments_root,
                preexisting_files=preexisting_files,
            )
        _emit_log(log_callback, f"❌ [重新下载] 发票 ID {item.invoice_id} 详情链接下载失败")
        return result(success=False, failure_detail=f"{type(exc).__name__}")
    finally:
        if downloader is not None:
            try:
                downloader.close()
            except Exception:
                pass
        if db is not None:
            db.close()


def run_invoice_redownload(
    snapshots: Iterable[RedownloadInvoiceSnapshot | Mapping[str, object]],
    db_path: str | Path,
    *,
    runtime_dir: str | Path = RUNTIME_DIR,
    config: Mapping[str, object] | None = None,
    scan_control: ScanControl | None = None,
    log_callback: Callable[[str], object] | None = None,
    progress_callback: Callable[[dict], object] | None = None,
) -> dict:
    """Execute the existing redownload workflow outside the GUI thread.

    All objects which touch the network, parser, filesystem, or SQLite are
    created and closed in this call.  The returned dictionary contains only
    structured, privacy-safe data suitable for a queued GUI signal.
    """

    items = _coerce_snapshots(snapshots)
    total = len(items)
    control = scan_control or ScanControl()
    runtime_dir = Path(runtime_dir)
    attachments_root = runtime_dir / "attachments"
    cfg = dict(config) if isinstance(config, Mapping) else _config.load_config_safe()
    categories = cfg.get("categories", {}) if isinstance(cfg, dict) else {}
    if not isinstance(categories, dict):
        categories = {}
    accounts = _config.get_email_accounts(cfg)
    default_account = {
        "mailbox_key": "legacy",
        "address": (cfg.get("email", {}) or {}).get("address", ""),
        "auth_code": "",
        "imap": cfg.get("imap", {}) or {},
        "search": cfg.get("search", {}) or {},
    }
    account_map = {
        str(account.get("mailbox_key") or "legacy"): account
        for account in accounts
    }

    buckets = {key: 0 for key in REDOWNLOAD_BUCKETS}
    failure_details: list[str] = []
    invoice_results: list[dict] = []
    processed = 0
    success_count = 0
    failed_count = 0
    no_url_count = 0
    reread_count = 0
    reread_success_count = 0
    reread_failed_count = 0
    cancelled = False
    downloader = None
    parser = None
    att_handler = None
    db = InvoiceDB(db_path)
    mail_fetchers: dict[str, tuple[object, object]] = {}
    secrets: set[str] = set()
    link_downloader = _link_downloader
    if link_downloader is None:
        from . import link_downloader as link_downloader

    def ensure_mail_fetcher(mailbox_key: str):
        key = str(mailbox_key or "legacy")
        cached = mail_fetchers.get(key)
        if cached is not None:
            return cached[0]

        account = account_map.get(key, default_account)
        email_addr = str(account.get("address") or "")
        if not email_addr or email_addr == "your_email@qq.com":
            raise ValueError("请先在[设置]中配置邮箱账号")
        try:
            auth_code_configured = _credentials.has_auth_code(email_addr)
        except Exception as exc:
            raise RuntimeError(
                f"读取邮箱 {mask_email(email_addr)} 授权配置失败 ({type(exc).__name__})"
            ) from None
        if not auth_code_configured:
            raise ValueError(f"邮箱账号 {mask_email(email_addr)} 未配置授权码，请先在[设置]中配置")

        try:
            auth_code = _credentials.get_auth_code(email_addr)
        except Exception as exc:
            # Do not propagate a credential-provider exception verbatim: some
            # providers include the secret or a credential-bearing payload in
            # their error text.
            raise RuntimeError(
                f"读取邮箱 {mask_email(email_addr)} 授权配置失败 ({type(exc).__name__})"
            ) from None
        if auth_code:
            secrets.add(str(auth_code))
        imap_cfg = account.get("imap") or cfg.get("imap", {})
        _emit_log(log_callback, f"📥 [重新下载] 连接 IMAP {mask_email(email_addr)} ...")
        mail_fetcher_cm = _mail_fetcher.MailFetcher(
            address=email_addr,
            auth_code=auth_code,
            server=imap_cfg.get("server", "imap.qq.com"),
            port=imap_cfg.get("port", 993),
            control=control,
        )
        try:
            mail_fetcher = mail_fetcher_cm.__enter__()
        except Exception:
            # A failed context-manager enter may still have allocated a
            # socket/registration.  Close it in the same worker thread before
            # allowing this invoice to continue through its existing failure
            # path.
            try:
                mail_fetcher_cm.__exit__(None, None, None)
            except Exception:
                pass
            raise
        mail_fetchers[key] = (mail_fetcher, mail_fetcher_cm)
        return mail_fetcher

    try:
        control.raise_if_cancelled()
        downloader = link_downloader.LinkDownloader(
            download_dir=attachments_root,
        )
        parser = _invoice_parser.InvoiceParser()
        att_handler = _attachment_handler.AttachmentHandler(attachments_root)

        for inv in items:
            if control.cancelled:
                cancelled = True
                break
            inv_id = int(inv.invoice_id)
            download_url = inv.download_url
            mail_uid = inv.mail_uid
            mail_date = inv.mail_date or inv.invoice_date or "unknown_date"
            direct_download_ok = False
            fallback_reason = ""
            status = "download_failed"
            failure_detail = ""

            if download_url:
                preexisting_files = _snapshot_attachment_files(attachments_root)
                final_path: Path | None = None
                try:
                    dl = downloader._download_url(download_url, mail_uid or 0, inv_id, mail_date)
                    if dl and dl.file_path and os.path.exists(dl.file_path):
                        suffix = os.path.splitext(dl.file_path)[1].lower()
                        original_invoice = db.get_invoice(inv_id)
                        if suffix == ".pdf":
                            info = parser.parse_pdf(dl.file_path)
                            if info.parse_success:
                                from . import services as _services

                                cat, extra_type, extra_req = _services._classify(
                                    inv.mail_subject,
                                    inv.mail_sender,
                                    info.seller_name,
                                    categories,
                                )
                                code = info.invoice_code or info.invoice_number
                                att_path = _services._rename_by_invoice_code(
                                    dl.file_path,
                                    code,
                                    info.invoice_date or mail_date,
                                    attachments_root,
                                    category=cat,
                                    total_amount=info.total_amount,
                                    invoice_number=info.invoice_number,
                                    source_mode="reprocess",
                                )
                                final_path = _resolve_stored_attachment(att_path, runtime_dir)
                                updated = db.update_invoice_parsed_metadata(
                                    invoice_id=inv_id,
                                    invoice_number=info.invoice_number,
                                    invoice_code=info.invoice_code,
                                    invoice_date=info.invoice_date,
                                    amount=info.amount,
                                    total_amount=info.total_amount,
                                    seller_name=info.seller_name,
                                    buyer_name=info.buyer_name,
                                    invoice_type=info.invoice_type or inv.invoice_type or "电子发票",
                                    category=cat,
                                    has_extra=inv.has_extra,
                                    extra_type=extra_type,
                                    missing_extra=extra_req,
                                    parse_success=True,
                                    parse_note="重新下载后解析",
                                    item_name=getattr(info, "item_name", ""),
                                    expense_date=getattr(info, "expense_date", ""),
                                    date_source=getattr(info, "date_source", ""),
                                )
                                if not updated:
                                    _rollback_created_attachment(
                                        final_path,
                                        attachments_root=attachments_root,
                                        preexisting_files=preexisting_files,
                                    )
                                    if getattr(db, "last_error", "") == "unique_conflict":
                                        fallback_reason = "解析结果与已有发票唯一键冲突"
                                        _emit_log(
                                            log_callback,
                                            f"⚠️ [重新下载] 发票 ID {inv_id} 更新元数据时发生唯一键冲突，尝试回读邮件",
                                        )
                                    else:
                                        fallback_reason = "解析结果写入数据库失败"
                                elif not _persist_attachment_reference(
                                    db,
                                    invoice_id=inv_id,
                                    attachment_path=att_path,
                                    original=original_invoice,
                                ):
                                    _rollback_created_attachment(
                                        final_path,
                                        attachments_root=attachments_root,
                                        preexisting_files=preexisting_files,
                                    )
                                    fallback_reason = "附件路径写入数据库失败"
                                else:
                                    success_count += 1
                                    buckets["file_restored"] += 1
                                    status = "file_restored"
                                    direct_download_ok = True
                                    _emit_log(log_callback, f"✅ [重新下载] 发票 ID {inv_id} 链接下载成功")
                            else:
                                fallback_reason = f"链接下载后解析失败: {info.parse_note}"
                                if os.path.exists(dl.file_path):
                                    _emit_log(
                                        log_callback,
                                        f"⚠️ [重新下载] 发票 ID {inv_id} 下载的文件是 PDF 但解析失败，正在清理本次临时文件: {dl.file_path}",
                                    )
                                    _rollback_created_attachment(
                                        Path(dl.file_path),
                                        attachments_root=attachments_root,
                                        preexisting_files=preexisting_files,
                                    )
                        elif suffix == ".ofd":
                            from . import services as _services

                            code = inv.invoice_code or inv.invoice_number
                            inv_date = inv.invoice_date or mail_date or "unknown_date"
                            cat = inv.category or "其他"
                            att_path = _services._rename_by_invoice_code(
                                dl.file_path,
                                code,
                                inv_date,
                                attachments_root,
                                category=cat,
                                total_amount=inv.total_amount,
                                invoice_number=inv.invoice_number,
                                source_mode="reprocess",
                            )
                            final_path = _resolve_stored_attachment(att_path, runtime_dir)
                            note = "OFD 原件已恢复，需手动处理/转换后再解析。"
                            if _update_unparsed_direct_download(
                                db,
                                original=original_invoice,
                                attachment_path=att_path,
                                parse_note=note,
                            ):
                                _emit_log(log_callback, f"✅ [重新下载] 发票 ID {inv_id} {note}")
                                buckets["metadata_refreshed"] += 1
                                status = "metadata_refreshed"
                                direct_download_ok = True
                            else:
                                _rollback_created_attachment(
                                    final_path,
                                    attachments_root=attachments_root,
                                    preexisting_files=preexisting_files,
                                )
                                fallback_reason = "OFD 原件写入数据库失败"
                        else:
                            from . import services as _services

                            code = inv.invoice_code or inv.invoice_number
                            inv_date = inv.invoice_date or mail_date or "unknown_date"
                            cat = inv.category or "其他"
                            att_path = _services._rename_by_invoice_code(
                                dl.file_path,
                                code,
                                inv_date,
                                attachments_root,
                                category=cat,
                                total_amount=inv.total_amount,
                                invoice_number=inv.invoice_number,
                                source_mode="reprocess",
                            )
                            final_path = _resolve_stored_attachment(att_path, runtime_dir)
                            note = f"下载了不支持的文件类型 ({suffix})，需手动处理。"
                            if _update_unparsed_direct_download(
                                db,
                                original=original_invoice,
                                attachment_path=att_path,
                                parse_note=note,
                            ):
                                _emit_log(log_callback, f"✅ [重新下载] 发票 ID {inv_id} {note}")
                                buckets["metadata_refreshed"] += 1
                                status = "metadata_refreshed"
                                direct_download_ok = True
                            else:
                                _rollback_created_attachment(
                                    final_path,
                                    attachments_root=attachments_root,
                                    preexisting_files=preexisting_files,
                                )
                                fallback_reason = "下载文件写入数据库失败"
                    else:
                        fallback_reason = "下载超时或链接失效"
                except Exception as exc:
                    if final_path is not None:
                        _rollback_created_attachment(
                            final_path,
                            attachments_root=attachments_root,
                            preexisting_files=preexisting_files,
                        )
                    fallback_reason = _safe_failure(f"链接下载异常: {exc}", secrets)

            if not direct_download_ok:
                # A cancellation requested while a direct link operation was
                # finishing must not start a new IMAP fallback for this item.
                control.raise_if_cancelled()
                if not mail_uid:
                    no_url_count += 1
                    failed_count += 1
                    failure_detail = fallback_reason or "无邮件 UID，无法重新读取邮件"
                    if download_url or fallback_reason:
                        buckets["download_failed"] += 1
                        status = "download_failed"
                    else:
                        buckets["no_candidate_link"] += 1
                        status = "no_candidate_link"
                    failure_detail = _safe_failure(failure_detail, secrets)
                    failure_details.append(f"发票 ID {inv_id}: {failure_detail}")
                    _emit_log(log_callback, f"❌ [重新下载] 发票 ID {inv_id} {failure_detail}")
                else:
                    reread_count += 1
                    if not download_url:
                        no_url_count += 1
                    try:
                        from . import services as _services

                        mailbox_key = str(inv.mailbox_key or "legacy")
                        account = account_map.get(mailbox_key, default_account)
                        mailbox_folder = account.get("search", {}).get("folder", "INBOX")
                        fetcher = ensure_mail_fetcher(mailbox_key)
                        _emit_log(
                            log_callback,
                            f"↩️ [重新下载] 发票 ID {inv_id} {fallback_reason or '无下载链接'}，改为重新读取邮件 UID={mail_uid}",
                        )
                        reread_ok = _services._handle_pending_email(
                            row={"uid": mail_uid, "mail_date": mail_date, "mailbox_key": mailbox_key},
                            fetcher=fetcher,
                            folder=mailbox_folder,
                            att_handler=att_handler,
                            parser=parser,
                            link_dl=downloader,
                            db=db,
                            categories=categories,
                        )
                        reread_status = getattr(reread_ok, "status", "")
                        if reread_ok:
                            raw_status = reread_status or "recorded"
                            if raw_status == "duplicate":
                                refreshed = db.get_invoice(inv_id)
                                refreshed_att_path = refreshed.get("attachment_path") if refreshed else None
                                resolved_path = _resolve_stored_attachment(refreshed_att_path, runtime_dir) if refreshed_att_path else None
                                if not _is_file_valid_and_openable(resolved_path):
                                    raw_status = "download_failed"
                            status = _bucket_redownload_status(raw_status)
                            buckets[status] += 1
                            if status == "file_restored":
                                success_count += 1
                                reread_success_count += 1
                                _emit_log(log_callback, f"✅ [重新下载] 发票 ID {inv_id} 已通过重新读取邮件修复原文件")
                            elif status == "metadata_refreshed":
                                _emit_log(log_callback, f"ℹ️ [重新下载] 发票 ID {inv_id} 仅刷新元数据或仍需手动下载")
                            elif status == "duplicate_only":
                                _emit_log(log_callback, f"ℹ️ [重新下载] 发票 ID {inv_id} 仅命中已有重复记录")
                            else:
                                reread_failed_count += 1
                                failed_count += 1
                                diagnostics = getattr(downloader, "last_download_diagnostics", {}) or {}
                                attempted = int(diagnostics.get("attempted", 0) or 0)
                                failed = int(diagnostics.get("failed", 0) or 0)
                                fail_reason = (
                                    "链接下载失败并且未恢复原件"
                                    if attempted > 0 and failed > 0
                                    else "未恢复原件文件"
                                )
                                failure_details.append(f"发票 ID {inv_id}: {fail_reason}")
                                _emit_log(log_callback, f"❌ [重新下载] 发票 ID {inv_id} 重新读取邮件后仍未成功恢复原件")
                        elif reread_status == "no_candidate_link":
                            status = "no_candidate_link"
                            buckets["no_candidate_link"] += 1
                            reread_failed_count += 1
                            failed_count += 1
                            failure_details.append(f"发票 ID {inv_id}: 无候选下载链接")
                            _emit_log(log_callback, f"⚠️ [重新下载] 发票 ID {inv_id} 无候选下载链接")
                        else:
                            status = "download_failed"
                            reread_failed_count += 1
                            failed_count += 1
                            buckets["download_failed"] += 1
                            failure_details.append(f"发票 ID {inv_id}: 重新读取邮件后仍未成功入库")
                            _emit_log(log_callback, f"⚠️ [重新下载] 发票 ID {inv_id} 重新读取邮件后仍未成功入库")
                    except ScanCancelled:
                        cancelled = True
                        break
                    except Exception as exc:
                        status = "download_failed"
                        reread_failed_count += 1
                        failed_count += 1
                        buckets["download_failed"] += 1
                        detail = _safe_failure(f"重新读取邮件失败 ({exc})", secrets)
                        failure_details.append(f"发票 ID {inv_id}: {detail}")
                        _emit_log(log_callback, f"❌ [重新下载] 发票 ID {inv_id} {detail}")

            processed += 1
            invoice_results.append({"invoice_id": inv_id, "status": status})
            _emit_progress(
                progress_callback,
                processed=processed,
                total=total,
                invoice_id=inv_id,
                status=status,
            )

    except ScanCancelled:
        cancelled = True
    except Exception as exc:
        # Keep fatal worker errors useful while ensuring a transport/provider
        # exception can never carry the temporary mailbox credential into the
        # result/error signal.
        raise RuntimeError(_safe_failure(exc, secrets)) from exc
    finally:
        if downloader is not None:
            try:
                downloader.close()
            except Exception:
                pass
        for _, mail_fetcher_cm in mail_fetchers.values():
            try:
                mail_fetcher_cm.__exit__(None, None, None)
            except Exception:
                pass
        db.close()

    if control.cancelled:
        cancelled = True
    if cancelled:
        _emit_progress(
            progress_callback,
            processed=processed,
            total=total,
            status="cancelled",
            cancelled=True,
        )
    return {
        "requested_count": total,
        "completed_count": processed,
        "success_count": success_count,
        "failed_count": failed_count,
        "cancelled": cancelled,
        "buckets": dict(buckets),
        "invoice_results": tuple(invoice_results),
        "failure_details": tuple(failure_details),
        "no_url_count": no_url_count,
        "reread_count": reread_count,
        "reread_success_count": reread_success_count,
        "reread_failed_count": reread_failed_count,
    }


__all__ = [
    "REDOWNLOAD_BUCKETS",
    "REDOWNLOAD_MODE_BATCH",
    "REDOWNLOAD_MODE_DETAIL_LINK_RETRY",
    "RedownloadInvoiceSnapshot",
    "run_invoice_link_retry",
    "run_invoice_redownload",
]
