"""CLI entry point — ``python -m scripts.invoice_fetch``

Usage:
    python -m scripts.invoice_fetch               # normal incremental run
    python -m scripts.invoice_fetch --scan-only   # scan and classify only
    python -m scripts.invoice_fetch --download-only # download pending invoices
    python -m scripts.invoice_fetch --classify-only # run AI on unclassified
    python -m scripts.invoice_fetch --reset       # clear processed list, re-scan
"""

from __future__ import annotations

import argparse
import email
import json
import hashlib
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .config import load_config, load_config_safe, RUNTIME_DIR, PROJECT_ROOT
from .credentials import get_auth_code
from .db import InvoiceDB
from .attachment_handler import AttachmentHandler
from .invoice_parser import InvoiceParser, parse_html_body, parse_subject
from .link_downloader import LinkDownloader, extract_html_from_message
from .mail_fetcher import MailFetcher
from .log_privacy import PrivacyLogFilter, mask_filename, mask_invoice_number, mask_path, mask_uid, redact_text
from .url_utils import _mask_url
from .rule_classifier import classify as rule_classify
from . import review_status

# Re-export selected classes for tests while keeping optional AI imports lazy.
def __getattr__(name: str):
    if name == "MailMessage":
        from .mail_fetcher import MailMessage
        return MailMessage
    if name == "AIClassifier":
        from .ai_classifier import AIClassifier
        return AIClassifier
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

_log = logging.getLogger("invoice_fetch")
_log.addFilter(PrivacyLogFilter())

STATUS_LABELS = {
    review_status.TO_REVIEW: "待审核",
    review_status.APPROVED: "已通过",
    review_status.IGNORED: "已忽略",
    review_status.ERROR: "异常",
}


def _status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or review_status.TO_REVIEW, status or review_status.TO_REVIEW)


RECEIPT_KEYWORDS = [
    "receipt", "e-receipt", "ereceipt", "folio", "hotel bill",
    "tax invoice", "trip receipt", "itinerary", "grab", "sgd",
    "singapore", ".sg", "changi", "restaurant", "dining", "meal",
    "food", "ride", "taxi", "水单", "行程单", "行程记录", "账单",
]

TRANSPORT_DETAIL_RULES = [
    ("火车票", ["火车票", "火车", "高铁", "动车", "铁路", "12306", "train", "rail"]),
    ("过路费", ["过路费", "通行费", "高速", "路桥", "etc", "toll", "expressway"]),
    ("出租车", ["出租车", "打车", "网约车", "用车", "滴滴", "曹操", "t3出行", "高德打车", "美团打车", "grab", "taxi", "cab", "ride"]),
]

DEFAULT_CATEGORY_RULES = [
    ("餐饮", ["海底捞", "餐饮", "餐厅", "饭店", "美食", "食品", "restaurant", "dining", "meal", "food"]),
    ("酒店住宿", ["酒店", "住宿", "hotel", "folio"]),
    ("通信", ["电信", "移动", "联通", "话费", "通信", "宽带", "流量"]),
    ("交通", ["changi", "airport", "机场", "行李", "地铁", "公交"]),
]

# ── Logging setup ────────────────────────────────────────────────────

def _setup_logging(verbose: bool = False):
    log_dir = RUNTIME_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt_console = logging.Formatter("[%(levelname)s] %(message)s")
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt_console)
    root.addHandler(ch)

    fmt_file = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    try:
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt_file)
        root.addHandler(fh)
    except OSError as exc:
        root.warning("Failed to open log file %s: %s", log_file, exc)

    # Suppress verbose third-party loggers to clean up output
    logging.getLogger("pdfminer").setLevel(logging.ERROR)


# ── CLI ──────────────────────────────────────────────────────────────

class ChineseHelpArgumentParser(argparse.ArgumentParser):
    """ArgumentParser with Chinese help text for the MVP CLI surface."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "--help", action="help", help="显示帮助信息并退出")
        self._positionals.title = "位置参数"
        self._optionals.title = "选项"

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法:", 1)

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "用法:", 1)


def _parse_args() -> argparse.Namespace:
    p = ChineseHelpArgumentParser(
        description="Invoice Hub - 本地优先的报销资料整理助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", default=None, help="配置文件路径")
    p.add_argument("--limit", type=int, default=None, help="最大处理邮件数")
    p.add_argument("--months", type=int, default=None, help="搜索最近N个月")
    p.add_argument("--reset", action="store_true", help="清空记录，重新扫描")
    p.add_argument("--export-only", action="store_true", help="仅重新生成Excel")
    p.add_argument("--scan-only", action="store_true", help="仅扫描邮件头并分类")
    p.add_argument("--download-only", action="store_true", help="仅下载已标记的发票邮件")
    p.add_argument("--classify-only", action="store_true", help="仅对未分类邮件执行AI分类")
    p.add_argument("--import-dir", action="append", default=[], help="导入本地发票目录，可重复指定")
    p.add_argument("--no-ai", action="store_true", help="跳过AI分类（仅用规则）")
    p.add_argument("--headed", action="store_true", help="显示浏览器窗口（用于人工辅助验证或下载）")
    p.add_argument("--retry-failed", action="store_true", help="重新尝试下载之前失败的发票链接")
    p.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    subparsers = p.add_subparsers(dest="command", help="子命令", parser_class=ChineseHelpArgumentParser)

    # claim-create
    p_create = subparsers.add_parser("claim-create", help="新建报销组")
    p_create.add_argument("--name", required=True, help="报销组名称")
    p_create.add_argument("--start", default="", help="开始日期 (YYYY-MM-DD)")
    p_create.add_argument("--end", default="", help="结束日期 (YYYY-MM-DD)")

    # claim-add
    p_add = subparsers.add_parser("claim-add", help="添加发票到报销组")
    p_add.add_argument("--claim-id", type=int, required=True, help="报销组ID")
    p_add.add_argument("--invoice-id", type=int, required=True, help="发票ID")
    p_add.add_argument("--note", default="", help="备注")

    # claim-export
    p_export = subparsers.add_parser("claim-export", help="导出报销包（已忽略或异常状态的发票将始终被排除）")
    p_export.add_argument("--claim-id", type=int, required=True, help="报销组ID")
    p_export.add_argument("--include-to-review", action="store_true", help="是否包含待审核发票记录")

    # invoice-list
    p_inv_list = subparsers.add_parser("invoice-list", help="列出发票记录")
    p_inv_list.add_argument("--status", choices=["to_review", "approved", "ignored", "error"], help="根据审核状态筛选发票")
    p_inv_list.add_argument("--limit", type=int, default=None, help="限制输出的记录数")

    # invoice-claimable
    subparsers.add_parser("invoice-claimable", help="列出所有已通过可报销发票（等同于 invoice-list --status approved）")

    # invoice-show
    p_inv_show = subparsers.add_parser("invoice-show", help="显示发票的完整字段详情")
    p_inv_show.add_argument("--invoice-id", type=int, required=True, help="发票ID")

    # invoice-review
    p_inv_review = subparsers.add_parser("invoice-review", help="更新发票的审核状态")
    p_inv_review.add_argument("--invoice-id", type=int, required=True, help="发票ID")
    p_inv_review.add_argument("--status", required=True, choices=["to_review", "approved", "ignored", "error"], help="审核状态")
    p_inv_review.add_argument("--note", default="", help="审核备注")

    # desktop
    p_desktop = subparsers.add_parser("desktop", help="启动 PySide6 发票审核桌面应用")
    p_desktop.add_argument(
        "--startup-probe",
        action="store_true",
        help="无头启动探针：渲染首帧后立即退出，用于 CI 启动性能验证",
    )

    # invoice-delete
    p_inv_del = subparsers.add_parser("invoice-delete", help="删除发票记录 (软删除)")
    p_inv_del.add_argument("--invoice-id", type=int, required=True, help="发票ID")

    # invoice-restore
    p_inv_rest = subparsers.add_parser("invoice-restore", help="恢复已软删除的发票记录")
    p_inv_rest.add_argument("--invoice-id", type=int, required=True, help="发票ID")

    return p.parse_args()


# ── Classify ─────────────────────────────────────────────────────────

def _classify(subject: str, sender: str, seller: str,
              categories: dict) -> tuple[str, str, bool]:
    """Return (category, extra_type, extra_required)."""
    if seller == "中国国家铁路集团有限公司":
        return "交通", "", False
    combined = (subject + " " + sender + " " + seller).lower()
    cat_map = {
        "hotel": "酒店住宿",
        "taxi": "出租车",
        "train": "火车票",
        "toll": "过路费",
        "meal": "餐饮",
        "telecom": "通信",
        "transport": "交通",
    }
    for label, keywords in TRANSPORT_DETAIL_RULES:
        if any(kw.lower() in combined for kw in keywords):
            taxi_extra = categories.get("taxi", {}).get("extra_name", "")
            extra = taxi_extra if label == "出租车" else ""
            return label, extra, bool(extra)

    for label, keywords in DEFAULT_CATEGORY_RULES:
        if any(kw.lower() in combined for kw in keywords):
            return label, "", False

    for key, cfg in categories.items():
        kws = cfg.get("keywords", [])
        if any(kw.lower() in combined for kw in kws):
            label = cat_map.get(key, key)
            extra = cfg.get("extra_name", "")
            return label, extra, bool(extra)
    return "其他", "", False


def _safe_date_dirname(invoice_date: str) -> str:
    """Return a safe YYYY-MM-DD directory name or a fallback."""
    text = (invoice_date or "").strip()
    if not text:
        return "unknown_date"
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return "unknown_date"


def _rename_by_invoice_code(
    file_path: str, invoice_code: str, invoice_date: str,
    att_dir: Path, is_extra: bool = False,
    category: str = "", total_amount: str = "", invoice_number: str = "",
) -> str:
    """Rename a file to ``{date}/{category}_{amount}_{invoice_number}.pdf``.

    Returns the new relative path under RUNTIME_DIR.
    """
    if not file_path or not invoice_code:
        return file_path  # can't rename without a code

    src = Path(file_path)
    if not src.exists():
        return file_path

    ext = src.suffix.lower() or ".pdf"
    date_dir = att_dir / _safe_date_dirname(invoice_date)
    date_dir.mkdir(parents=True, exist_ok=True)

    # New naming: {category}_{amount}_{invoice_number}.pdf
    safe_cat = (category or "其他").replace("/", "_").replace("\\", "_").replace(":", "_")
    amt = total_amount or ""
    num = invoice_number or invoice_code

    if is_extra:
        new_name = f"{safe_cat}_{amt}_{num}_ex{ext}"
    else:
        new_name = f"{safe_cat}_{amt}_{num}{ext}"

    dest = date_dir / new_name
    # Avoid overwriting a different file; keep both invoices visible.
    if dest.exists() and dest != src:
        stem = dest.stem
        for n in range(1, 100):
            candidate = date_dir / f"{stem}_{n}{ext}"
            if not candidate.exists():
                dest = candidate
                _log.warning("  文件名冲突，改用序号保存: %s", mask_filename(dest.name))
                break
        else:
            timestamp = datetime.now().strftime("%H%M%S")
            dest = date_dir / f"{stem}_{timestamp}{ext}"
            _log.warning("  文件名冲突过多，改用时间戳保存: %s", mask_filename(dest.name))

    if src != dest:
        shutil.move(str(src), str(dest))
        _log.info(
            "  📄 重命名: %s → %s/%s",
            mask_filename(src.name),
            redact_text(invoice_date, "date"),
            mask_filename(new_name),
        )

    try:
        return os.path.relpath(str(dest), RUNTIME_DIR)
    except ValueError:
        return str(dest)


def _safe_local_import_name(path: Path, max_len: int = 80) -> str:
    name = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in path.name)
    return name[:max_len] if len(name) > max_len else name


def _copy_local_file_to_staging(src: Path, staging_dir: Path) -> Path:
    staging_dir.mkdir(parents=True, exist_ok=True)
    dest = staging_dir / _safe_local_import_name(src)
    if dest.exists():
        stem = dest.stem
        ext = dest.suffix
        for n in range(1, 100):
            candidate = staging_dir / f"{stem}_{n}{ext}"
            if not candidate.exists():
                dest = candidate
                break
    shutil.copy2(str(src), str(dest))
    return dest


def _runtime_relative(path: Path) -> str:
    try:
        return os.path.relpath(str(path), RUNTIME_DIR)
    except ValueError:
        return str(path)


def _resolve_runtime_path(stored_path: str) -> Path | None:
    """Resolve a stored attachment path to an existing file on disk."""
    if not stored_path:
        return None

    raw_path = Path(str(stored_path))
    candidates = [raw_path] if raw_path.is_absolute() else [
        RUNTIME_DIR / raw_path,
        RUNTIME_DIR / "attachments" / raw_path,
        PROJECT_ROOT / raw_path,
        PROJECT_ROOT / "runtime" / raw_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _normalize_path_list(raw_value) -> list[str]:
    if not raw_value:
        return []
    if isinstance(raw_value, list):
        return [str(v) for v in raw_value if v]
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return [raw_value]
        if isinstance(parsed, list):
            return [str(v) for v in parsed if v]
        return [str(raw_value)]
    return [str(raw_value)]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path = path.resolve()
        parent = parent.resolve()
    except Exception:
        return False
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _refresh_invoice_from_parse(
    db: InvoiceDB,
    existing: dict,
    *,
    invoice_number: str,
    invoice_code: str,
    invoice_date: str,
    amount: str,
    total_amount: str,
    seller_name: str,
    buyer_name: str,
    invoice_type: str,
    category: str,
    has_extra: bool,
    extra_type: str,
    missing_extra: bool,
    parse_note: str,
) -> bool:
    """Refresh parsed invoice metadata in place."""
    return db.update_invoice_parsed_metadata(
        existing["id"],
        invoice_number=invoice_number,
        invoice_code=invoice_code,
        invoice_date=invoice_date,
        amount=amount,
        total_amount=total_amount,
        seller_name=seller_name,
        buyer_name=buyer_name,
        invoice_type=invoice_type,
        category=category,
        has_extra=has_extra,
        extra_type=extra_type,
        missing_extra=missing_extra,
        parse_success=True,
        parse_note=parse_note,
    )


def _restore_existing_invoice_if_deleted(db: InvoiceDB, existing: dict, context: str) -> dict:
    """Restore a matching soft-deleted invoice before refreshing parsed metadata."""
    if int(existing.get("is_deleted") or 0) != 1:
        return existing
    if db.restore_invoice(existing["id"]):
        existing = dict(existing)
        existing["is_deleted"] = 0
        _log.info("  已恢复已删除的重复发票(%s): %s", context, mask_invoice_number(existing.get("invoice_number", "")))
    return existing


def _find_existing_invoice_for_parse(
    db: InvoiceDB,
    invoice_number: str,
    total_amount: str,
    seller_name: str,
    include_deleted: bool = True,
) -> dict | None:
    """Find an existing invoice using the strongest parsed identity available."""
    invoice_number = (invoice_number or "").strip()
    total_amount = (total_amount or "").strip()
    seller_name = (seller_name or "").strip()
    if invoice_number and seller_name:
        exact = db.find_invoice_by_unique_fields(
            invoice_number, total_amount, seller_name, include_deleted=include_deleted
        )
        if exact:
            return exact
        existing = db.find_invoice_by_number_and_amount(
            invoice_number, total_amount, include_deleted=include_deleted
        )
        if existing and int(existing.get("is_deleted") or 0) == 0:
            return existing
        return None
    if invoice_number:
        return db.find_invoice_by_number_and_amount(
            invoice_number, total_amount, include_deleted=include_deleted
        )
    if seller_name and total_amount:
        return db.find_invoice_by_seller_and_amount(
            seller_name, total_amount, include_deleted=include_deleted
        )
    return None


def _log_existing_invoice_duplicate(existing: dict, reason: str) -> None:
    _log.info(
        "  跳过重复发票: existing_id=%s review_status=%s is_deleted=%s duplicate_reason=%s",
        existing.get("id"),
        existing.get("review_status", ""),
        existing.get("is_deleted", 0),
        reason,
    )


def _insert_local_exception(
    db: InvoiceDB,
    file_path: Path,
    original_name: str,
    note: str,
    categories: dict,
) -> tuple[str, int | None]:
    file_hash = _sha256_file(file_path) if file_path.exists() else ""
    existing_by_hash = db.find_invoice_by_file_hash(file_hash, include_deleted=True) if file_hash else None
    if existing_by_hash:
        existing_by_hash = _restore_existing_invoice_if_deleted(db, existing_by_hash, "本地导入")
        if int(existing_by_hash.get("is_deleted") or 0) == 0 and existing_by_hash.get("attachment_path"):
            _log.info("  本地导入跳过重复文件: %s", mask_filename(original_name))
            return "duplicate", None
        db.update_invoice_file_paths(existing_by_hash["id"], attachment_path=_runtime_relative(file_path))
        _log.info("  本地导入恢复已删除待处理文件: %s", mask_filename(original_name))
        return "pending_manual", existing_by_hash["id"]

    category, extra_type, extra_required = _classify(original_name, "local import", "", categories)
    rec = {
        "invoice_number": "",
        "invoice_code": "",
        "invoice_date": "",
        "amount": "",
        "total_amount": "",
        "seller_name": "",
        "buyer_name": "",
        "invoice_type": "本地导入待处理",
        "category": category,
        "has_extra": False,
        "extra_type": extra_type,
        "missing_extra": extra_required,
        "mail_uid": None,
        "mail_subject": f"本地导入: {original_name}",
        "mail_date": "",
        "mail_sender": "local import",
        "parse_success": False,
        "parse_note": note,
        "attachment_path": _runtime_relative(file_path),
        "extra_paths": [],
        "file_hash": file_hash,
    }
    row_id = db.insert_invoice(rec)
    return "pending_manual", row_id


def _import_local_pdf(
    source_name: str,
    file_path: Path,
    db: InvoiceDB,
    parser: InvoiceParser,
    categories: dict,
    att_dir: Path,
    preserve_source_path: bool = False,
) -> tuple[str, int | None]:
    file_hash = _sha256_file(file_path) if file_path.exists() else ""
    existing_by_hash = db.find_invoice_by_file_hash(file_hash, include_deleted=True) if file_hash else None

    info = parser.parse_pdf(str(file_path))
    if not info.parse_success:
        status, row_id = _insert_local_exception(
            db=db,
            file_path=file_path,
            original_name=source_name,
            note=info.parse_note or "本地导入PDF解析失败",
            categories=categories,
        )
        return status, row_id

    # If duplicate file hash, check if it's a re-import of the exact same record or a new file
    if existing_by_hash:
        existing_by_hash = _restore_existing_invoice_if_deleted(db, existing_by_hash, "本地导入")
        # Check if we should update it
        category, extra_type, extra_required = _classify(source_name, "local import", info.seller_name or "", categories)
        refreshed = _refresh_invoice_from_parse(
            db=db,
            existing=existing_by_hash,
            invoice_number=info.invoice_number or "",
            invoice_code=info.invoice_code or "",
            invoice_date=info.invoice_date or "",
            amount=info.amount or "",
            total_amount=info.total_amount or "",
            seller_name=info.seller_name or "",
            buyer_name=info.buyer_name or "",
            invoice_type=info.invoice_type or "本地导入发票",
            category=category,
            has_extra=bool(extra_type),
            extra_type=extra_type,
            missing_extra=extra_required,
            parse_note=info.parse_note or "本地导入",
        )
        if refreshed:
            _log.info(
                "  本地导入更新已存在发票: %s (%s)",
                mask_invoice_number(info.invoice_number),
                mask_filename(source_name),
            )
            return "added", existing_by_hash["id"]
        _log.info("  本地导入跳过重复文件: %s", mask_filename(source_name))
        return "duplicate", None

    # Check for duplicate by the full invoice uniqueness key.
    existing_by_fields = db.find_invoice_by_unique_fields(
        info.invoice_number, info.total_amount, info.seller_name, include_deleted=True
    )
    if existing_by_fields:
        existing_by_fields = _restore_existing_invoice_if_deleted(db, existing_by_fields, "本地导入")
        # If it matches number, amount, and seller_name, it's a duplicate.
        # But wait, is it the exact same record we are reimporting?
        # If the file path / hash differs, it's a duplicate transaction/file.
        # However, if we are reimporting and it matches existing, we should allow update.
        if existing_by_fields.get("seller_name") == info.seller_name:
            # Check if this file is a re-import of the exact same path
            att_path = existing_by_fields.get("attachment_path")
            if att_path:
                full_att_path = RUNTIME_DIR / att_path
                if full_att_path.exists() and _sha256_file(full_att_path) == file_hash:
                    category, extra_type, extra_required = _classify(source_name, "local import", info.seller_name or "", categories)
                    _refresh_invoice_from_parse(
                        db=db,
                        existing=existing_by_fields,
                        invoice_number=info.invoice_number or "",
                        invoice_code=info.invoice_code or "",
                        invoice_date=info.invoice_date or "",
                        amount=info.amount or "",
                        total_amount=info.total_amount or "",
                        seller_name=info.seller_name or "",
                        buyer_name=info.buyer_name or "",
                        invoice_type=info.invoice_type or "本地导入发票",
                        category=category,
                        has_extra=bool(extra_type),
                        extra_type=extra_type,
                        missing_extra=extra_required,
                        parse_note=info.parse_note or "本地导入",
                    )
                    return "added", existing_by_fields["id"]

            _log.info(
                "  本地导入跳过重复发票: %s (%s)",
                mask_invoice_number(info.invoice_number),
                mask_filename(source_name),
            )
            try:
                if not preserve_source_path:
                    file_path.unlink()
            except OSError:
                pass
            return "duplicate", None

    # Check for conflict: same number but different amount/seller/date
    existing_same_num = db.find_invoice_by_number(info.invoice_number)
    if existing_same_num:
        if (existing_same_num.get("total_amount") != info.total_amount or
            existing_same_num.get("seller_name") != info.seller_name or
            existing_same_num.get("invoice_date") != info.invoice_date):

            _log.warning(
                "  本地导入发现冲突发票 (发票号相同但内容不一致): %s (%s)",
                mask_invoice_number(info.invoice_number),
                mask_filename(source_name),
            )
            category, extra_type, extra_required = _classify(source_name, "local import", info.seller_name, categories)
            if preserve_source_path:
                attachment_path = _runtime_relative(file_path)
            else:
                code = info.invoice_code or info.invoice_number
                attachment_path = _rename_by_invoice_code(
                    str(file_path),
                    code,
                    info.invoice_date or "unknown_date",
                    att_dir,
                    category=category,
                    total_amount=info.total_amount,
                    invoice_number=info.invoice_number,
                )
            rec = {
                "invoice_number": info.invoice_number,
                "invoice_code": info.invoice_code,
                "invoice_date": info.invoice_date,
                "amount": info.amount,
                "total_amount": info.total_amount,
                "seller_name": info.seller_name,
                "buyer_name": info.buyer_name,
                "invoice_type": "本地导入冲突",
                "category": category,
                "has_extra": False,
                "extra_type": extra_type,
                "missing_extra": extra_required,
                "mail_uid": None,
                "mail_subject": f"本地导入冲突: {source_name}",
                "mail_date": info.invoice_date,
                "mail_sender": "local import",
                "parse_success": True,
                "review_status": "error",
                "parse_note": "发票号重复但信息不一致，请人工确认",
                "attachment_path": attachment_path,
                "extra_paths": [],
                "file_hash": file_hash,
            }
            row_id = db.insert_invoice(rec)
            return "conflict", row_id

    category, extra_type, extra_required = _classify(source_name, "local import", info.seller_name, categories)
    if preserve_source_path:
        attachment_path = _runtime_relative(file_path)
    else:
        code = info.invoice_code or info.invoice_number
        attachment_path = _rename_by_invoice_code(
            str(file_path),
            code,
            info.invoice_date or "unknown_date",
            att_dir,
            category=category,
            total_amount=info.total_amount,
            invoice_number=info.invoice_number,
        )
    rec = {
        "invoice_number": info.invoice_number,
        "invoice_code": info.invoice_code,
        "invoice_date": info.invoice_date,
        "amount": info.amount,
        "total_amount": info.total_amount,
        "seller_name": info.seller_name,
        "buyer_name": info.buyer_name,
        "invoice_type": info.invoice_type or "本地导入发票",
        "category": category,
        "has_extra": False,
        "extra_type": extra_type,
        "missing_extra": extra_required,
        "mail_uid": None,
        "mail_subject": f"本地导入: {source_name}",
        "mail_date": info.invoice_date,
        "mail_sender": "local import",
        "parse_success": True,
        "parse_note": info.parse_note or "本地导入",
        "attachment_path": attachment_path,
        "extra_paths": [],
        "file_hash": file_hash,
    }
    row_id = db.insert_invoice(rec)
    return "added", row_id


def _extract_local_zip(src: Path, att_dir: Path) -> list[Path]:
    msg = email.message.Message()
    msg["Content-Type"] = f'application/zip; name="{src.name}"'
    msg["Content-Disposition"] = f'attachment; filename="{src.name}"'
    msg.set_payload(src.read_bytes())
    handler = AttachmentHandler(att_dir)
    attachments = handler.extract(msg, mail_uid=0, date_str="local_import")
    return [Path(a.file_path) for a in attachments if Path(a.file_path).suffix.lower() in {".pdf", ".ofd"}]


def _import_local_directory(
    import_dir: str | Path,
    db: InvoiceDB,
    parser: InvoiceParser,
    categories: dict,
    att_dir: Path,
) -> dict:
    root = Path(import_dir)
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"本地导入目录不存在或不是文件夹: {root}")

    root = root.resolve()
    runtime_root = RUNTIME_DIR.resolve()
    staging_dir = att_dir / "local_import"
    supported_exts = {".pdf", ".ofd", ".zip", ".png", ".jpg", ".jpeg", ".heic"}
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in supported_exts)

    stats = {"added": 0, "duplicates": 0, "conflicts": 0, "pending_manual": 0, "failed": 0}
    if not files:
        _log.warning("本地导入目录没有发现 PDF/OFD/ZIP: %s", mask_path(root))
        return stats

    _log.info("开始本地导入: %s (%d 个文件)", mask_path(root), len(files))
    for src in files:
        ext = src.suffix.lower()
        try:
            preserve_source_path = _path_is_within(src, runtime_root)
            if ext == ".zip":
                extracted = _extract_local_zip(src, att_dir)
                if not extracted:
                    copied = _copy_local_file_to_staging(src, staging_dir)
                    status, row_id = _insert_local_exception(db, copied, src.name, "ZIP中未发现可处理 ofd/pdf 文件", categories)
                    key = status + "s" if status in ("duplicate", "conflict") else status
                    stats[key] += 1
                    continue
                for extracted_file in extracted:
                    if extracted_file.suffix.lower() == ".pdf":
                        status, row_id = _import_local_pdf(src.name, extracted_file, db, parser, categories, att_dir)
                        key = status + "s" if status in ("duplicate", "conflict") else status
                        stats[key] += 1
                    else:
                        status, row_id = _insert_local_exception(
                            db, extracted_file, extracted_file.name,
                            "本地导入暂不支持OFD解析，请人工处理",
                            categories,
                        )
                        key = status + "s" if status in ("duplicate", "conflict") else status
                        stats[key] += 1
                continue

            working_file = src if preserve_source_path else _copy_local_file_to_staging(src, staging_dir)
            if ext == ".pdf":
                status, row_id = _import_local_pdf(
                    src.name,
                    working_file,
                    db,
                    parser,
                    categories,
                    att_dir,
                    preserve_source_path=preserve_source_path,
                )
                key = status + "s" if status in ("duplicate", "conflict") else status
                stats[key] += 1
            elif ext in {".png", ".jpg", ".jpeg", ".heic"}:
                status, row_id = _insert_local_exception(
                    db,
                    working_file,
                    src.name,
                    "本地导入图片待识别，请人工处理",
                    categories,
                )
                key = status + "s" if status in ("duplicate", "conflict") else status
                stats[key] += 1
            else:
                status, row_id = _insert_local_exception(
                    db, working_file, src.name,
                    "本地导入暂不支持OFD解析，请人工处理",
                    categories,
                )
                key = status + "s" if status in ("duplicate", "conflict") else status
                stats[key] += 1
        except Exception as exc:
            _log.warning("本地导入失败 %s: %s", mask_path(src), exc)
            stats["failed"] += 1

    total_recorded = stats["added"] + stats["conflicts"] + stats["pending_manual"]
    _log.info("本地导入完成: 入库/待处理 %d 条 (新增: %d, 重复: %d, 冲突: %d, 失败: %d)",
              total_recorded, stats["added"], stats["duplicates"], stats["conflicts"], stats["failed"])
    return stats


def _looks_like_receipt_evidence(
    subject: str, sender: str, filename: str = "", html: str = "",
) -> bool:
    """Return True for overseas/non-invoice reimbursement evidence."""
    text = " ".join([subject or "", sender or "", filename or "", html or ""]).lower()
    return any(kw.lower() in text for kw in RECEIPT_KEYWORDS)


def _rename_receipt_file(
    file_path: str,
    mail_uid: int,
    invoice_date: str,
    att_dir: Path,
    category: str = "",
    filename_hint: str = "",
) -> str:
    """Rename a non-invoice receipt under the normal attachment tree."""
    if not file_path:
        return ""
    src = Path(file_path)
    if not src.exists():
        return file_path

    ext = src.suffix.lower() or ".pdf"
    date_dir = att_dir / _safe_date_dirname(invoice_date)
    date_dir.mkdir(parents=True, exist_ok=True)

    safe_cat = (category or "其他").replace("/", "_").replace("\\", "_").replace(":", "_")
    hint = Path(filename_hint or src.stem).stem
    hint = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in hint).strip("_")
    if len(hint) > 40:
        hint = hint[:40]
    new_name = f"{safe_cat}_receipt_{mail_uid}"
    if hint:
        new_name = f"{new_name}_{hint}"
    dest = date_dir / f"{new_name}{ext}"
    if dest.exists() and dest != src:
        for n in range(1, 100):
            candidate = date_dir / f"{new_name}_{n}{ext}"
            if not candidate.exists():
                dest = candidate
                break

    if src != dest:
        shutil.move(str(src), str(dest))
        _log.info("  保存海外凭证/收据: %s -> %s", mask_filename(src.name), mask_filename(dest.name))

    try:
        return os.path.relpath(str(dest), RUNTIME_DIR)
    except ValueError:
        return str(dest)


def _insert_receipt_record(
    msg: MailMessage,
    db: InvoiceDB,
    att_handler: AttachmentHandler,
    categories: dict,
    file_path: str,
    filename_hint: str = "",
    parse_note: str = "海外凭证/收据",
    download_url: str = "",
) -> int | None:
    """Insert a non-invoice reimbursement receipt and preserve its file."""
    cat, extra_type, _ = _classify(msg.subject, msg.sender, msg.sender, categories)
    att_path = _rename_receipt_file(
        file_path=file_path,
        mail_uid=msg.uid,
        invoice_date=msg.date,
        att_dir=att_handler._base,
        category=cat,
        filename_hint=filename_hint,
    )
    rec = {
        "invoice_number": "",
        "invoice_code": "",
        "invoice_date": msg.date,
        "amount": "",
        "total_amount": "",
        "seller_name": msg.sender,
        "buyer_name": "",
        "invoice_type": "海外凭证/收据",
        "category": cat,
        "has_extra": bool(extra_type),
        "extra_type": extra_type,
        "missing_extra": False,
        "mail_uid": msg.uid,
        "mail_subject": msg.subject,
        "mail_date": msg.date,
        "mail_sender": msg.sender,
        "parse_success": True,
        "parse_note": parse_note,
        "attachment_path": att_path,
        "extra_paths": [],
        "download_url": download_url,
    }
    return db.insert_invoice(rec)


# ── Process one email ────────────────────────────────────────────────

def _process_email(
    msg: MailMessage,
    att_handler: AttachmentHandler,
    parser: InvoiceParser,
    link_dl: LinkDownloader,
    db: InvoiceDB,
    categories: dict,
) -> int:
    """Process a single email.  Return the number of invoices recorded."""
    _log.info("── 处理 %s: %s", mask_uid(msg.uid), redact_text(msg.subject[:60], "subject"))

    # 1. Extract attachments
    attachments = att_handler.extract(msg.raw_msg, msg.uid, date_str=msg.date)
    invoice_pdfs = [a for a in attachments if a.is_invoice and a.file_path.lower().endswith(".pdf")]
    extra_files = [a for a in attachments if a.is_extra]
    kept_paths = set()
    link_pdf_skipped_as_duplicate = False
    link_download_failed = False
    recorded = 0

    # 2. Try downloading links via browser in addition to attachments
    combined_text = (msg.subject + " " + msg.sender).lower()
    has_invoice_hint = any(kw in combined_text
                           for kw in ["发票", "invoice", "fapiao", "电子发票", "行程单"])
    if has_invoice_hint:
        downloaded = link_dl.download_from_email(msg.raw_msg, msg.uid, msg.date)
        if not downloaded and not invoice_pdfs:
            link_download_failed = True
        if downloaded:
            for dl in downloaded:
                if not dl.is_invoice:
                    continue
                info = parser.parse_pdf(dl.file_path)
                if not info.parse_success:
                    if _looks_like_receipt_evidence(
                        msg.subject, msg.sender, dl.filename,
                        extract_html_from_message(msg.raw_msg),
                    ):
                        row_id = _insert_receipt_record(
                            msg=msg,
                            db=db,
                            att_handler=att_handler,
                            categories=categories,
                            file_path=dl.file_path,
                            filename_hint=dl.filename,
                            parse_note=info.parse_note or "海外凭证/收据",
                            download_url=dl.url,
                        )
                        if row_id:
                            recorded += 1
                            _log.info("  已入库海外凭证/收据: %s", mask_filename(dl.filename))
                        continue
                    _log.warning("  下载的 PDF 解析失败 (不是有效的发票文件): %s", redact_text(info.parse_note, "parse_note"))
                    if os.path.exists(dl.file_path):
                        os.remove(dl.file_path)
                    continue
                existing = _find_existing_invoice_for_parse(
                    db, info.invoice_number, info.total_amount, info.seller_name, include_deleted=True
                )
                if existing:
                    was_deleted = int(existing.get("is_deleted") or 0) == 1
                    existing = _restore_existing_invoice_if_deleted(db, existing, "链接下载")
                    existing_attachment_missing = _resolve_runtime_path(existing.get("attachment_path") or "") is None
                    existing_extra_paths = _normalize_path_list(existing.get("extra_paths"))
                    repair_extra_paths = bool(extra_files) and (
                        not existing_extra_paths
                        or any(_resolve_runtime_path(p) is None for p in existing_extra_paths)
                    )
                    repaired_attachment_path = ""
                    repaired_extra_paths: list[str] = []
                    category, extra_type, extra_req = _classify(
                        msg.subject, msg.sender, info.seller_name, categories)
                    if existing_attachment_missing:
                        code = info.invoice_code or info.invoice_number
                        repaired_attachment_path = _rename_by_invoice_code(
                            dl.file_path, code, info.invoice_date or msg.date,
                            att_handler._base,
                            category=category, total_amount=info.total_amount,
                            invoice_number=info.invoice_number)
                        if repaired_attachment_path:
                            kept_paths.add(str((att_handler._base.parent / repaired_attachment_path).resolve()))
                    if repair_extra_paths:
                        code = info.invoice_code or info.invoice_number
                        for e in extra_files:
                            ep = _rename_by_invoice_code(
                                e.file_path, code, info.invoice_date or msg.date,
                                att_handler._base, is_extra=True,
                                category=category, total_amount=info.total_amount,
                                invoice_number=info.invoice_number)
                            if ep:
                                kept_paths.add(str((att_handler._base.parent / ep).resolve()))
                                repaired_extra_paths.append(ep)
                    if _refresh_invoice_from_parse(
                        db,
                        existing,
                        invoice_number=info.invoice_number,
                        invoice_code=info.invoice_code,
                        invoice_date=info.invoice_date,
                        amount=info.amount,
                        total_amount=info.total_amount,
                        seller_name=info.seller_name,
                        buyer_name=info.buyer_name,
                        invoice_type=info.invoice_type,
                        category=category,
                        has_extra=bool(extra_files) if extra_req else False,
                        extra_type=extra_type,
                        missing_extra=extra_req and not bool(extra_files),
                        parse_note=info.parse_note or "链接下载",
                    ):
                        if repaired_attachment_path or repaired_extra_paths:
                            db.update_invoice_file_paths(
                                existing["id"],
                                attachment_path=repaired_attachment_path or None,
                                extra_paths=repaired_extra_paths or None,
                            )
                            _log.info(
                                "  已刷新重复发票元数据(链接下载)并修复附件路径: %s",
                                mask_invoice_number(info.invoice_number),
                            )
                        else:
                            _log.info("  已刷新重复发票元数据(链接下载): %s", mask_invoice_number(info.invoice_number))
                        if not was_deleted:
                            _log_existing_invoice_duplicate(existing, "link_download_parsed_pdf")
                        recorded += 1
                    link_pdf_skipped_as_duplicate = True
                    if os.path.exists(dl.file_path):
                        os.remove(dl.file_path)
                    continue
                duplicate = _find_existing_invoice_for_parse(
                    db, info.invoice_number, info.total_amount, info.seller_name, include_deleted=False
                )
                if duplicate:
                    _log.info("  跳过重复: %s", mask_invoice_number(info.invoice_number))
                    _log_existing_invoice_duplicate(duplicate, "link_download_duplicate")
                    link_pdf_skipped_as_duplicate = True
                    recorded += 1
                    # Clean up the downloaded file for the duplicate
                    if os.path.exists(dl.file_path):
                        os.remove(dl.file_path)
                    continue
                cat, extra_type, extra_req = _classify(
                    msg.subject, msg.sender, info.seller_name, categories)
                # Rename file: {invoice_code}.pdf under {invoice_date}/
                code = info.invoice_code or info.invoice_number
                att_path = _rename_by_invoice_code(
                    dl.file_path, code, info.invoice_date or msg.date,
                    att_handler._base,
                    category=cat, total_amount=info.total_amount,
                    invoice_number=info.invoice_number)
                if att_path:
                    kept_paths.add(str((att_handler._base.parent / att_path).resolve()))
                rec = {
                    "invoice_number": info.invoice_number,
                    "invoice_code": info.invoice_code,
                    "invoice_date": info.invoice_date,
                    "amount": info.amount,
                    "total_amount": info.total_amount,
                    "seller_name": info.seller_name,
                    "buyer_name": info.buyer_name,
                    "invoice_type": info.invoice_type,
                    "category": cat,
                    "has_extra": False,
                    "extra_type": extra_type,
                    "missing_extra": extra_req,
                    "mail_uid": msg.uid,
                    "mail_subject": msg.subject,
                    "mail_date": msg.date,
                    "mail_sender": msg.sender,
                    "parse_success": info.parse_success,
                    "parse_note": info.parse_note or "链接下载",
                    "attachment_path": att_path,
                    "extra_paths": [],
                    "download_url": dl.url,
                }
                row_id = db.insert_invoice(rec)
                if row_id:
                    recorded += 1
                    _log.info("  ✅ 已入库(链接下载): %s (%s)", mask_invoice_number(info.invoice_number), cat)

            # Clean up all downloaded files if none of them successfully imported
            for other_dl in downloaded:
                try:
                    p = Path(other_dl.file_path).resolve()
                    if p.exists() and str(p) not in kept_paths:
                        p.unlink()
                except Exception:
                    pass

    # 3. Parse each invoice PDF from attachments
    for att in invoice_pdfs:
        info = parser.parse_pdf(att.file_path)
        if not info.parse_success:
            if _looks_like_receipt_evidence(msg.subject, msg.sender, att.original_name):
                row_id = _insert_receipt_record(
                    msg=msg,
                    db=db,
                    att_handler=att_handler,
                    categories=categories,
                    file_path=att.file_path,
                    filename_hint=att.original_name,
                    parse_note=info.parse_note or "海外凭证/收据",
                )
                if row_id:
                    recorded += 1
                    _log.info("  已入库海外凭证/收据: %s", mask_filename(att.original_name))
                continue

            _log.warning("  PDF 解析失败且不像报销凭证，跳过: %s", redact_text(info.parse_note, "parse_note"))
            continue
        existing = _find_existing_invoice_for_parse(
            db, info.invoice_number, info.total_amount, info.seller_name, include_deleted=True
        )
        if existing:
            was_deleted = int(existing.get("is_deleted") or 0) == 1
            existing = _restore_existing_invoice_if_deleted(db, existing, "附件")
            cat, extra_type, extra_req = _classify(
                msg.subject, msg.sender, info.seller_name, categories)
            existing_attachment_missing = _resolve_runtime_path(existing.get("attachment_path") or "") is None
            existing_extra_paths = _normalize_path_list(existing.get("extra_paths"))
            repair_extra_paths = bool(extra_files) and (
                not existing_extra_paths
                or any(_resolve_runtime_path(p) is None for p in existing_extra_paths)
            )
            repaired_attachment_path = ""
            repaired_extra_paths: list[str] = []
            if existing_attachment_missing:
                code = info.invoice_code or info.invoice_number
                repaired_attachment_path = _rename_by_invoice_code(
                    att.file_path, code, info.invoice_date or msg.date,
                    att_handler._base,
                    category=cat, total_amount=info.total_amount,
                    invoice_number=info.invoice_number)
                if repaired_attachment_path:
                    kept_paths.add(str((att_handler._base.parent / repaired_attachment_path).resolve()))
            if repair_extra_paths:
                code = info.invoice_code or info.invoice_number
                for e in extra_files:
                    ep = _rename_by_invoice_code(
                        e.file_path, code, info.invoice_date or msg.date,
                        att_handler._base, is_extra=True,
                        category=cat, total_amount=info.total_amount,
                        invoice_number=info.invoice_number)
                    if ep:
                        kept_paths.add(str((att_handler._base.parent / ep).resolve()))
                        repaired_extra_paths.append(ep)
            if _refresh_invoice_from_parse(
                db,
                existing,
                invoice_number=info.invoice_number,
                invoice_code=info.invoice_code,
                invoice_date=info.invoice_date,
                amount=info.amount,
                total_amount=info.total_amount,
                seller_name=info.seller_name,
                buyer_name=info.buyer_name,
                invoice_type=info.invoice_type,
                category=cat,
                has_extra=bool(extra_files) if extra_req else False,
                extra_type=extra_type,
                missing_extra=extra_req and not bool(extra_files),
                parse_note=info.parse_note,
            ):
                if repaired_attachment_path or repaired_extra_paths:
                    db.update_invoice_file_paths(
                        existing["id"],
                        attachment_path=repaired_attachment_path or None,
                        extra_paths=repaired_extra_paths or None,
                    )
                    _log.info("  已刷新重复发票元数据并修复附件路径: %s", mask_invoice_number(info.invoice_number))
                else:
                    _log.info("  已刷新重复发票元数据: %s", mask_invoice_number(info.invoice_number))
                if not was_deleted:
                    _log_existing_invoice_duplicate(existing, "attachment_parsed_pdf")
                recorded += 1
            continue
        duplicate = _find_existing_invoice_for_parse(
            db, info.invoice_number, info.total_amount, info.seller_name, include_deleted=False
        )
        if duplicate:
            _log.info("  跳过重复: %s", mask_invoice_number(info.invoice_number))
            _log_existing_invoice_duplicate(duplicate, "attachment_duplicate")
            recorded += 1
            continue

        cat, extra_type, extra_req = _classify(
            msg.subject, msg.sender, info.seller_name, categories)

        has_extra = bool(extra_files) if extra_req else False

        # Rename files by invoice code under invoice_date/
        code = info.invoice_code or info.invoice_number
        inv_date = info.invoice_date or msg.date
        att_path = _rename_by_invoice_code(
            att.file_path, code, inv_date, att_handler._base,
            category=cat, total_amount=info.total_amount,
            invoice_number=info.invoice_number)
        if att_path:
            kept_paths.add(str((att_handler._base.parent / att_path).resolve()))
        renamed_extras = []
        for e in extra_files:
            ep = _rename_by_invoice_code(
                e.file_path, code, inv_date, att_handler._base, is_extra=True,
                category=cat, total_amount=info.total_amount,
                invoice_number=info.invoice_number)
            if ep:
                kept_paths.add(str((att_handler._base.parent / ep).resolve()))
                renamed_extras.append(ep)

        rec = {
            "invoice_number": info.invoice_number,
            "invoice_code": info.invoice_code,
            "invoice_date": info.invoice_date,
            "amount": info.amount,
            "total_amount": info.total_amount,
            "seller_name": info.seller_name,
            "buyer_name": info.buyer_name,
            "invoice_type": info.invoice_type,
            "category": cat,
            "has_extra": has_extra,
            "extra_type": extra_type,
            "missing_extra": extra_req and not has_extra,
            "mail_uid": msg.uid,
            "mail_subject": msg.subject,
            "mail_date": msg.date,
            "mail_sender": msg.sender,
            "parse_success": info.parse_success,
            "parse_note": info.parse_note,
            "attachment_path": att_path,
            "extra_paths": renamed_extras,
        }
        row_id = db.insert_invoice(rec)
        if row_id:
            recorded += 1
            _log.info("  ✅ 已入库: %s (%s)", mask_invoice_number(info.invoice_number), cat)

    # 3b. Preserve standalone receipts/water bills/folios when no invoice PDF exists.
    if not invoice_pdfs and recorded == 0 and extra_files:
        for att in extra_files:
            if not _looks_like_receipt_evidence(msg.subject, msg.sender, att.original_name):
                continue
            row_id = _insert_receipt_record(
                msg=msg,
                db=db,
                att_handler=att_handler,
                categories=categories,
                file_path=att.file_path,
                filename_hint=att.original_name,
            )
            if row_id:
                recorded += 1
                _log.info("  已入库独立水单/收据: %s", mask_filename(att.original_name))

    # 4. Fallback: parse subject or HTML body when no PDF available
    if not invoice_pdfs and recorded == 0 and not link_pdf_skipped_as_duplicate:
        subj_info = parse_subject(msg.subject)
        html_body = extract_html_from_message(msg.raw_msg)
        body_info = parse_html_body(html_body)

        # Merge results, prioritizing subject over body
        merged = {**body_info, **subj_info}

        has_useful = merged.get("invoice_number") or (
            merged.get("seller_name") and merged.get("total_amount"))
        if has_useful:
            inv_num = merged.get("invoice_number", "")
            seller = merged.get("seller_name", "")
            amount = merged.get("total_amount", "")
            dedup_key = inv_num or f"{seller}_{amount}"
            cat, extra_type, extra_req = _classify(
                msg.subject, msg.sender, seller, categories)

            if inv_num:
                existing = _find_existing_invoice_for_parse(db, inv_num, amount, seller, include_deleted=True)
                if existing:
                    was_deleted = int(existing.get("is_deleted") or 0) == 1
                    existing = _restore_existing_invoice_if_deleted(db, existing, "主题/正文")
                    if _refresh_invoice_from_parse(
                        db,
                        existing,
                        invoice_number=inv_num,
                        invoice_code=merged.get("invoice_code", ""),
                        invoice_date=merged.get("invoice_date", "") or msg.date,
                        amount="",
                        total_amount=amount,
                        seller_name=seller,
                        buyer_name="",
                        invoice_type=merged.get("invoice_type", ""),
                        category=cat,
                        has_extra=False,
                        extra_type=extra_type,
                        missing_extra=extra_req,
                        parse_note="从主题/正文提取",
                    ):
                        recorded += 1
                        _log.info("  已刷新重复发票元数据(主题/正文): %s", redact_text(dedup_key, "dedup_key"))
                        if not was_deleted:
                            _log_existing_invoice_duplicate(existing, "subject_body_invoice_number")
                    return recorded

            existing = _find_existing_invoice_for_parse(db, "", amount, seller, include_deleted=True)
            if existing:
                was_deleted = int(existing.get("is_deleted") or 0) == 1
                existing = _restore_existing_invoice_if_deleted(db, existing, "主题/正文")
                if not was_deleted:
                    _log.info("  跳过重复(从主题/正文): %s", redact_text(dedup_key, "dedup_key"))
                    _log_existing_invoice_duplicate(existing, "subject_body_seller_amount")
                recorded += 1
                return recorded

            if db.is_duplicate(dedup_key, amount, seller):
                _log.info("  跳过重复(从主题/正文): %s", redact_text(dedup_key, "dedup_key"))
                recorded += 1
                return recorded

            rec = {
                "invoice_number": inv_num,
                "invoice_code": merged.get("invoice_code", ""),
                "invoice_date": merged.get("invoice_date", "") or msg.date,
                "amount": "",
                "total_amount": amount,
                "seller_name": seller,
                "buyer_name": "",
                "invoice_type": merged.get("invoice_type", ""),
                "category": cat,
                "has_extra": False,
                "extra_type": extra_type,
                "missing_extra": extra_req,
                "mail_uid": msg.uid,
                "mail_subject": msg.subject,
                "mail_date": msg.date,
                "mail_sender": msg.sender,
                "parse_success": True,
                "parse_note": "⬇️待手动下载",
                "attachment_path": "",
                "extra_paths": [],
            }
            row_id = db.insert_invoice(rec)
            if row_id:
                recorded += 1
                _log.info("  📝 从主题/正文提取: %s — 待手动下载", redact_text(dedup_key, "dedup_key"))

    # Clean up any leftover attachment files that were not successfully kept
    for a in attachments:
        try:
            p = Path(a.file_path).resolve()
            if p.exists() and str(p) not in kept_paths:
                p.unlink()
                _log.debug("  🗑️ 清理未使用的临时附件: %s", mask_filename(p.name))
        except Exception:
            pass

    if recorded == 0:
        if link_pdf_skipped_as_duplicate:
            _log.info("  ℹ️ 发票已存在于数据库，跳过（重复）")
        elif invoice_pdfs:
            # Had attachment PDFs but all were duplicates
            _log.info("  ℹ️ 附件发票已存在于数据库，跳过（重复）")
        else:
            if link_download_failed:
                _log.warning("  链接下载未获得官方 PDF/OFD，保留为待下载重试")
            _log.warning("  ⚠️ 未发现可用的发票附件或下载链接，且无法从主题提取有效信息")

    return recorded


# ── Subcommand Handlers ───────────────────────────────────────────────

def _cmd_claim_create(args: argparse.Namespace, db: InvoiceDB):
    try:
        claim_id = db.create_claim_group(args.name, args.start, args.end)
        print(f"已创建报销组“{args.name}”，ID: {claim_id}")
        sys.exit(0)
    except Exception as e:
        _log.error("Failed to create claim group: %s", e)
        sys.exit(1)


def _cmd_claim_add(args: argparse.Namespace, db: InvoiceDB):
    try:
        claim = db.get_claim_group(args.claim_id)
        if not claim:
            print(f"错误: 报销组 ID {args.claim_id} 不存在。")
            sys.exit(1)

        # Check if invoice exists
        inv = db.get_invoice(args.invoice_id)
        if not inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        success = db.add_invoice_to_claim(args.claim_id, args.invoice_id, args.note)
        if success:
            print(f"已将发票 ID {args.invoice_id} 添加到报销组 ID {args.claim_id}。")
            sys.exit(0)
        else:
            print(f"错误: 发票 ID {args.invoice_id} 已在报销组 ID {args.claim_id} 中，或存在重复关联。")
            sys.exit(1)
    except Exception as e:
        _log.error("Failed to add invoice to claim group: %s", e)
        sys.exit(1)


def _cmd_claim_export(args: argparse.Namespace, db: InvoiceDB, project_root: Path, runtime_dir: Path):
    try:
        claim = db.get_claim_group(args.claim_id)
        if not claim:
            print(f"错误: 报销组 ID {args.claim_id} 不存在。")
            sys.exit(1)

        from .claim_export import export_claim_package
        include_to_review = getattr(args, "include_to_review", False)
        export_dir = export_claim_package(db, args.claim_id, project_root, runtime_dir, include_to_review=include_to_review)
        print(f"已导出报销组 ID {args.claim_id} 的报销包: {export_dir}")
        sys.exit(0)
    except ValueError as ve:
        print(f"错误: {ve}")
        sys.exit(1)
    except Exception as e:
        _log.error("Failed to export claim group: %s", e)
        sys.exit(1)


def _cmd_invoice_list(args: argparse.Namespace, db: InvoiceDB):
    try:
        invoices = db.list_invoices(status=getattr(args, "status", None), limit=getattr(args, "limit", None))
        if not invoices:
            print("未找到发票记录。")
            sys.exit(0)

        # Beautiful, clean text table format
        header_fmt = "{:<6} | {:<12} | {:<15} | {:<12} | {:<12} | {:<10} | {:<25}"
        row_fmt    = "{:<6} | {:<12} | {:<15} | {:<12} | {:<12} | {:<10} | {:<25}"

        print(header_fmt.format("ID", "状态", "发票号码", "日期", "金额", "分类", "销售方"))
        print("-" * 110)
        for inv in invoices:
            inv_id = inv.get("id") or ""
            status = _status_label(inv.get("review_status") or review_status.TO_REVIEW)
            number = inv.get("invoice_number") or ""
            date = inv.get("invoice_date") or ""
            amount = inv.get("total_amount") or ""
            category = inv.get("category") or ""
            seller = inv.get("seller_name") or ""

            if len(seller) > 25:
                seller = seller[:22] + "..."
            print(row_fmt.format(inv_id, status, number, date, amount, category, seller))
        sys.exit(0)
    except Exception as e:
        _log.error("Failed to list invoices: %s", e)
        sys.exit(1)


def _cmd_invoice_claimable(args: argparse.Namespace, db: InvoiceDB):
    args.status = "approved"
    args.limit = None
    _cmd_invoice_list(args, db)


def _cmd_invoice_show(args: argparse.Namespace, db: InvoiceDB):
    try:
        inv = db.get_invoice(args.invoice_id)
        if not inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        print("=" * 60)
        print(f"发票详情 (ID: {inv.get('id')})")
        print("=" * 60)
        print(f"发票号码:       {inv.get('invoice_number') or ''}")
        print(f"发票代码:       {inv.get('invoice_code') or ''}")
        print(f"开票日期:       {inv.get('invoice_date') or ''}")
        print(f"金额 (税前):    {inv.get('amount') or ''}")
        print(f"价税合计:       {inv.get('total_amount') or ''}")
        print(f"销售方名称:     {inv.get('seller_name') or ''}")
        print(f"购买方名称:     {inv.get('buyer_name') or ''}")
        print(f"发票类型:       {inv.get('invoice_type') or ''}")
        print(f"发票分类:       {inv.get('category') or ''}")
        print(f"审核状态:       {_status_label(inv.get('review_status') or review_status.TO_REVIEW)}")
        print(f"确认时间:       {inv.get('confirmed_at') or ''}")
        print(f"审核备注:       {inv.get('confirmed_note') or ''}")
        print(f"附加材料:       {'是' if inv.get('has_extra') else '否'}")
        print(f"缺少附件:       {'是' if inv.get('missing_extra') else '否'}")
        print(f"邮件主题:       {inv.get('mail_subject') or ''}")
        print(f"文件路径:       {inv.get('attachment_path') or ''}")
        print(f"下载链接:       {_mask_url(inv.get('download_url') or '')}")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        _log.error("Failed to show invoice details: %s", e)
        sys.exit(1)


def _cmd_invoice_review(args: argparse.Namespace, db: InvoiceDB):
    try:
        old_inv = db.get_invoice(args.invoice_id)
        if not old_inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        old_status = old_inv.get("review_status") or "to_review"

        success = db.update_invoice_review_status(args.invoice_id, args.status, args.note)
        if not success:
            print(f"错误: 发票 ID {args.invoice_id} 更新失败。")
            sys.exit(1)

        new_inv = db.get_invoice(args.invoice_id)
        new_status = new_inv.get("review_status")
        confirmed_at = new_inv.get("confirmed_at") or ""

        print("已更新发票审核状态:")
        print(f"  发票 ID:   {args.invoice_id}")
        print(f"  原状态:    {_status_label(old_status)}")
        print(f"  新状态:    {_status_label(new_status)}")
        print(f"  确认时间:  {confirmed_at}")
        print(f"  审核备注:  {args.note}")
        sys.exit(0)
    except ValueError as ve:
        print(f"错误: {ve}")
        sys.exit(1)
    except Exception as e:
        _log.error("Failed to review invoice: %s", e)
        sys.exit(1)


def _cmd_invoice_delete(args: argparse.Namespace, db: InvoiceDB):
    try:
        inv = db.get_invoice(args.invoice_id)
        if not inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        success = db.soft_delete_invoice(args.invoice_id)
        if success:
            print(f"已删除发票 ID {args.invoice_id}。")
            sys.exit(0)
        else:
            print(f"错误: 发票 ID {args.invoice_id} 删除失败。")
            sys.exit(1)
    except Exception as e:
        _log.error("Failed to delete invoice: %s", e)
        sys.exit(1)


def _cmd_invoice_restore(args: argparse.Namespace, db: InvoiceDB):
    try:
        inv = db.get_invoice(args.invoice_id, include_deleted=True)
        if not inv:
            print(f"错误: 发票 ID {args.invoice_id} 不存在。")
            sys.exit(1)

        success = db.restore_invoice(args.invoice_id)
        if success:
            print(f"已恢复发票 ID {args.invoice_id}。")
            sys.exit(0)
        else:
            print(f"错误: 发票 ID {args.invoice_id} 恢复失败。")
            sys.exit(1)
    except Exception as e:
        _log.error("Failed to restore invoice: %s", e)
        sys.exit(1)


def _dispatch_claim_command(args: argparse.Namespace):
    """Execute the matching claim subcommand and exit, bypassing config loading."""
    db_path = RUNTIME_DIR / "invoices.db"
    if args.command == "desktop":
        import time as _time
        _t0 = _time.monotonic()
        from .gui import start_gui
        _t1 = _time.monotonic()
        app_init_ms = int((_t1 - _t0) * 1000)
        startup_probe = getattr(args, "startup_probe", False)
        start_gui(db_path, startup_probe=startup_probe, app_init_ms=app_init_ms)
        return

    with InvoiceDB(db_path) as db:
        if args.command == "claim-create":
            _cmd_claim_create(args, db)
        elif args.command == "claim-add":
            _cmd_claim_add(args, db)
        elif args.command == "claim-export":
            _cmd_claim_export(args, db, PROJECT_ROOT, RUNTIME_DIR)
        elif args.command == "invoice-list":
            _cmd_invoice_list(args, db)
        elif args.command == "invoice-claimable":
            _cmd_invoice_claimable(args, db)
        elif args.command == "invoice-show":
            _cmd_invoice_show(args, db)
        elif args.command == "invoice-review":
            _cmd_invoice_review(args, db)
        elif args.command == "invoice-delete":
            _cmd_invoice_delete(args, db)
        elif args.command == "invoice-restore":
            _cmd_invoice_restore(args, db)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    args = _parse_args()
    _setup_logging(args.verbose)

    # Early dispatch for subcommands (bypassing config.json loading)
    if getattr(args, "command", None):
        _dispatch_claim_command(args)
        return

    _log.info("=" * 60)
    _log.info("Invoice Hub - 本地优先的报销资料整理助手")
    _log.info("运行时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    _log.info("=" * 60)

    cfg = load_config(args.config)
    email_addr = cfg["email"]["address"]
    imap_cfg = cfg.get("imap", {})
    search_cfg = cfg.get("search", {})
    ai_cfg = cfg.get("ai", {})
    categories = cfg.get("categories", {})
    months = args.months or search_cfg.get("months_back", 3)

    # Paths
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    att_dir = RUNTIME_DIR / "attachments"
    db_path = RUNTIME_DIR / "invoices.db"
    excel_path = RUNTIME_DIR / "发票汇总.xlsx"

    with InvoiceDB(db_path) as db:
        # Export-only mode
        if args.export_only:
            export_excel(db.get_all_invoices(), excel_path)
            _log.info("完成 (仅导出)")
            return

        # Classify-only mode (no IMAP needed)
        if args.classify_only:
            _run_classify(db, ai_cfg, args.no_ai)
            return

        # Reset mode
        if args.reset:
            db.reset_emails()
            db.reset_processed()
            db.reset_invoices()
            _log.info("已重置，将重新扫描所有邮件")

        if args.import_dir:
            parser = InvoiceParser()
            total_stats = {"added": 0, "duplicates": 0, "conflicts": 0, "pending_manual": 0, "failed": 0}
            for import_dir in args.import_dir:
                stats = _import_local_directory(
                    import_dir=import_dir,
                    db=db,
                    parser=parser,
                    categories=categories,
                    att_dir=att_dir,
                )
                for k in total_stats:
                    total_stats[k] += stats.get(k, 0)
            export_excel(db.get_all_invoices(), excel_path)
            total_recorded = total_stats["added"] + total_stats["conflicts"] + total_stats["pending_manual"]
            _log.info(
                "本地导入完成: 成功入库/待处理 %d 条 (新增: %d, 重复: %d, 冲突: %d, 失败: %d)",
                total_recorded,
                total_stats["added"],
                total_stats["duplicates"],
                total_stats["conflicts"],
                total_stats["failed"],
            )
            _print_stats(db, excel_path)
            return

        # Retry failed downloads mode
        if args.retry_failed:
            failed_invoices = db.get_failed_downloads()
            if failed_invoices:
                failed_uids = [inv["mail_uid"] for inv in failed_invoices if inv["mail_uid"]]
                if failed_uids:
                    db.reset_emails_download_status(failed_uids)
                    db.delete_invoices_by_uid(failed_uids)
                    _log.info("已重置 %d 封未成功下载的发票邮件状态，将重新尝试下载", len(failed_uids))
            else:
                _log.info("未发现需要重新下载的失败发票记录")

        # Credential
        auth_code = get_auth_code(email_addr)

        try:
            with MailFetcher(
                address=email_addr,
                auth_code=auth_code,
                server=imap_cfg.get("server", "imap.qq.com"),
                port=imap_cfg.get("port", 993),
            ) as fetcher:
                auth_code = ""

                # ═══════════════════════════════════
                # 阶段 1: 扫描 & 分类
                # ═══════════════════════════════════
                if not args.download_only:
                    since = ""
                    if args.months:
                        _log.info("指定扫描范围: 最近 %d 个月", months)
                    elif not args.reset:
                        since = db.get_last_scanned_date()
                        if since:
                            _log.info("增量扫描: 从 %s 开始", since)

                    known = db.get_all_email_uids()
                    headers = fetcher.scan_headers(
                        folder=search_cfg.get("folder", "INBOX"),
                        months_back=months,
                        since_date=since,
                        known_uids=known,
                        limit=args.limit,
                    )
                    new_count = db.bulk_upsert_emails(headers)
                    _log.info("扫描完成: %d 封新邮件入库", new_count)

                    # Classify
                    _run_classify(db, ai_cfg, args.no_ai)

                    if args.scan_only:
                        _print_stats(db, excel_path)
                        return

                # ═══════════════════════════════════
                # 阶段 2: 下载 & 解析
                # ═══════════════════════════════════
                pending = db.get_invoice_emails_to_download()
                if not pending:
                    _log.info("没有待下载的发票邮件")
                else:
                    _log.info("\n开始下载 %d 封发票邮件…", len(pending))
                    att_handler = AttachmentHandler(att_dir)
                    parser = InvoiceParser()
                    link_dl = LinkDownloader(att_dir, headed=args.headed)

                    for i, row in enumerate(pending, 1):
                        _log.info("\n[%d/%d] ────────────────", i, len(pending))
                        try:
                            _handle_pending_email(
                                row=row,
                                fetcher=fetcher,
                                folder=search_cfg.get("folder", "INBOX"),
                                att_handler=att_handler,
                                parser=parser,
                                link_dl=link_dl,
                                db=db,
                                categories=categories,
                            )
                        except Exception as exc:
                            _log.error("处理 %s 出错: %s", mask_uid(row["uid"]), exc)

                    link_dl.close()

        except ConnectionError as exc:
            _log.error("连接失败: %s", exc)
            sys.exit(1)

        # Export & stats
        export_excel(db.get_all_invoices(), excel_path)
        _print_stats(db, excel_path)


def _run_classify(db: InvoiceDB, ai_cfg: dict, no_ai: bool):
    """Run rule + AI classification on unclassified emails."""
    unclassified = db.get_unclassified_emails()
    if not unclassified:
        _log.info("没有未分类的邮件")
        return

    # Rule classification (including trusted senders)
    rule_results = []
    rule_count = 0
    for row in unclassified:
        # 1. Run local keyword classifier first (exclusion rules take absolute highest priority)
        result, reason = rule_classify(row["subject"], row["sender"])
        if result == 0:
            # Blocked by local exclusion keywords (even if sender is whitelisted)
            rule_results.append({
                "uid": row["uid"], "is_invoice": False,
                "by": "rule", "reason": reason
            })
            rule_count += 1
            continue
        elif result == 1:
            # Confirmed by local positive keywords
            rule_results.append({
                "uid": row["uid"], "is_invoice": True,
                "by": "rule", "reason": reason
            })
            rule_count += 1
            continue

        # 2. Check trusted senders whitelist if rules are uncertain (-1)
        if db.is_trusted_sender(row["sender"]):
            rule_results.append({
                "uid": row["uid"], "is_invoice": True,
                "by": "whitelist", "reason": "发送者在白名单中"
            })
            rule_count += 1
            continue

    if rule_results:
        db.bulk_classify(rule_results)
    _log.info("规则/白名单分类: %d/%d", rule_count, len(unclassified))

    # AI classification
    still_unknown = db.get_unclassified_emails()
    if still_unknown and not no_ai:
        try:
            provider = ai_cfg.get("provider", "deepseek")
            ai = AIClassifier(
                provider=provider,
                model=ai_cfg.get("model", ""),
                batch_size=ai_cfg.get("batch_size", 20),
            )
            results = ai.classify_batch(still_unknown)
            classified_results = [r for r in results if r.get("is_invoice") is not None]
            pending_count = len(results) - len(classified_results)
            db.bulk_classify([
                {"uid": r["uid"], "is_invoice": r["is_invoice"],
                 "by": provider, "reason": r.get("reason", "")}
                for r in classified_results
            ])
            if pending_count:
                _log.warning("⚠️ AI 分类 API 失败，%d 封邮件将在下次运行时重试", pending_count)

            # Save confirmed senders to whitelist
            uid_to_sender = {r["uid"]: r["sender"] for r in still_unknown}
            for r in classified_results:
                if r["is_invoice"]:
                    sender = uid_to_sender.get(r["uid"])
                    if sender:
                        db.add_trusted_sender(sender)

            _log.info("AI 分类: %d/%d", len(classified_results), len(still_unknown))
        except SystemExit:
            _log.warning("AI API 未配置，跳过 AI 分类 (%d 封未分类)",
                         len(still_unknown))
    elif still_unknown:
        _log.info("跳过 AI 分类 (--no-ai): %d 封未分类", len(still_unknown))

    stats = db.get_email_stats()
    _log.info("分类结果: 发票 %d, 非发票 %d, 未分类 %d",
              stats["invoice"], stats["not_invoice"], stats["unclassified"])


def _print_stats(db: InvoiceDB, excel_path):
    """Print final statistics."""
    stats = db.get_email_stats()
    inv_count = db.count_invoices()
    rows = db.get_all_invoices()
    has_file = sum(1 for r in rows if r.get("attachment_path") and os.path.exists(RUNTIME_DIR / r.get("attachment_path")))

    _log.info("\n" + "=" * 60)
    _log.info("运行统计:")
    _log.info("  邮件: 总计 %d, 发票 %d, 非发票 %d, 未分类 %d",
              stats["total"], stats["invoice"],
              stats["not_invoice"], stats["unclassified"])
    _log.info("  发票入库: %d 张, 已下载文件: %d", inv_count, has_file)
    if stats["pending"]:
        _log.info("  ⬇️ 待下载: %d 封", stats["pending"])
    _log.info("  输出: %s", mask_path(excel_path))
    _log.info("=" * 60)


def _handle_pending_email(
    row: dict,
    fetcher: MailFetcher,
    folder: str,
    att_handler: AttachmentHandler,
    parser: InvoiceParser,
    link_dl: LinkDownloader,
    db: InvoiceDB,
    categories: dict,
) -> bool:
    """Fetch and process one pending invoice email.

    Returns True only when at least one invoice record was created. This avoids
    hiding failed downloads from future retries.
    """
    msg = fetcher.fetch_by_uid(row["uid"], folder=folder)
    if not msg:
        _log.warning("  获取 %s 失败，跳过", mask_uid(row["uid"]))
        return False
    if not msg.date:
        msg.date = row.get("mail_date", "")

    recorded = _process_email(msg, att_handler, parser, link_dl, db, categories)
    if recorded > 0:
        db.mark_downloaded(row["uid"])
        return True

    _log.warning("  %s 未成功入库，保留为待下载以便重试", mask_uid(row["uid"]))
    return False


def import_local_directory(
    import_dir: str | Path,
    db_path: Path,
    config_path: Path | None = None
) -> int:
    """Public wrapper to import a local directory of invoices."""
    from .services import import_local_directory as _service_import
    try:
        return _service_import(import_dir, db_path, config_path)
    except ValueError as e:
        raise SystemExit(str(e))


def scan_email_and_download(
    db_path: Path,
    config_path: Path | None = None,
    months: int | None = None,
    limit: int | None = None,
    scan_only: bool = False,
    download_only: bool = False,
    log_callback = None
) -> dict:
    """Public wrapper to scan emails and download invoices safely from GUI/CLI."""
    from .services import scan_email_and_download as _service_scan
    return _service_scan(
        db_path=db_path,
        config_path=config_path,
        months=months,
        limit=limit,
        scan_only=scan_only,
        download_only=download_only,
        log_callback=log_callback
    )


if __name__ == "__main__":
    main()
