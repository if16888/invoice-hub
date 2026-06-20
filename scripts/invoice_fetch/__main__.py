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
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import get_email_accounts, load_config, load_config_safe, RUNTIME_DIR, PROJECT_ROOT, is_outlook_like_account
from .credentials import get_auth_code
from .db import InvoiceDB, is_pending_evidence_invoice
from .excel_export import export_excel
from .attachment_handler import AttachmentHandler, build_managed_attachment_name
from .invoice_parser import InvoiceParser, parse_html_body, parse_subject
from .link_downloader import LinkDownloader, extract_html_from_message
from .mail_fetcher import MailFetcher
from .log_privacy import PrivacyLogFilter, mask_email, sanitize_log_message, mask_filename, mask_invoice_number, mask_path, mask_uid, redact_text
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


@dataclass(frozen=True)
class PendingEmailResult:
    """Structured pending-email outcome with legacy truthiness compatibility."""

    status: str

    def __bool__(self) -> bool:
        return self.status in {
            "recorded",
            "file_restored",
            "metadata_refreshed",
            "duplicate",
            "manual_required",
        }

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

def _configure_console_utf8():
    """Use UTF-8 consistently for Windows console logging."""
    if os.name != "nt":
        return

    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except (AttributeError, OSError):
        pass

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError, ValueError):
                pass


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
    for logger_name in ("urllib3", "keyring", "asyncio", "win32ctypes", "PIL"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


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

    # email-reprocess
    p_reprocess = subparsers.add_parser("email-reprocess", help="安全的邮箱重处理修复工具")
    p_reprocess.add_argument("--mailbox", help="指定 mailbox_key 或邮箱地址")
    p_reprocess.add_argument("--uid", action="append", type=int, help="要处理的邮件 UID，可重复指定")
    p_reprocess.add_argument("--uid-range", help="要处理的邮件 UID 范围，例如 10000-10200")
    p_reprocess.add_argument("--since", help="起始日期 (YYYY-MM-DD)")
    p_reprocess.add_argument("--until", help="结束日期 (YYYY-MM-DD)")
    p_reprocess.add_argument("--subject-contains", help="邮件主题包含关键词")
    p_reprocess.add_argument("--sender-contains", help="发件人包含关键词")
    p_reprocess.add_argument("--only-downloaded", action="store_true", default=True, help="只处理 downloaded=1 的邮件")
    p_reprocess.add_argument("--no-only-downloaded", action="store_false", dest="only_downloaded", help="处理包含未下载 (downloaded=0) 的邮件")
    p_reprocess.add_argument("--include-approved", action="store_true", help="允许处理已审核通过的发票记录")
    p_reprocess.add_argument("--include-claimed", action="store_true", help="允许处理已关联报销组的发票记录")
    p_reprocess.add_argument("--reclassify", action="store_true", help="重置 is_invoice 为 -1 并重新运行规则/AI 分类")
    p_reprocess.add_argument("--dry-run", action="store_true", help="仅预览修改，默认开启")
    p_reprocess.add_argument("--apply", action="store_true", help="真正执行修复")
    p_reprocess.add_argument("--limit", type=int, default=50, help="最多处理的邮件数量，默认 50")
    p_reprocess.add_argument("--headed", action="store_true", help="显示浏览器窗口（用于人工辅助验证或下载）")
    p_reprocess.add_argument("--force-large-batch", action="store_true", help="允许在 apply 模式下处理超过 200 封邮件")

    # evidence-repair
    p_ev_repair = subparsers.add_parser("evidence-repair", help="邮箱未关联证明材料修复工具")
    p_ev_repair.add_argument("--mailbox", required=True, help="指定 mailbox_key 邮箱账号")
    p_ev_repair.add_argument("--uid", type=int, required=True, help="指定邮件 UID")
    p_ev_repair.add_argument("--dry-run", action="store_true", help="仅预览，不修改数据库")
    p_ev_repair.add_argument("--apply", action="store_true", help="真实执行，修补待关联证明材料记录")

    return p.parse_args()


# ── Classify ─────────────────────────────────────────────────────────

def _classify(subject: str, sender: str, seller: str,
              categories: dict, item_name: str | None = None,
              invoice_type: str | None = None,
              raw_text: str | None = None,
              parse_note: str | None = None) -> tuple[str, str, bool]:
    """Return (category, extra_type, extra_required)."""
    dining_kws = ["餐饮服务", "餐费", "盒饭", "炒饭", "饭", "饮品", "早餐", "午餐", "晚餐", "小吃"]
    traffic_kws = ["旅客运输服务", "客运服务", "火车票", "铁路客运", "车票"]

    # 1. item_name strong keywords (highest priority)
    if item_name:
        item_name_lower = item_name.lower()
        if any(kw in item_name_lower for kw in dining_kws):
            return "餐饮", "", False

        if any(kw in item_name_lower for kw in traffic_kws):
            return "交通", "", False

    # 1.5 Toll keyword classification (should not override dining)
    toll_kws = ["通行费", "高速公路", "入站", "出口站", "车牌号", "ETC", "收费站"]
    check_str = ""
    if raw_text:
        check_str += " " + raw_text
    if item_name:
        check_str += " " + item_name
    if parse_note:
        check_str += " " + parse_note
    if invoice_type:
        check_str += " " + invoice_type
    if subject:
        check_str += " " + subject

    if any(kw in check_str for kw in toll_kws):
        return "过路费", "", False

    # 2. Existing seller/subject checks
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


# Module-level context for filename conflict log severity
_rename_source_mode: str = "normal"


def _rename_by_invoice_code(
    file_path: str, invoice_code: str, invoice_date: str,
    att_dir: Path, is_extra: bool = False,
    category: str = "", total_amount: str = "", invoice_number: str = "",
    source_mode: str | None = None,
    original_name: str | None = None,
    expense_date: str | None = None,
    fallback_date: str | None = None,
) -> str:
    """Rename a file to ``{date}/{YYYY-MM-DD_original_filename.ext}``.

    Returns the new relative path under RUNTIME_DIR.

    ``source_mode`` controls log severity for name conflicts:
    - ``"normal"`` – WARNING (first scan)
    - ``"reprocess"`` / ``"repair"`` – INFO (safe re-download / reprocess)
    If ``None`` (default), defers to the module-level ``_rename_source_mode``.
    """
    if not file_path:
        return file_path

    src = Path(file_path)
    if not src.exists():
        return file_path

    ext = src.suffix.lower() or ".pdf"
    date_dir = att_dir / _safe_date_dirname(invoice_date)
    date_dir.mkdir(parents=True, exist_ok=True)

    # Build the unified filename
    orig_name_to_use = original_name or src.name
    new_name = build_managed_attachment_name(
        original_name=orig_name_to_use,
        invoice_date=invoice_date,
        expense_date=expense_date,
        fallback_date=fallback_date,
        category=category or None,
        total_amount=total_amount or None,
        invoice_number=invoice_number or None,
        role="证明材料" if is_extra else "原件",
    )

    # Ensure extension matches src extension
    if not new_name.lower().endswith(ext):
        new_name = os.path.splitext(new_name)[0] + ext

    dest = date_dir / new_name
    # Avoid overwriting a different file; keep both invoices visible.
    effective_mode = source_mode if source_mode is not None else _rename_source_mode
    if dest.exists() and dest != src:
        try:
            if _sha256_file(dest) == _sha256_file(src):
                if is_extra:
                    src.unlink()
                else:
                    src.unlink()
                _log.info("  检测到相同附件内容，复用已存在文件: %s", mask_filename(dest.name))
                try:
                    return os.path.relpath(str(dest), RUNTIME_DIR)
                except ValueError:
                    return str(dest)
        except Exception:
            pass
        stem = dest.stem
        for n in range(1, 100):
            candidate = date_dir / f"{stem}_{n}{ext}"
            if not candidate.exists():
                dest = candidate
                conflict_msg = f"  检测到同名文件，已安全改名保存: {mask_filename(dest.name)}"
                if effective_mode in ("reprocess", "repair"):
                    _log.info(conflict_msg)
                else:
                    _log.warning(conflict_msg)
                break
        else:
            timestamp = datetime.now().strftime("%H%M%S")
            dest = date_dir / f"{stem}_{timestamp}{ext}"
            conflict_msg = f"  文件名冲突过多，改用时间戳保存: {mask_filename(dest.name)}"
            if effective_mode in ("reprocess", "repair"):
                _log.warning(conflict_msg)
            else:
                _log.warning(conflict_msg)

    if src != dest:
        if is_extra:
            shutil.copy2(str(src), str(dest))
            _log.info(
                "  已复制证明材料: %s -> %s/%s",
                mask_filename(src.name),
                redact_text(invoice_date, "date"),
                mask_filename(new_name),
            )
        else:
            shutil.move(str(src), str(dest))
            _log.info(
                "  已整理发票文件: %s -> %s/%s",
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


EVIDENCE_DOCUMENT_KEYWORDS = (
    "电子票据行程单",
    "通行费行程单",
    "行程单",
    "水单",
    "支付截图",
    "订单截图",
    "交易记录",
    "滴滴行程",
    "高德打车",
    "用车明细",
    "费用明细",
    "支付凭证",
    "订单明细",
    "铁路电子客票",
    "机票行程单",
)

STANDARD_INVOICE_TITLES = (
    "增值税电子普通发票",
    "增值税普通发票",
    "增值税专用发票",
    "电子发票",
    "数电发票",
)


def _normalize_amount_for_match(value: str) -> str:
    if not value:
        return ""
    try:
        from decimal import Decimal, ROUND_HALF_UP
        val = Decimal(value.replace(",", "").strip())
        return str(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return ""


def _looks_like_transport_evidence(text: str) -> bool:
    keywords = ["滴滴", "出行", "出租车", "网约车", "用车明细", "行程单", "行程记录", "高德打车", "T3出行", "曹操出行"]
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _extract_amount_candidates_for_evidence(text: str) -> list[str]:
    """Extract conservative money candidates from evidence-oriented text."""
    text = str(text or "")
    patterns = [
        r"(?:实付|合计|总计|金额)\s*[:：]?\s*(?:¥|￥|CNY|RMB)?\s*(\d{1,6}(?:\.\d{1,2})?)",
        r"(?:¥|￥|CNY|RMB)\s*(\d{1,6}(?:\.\d{1,2})?)",
        r"(?<!\d)(\d{1,6}(?:\.\d{1,2})?)\s*元",
        r"(?<!\d)(\d{1,6}\.\d{2})(?!\d)",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for value in re.findall(pattern, text, flags=re.IGNORECASE):
            normalized = _normalize_amount_for_match(value)
            if not normalized:
                continue
            try:
                numeric = float(normalized)
            except ValueError:
                continue
            if not 1 <= numeric <= 100000:
                continue
            if normalized not in candidates:
                candidates.append(normalized)
    return candidates


def _extract_evidence_match_hints(parsed, file_path: Path, source_name: str = "") -> dict:
    from .invoice_parser import normalize_date
    combined_text = " ".join([
        file_path.name,
        source_name,
        getattr(parsed, "raw_text", "") or "",
        getattr(parsed, "parse_note", "") or ""
    ])

    dates = []
    # YYYY-MM-DD
    for d in re.findall(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", combined_text):
        dates.append(f"{d[0]}-{int(d[1]):02d}-{int(d[2]):02d}")
    # YYYY年MM月DD日
    for d in re.findall(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", combined_text):
        dates.append(f"{d[0]}-{int(d[1]):02d}-{int(d[2]):02d}")

    amounts = _extract_amount_candidates_for_evidence(combined_text)

    parsed_date = normalize_date(getattr(parsed, "invoice_date", "") or "")
    if parsed_date and parsed_date not in dates:
        dates.append(parsed_date)
    parsed_amount = getattr(parsed, "total_amount", "") or getattr(parsed, "amount", "") or ""
    if parsed_amount:
        norm_parsed = _normalize_amount_for_match(parsed_amount)
        if norm_parsed and norm_parsed not in amounts:
            amounts.append(norm_parsed)

    return {
        "dates": list(set(dates)),
        "amounts": list(set(amounts)),
        "combined_text": combined_text
    }


def _is_evidence_document(parsed, file_path: Path, text_hint: str = "") -> bool:
    """Identify supporting evidence without reclassifying standard invoices."""
    document_text = " ".join([
        str(file_path.name if file_path else ""),
        str(getattr(parsed, "raw_text", "") or ""),
        str(getattr(parsed, "parse_note", "") or ""),
        str(text_hint or ""),
    ])
    if any(title in document_text for title in STANDARD_INVOICE_TITLES):
        return False

    evidence_text = " ".join([
        document_text,
        str(getattr(parsed, "invoice_type", "") or ""),
    ])
    return any(keyword in evidence_text for keyword in EVIDENCE_DOCUMENT_KEYWORDS)


def _find_matching_invoice_for_evidence(
    db: InvoiceDB,
    parsed,
    file_path: Path,
    source_name: str = "",
) -> tuple[dict | None, str | None]:
    """Find a standard invoice using exact invoice-number matches or conservative hints."""
    candidates: list[str] = []
    parsed_number = str(getattr(parsed, "invoice_number", "") or "").strip()
    if parsed_number:
        candidates.append(parsed_number)
    candidates.extend(
        number
        for number in re.findall(
            r"(?<!\d)(\d{8,20})(?!\d)",
            " ".join((file_path.stem, Path(source_name).stem)),
        )
        if number not in candidates
    )

    # 1. Try exact matches first
    for invoice_number in candidates:
        existing = db.find_invoice_by_number(invoice_number)
        if not existing:
            continue
        if is_pending_evidence_invoice(existing):
            continue
        return existing, None

    # 2. Try conservative transport/taxi matching rules
    # First, gather hints
    hints = _extract_evidence_match_hints(parsed, file_path, source_name)
    combined_text = hints["combined_text"]
    if not _looks_like_transport_evidence(combined_text):
        return None, None

    dates = hints["dates"]
    amounts = hints["amounts"]

    # We must have at least one date and one amount to attempt a guess match
    if not dates or not amounts:
        return None, "unmatched" if dates or amounts else None

    from .invoice_parser import normalize_date
    # Retrieve all invoices and filter
    all_invoices = db.get_all_invoices(include_deleted=False)
    matches = []
    transport_kws = ["滴滴", "出行", "出租车", "网约车", "高德打车", "t3出行", "曹操出行"]

    for inv in all_invoices:
        if is_pending_evidence_invoice(inv):
            continue

        # Check date
        inv_date = normalize_date(str(inv.get("invoice_date") or ""))
        if inv_date not in dates:
            continue

        # Check amount
        inv_amount = _normalize_amount_for_match(str(inv.get("total_amount") or ""))
        if inv_amount not in amounts:
            continue

        # Check transport category/context
        combined_inv_fields = " ".join([
            str(inv.get("seller_name") or ""),
            str(inv.get("mail_subject") or ""),
            str(inv.get("attachment_path") or "")
        ]).lower()
        has_transport_context = (
            inv.get("category") in ("出租车", "交通") or
            any(kw in combined_inv_fields for kw in transport_kws)
        )
        if has_transport_context:
            matches.append(inv)

    if len(matches) == 1:
        return matches[0], None
    elif len(matches) > 1:
        return None, "multiple"

    return None, "unmatched"


def _attach_evidence_to_invoice(
    db: InvoiceDB,
    invoice: dict,
    file_path: Path,
) -> bool:
    """Attach evidence to an invoice, deduplicating by path and file content."""
    code = invoice.get("invoice_code") or invoice.get("invoice_number") or "extra"
    inv_date = invoice.get("invoice_date") or invoice.get("mail_date") or "unknown_date"
    att_dir = RUNTIME_DIR / "attachments"

    renamed_rel = _rename_by_invoice_code(
        str(file_path),
        invoice_code=code,
        invoice_date=inv_date,
        att_dir=att_dir,
        is_extra=True,
        category=invoice.get("category") or "",
        total_amount=invoice.get("total_amount") or "",
        invoice_number=invoice.get("invoice_number") or "",
        expense_date=invoice.get("expense_date"),
        fallback_date=invoice.get("mail_date") or invoice.get("created_at"),
    )
    if not renamed_rel:
        return False

    resolved_path = RUNTIME_DIR / renamed_rel
    stored_path = renamed_rel

    extra_paths = _normalize_path_list(invoice.get("extra_paths"))
    if stored_path in extra_paths:
        return False

    file_hash = _sha256_file(resolved_path) if resolved_path.exists() else ""
    if file_hash:
        for existing_path in extra_paths:
            resolved = _resolve_runtime_path(existing_path)
            if resolved and _sha256_file(resolved) == file_hash:
                if resolved.resolve() != resolved_path.resolve():
                    try:
                        resolved_path.unlink()
                    except OSError:
                        pass
                return False

    extra_paths.append(stored_path)
    db.update_invoice_file_paths(invoice["id"], extra_paths=extra_paths)
    db.update_invoice_extra_flags(
        invoice["id"],
        has_extra=True,
        missing_extra=False,
    )
    _log.info(
        "  已将证明材料关联到发票: invoice_id=%s file=%s",
        invoice["id"],
        mask_filename(resolved_path.name),
    )
    return True


def _attach_email_extras_to_invoice(
    db: InvoiceDB,
    invoice_id: int,
    extra_files: list,
    code: str,
    inv_date: str,
    att_base: Path,
    category: str,
    total_amount: str,
    invoice_number: str,
    kept_paths: set,
    attached_source_paths: set[str] | None = None,
    expense_date: str | None = None,
    fallback_date: str | None = None,
) -> list[str]:
    """Rename and associate extra files with an invoice, avoiding duplicate paths or file hashes.

    Returns the list of all associated extra paths (stored relative paths).
    """
    inv = db.get_invoice(invoice_id)
    if not inv:
        return []
    current_extras = _normalize_path_list(inv.get("extra_paths"))

    # Pre-calculate hashes of existing extras
    existing_hashes = set()
    for ep in current_extras:
        res = _resolve_runtime_path(ep)
        if res and res.exists():
            try:
                existing_hashes.add(_sha256_file(res))
            except Exception:
                pass

    updated = False
    for e in extra_files:
        e_path = Path(e.file_path)
        source_path = ""
        if e_path.exists():
            source_path = str(e_path.resolve())
            kept_paths.add(source_path)
            try:
                h = _sha256_file(e_path)
                if h in existing_hashes:
                    if attached_source_paths is not None:
                        attached_source_paths.add(source_path)
                    continue
            except Exception:
                pass

        ep = _rename_by_invoice_code(
            e.file_path, code, inv_date, att_base, is_extra=True,
            category=category, total_amount=total_amount,
            invoice_number=invoice_number,
            original_name=getattr(e, "original_name", None),
            expense_date=expense_date,
            fallback_date=fallback_date,
        )
        if ep:
            if ep in current_extras:
                kept_paths.add(str((att_base.parent / ep).resolve()))
                if attached_source_paths is not None and source_path:
                    attached_source_paths.add(source_path)
                continue

            res_ep = _resolve_runtime_path(ep)
            if res_ep and res_ep.exists():
                try:
                    h_new = _sha256_file(res_ep)
                    if h_new in existing_hashes:
                        if str(res_ep.resolve()) not in kept_paths:
                            res_ep.unlink()
                        if attached_source_paths is not None and source_path:
                            attached_source_paths.add(source_path)
                        continue
                    existing_hashes.add(h_new)
                except Exception:
                    pass

            kept_paths.add(str((att_base.parent / ep).resolve()))
            current_extras.append(ep)
            updated = True
            if attached_source_paths is not None and source_path:
                attached_source_paths.add(source_path)

    if updated:
        db.update_invoice_file_paths(invoice_id, extra_paths=current_extras)
        _log.info("  已为发票 %s 关联/追加额外的证明材料: %s", invoice_id, current_extras)

    if current_extras:
        db.update_invoice_extra_flags(
            invoice_id,
            has_extra=True,
            missing_extra=False,
        )

    return current_extras


def _extract_pdf_text_simple(path: Path) -> str:
    """Extract first 2 pages text from a PDF file simply without creating InvoiceParser."""
    if not path or not path.exists() or path.suffix.lower() != ".pdf":
        return ""
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            text = ""
            for p in pdf.pages[:2]:
                t = p.extract_text()
                if t:
                    text += t + "\n"
            # Normalize radical variants
            text = text.replace("\u2f26", "月").replace("\u2f49", "月")
            text = text.replace("\u2f3c", "日").replace("\u2f47", "日").replace("\u2f52", "日")
            return text
    except Exception as e:
        _log.debug("PDF 文本提取失败 %s: %s", path, e)
        return ""


def _extract_possible_order_index(filename: str) -> int | None:
    """Extract a 1-2 digit sequence number from a filename stem."""
    if not filename:
        return None
    name_without_ext = Path(filename).stem
    # Match standalone 1-2 digits
    matches = re.findall(r"(?:^|[^0-9])([0-9]{1,2})(?:$|[^0-9])", name_without_ext)
    if matches:
        try:
            return int(matches[-1]) # Use the last sequence number candidate
        except ValueError:
            pass
    return None


def score_evidence_invoice_match(
    evidence_hint: dict,
    invoice_hint: dict,
    invoice_count: int,
    evidence_count: int,
) -> tuple[int, list[str]]:
    """Calculate match score and return reasons for a pair of evidence and invoice."""
    score = 0
    reasons = []

    # 0. Invoice number or code directly present in filename stem (Strong matching signal)
    inv_num = invoice_hint.get("invoice_number")
    inv_code = invoice_hint.get("invoice_code")
    ev_orig = (evidence_hint.get("original_name") or "").lower()

    if inv_num and len(inv_num) >= 6 and inv_num.lower() in ev_orig:
        score += 100
        reasons.append(f"发票号存在于文件名中(+100): {inv_num}")
    if inv_code and len(inv_code) >= 6 and inv_code.lower() in ev_orig:
        score += 100
        reasons.append(f"发票代码存在于文件名中(+100): {inv_code}")

    # 1. Amount matching (Total amount or Pre-tax amount)
    inv_amt = invoice_hint.get("total_amount") or invoice_hint.get("amount") or ""
    if inv_amt and inv_amt in evidence_hint["amounts"]:
        score += 50
        reasons.append(f"金额一致(+50): {inv_amt}")
    elif inv_amt and evidence_hint["amounts"]:
        score -= 60
        reasons.append("金额冲突(-60)")

    # 2. Date matching
    inv_date = invoice_hint.get("invoice_date") or ""
    if inv_date and inv_date in evidence_hint["dates"]:
        score += 30
        reasons.append(f"日期一致(+30): {inv_date}")
    elif inv_date and evidence_hint["dates"]:
        score -= 30
        reasons.append("日期冲突(-30)")

    # 3. Sequence number matching (like -01, _02, (3))
    inv_seq = invoice_hint.get("possible_order_index")
    ev_seq = evidence_hint.get("possible_order_index")
    if inv_seq is not None and ev_seq is not None and inv_seq == ev_seq:
        score += 20
        reasons.append(f"文件名序号一致(+20): {inv_seq}")

    # 4. Attachment order matching (when counts match)
    if invoice_count == evidence_count and invoice_count > 0:
        inv_rank = invoice_hint.get("attachment_rank")
        ev_rank = evidence_hint.get("attachment_rank")
        if inv_rank is not None and ev_rank is not None and inv_rank == ev_rank:
            score += 15
            reasons.append(f"附件顺序一致(+15): rank {inv_rank}")

    # 5. Shared token in filenames (such as order number or serials >= 4 chars)
    inv_orig = invoice_hint.get("original_name") or ""
    ev_orig = evidence_hint.get("original_name") or ""

    def get_meaningful_tokens(name: str) -> set[str]:
        name_lower = name.lower()
        stem = Path(name_lower).stem
        tokens = set(re.findall(r"[a-z0-9]{4,}", stem))
        noise = {"fapiao", "invoice", "pdf", "ofd", "xingcheng", "xingchengdan", "evidence", "extra"}
        return tokens - noise

    inv_tokens = get_meaningful_tokens(inv_orig)
    ev_tokens = get_meaningful_tokens(ev_orig)
    shared = inv_tokens & ev_tokens
    if shared:
        score += 10
        reasons.append(f"文件名共享标识符(+10): {list(shared)}")

    return score, reasons


def _match_email_extras_to_invoices(
    extra_files: list,
    invoice_infos: list,
    config: dict | None = None,
) -> tuple[dict[int, list], list]:
    """Map each extra to one parsed invoice using scoring or single-invoice routing."""
    if not invoice_infos:
        return {}, list(extra_files)

    invoice_count = len(invoice_infos)
    evidence_count = len(extra_files)

    allow_unconditional = False
    if config:
        allow_unconditional = config.get("allow_unconditional_single_invoice_extras", False)

    # Case 1: Single Invoice in Email with unconditional matching enabled
    if invoice_count == 1 and allow_unconditional:
        matched = invoice_infos[0]
        for extra in extra_files:
            orig_name = getattr(extra, "original_name", "") or (Path(extra.file_path).name if getattr(extra, "file_path", None) else "")
            _log.info(
                "  单发票邮件：证明材料 %s 直接自动关联到唯一的发票 %s (无条件配置生效)",
                mask_filename(orig_name),
                mask_invoice_number(str(getattr(matched, "invoice_number", "") or "")),
            )
        return {id(matched): list(extra_files)}, []

    # Calculate attachment rank for sorting consistency
    def get_info_idx(info):
        orig = getattr(info, "original_file", None)
        return getattr(orig, "attachment_index", 999)
    sorted_infos = sorted(invoice_infos, key=get_info_idx)
    for r, info in enumerate(sorted_infos):
        info.attachment_rank = r

    def get_extra_idx(extra):
        return getattr(extra, "attachment_index", 999)
    sorted_extras = sorted(extra_files, key=get_extra_idx)
    for r, extra in enumerate(sorted_extras):
        extra.attachment_rank = r

    # Construct invoice hints
    invoice_hints = {}
    for info in invoice_infos:
        orig_file = getattr(info, "original_file", None)
        orig_name = ""
        if orig_file:
            orig_name = getattr(orig_file, "original_name", "") or (Path(orig_file.file_path).name if getattr(orig_file, "file_path", None) else "")
        invoice_hints[id(info)] = {
            "invoice_number": getattr(info, "invoice_number", ""),
            "invoice_code": getattr(info, "invoice_code", ""),
            "invoice_date": getattr(info, "invoice_date", ""),
            "total_amount": _normalize_amount_for_match(getattr(info, "total_amount", "")),
            "amount": _normalize_amount_for_match(getattr(info, "amount", "")),
            "seller_name": getattr(info, "seller_name", ""),
            "original_name": orig_name,
            "attachment_index": getattr(orig_file, "attachment_index", 999),
            "attachment_rank": getattr(info, "attachment_rank", 999),
            "possible_order_index": _extract_possible_order_index(orig_name),
        }

    # Construct evidence hints
    evidence_hints = {}
    for extra in extra_files:
        orig_name = getattr(extra, "original_name", "") or (Path(extra.file_path).name if getattr(extra, "file_path", None) else "")
        file_path_str = getattr(extra, "file_path", "")
        file_path = Path(file_path_str) if file_path_str else None

        # Simple text extraction for scoring dates and amounts
        pdf_text = ""
        if file_path:
            pdf_text = _extract_pdf_text_simple(file_path)

        hints = _extract_evidence_match_hints(None, file_path, orig_name)
        if pdf_text:
            # Extract date (YYYY-MM-DD)
            for d in re.findall(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", pdf_text):
                hints["dates"].append(f"{d[0]}-{int(d[1]):02d}-{int(d[2]):02d}")
            # YYYY年MM月DD日
            for d in re.findall(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", pdf_text):
                hints["dates"].append(f"{d[0]}-{int(d[1]):02d}-{int(d[2]):02d}")
            # Extract money candidates
            for amt in _extract_amount_candidates_for_evidence(pdf_text):
                hints["amounts"].append(amt)

            hints["dates"] = list(set(hints["dates"]))
            hints["amounts"] = list(set(hints["amounts"]))

        evidence_hints[id(extra)] = {
            "original_name": orig_name,
            "text": pdf_text,
            "dates": hints["dates"],
            "amounts": hints["amounts"],
            "attachment_index": getattr(extra, "attachment_index", 999),
            "attachment_rank": getattr(extra, "attachment_rank", 999),
            "possible_order_index": _extract_possible_order_index(orig_name),
        }

    # Case 2: Single Invoice conservative matching (allow_unconditional = False)
    if invoice_count == 1:
        matched_info = invoice_infos[0]
        matched_extras = []
        unmatched_extras = []
        for extra in extra_files:
            ev_hint = evidence_hints[id(extra)]
            inv_hint = invoice_hints[id(matched_info)]
            score, reasons = score_evidence_invoice_match(ev_hint, inv_hint, invoice_count, evidence_count)

            file_path_str = getattr(extra, "file_path", "")
            file_path = Path(file_path_str) if file_path_str else None

            combined_text_for_transport = ev_hint["original_name"] + " " + ev_hint["text"]
            is_evidence = _is_evidence_document(None, file_path, text_hint=ev_hint["original_name"]) or \
                          _looks_like_transport_evidence(combined_text_for_transport)

            # 排除附件顺序分和随机 shared token 分，必须有强证据（如日期/金额/发票号代码/文件名序号）
            effective_score = score
            for r_msg in reasons:
                if "附件顺序" in r_msg:
                    effective_score -= 15
                elif "文件名共享标识符" in r_msg:
                    effective_score -= 10

            if effective_score > 0 or is_evidence:
                matched_extras.append(extra)
                _log.info(
                    "  单发票邮件（保守模式）：证明材料 %s 匹配成功 (score=%d, reasons=%s, is_evidence=%s)，关联到唯一发票 %s",
                    mask_filename(ev_hint["original_name"]),
                    score,
                    ", ".join(reasons),
                    is_evidence,
                    mask_invoice_number(str(getattr(matched_info, "invoice_number", "") or "")),
                )
            else:
                unmatched_extras.append(extra)
                _log.info(
                    "  单发票邮件（保守模式）：证明材料 %s 未通过保守匹配校验，准备保留为待关联 (score=%d)",
                    mask_filename(ev_hint["original_name"]),
                    score,
                )
        return {id(matched_info): matched_extras}, unmatched_extras

    # Case 3: Multiple Invoices in Email -> strict matching
    matches_by_invoice: dict[int, list] = {}
    unmatched = []
    extra_matches = []

    for extra in extra_files:
        ev_hint = evidence_hints[id(extra)]
        scores = []
        for info in invoice_infos:
            inv_hint = invoice_hints[id(info)]
            score, reasons = score_evidence_invoice_match(ev_hint, inv_hint, invoice_count, evidence_count)
            scores.append((info, score, reasons))

        scores.sort(key=lambda x: x[1], reverse=True)
        if not scores:
            unmatched.append(extra)
            continue

        best_info, best_score, best_reasons = scores[0]

        is_valid_match = False
        if best_score >= 70:
            if len(scores) > 1:
                second_score = scores[1][1]
                if best_score - second_score >= 20:
                    is_valid_match = True
                else:
                    _log.info(
                        "  多发票邮件：证明材料 %s 与两张发票匹配分数太接近(最高分=%d, 次高分=%d)，置信度不足，准备保留为待关联",
                        mask_filename(ev_hint["original_name"]), best_score, second_score
                    )
            else:
                is_valid_match = True
        else:
            _log.info(
                "  多发票邮件：证明材料未达到自动关联阈值，准备保留为待关联: %s (最高分=%d, 原因=%s)",
                mask_filename(ev_hint["original_name"]), best_score, ", ".join(best_reasons)
            )

        if is_valid_match:
            extra_matches.append((extra, best_info, best_score, best_reasons))
        else:
            unmatched.append(extra)

    # Assign matches greedily by score
    extra_matches.sort(key=lambda x: x[2], reverse=True)
    assigned_extras = set()
    assigned_invoices = set()
    strict_one_to_one = (invoice_count == evidence_count and invoice_count > 1)

    for extra, info, score, reasons in extra_matches:
        if id(extra) in assigned_extras:
            continue

        if strict_one_to_one and id(info) in assigned_invoices:
            unmatched.append(extra)
            _log.info(
                "  多发票同数目邮件（一对一硬化）：证明材料 %s 的最佳匹配发票 %s 已被更匹配的材料占用，退回为待关联",
                mask_filename(getattr(extra, "original_name", "") or Path(extra.file_path).name),
                mask_invoice_number(str(getattr(info, "invoice_number", "") or "")),
            )
            continue

        assigned_extras.add(id(extra))
        if strict_one_to_one:
            assigned_invoices.add(id(info))

        matches_by_invoice.setdefault(id(info), []).append(extra)
        _log.info(
            "  多发票邮件：证明材料按 %s 自动匹配到发票 %s，score=%d reason=%s",
            "日期+金额/文件名/顺序",
            mask_invoice_number(str(getattr(info, "invoice_number", "") or "")),
            score,
            ", ".join(reasons)
        )

    return matches_by_invoice, unmatched



def _import_local_evidence(
    db: InvoiceDB,
    parsed,
    file_path: Path,
    source_name: str,
    categories: dict,
    preserve_source_path: bool = False,
) -> tuple[str, int | None] | None:
    """Attach strong-matched evidence or retain it as a pending-link record."""
    if not _is_evidence_document(parsed, file_path, source_name):
        return None

    matching_invoice, match_status = _find_matching_invoice_for_evidence(
        db,
        parsed,
        file_path,
        source_name=source_name,
    )
    if matching_invoice:
        attached = _attach_evidence_to_invoice(db, matching_invoice, file_path)
        if not attached and not preserve_source_path:
            try:
                file_path.unlink()
            except OSError:
                pass
        return ("added", matching_invoice["id"]) if attached else ("duplicate", None)

    parse_note = str(getattr(parsed, "parse_note", "") or "")
    if match_status == "multiple":
        note = "疑似滴滴/出租车证明材料，但匹配到多张候选发票，请人工关联"
        _log.info("  发现多个候选主发票，已保留为待关联证明材料")
    elif match_status == "unmatched":
        note = "发现疑似证明材料，但没有唯一匹配的主发票，请人工关联"
        _log.info("  发现疑似证明材料，但没有唯一匹配的主发票，请人工关联")
    else:
        note = f"待关联证明材料: {parse_note or '未匹配到已有发票号码'}"

    return _insert_local_exception(
        db=db,
        file_path=file_path,
        original_name=source_name,
        note=note,
        categories=categories,
        invoice_type="待关联证明材料",
    )


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


def _looks_like_fiscal_platform_seller_name(name: str) -> bool:
    if not name:
        return False
    name = name.strip()
    # Matches XX省/市/自治区/特别行政区财政电子票据
    pat = re.compile(
        r"^(?:[\u4e00-\u9fff]{2,12}?(?:省|市|自治区|特别行政区))?财政电子票据$"
    )
    if pat.match(name):
        return True

    # Matches various platform names
    platforms = [
        "财政电子票据公共服务平台",
        "财政电子票据服务平台",
        "财政票据公共服务平台",
    ]
    if any(p in name for p in platforms):
        return True

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
    item_name: str = "",
    expense_date: str = "",
    date_source: str = "",
    force_refresh_metadata: bool = False,
) -> bool:
    """Refresh parsed invoice metadata in place, with safe backfill.

    - approved/claimed invoices: skip business-field refresh (only backfill attachment_path)
    - to_review/error invoices: refresh all fields + safe backfill missing fields

    Safety constraints on force_refresh_metadata:
    - force_refresh_metadata=True is a dangerous explicit overwrite mode, which will overwrite
      existing business metadata fields. It should only be used in scenarios where explicit user
      intent requires metadata force-refresh.
    - By default, force_refresh_metadata=False is used for safe backfilling, ensuring existing
      fields (seller_name, amount, invoice_date, category) are preserved if non-empty.
    - Both approved and claimed records are never overwritten for business fields under any circumstances.
    """
    existing_status = str(existing.get("review_status") or "to_review")
    is_approved = existing_status in ("approved",)
    is_claimed = db.count_claim_links(existing["id"]) > 0

    if is_approved or is_claimed:
        # Approved or Claimed: skip business-field metadata overwrite, but signal
        # success so callers can still backfill attachment_path.
        reason = "已审核" if is_approved else "已报销"
        _log.info("  重复发票%s，跳过元数据刷新但允许附件回填: existing_id=%d", reason, existing["id"])
        return True

    # For to_review / error / ignored: refresh + safe backfill missing fields
    existing_category = str(existing.get("category") or "").strip()
    existing_seller = str(existing.get("seller_name") or "").strip()

    backfill_dining = False
    if existing_category in ("", "其他", "未分类") and category == "餐饮" and item_name:
        dining_kws = ["餐饮服务", "餐费", "盒饭", "炒饭", "饭", "饮品", "早餐", "午餐", "晚餐", "小吃"]
        if any(kw in item_name.lower() for kw in dining_kws):
            backfill_dining = True

    backfill_fiscal_seller = False
    backfill_fiscal_category = False
    clear_miswritten_platform_seller = False
    if existing_status == "to_review" and not is_claimed:
        new_is_fiscal_fallback = (
            seller_name
            and ("开票/收款/执收单位识别" in parse_note or "票据章附近文本推断" in parse_note)
            and not any(kw in parse_note for kw in ["检测到财政电子票据平台", "未识别到具体开票单位", "platform_only"])
        )
        if not existing_seller and new_is_fiscal_fallback:
            backfill_fiscal_seller = True
        if existing_category in ("", "其他", "未分类") and category == "过路费":
            backfill_fiscal_category = True

        is_platform_only_parse = "未识别到具体开票单位" in parse_note or "platform_only" in parse_note
        if _looks_like_fiscal_platform_seller_name(existing_seller) and is_platform_only_parse:
            clear_miswritten_platform_seller = True

    if force_refresh_metadata:
        backfill_fields = {}
        for field_key, new_val in [
            ("seller_name", seller_name),
            ("buyer_name", buyer_name),
            ("invoice_date", invoice_date),
            ("total_amount", total_amount),
            ("amount", amount),
            ("category", category),
            ("invoice_type", invoice_type),
        ]:
            existing_val = str(existing.get(field_key) or "").strip()
            new_val_str = str(new_val or "").strip()
            if new_val_str and not existing_val:
                backfill_fields[field_key] = new_val_str

        # If safe backfill dining applies, ensure we backfill category as dining even if not empty (like "其他")
        if backfill_dining and backfill_fields.get("category") != "餐饮":
            backfill_fields["category"] = "餐饮"

        # Apply fiscal fallback backfills if conditions met
        if backfill_fiscal_seller:
            backfill_fields["seller_name"] = seller_name
        if backfill_fiscal_category:
            backfill_fields["category"] = "过路费"

        if backfill_fields:
            db.update_invoice_missing_fields(
                existing["id"], backfill_fields, only_if_empty=True,
            )

        if backfill_dining:
            _log.info("重复发票根据项目名称回填消费类型: existing_id=%d, category=餐饮", existing["id"])

        if backfill_fiscal_seller or backfill_fiscal_category:
            f_list = []
            if backfill_fiscal_seller:
                f_list.append("seller_name")
            if backfill_fiscal_category:
                f_list.append("category")
            _log.info("财政票据开票单位 fallback 已回填: existing_id=%d, fields=%s", existing["id"], ",".join(f_list))

        if clear_miswritten_platform_seller:
            _log.info("财政票据平台名不是销售方，已清空旧的 seller_name: existing_id=%d", existing["id"])

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
            item_name=item_name,
            expense_date=expense_date,
            date_source=date_source,
        )
    else:
        # Safe backfill (default): do not overwrite non-empty fields in existing.
        # Ensure seller_name, amount, invoice_date (date), category, etc. are preserved if non-empty.
        if clear_miswritten_platform_seller:
            updated_seller_name = ""
        elif backfill_fiscal_seller:
            updated_seller_name = seller_name
        else:
            updated_seller_name = existing.get("seller_name") if str(existing.get("seller_name") or "").strip() else seller_name

        updated_amount = existing.get("amount") if str(existing.get("amount") or "").strip() else amount
        updated_total_amount = existing.get("total_amount") if str(existing.get("total_amount") or "").strip() else total_amount
        updated_invoice_date = existing.get("invoice_date") if str(existing.get("invoice_date") or "").strip() else invoice_date

        weak_sources = {"", "unknown", "legacy", "invoice_date"}
        strong_sources = {"travel_date", "service_date", "payment_date"}

        new_expense_date_clean = str(expense_date or "").strip()
        new_date_source_clean = str(date_source or "").strip()
        existing_expense_date_clean = str(existing.get("expense_date") or "").strip()
        existing_date_source_clean = str(existing.get("date_source") or "").strip()

        # Date source upgrade rule
        is_upgrade = (
            new_expense_date_clean
            and new_date_source_clean in strong_sources
            and existing_date_source_clean in weak_sources
            and existing_expense_date_clean != new_expense_date_clean
        )

        if is_upgrade:
            updated_expense_date = new_expense_date_clean
            updated_date_source = new_date_source_clean
            _log.info(
                "  重复发票费用日期升级: existing_id=%d, %s(%s) -> %s(%s)",
                existing["id"],
                existing_expense_date_clean or "空",
                existing_date_source_clean or "空",
                new_expense_date_clean,
                new_date_source_clean
            )
        else:
            updated_expense_date = existing.get("expense_date") if existing_expense_date_clean else expense_date
            updated_date_source = existing.get("date_source") if existing_date_source_clean else date_source

        if backfill_fiscal_category:
            updated_category = "过路费"
        elif backfill_dining:
            updated_category = "餐饮"
        else:
            updated_category = existing.get("category") if str(existing.get("category") or "").strip() else category

        updated_buyer_name = existing.get("buyer_name") if str(existing.get("buyer_name") or "").strip() else buyer_name
        updated_invoice_type = existing.get("invoice_type") if str(existing.get("invoice_type") or "").strip() else invoice_type
        updated_invoice_code = existing.get("invoice_code") if str(existing.get("invoice_code") or "").strip() else invoice_code
        updated_item_name = existing.get("item_name") if str(existing.get("item_name") or "").strip() else item_name

        # Log fields being backfilled
        backfilled_logs = []
        fiscal_logged_fields = set()
        if backfill_fiscal_seller:
            fiscal_logged_fields.add("seller_name")
        if backfill_fiscal_category:
            fiscal_logged_fields.add("category")

        for k, old, new in [
            ("seller_name", existing.get("seller_name"), seller_name),
            ("amount", existing.get("amount"), amount),
            ("total_amount", existing.get("total_amount"), total_amount),
            ("invoice_date", existing.get("invoice_date"), invoice_date),
            ("expense_date", existing.get("expense_date"), expense_date),
            ("category", existing.get("category"), updated_category),
            ("buyer_name", existing.get("buyer_name"), buyer_name),
            ("invoice_type", existing.get("invoice_type"), invoice_type),
            ("invoice_code", existing.get("invoice_code"), invoice_code),
        ]:
            if k in fiscal_logged_fields:
                continue
            if not str(old or "").strip() and str(new or "").strip():
                backfilled_logs.append(k)

        if backfilled_logs:
            _log.info("  重复发票回填空字段: existing_id=%d, fields=%s", existing["id"], ",".join(backfilled_logs))

        if backfill_dining:
            _log.info("重复发票根据项目名称回填消费类型: existing_id=%d, category=餐饮", existing["id"])

        if backfill_fiscal_seller or backfill_fiscal_category:
            f_list = sorted(list(fiscal_logged_fields))
            _log.info("财政票据开票单位 fallback 已回填: existing_id=%d, fields=%s", existing["id"], ",".join(f_list))

        if clear_miswritten_platform_seller:
            _log.info("财政票据平台名不是销售方，已清空旧的 seller_name: existing_id=%d", existing["id"])

        return db.update_invoice_parsed_metadata(
            existing["id"],
            invoice_number=existing.get("invoice_number") or invoice_number,
            invoice_code=updated_invoice_code,
            invoice_date=updated_invoice_date,
            amount=updated_amount,
            total_amount=updated_total_amount,
            seller_name=updated_seller_name,
            buyer_name=updated_buyer_name,
            invoice_type=updated_invoice_type,
            category=updated_category,
            has_extra=has_extra,
            extra_type=extra_type,
            missing_extra=missing_extra,
            parse_success=True,
            parse_note=parse_note,
            item_name=updated_item_name,
            expense_date=updated_expense_date,
            date_source=updated_date_source,
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
    invoice_type: str = "本地导入待处理",
) -> tuple[str, int | None]:
    file_hash = _sha256_file(file_path) if file_path.exists() else ""
    existing_by_hash = db.find_invoice_by_file_hash(file_hash, include_deleted=True) if file_hash else None
    if existing_by_hash:
        existing_by_hash = _restore_existing_invoice_if_deleted(db, existing_by_hash, "本地导入")
        if int(existing_by_hash.get("is_deleted") or 0) == 0 and existing_by_hash.get("attachment_path"):
            _log.info("  本地导入跳过重复文件: %s", mask_filename(original_name))
            return "duplicate", None
        category, _, _ = _classify(original_name, "local import", "", categories)
        import_date = datetime.now().strftime("%Y-%m-%d")
        att_dir = RUNTIME_DIR / "attachments"
        attachment_path = _rename_by_invoice_code(
            str(file_path),
            invoice_code="exception",
            invoice_date=import_date,
            att_dir=att_dir,
            category=category,
            original_name=original_name,
            fallback_date=import_date,
        )
        db.update_invoice_file_paths(existing_by_hash["id"], attachment_path=attachment_path)
        _log.info("  本地导入恢复已删除待处理文件: %s", mask_filename(original_name))
        return "pending_manual", existing_by_hash["id"]

    category, extra_type, extra_required = _classify(original_name, "local import", "", categories)
    import_date = datetime.now().strftime("%Y-%m-%d")
    att_dir = RUNTIME_DIR / "attachments"
    attachment_path = _rename_by_invoice_code(
        str(file_path),
        invoice_code="exception",
        invoice_date=import_date,
        att_dir=att_dir,
        category=category,
        original_name=original_name,
        fallback_date=import_date,
    )

    rec = {
        "invoice_number": "",
        "invoice_code": "",
        "invoice_date": "",
        "expense_date": "",
        "date_source": "unknown",
        "amount": "",
        "total_amount": "",
        "seller_name": "",
        "buyer_name": "",
        "invoice_type": invoice_type,
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
        "attachment_path": attachment_path,
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
    evidence_result = _import_local_evidence(
        db=db,
        parsed=info,
        file_path=file_path,
        source_name=source_name,
        categories=categories,
        preserve_source_path=preserve_source_path,
    )
    if evidence_result is not None:
        return evidence_result

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
        category, extra_type, extra_required = _classify(
            f"{source_name} {info.invoice_type or ''}", "local import",
            info.seller_name or "", categories,
            item_name=info.item_name, invoice_type=info.invoice_type,
            raw_text=info.raw_text, parse_note=info.parse_note
        )
        refreshed = _refresh_invoice_from_parse(
            db=db,
            existing=existing_by_hash,
            invoice_number=info.invoice_number or "",
            invoice_code=info.invoice_code or "",
            invoice_date=info.invoice_date or "",
            expense_date=info.expense_date or "",
            date_source=info.date_source or "",
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
            item_name=info.item_name,
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

    # A bilingual or regenerated receipt can have different bytes and omit
    # different optional fields. Its provider order ID remains the stable key.
    if info.invoice_type == "网约车电子收据" and info.invoice_number:
        existing_receipt = db.find_invoice_by_number(info.invoice_number, include_deleted=True)
        if existing_receipt and existing_receipt.get("invoice_type") == "网约车电子收据":
            existing_receipt = _restore_existing_invoice_if_deleted(
                db, existing_receipt, "本地导入收据"
            )
            category, extra_type, extra_required = _classify(
                f"{source_name} {info.invoice_type or ''}", "local import",
                info.seller_name or existing_receipt.get("seller_name") or "", categories,
                item_name=info.item_name, invoice_type=info.invoice_type,
                raw_text=info.raw_text, parse_note=info.parse_note
            )
            _refresh_invoice_from_parse(
                db=db,
                existing=existing_receipt,
                invoice_number=info.invoice_number,
                invoice_code=info.invoice_code or existing_receipt.get("invoice_code") or "",
                invoice_date=info.invoice_date or existing_receipt.get("invoice_date") or "",
                expense_date=info.expense_date or existing_receipt.get("expense_date") or "",
                date_source=info.date_source or existing_receipt.get("date_source") or "",
                amount=info.amount or existing_receipt.get("amount") or "",
                total_amount=info.total_amount or existing_receipt.get("total_amount") or "",
                seller_name=info.seller_name or existing_receipt.get("seller_name") or "",
                buyer_name=info.buyer_name or existing_receipt.get("buyer_name") or "",
                invoice_type=info.invoice_type or existing_receipt.get("invoice_type") or "",
                category=category or existing_receipt.get("category") or "",
                has_extra=bool(extra_type) or bool(existing_receipt.get("has_extra")),
                extra_type=extra_type or existing_receipt.get("extra_type") or "",
                missing_extra=extra_required,
                parse_note=info.parse_note or existing_receipt.get("parse_note") or "",
                item_name=info.item_name,
            )
            attached = _attach_evidence_to_invoice(db, existing_receipt, file_path)
            if attached:
                _log.info(
                    "  已合并同一订单的收据版本: invoice_id=%s file=%s",
                    existing_receipt["id"],
                    mask_filename(source_name),
                )
                return "added", existing_receipt["id"]
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
                    category, extra_type, extra_required = _classify(
                        f"{source_name} {info.invoice_type or ''}", "local import",
                        info.seller_name or "", categories,
                        item_name=info.item_name, invoice_type=info.invoice_type,
                        raw_text=info.raw_text, parse_note=info.parse_note
                    )
                    _refresh_invoice_from_parse(
                        db=db,
                        existing=existing_by_fields,
                        invoice_number=info.invoice_number or "",
                        invoice_code=info.invoice_code or "",
                        invoice_date=info.invoice_date or "",
                        expense_date=info.expense_date or "",
                        date_source=info.date_source or "",
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
                        item_name=info.item_name,
                    )
                    return "added", existing_by_fields["id"]

            if info.invoice_type == "网约车电子收据":
                attached = _attach_evidence_to_invoice(db, existing_by_fields, file_path)
                if attached:
                    _log.info(
                        "  已将同一订单的收据版本关联为证明材料: invoice_id=%s file=%s",
                        existing_by_fields["id"],
                        mask_filename(source_name),
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
            category, extra_type, extra_required = _classify(
                f"{source_name} {info.invoice_type or ''}", "local import",
                info.seller_name, categories,
                item_name=info.item_name, invoice_type=info.invoice_type,
                raw_text=info.raw_text, parse_note=info.parse_note
            )
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
                    original_name=source_name,
                    expense_date=info.expense_date,
                    fallback_date=datetime.now().strftime("%Y-%m-%d"),
                )
            rec = {
                "invoice_number": info.invoice_number,
                "invoice_code": info.invoice_code,
                "invoice_date": info.invoice_date,
                "expense_date": info.expense_date,
                "date_source": info.date_source,
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
                "item_name": info.item_name,
            }
            row_id = db.insert_invoice(rec)
            return "conflict", row_id

    category, extra_type, extra_required = _classify(
        f"{source_name} {info.invoice_type or ''}", "local import",
        info.seller_name, categories,
        item_name=info.item_name, invoice_type=info.invoice_type,
        raw_text=info.raw_text, parse_note=info.parse_note
    )
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
            original_name=source_name,
            expense_date=info.expense_date,
            fallback_date=datetime.now().strftime("%Y-%m-%d"),
        )
    rec = {
        "invoice_number": info.invoice_number,
        "invoice_code": info.invoice_code,
        "invoice_date": info.invoice_date,
        "expense_date": info.expense_date,
        "date_source": info.date_source,
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
        "item_name": info.item_name,
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
    file_paths=None,
) -> dict:
    root = Path(import_dir)
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"本地导入目录不存在或不是文件夹: {root}")

    root = root.resolve()
    runtime_root = RUNTIME_DIR.resolve()
    staging_dir = att_dir / "local_import"
    supported_exts = {".pdf", ".ofd", ".zip", ".png", ".jpg", ".jpeg", ".heic"}
    if file_paths is None:
        files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in supported_exts)
    else:
        files = []
        for item in file_paths:
            candidate = Path(item).resolve()
            if not candidate.is_relative_to(root):
                raise ValueError(f"导入文件不在指定目录内: {candidate}")
            if candidate.is_file() and candidate.suffix.lower() in supported_exts:
                files.append(candidate)
        files.sort()

    stats = {"added": 0, "duplicates": 0, "conflicts": 0, "pending_manual": 0, "failed": 0}
    if not files:
        _log.warning("本地导入目录没有发现 PDF/OFD/ZIP: %s", mask_path(root))
        return stats

    _log.info("开始本地导入: %s (%d 个文件)", mask_path(root), len(files))
    for src in files:
        ext = src.suffix.lower()
        try:
            preserve_source_path = _path_is_within(src, runtime_root)
            if preserve_source_path and ("inbox/mobile_upload" in src.as_posix() or "inbox\\mobile_upload" in str(src)):
                preserve_source_path = False

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
                evidence_result = _import_local_evidence(
                    db=db,
                    parsed=None,
                    file_path=working_file,
                    source_name=src.name,
                    categories=categories,
                    preserve_source_path=preserve_source_path,
                )
                if evidence_result is None:
                    status, row_id = _insert_local_exception(
                        db,
                        working_file,
                        src.name,
                        "本地导入图片待识别，请人工处理",
                        categories,
                    )
                else:
                    status, row_id = evidence_result
                key = status + "s" if status in ("duplicate", "conflict") else status
                stats[key] += 1
            else:
                evidence_result = _import_local_evidence(
                    db=db,
                    parsed=None,
                    file_path=working_file,
                    source_name=src.name,
                    categories=categories,
                    preserve_source_path=preserve_source_path,
                )
                if evidence_result is None:
                    status, row_id = _insert_local_exception(
                        db, working_file, src.name,
                        "本地导入暂不支持OFD解析，请人工处理",
                        categories,
                    )
                else:
                    status, row_id = evidence_result
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

    orig_name_to_use = filename_hint or src.name
    new_name = build_managed_attachment_name(
        original_name=orig_name_to_use,
        invoice_date=invoice_date,
        fallback_date=invoice_date,
    )
    if not new_name.lower().endswith(ext):
        new_name = os.path.splitext(new_name)[0] + ext

    dest = date_dir / new_name
    if dest.exists() and dest != src:
        stem = dest.stem
        for n in range(1, 100):
            candidate = date_dir / f"{stem}_{n}{ext}"
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
    mailbox_key: str = "legacy",
) -> int | None:
    """Insert a non-invoice reimbursement receipt and preserve its file."""
    src = Path(file_path)
    file_hash = _sha256_file(src) if src.exists() else ""
    if file_hash:
        existing = db.find_invoice_by_file_hash(file_hash, include_deleted=True)
        if existing:
            existing = _restore_existing_invoice_if_deleted(db, existing, "海外凭证/收据")
            if int(existing.get("is_deleted") or 0) == 0:
                _log.info("  海外凭证/收据已存在: %s", mask_filename(filename_hint or src.name))
                return None

        existing = db.find_receipt_by_source(
            mailbox_key=mailbox_key,
            mail_uid=msg.uid,
            filename_hint=filename_hint,
            include_deleted=True,
        )
        if existing:
            existing = _restore_existing_invoice_if_deleted(db, existing, "海外凭证/收据")
            if int(existing.get("is_deleted") or 0) == 0:
                _log.info(
                    "  海外凭证/收据已存在: mailbox_key=%s uid=%s hint=%s",
                    mailbox_key,
                    mask_uid(msg.uid),
                    mask_filename(filename_hint or src.name),
                )
                return None

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
        "expense_date": msg.date,
        "date_source": "invoice_date",
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
        "mailbox_key": mailbox_key,
        "file_hash": file_hash,
    }
    return db.insert_invoice(rec)


def _insert_pending_image_record(
    msg: MailMessage,
    db: InvoiceDB,
    file_path: str,
    original_name: str,
    categories: dict,
    mailbox_key: str = "legacy",
) -> int | None:
    """Insert a pending-manual image attachment record without silently dropping it."""
    src = Path(file_path)
    file_hash = _sha256_file(src) if src.exists() else ""
    if file_hash:
        existing = db.find_invoice_by_file_hash(file_hash, include_deleted=True)
        if existing:
            existing = _restore_existing_invoice_if_deleted(db, existing, "图片待识别")
            if int(existing.get("is_deleted") or 0) == 0:
                _log.info("  图片待识别已存在: %s", mask_filename(original_name or src.name))
                return None

    cat, extra_type, extra_required = _classify(msg.subject, msg.sender, original_name, categories)
    rec = {
         "invoice_number": "",
         "invoice_code": "",
         "invoice_date": msg.date,
         "expense_date": msg.date,
         "date_source": "invoice_date",
         "amount": "",
         "total_amount": "",
         "seller_name": msg.sender,
         "buyer_name": "",
         "invoice_type": "图片待识别",
         "category": cat,
         "has_extra": bool(extra_type),
         "extra_type": extra_type,
         "missing_extra": extra_required,
         "mail_uid": msg.uid,
         "mail_subject": msg.subject,
         "mail_date": msg.date,
         "mail_sender": msg.sender,
         "parse_success": False,
         "parse_note": "图片待识别，请人工处理",
         "attachment_path": _runtime_relative(src),
         "extra_paths": [],
         "download_url": "",
         "mailbox_key": mailbox_key,
         "file_hash": file_hash,
    }
    return db.insert_invoice(rec)


def _insert_unsupported_ofd_record(
    *,
    msg: MailMessage,
    db: InvoiceDB,
    file_path: str,
    filename_hint: str,
    mailbox_key: str,
) -> int:
    src = Path(file_path)
    file_hash = _sha256_file(src) if src.exists() else ""
    if file_hash:
        existing = db.find_invoice_by_file_hash(file_hash, include_deleted=True)
        if existing:
            if int(existing.get("is_deleted") or 0) == 1:
                db.restore_deleted_invoices_by_file_hashes({file_hash})
                return int(existing.get("id") or 0)
            return 0

    rec = {
        "invoice_number": "",
        "invoice_code": "",
        "invoice_date": msg.date or "",
        "expense_date": msg.date or "",
        "date_source": "mail_date",
        "amount": "",
        "total_amount": "",
        "seller_name": "",
        "buyer_name": "",
        "invoice_type": "OFD待手动处理",
        "category": "其他",
        "has_extra": False,
        "extra_type": "",
        "missing_extra": False,
        "mail_uid": msg.uid,
        "mail_subject": msg.subject,
        "mail_date": msg.date,
        "mail_sender": msg.sender,
        "parse_success": False,
        "parse_note": "unsupported_ofd: 当前版本暂不解析 OFD，请手动转换或补充 PDF 原件",
        "attachment_path": _runtime_relative(src),
        "extra_paths": [],
        "download_url": "",
        "mailbox_key": mailbox_key,
        "file_hash": file_hash,
    }
    row_id = db.insert_invoice(rec)
    if row_id:
        _log.info("  OFD 暂不解析，已作为待人工处理记录入库: %s", mask_filename(filename_hint))
    return row_id


def _process_email(
    msg: MailMessage,
    att_handler: AttachmentHandler,
    parser: InvoiceParser,
    link_dl: LinkDownloader,
    db: InvoiceDB,
    categories: dict,
    mailbox_key: str = "legacy",
    config: dict | None = None,
    source_mode: str = "normal",
) -> int:
    """Process a single email.  Return the number of invoices recorded."""
    _log.info("── 处理 %s: %s", mask_uid(msg.uid), redact_text(msg.subject[:60], "subject"))

    # 1. Extract attachments
    attachments = att_handler.extract(msg.raw_msg, msg.uid, date_str=msg.date)
    invoice_pdfs = [a for a in attachments if a.is_invoice and a.file_path.lower().endswith(".pdf")]
    invoice_ofds = [a for a in attachments if a.is_invoice and a.file_path.lower().endswith(".ofd")]
    extra_files = [a for a in attachments if a.is_extra]
    parsed_invoice_pdfs = [
        (att, parser.parse_pdf(att.file_path))
        for att in invoice_pdfs
    ]
    kept_paths = set()
    attached_extra_source_paths: set[str] = set()
    link_pdf_skipped_as_duplicate = False
    link_download_failed = False
    manual_required_recorded = False
    metadata_refreshed_recorded = False
    file_restored_recorded = False
    recorded = 0

    def set_process_outcome(status: str) -> None:
        try:
            link_dl.last_process_outcome = status
        except (AttributeError, TypeError):
            pass

    for att in invoice_ofds:
        row_id = _insert_unsupported_ofd_record(
            msg=msg,
            db=db,
            file_path=att.file_path,
            filename_hint=att.original_name,
            mailbox_key=mailbox_key,
        )
        if row_id:
            recorded += 1
            manual_required_recorded = True
            try:
                kept_paths.add(str(Path(att.file_path).resolve()))
            except Exception:
                pass

    # 2. Try downloading links via browser in addition to attachments
    combined_text = (msg.subject + " " + msg.sender).lower()
    has_invoice_hint = any(kw in combined_text
                           for kw in ["发票", "invoice", "fapiao", "电子发票", "行程单"])
    downloaded = []
    if has_invoice_hint:
        # ── Skip browser link download when attachment invoices already parse successfully ──
        skip_for_attachment = False
        if getattr(link_dl, "_skip_when_attachment_invoice_present", True):
            success_attachment_pdfs = [
                att for att, info in parsed_invoice_pdfs
                if info.parse_success
            ]
            if success_attachment_pdfs:
                skip_for_attachment = True
                _log.info("附件中已存在可解析发票，跳过浏览器链接下载")

        if not skip_for_attachment:
            downloaded = link_dl.download_from_email(msg.raw_msg, msg.uid, msg.date)

    downloaded_ofds = [
        dl for dl in downloaded
        if dl.is_invoice and str(dl.file_path).lower().endswith(".ofd")
    ]
    for dl in downloaded_ofds:
        row_id = _insert_unsupported_ofd_record(
            msg=msg,
            db=db,
            file_path=dl.file_path,
            filename_hint=dl.filename,
            mailbox_key=mailbox_key,
        )
        if row_id:
            recorded += 1
            manual_required_recorded = True
            try:
                kept_paths.add(str(Path(dl.file_path).resolve()))
            except Exception:
                pass
        else:
            link_pdf_skipped_as_duplicate = True
            try:
                if os.path.exists(dl.file_path):
                    os.remove(dl.file_path)
            except Exception:
                pass

    downloaded_invoice_items = [
        (dl, parser.parse_pdf(dl.file_path))
        for dl in downloaded
        if dl.is_invoice and str(dl.file_path).lower().endswith(".pdf")
    ]
    parsed_invoice_infos = [
        info for _, info in (downloaded_invoice_items + parsed_invoice_pdfs)
        if info.parse_success
    ]

    # 动态注入附件 index 以及绑定 info 的 original_file，用于多发票/单发票评分关联算法
    for idx, att in enumerate(attachments):
        att.attachment_index = idx
    for idx, dl in enumerate(downloaded):
        dl.attachment_index = len(attachments) + idx

    for f, info in (downloaded_invoice_items + parsed_invoice_pdfs):
        if info.parse_success:
            info.original_file = f
    matched_extra_files, unmatched_extra_files = _match_email_extras_to_invoices(
        extra_files,
        parsed_invoice_infos,
        config=config,
    )

    def extras_for_invoice(info) -> list:
        return matched_extra_files.get(id(info), [])

    if has_invoice_hint:
        if not downloaded and not invoice_pdfs:
            link_download_failed = True
        if downloaded:
            for dl, info in downloaded_invoice_items:
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
                            mailbox_key=mailbox_key,
                        )
                        if row_id:
                            recorded += 1
                            _log.info("  已入库海外凭证/收据: %s", mask_filename(dl.filename))
                        continue
                    if dl.source_type == "invoice_page_pdf_fallback":
                        _log.info("  发票展示页面 PDF 副本未参与结构化解析，仅作为原件候选保留/或已跳过重复结构化入库")
                    else:
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
                    repaired_attachment_path = ""
                    category, extra_type, extra_req = _classify(
                        msg.subject, msg.sender, info.seller_name, categories,
                        item_name=info.item_name, invoice_type=info.invoice_type,
                        raw_text=info.raw_text, parse_note=info.parse_note
                    )
                    if existing_attachment_missing:
                        code = info.invoice_code or info.invoice_number
                        repaired_attachment_path = _rename_by_invoice_code(
                            dl.file_path, code, info.invoice_date or msg.date,
                            att_handler._base,
                            category=category, total_amount=info.total_amount,
                            invoice_number=info.invoice_number,
                            original_name=dl.filename,
                            expense_date=info.expense_date,
                            fallback_date=msg.date)
                        if repaired_attachment_path:
                            kept_paths.add(str((att_handler._base.parent / repaired_attachment_path).resolve()))

                    repaired_extra_paths = _normalize_path_list(existing.get("extra_paths"))
                    invoice_extras = extras_for_invoice(info)
                    if invoice_extras:
                        code = info.invoice_code or info.invoice_number
                        repaired_extra_paths = _attach_email_extras_to_invoice(
                            db=db,
                            invoice_id=existing["id"],
                            extra_files=invoice_extras,
                            code=code,
                            inv_date=info.invoice_date or msg.date,
                            att_base=att_handler._base,
                            category=category,
                            total_amount=info.total_amount,
                            invoice_number=info.invoice_number,
                            kept_paths=kept_paths,
                            attached_source_paths=attached_extra_source_paths,
                            expense_date=info.expense_date,
                            fallback_date=msg.date,
                        )

                    if _refresh_invoice_from_parse(
                        db,
                        existing,
                        invoice_number=info.invoice_number,
                        invoice_code=info.invoice_code,
                        invoice_date=info.invoice_date,
                        expense_date=info.expense_date or "",
                        date_source=info.date_source or "",
                        amount=info.amount,
                        total_amount=info.total_amount,
                        seller_name=info.seller_name,
                        buyer_name=info.buyer_name,
                        invoice_type=info.invoice_type,
                        category=category,
                        has_extra=bool(repaired_extra_paths),
                        extra_type=extra_type,
                        missing_extra=extra_req and not bool(repaired_extra_paths),
                        parse_note=info.parse_note or "链接下载",
                        item_name=info.item_name,
                    ):
                        if repaired_attachment_path:
                            db.update_invoice_file_paths(
                                existing["id"],
                                attachment_path=repaired_attachment_path,
                            )
                            file_restored_recorded = True
                            _log.info(
                                "  已刷新重复发票元数据(链接下载)并修复附件路径: %s",
                                mask_invoice_number(info.invoice_number),
                            )
                        else:
                            metadata_refreshed_recorded = True
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
                    code = info.invoice_code or info.invoice_number
                    cat_ld, extra_type_ld, extra_req_ld = _classify(
                        msg.subject, msg.sender, info.seller_name, categories,
                        item_name=info.item_name, invoice_type=info.invoice_type,
                        raw_text=info.raw_text, parse_note=info.parse_note
                    )
                    # ── Backfill attachment_path before removing the download ──
                    if os.path.exists(dl.file_path):
                        backfill_path = _rename_by_invoice_code(
                            dl.file_path, code, info.invoice_date or msg.date,
                            att_handler._base,
                            category=cat_ld, total_amount=info.total_amount,
                            invoice_number=info.invoice_number,
                            original_name=dl.filename,
                            expense_date=info.expense_date,
                            fallback_date=msg.date)
                        if backfill_path:
                            backfill_abs = str((att_handler._base.parent / backfill_path).resolve())
                            if backfill_abs not in kept_paths:
                                kept_paths.add(backfill_abs)
                            file_hash_val = _sha256_file(Path(backfill_abs)) if os.path.exists(backfill_abs) else ""
                            if db.update_invoice_attachment_path_if_missing(
                                duplicate["id"], backfill_path, file_hash=file_hash_val or None,
                            ):
                                file_restored_recorded = True
                                _log.info("重复发票已有记录缺少原件，已回填链接下载文件: existing_id=%d", duplicate["id"])
                            else:
                                _log.debug("重复发票已有原件，跳过链接文件回填")
                        # Clean up the downloaded file for the duplicate
                        if os.path.exists(dl.file_path):
                            os.remove(dl.file_path)
                    invoice_extras = extras_for_invoice(info)
                    if invoice_extras:
                        _attach_email_extras_to_invoice(
                            db=db,
                            invoice_id=duplicate["id"],
                            extra_files=invoice_extras,
                            code=code,
                            inv_date=info.invoice_date or msg.date,
                            att_base=att_handler._base,
                            category=cat_ld,
                            total_amount=info.total_amount,
                            invoice_number=info.invoice_number,
                            kept_paths=kept_paths,
                            attached_source_paths=attached_extra_source_paths,
                            expense_date=info.expense_date,
                            fallback_date=msg.date,
                        )
                    link_pdf_skipped_as_duplicate = True
                    recorded += 1
                    continue
                cat, extra_type, extra_req = _classify(
                    msg.subject, msg.sender, info.seller_name, categories,
                    item_name=info.item_name, invoice_type=info.invoice_type,
                    raw_text=info.raw_text, parse_note=info.parse_note
                )
                # Rename file: {invoice_code}.pdf under {invoice_date}/
                code = info.invoice_code or info.invoice_number
                att_path = _rename_by_invoice_code(
                    dl.file_path, code, info.invoice_date or msg.date,
                    att_handler._base,
                    category=cat, total_amount=info.total_amount,
                    invoice_number=info.invoice_number,
                    original_name=dl.filename,
                    expense_date=info.expense_date,
                    fallback_date=msg.date)
                if att_path:
                    kept_paths.add(str((att_handler._base.parent / att_path).resolve()))
                rec = {
                    "invoice_number": info.invoice_number,
                    "invoice_code": info.invoice_code,
                    "invoice_date": info.invoice_date,
                    "expense_date": info.expense_date or "",
                    "date_source": info.date_source or "",
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
                    "item_name": info.item_name,
                }
                row_id = db.insert_invoice(rec)
                if row_id:
                    file_restored_recorded = True
                    invoice_extras = extras_for_invoice(info)
                    if invoice_extras:
                        _attach_email_extras_to_invoice(
                            db=db,
                            invoice_id=row_id,
                            extra_files=invoice_extras,
                            code=code,
                            inv_date=info.invoice_date or msg.date,
                            att_base=att_handler._base,
                            category=cat,
                            total_amount=info.total_amount,
                            invoice_number=info.invoice_number,
                            kept_paths=kept_paths,
                            attached_source_paths=attached_extra_source_paths,
                            expense_date=info.expense_date,
                            fallback_date=msg.date,
                        )
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
    for att, info in parsed_invoice_pdfs:
        if not info.parse_success:
            evidence_res = _import_local_evidence(
                db=db,
                parsed=info,
                file_path=Path(att.file_path),
                source_name=att.original_name,
                categories=categories,
                preserve_source_path=True
            )
            if evidence_res:
                status, row_id = evidence_res
                recorded += 1
                if row_id is not None:
                    kept_paths.add(str(Path(att.file_path).resolve()))
                _log.info("  已处理解析失败PDF作为证明材料(邮箱路径): %s, 结果=%s, ID=%s",
                          mask_filename(att.original_name), status, row_id)
                continue

            if _looks_like_receipt_evidence(msg.subject, msg.sender, att.original_name):
                row_id = _insert_receipt_record(
                    msg=msg,
                    db=db,
                    att_handler=att_handler,
                    categories=categories,
                    file_path=att.file_path,
                    filename_hint=att.original_name,
                    parse_note=info.parse_note or "海外凭证/收据",
                    mailbox_key=mailbox_key,
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
                msg.subject, msg.sender, info.seller_name, categories,
                item_name=info.item_name, invoice_type=info.invoice_type,
                raw_text=info.raw_text, parse_note=info.parse_note
            )
            existing_attachment_missing = _resolve_runtime_path(existing.get("attachment_path") or "") is None
            repaired_attachment_path = ""
            if existing_attachment_missing:
                code = info.invoice_code or info.invoice_number
                repaired_attachment_path = _rename_by_invoice_code(
                    att.file_path, code, info.invoice_date or msg.date,
                    att_handler._base,
                    category=cat, total_amount=info.total_amount,
                    invoice_number=info.invoice_number,
                    original_name=att.original_name,
                    expense_date=info.expense_date,
                    fallback_date=msg.date)
                if repaired_attachment_path:
                    kept_paths.add(str((att_handler._base.parent / repaired_attachment_path).resolve()))

            repaired_extra_paths = _normalize_path_list(existing.get("extra_paths"))
            invoice_extras = extras_for_invoice(info)
            if invoice_extras:
                code = info.invoice_code or info.invoice_number
                repaired_extra_paths = _attach_email_extras_to_invoice(
                    db=db,
                    invoice_id=existing["id"],
                    extra_files=invoice_extras,
                    code=code,
                    inv_date=info.invoice_date or msg.date,
                    att_base=att_handler._base,
                    category=cat,
                    total_amount=info.total_amount,
                    invoice_number=info.invoice_number,
                    kept_paths=kept_paths,
                    attached_source_paths=attached_extra_source_paths,
                    expense_date=info.expense_date,
                    fallback_date=msg.date,
                )

            if _refresh_invoice_from_parse(
                db,
                existing,
                invoice_number=info.invoice_number,
                invoice_code=info.invoice_code,
                invoice_date=info.invoice_date,
                expense_date=info.expense_date or "",
                date_source=info.date_source or "",
                amount=info.amount,
                total_amount=info.total_amount,
                seller_name=info.seller_name,
                buyer_name=info.buyer_name,
                invoice_type=info.invoice_type,
                category=cat,
                has_extra=bool(repaired_extra_paths),
                extra_type=extra_type,
                missing_extra=extra_req and not bool(repaired_extra_paths),
                parse_note=info.parse_note,
                item_name=info.item_name,
            ):
                if repaired_attachment_path:
                    db.update_invoice_file_paths(
                        existing["id"],
                        attachment_path=repaired_attachment_path,
                    )
                    file_restored_recorded = True
                    _log.info("  已刷新重复发票元数据并修复附件路径: %s", mask_invoice_number(info.invoice_number))
                else:
                    metadata_refreshed_recorded = True
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
            # Define category for both backfill and extras
            cat_dup, extra_type_dup, extra_req_dup = _classify(
                msg.subject, msg.sender, info.seller_name, categories,
                item_name=info.item_name, invoice_type=info.invoice_type,
                raw_text=info.raw_text, parse_note=info.parse_note
            )
            code = info.invoice_code or info.invoice_number
            # ── Backfill attachment_path for duplicate with missing original ──
            if att.file_path and os.path.exists(att.file_path):
                dup_att_path = _rename_by_invoice_code(
                    att.file_path, code, info.invoice_date or msg.date,
                    att_handler._base,
                    category=cat_dup, total_amount=info.total_amount,
                    invoice_number=info.invoice_number,
                    original_name=att.original_name,
                    expense_date=info.expense_date,
                    fallback_date=msg.date)
                if dup_att_path:
                    dup_abs = str((att_handler._base.parent / dup_att_path).resolve())
                    if dup_abs not in kept_paths:
                        kept_paths.add(dup_abs)
                    file_hash_val = _sha256_file(Path(dup_abs)) if os.path.exists(dup_abs) else ""
                    if db.update_invoice_attachment_path_if_missing(
                        duplicate["id"], dup_att_path, file_hash=file_hash_val or None,
                    ):
                        file_restored_recorded = True
                        _log.info("重复发票已有记录缺少原件，已回填附件路径: existing_id=%d", duplicate["id"])
                    else:
                        _log.debug("重复发票已有原件，跳过附件文件回填")
            invoice_extras = extras_for_invoice(info)
            if invoice_extras:
                _attach_email_extras_to_invoice(
                    db=db,
                    invoice_id=duplicate["id"],
                    extra_files=invoice_extras,
                    code=code,
                    inv_date=info.invoice_date or msg.date,
                    att_base=att_handler._base,
                    category=cat_dup,
                    total_amount=info.total_amount,
                    invoice_number=info.invoice_number,
                    kept_paths=kept_paths,
                    attached_source_paths=attached_extra_source_paths,
                    expense_date=info.expense_date,
                    fallback_date=msg.date,
                )
            recorded += 1
            continue

        cat, extra_type, extra_req = _classify(
            msg.subject, msg.sender, info.seller_name, categories,
            item_name=info.item_name, invoice_type=info.invoice_type,
            raw_text=info.raw_text, parse_note=info.parse_note
        )

        invoice_extras = extras_for_invoice(info)
        has_extra = bool(invoice_extras) if extra_req else False

        # Rename files by invoice code under invoice_date/
        code = info.invoice_code or info.invoice_number
        inv_date = info.invoice_date or msg.date
        att_path = _rename_by_invoice_code(
            att.file_path, code, inv_date, att_handler._base,
            category=cat, total_amount=info.total_amount,
            invoice_number=info.invoice_number,
            original_name=att.original_name,
            expense_date=info.expense_date,
            fallback_date=msg.date)
        if att_path:
            kept_paths.add(str((att_handler._base.parent / att_path).resolve()))

        rec = {
            "invoice_number": info.invoice_number,
            "invoice_code": info.invoice_code,
            "invoice_date": info.invoice_date,
            "expense_date": info.expense_date or "",
            "date_source": info.date_source or "",
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
            "extra_paths": [],
            "mailbox_key": mailbox_key,
            "item_name": info.item_name,
        }
        row_id = db.insert_invoice(rec)
        if row_id:
            file_restored_recorded = True
            if invoice_extras:
                _attach_email_extras_to_invoice(
                    db=db,
                    invoice_id=row_id,
                    extra_files=invoice_extras,
                    code=code,
                    inv_date=inv_date,
                    att_base=att_handler._base,
                    category=cat,
                    total_amount=info.total_amount,
                    invoice_number=info.invoice_number,
                    kept_paths=kept_paths,
                    attached_source_paths=attached_extra_source_paths,
                )
            recorded += 1
            _log.info("  ✅ 已入库: %s (%s)", mask_invoice_number(info.invoice_number), cat)

    # 3b. Preserve standalone or unmatched receipts/water bills/folios.
    remaining_extra_files = [
        att
        for att in unmatched_extra_files
        if (
            not Path(att.file_path).exists()
            or str(Path(att.file_path).resolve()) not in attached_extra_source_paths
        )
    ]
    if remaining_extra_files:
        for att in remaining_extra_files:
            file_path = Path(att.file_path)
            file_hash = _sha256_file(file_path) if file_path.exists() else ""

            evidence_res = _import_local_evidence(
                db=db,
                parsed=None,
                file_path=file_path,
                source_name=att.original_name,
                categories=categories,
                preserve_source_path=True
            )

            processed_id = None
            if evidence_res:
                status, row_id = evidence_res
                recorded += 1
                if row_id is not None:
                    processed_id = row_id
                else:
                    if file_hash:
                        existing = db.find_invoice_by_file_hash(file_hash, include_deleted=True)
                        if existing:
                            processed_id = existing["id"]

                kept_paths.add(str(file_path.resolve()))

                if status == "added":
                    _log.info("  已处理待关联证明材料(邮箱路径): %s, 结果=%s, ID=%s",
                              mask_filename(att.original_name), status, row_id)
                else:
                    if processed_id:
                        _log.info("  已保留待关联证明材料: invoice_id=%s file=%s",
                                  processed_id, mask_filename(att.original_name))
                continue

            if _looks_like_receipt_evidence(msg.subject, msg.sender, att.original_name):
                row_id = _insert_receipt_record(
                    msg=msg,
                    db=db,
                    att_handler=att_handler,
                    categories=categories,
                    file_path=att.file_path,
                    filename_hint=att.original_name,
                    mailbox_key=mailbox_key,
                )
                if row_id:
                    recorded += 1
                    kept_paths.add(str(file_path.resolve()))
                    _log.info("  已入库独立水单/收据(海外凭证): %s", mask_filename(att.original_name))
                    continue

            # Fallback 逻辑
            existing = db.find_invoice_by_file_hash(file_hash, include_deleted=True) if file_hash else None
            if existing:
                existing = _restore_existing_invoice_if_deleted(db, existing, "证明材料")
                if not existing.get("attachment_path"):
                    db.update_invoice_file_paths(existing["id"], attachment_path=_runtime_relative(file_path))
                processed_id = existing["id"]
            else:
                category, extra_type, extra_required = _classify(att.original_name, msg.sender or "", "", categories)
                rec = {
                    "invoice_number": "",
                    "invoice_code": "",
                    "invoice_date": "",
                    "expense_date": "",
                    "date_source": "unknown",
                    "amount": "",
                    "total_amount": "",
                    "seller_name": "",
                    "buyer_name": "",
                    "invoice_type": "待关联证明材料",
                    "category": category,
                    "has_extra": False,
                    "extra_type": extra_type,
                    "missing_extra": False,
                    "mail_uid": msg.uid,
                    "mail_subject": msg.subject,
                    "mail_date": msg.date,
                    "mail_sender": msg.sender,
                    "parse_success": False,
                    "parse_note": "多发票邮件证明材料未唯一匹配，请人工关联",
                    "attachment_path": _runtime_relative(file_path),
                    "extra_paths": [],
                    "file_hash": file_hash,
                    "mailbox_key": mailbox_key,
                }
                processed_id = db.insert_invoice(rec)

            recorded += 1
            kept_paths.add(str(file_path.resolve()))
            if processed_id:
                _log.info("  已保留待关联证明材料: invoice_id=%s file=%s",
                          processed_id, mask_filename(att.original_name))

    image_attachments = [
        att for att in attachments
        if Path(att.file_path).suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".heic"}
        and not att.is_extra
    ]
    for att in image_attachments:
        row_id = _insert_pending_image_record(
            msg=msg,
            db=db,
            file_path=att.file_path,
            original_name=att.original_name,
            categories=categories,
            mailbox_key=mailbox_key,
        )
        if row_id:
            recorded += 1
            kept_paths.add(str(Path(att.file_path).resolve()))
            _log.info("  图片待识别已入库: %s", mask_filename(att.original_name))

    # 4. Fallback: parse subject or HTML body when no PDF available
    if not invoice_pdfs and recorded == 0 and not link_pdf_skipped_as_duplicate:
        subj_info = parse_subject(msg.subject)
        html_body = extract_html_from_message(msg.raw_msg)
        body_info = parse_html_body(html_body)

        # Merge results, prioritizing subject over body
        merged = {**body_info, **subj_info}
        if "invoice_date" in merged:
            merged["expense_date"] = merged.get("expense_date") or merged["invoice_date"]
            merged["date_source"] = merged.get("date_source") or "invoice_date"

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
                        expense_date=merged.get("expense_date", "") or merged.get("invoice_date", "") or msg.date,
                        date_source=merged.get("date_source", "") or "invoice_date",
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
                        metadata_refreshed_recorded = True
                        _log.info("  已刷新重复发票元数据(主题/正文): %s", redact_text(dedup_key, "dedup_key"))
                        if not was_deleted:
                            _log_existing_invoice_duplicate(existing, "subject_body_invoice_number")
                    set_process_outcome("metadata_refreshed" if recorded else "duplicate")
                    return recorded

            existing = _find_existing_invoice_for_parse(db, "", amount, seller, include_deleted=True)
            if existing:
                was_deleted = int(existing.get("is_deleted") or 0) == 1
                existing = _restore_existing_invoice_if_deleted(db, existing, "主题/正文")
                if not was_deleted:
                    _log.info("  跳过重复(从主题/正文): %s", redact_text(dedup_key, "dedup_key"))
                    _log_existing_invoice_duplicate(existing, "subject_body_seller_amount")
                recorded += 1
                set_process_outcome("duplicate")
                return recorded

            if db.is_duplicate(dedup_key, amount, seller):
                _log.info("  跳过重复(从主题/正文): %s", redact_text(dedup_key, "dedup_key"))
                recorded += 1
                set_process_outcome("duplicate")
                return recorded

            rec = {
                "invoice_number": inv_num,
                "invoice_code": merged.get("invoice_code", ""),
                "invoice_date": merged.get("invoice_date", "") or msg.date,
                "expense_date": merged.get("expense_date", "") or merged.get("invoice_date", "") or msg.date,
                "date_source": merged.get("date_source", "") or "invoice_date",
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
                "mailbox_key": mailbox_key,
            }
            row_id = db.insert_invoice(rec)
            if row_id:
                recorded += 1
                manual_required_recorded = True
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

    diagnostics = getattr(link_dl, "last_download_diagnostics", {}) or {}
    if manual_required_recorded:
        process_outcome = "manual_required"
    elif file_restored_recorded:
        process_outcome = "file_restored"
    elif metadata_refreshed_recorded:
        process_outcome = "metadata_refreshed"
    elif link_pdf_skipped_as_duplicate:
        process_outcome = "duplicate"
    elif recorded > 0:
        process_outcome = "recorded"
    elif invoice_pdfs or downloaded:
        process_outcome = "parse_failed"
    elif int(diagnostics.get("attempted", 0) or 0) > 0:
        process_outcome = "download_failed"
    else:
        process_outcome = "no_candidate_link"
    set_process_outcome(process_outcome)

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
        from .log_privacy import mask_path
        print(f"已导出报销组 ID {args.claim_id} 的报销包: {mask_path(export_dir)}")
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


def _cmd_evidence_repair(args: argparse.Namespace, db: InvoiceDB):
    """Subcommand to repair unassociated evidence documents for a given email UID."""
    mailbox_key = args.mailbox
    uid = args.uid
    dry_run = args.dry_run or not args.apply

    # Load configuration
    cfg = load_config(args.config)
    accounts = get_email_accounts(cfg)

    # 寻找匹配的邮箱
    acc = None
    for a in accounts:
        if a.get("mailbox_key") == mailbox_key or a.get("address") == mailbox_key:
            acc = a
            break

    if not acc:
        print(f"错误: 未在配置中找到 mailbox_key/address 匹配 '{mailbox_key}' 的邮箱配置。")
        sys.exit(1)

    addr = acc.get("address", "")
    auth_code = acc.get("auth_code", "")
    if not auth_code:
        try:
            auth_code = get_auth_code(addr)
        except (Exception, SystemExit) as e:
            print(f"错误: 获取邮箱 {addr} 的授权码失败: {e}")
            sys.exit(1)

    if not auth_code:
        print(f"错误: 邮箱 {addr} 的授权码为空。")
        sys.exit(1)

    provider = acc.get("provider", "")
    server = acc.get("imap", {}).get("server", "")
    if is_outlook_like_account(provider, addr, server):
        print(f"跳过 Outlook/Microsoft 邮箱：当前版本需要 OAuth2，暂不支持扫描。邮箱：{mask_email(addr)}")
        sys.exit(1)



    print(f"正在连接邮箱 {addr} 并获取邮件 UID: {uid}...")
    with MailFetcher(
        address=addr,
        auth_code=auth_code,
        server=acc.get("imap", {}).get("server", "imap.qq.com"),
        port=acc.get("imap", {}).get("port", 993),
    ) as fetcher:
        folder = acc.get("search", {}).get("folder", "INBOX")
        msg = fetcher.fetch_by_uid(uid, folder=folder)
        if not msg:
            print(f"错误: 未在邮箱中找到 UID 为 {uid} 的邮件。")
            sys.exit(1)

        print(f"邮件获取成功。主题: {msg.subject}")

        # 找出附加材料附件
        att_dir = db._path.parent / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        att_handler = AttachmentHandler(att_dir)

        # 提取附件
        attachments = att_handler.extract(msg.raw_msg, msg.uid, date_str=msg.date)
        extra_files = [a for a in attachments if a.is_extra]

        if not extra_files:
            print("该邮件的附件中未发现任何附加材料 [附加材料]。")
            sys.exit(0)

        # 获取该 UID 和 mailbox_key 在发票库里的所有未删除关联发票，以获得当前已经关联的 extra_paths
        invoices = db.get_invoices_by_mail_identity(mailbox_key, uid)
        associated_paths = set()
        for inv in invoices:
            paths = _normalize_path_list(inv.get("extra_paths"))
            for p in paths:
                resolved = _resolve_runtime_path(p)
                if resolved:
                    associated_paths.add(str(resolved.resolve()).lower())

        # 过滤出未关联 of extra_files
        unassociated_extras = []
        for att in extra_files:
            att_path = Path(att.file_path)
            if str(att_path.resolve()).lower() not in associated_paths:
                unassociated_extras.append(att)

        if not unassociated_extras:
            print("该邮件下的所有附加材料均已被关联，无需修复。")
            sys.exit(0)

        print(f"发现 {len(unassociated_extras)} 个未关联的证明材料：")
        categories = cfg.get("categories", {})

        for att in unassociated_extras:
            file_path = Path(att.file_path)
            file_hash = _sha256_file(file_path) if file_path.exists() else ""

            existing = None
            if file_hash:
                existing = db.find_invoice_by_file_hash(file_hash, include_deleted=True)

            if existing:
                inv_id = existing["id"]
                is_del = int(existing.get("is_deleted") or 0) == 1

                if is_del:
                    print(f"- [已删除记录] 文件: {att.original_name} (Hash: {file_hash[:10]}...), 准备在 apply 时恢复。")
                    if not dry_run:
                        _restore_existing_invoice_if_deleted(db, existing, "证明材料恢复")
                        if not existing.get("attachment_path"):
                            db.update_invoice_file_paths(inv_id, attachment_path=_runtime_relative(file_path))
                        print(f"  -> 已成功恢复记录 ID: {inv_id}")
                else:
                    print(f"- [已存在活跃记录] 文件: {att.original_name} (ID: {inv_id}), 跳过插入，已自动复用。")
                    if not dry_run:
                        if not existing.get("attachment_path"):
                            db.update_invoice_file_paths(inv_id, attachment_path=_runtime_relative(file_path))
            else:
                print(f"- [新证明材料] 文件: {att.original_name} (Hash: {file_hash[:10]}...), 准备在 apply 时创建待关联记录。")
                if not dry_run:
                    category, extra_type, extra_required = _classify(att.original_name, msg.sender or "", "", categories)
                    rec = {
                        "invoice_number": "",
                        "invoice_code": "",
                        "invoice_date": "",
                        "expense_date": "",
                        "date_source": "unknown",
                        "amount": "",
                        "total_amount": "",
                        "seller_name": "",
                        "buyer_name": "",
                        "invoice_type": "待关联证明材料",
                        "category": category,
                        "has_extra": False,
                        "extra_type": extra_type,
                        "missing_extra": False,
                        "mail_uid": msg.uid,
                        "mail_subject": msg.subject,
                        "mail_date": msg.date,
                        "mail_sender": msg.sender,
                        "parse_success": False,
                        "parse_note": "多发票邮件证明材料未唯一匹配，请人工关联",
                        "attachment_path": _runtime_relative(file_path),
                        "extra_paths": [],
                        "file_hash": file_hash,
                        "mailbox_key": mailbox_key,
                    }
                    row_id = db.insert_invoice(rec)
                    print(f"  -> 已成功创建待关联记录 ID: {row_id}")

        if dry_run:
            print("\n提示: 当前为 dry-run 预览模式，未对数据库做任何修改。如需真正执行修复，请添加 --apply 参数。")
        else:
            print("\n已成功完成修复。")

        sys.exit(0)


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
        elif args.command == "email-reprocess":
            _cmd_email_reprocess(args, db)
        elif args.command == "evidence-repair":
            _cmd_evidence_repair(args, db)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    _configure_console_utf8()
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

        try:
            scan_summary = _scan_mailboxes_with_db(
                db=db,
                db_path=db_path,
                cfg=cfg,
                months=months,
                limit=args.limit,
                scan_only=args.scan_only,
                download_only=args.download_only,
                headed=args.headed,
                retry_failed=args.retry_failed,
                no_ai=args.no_ai,
            )
            if scan_summary:
                _log.info(
                    "Mailbox scan finished: %d/%d accounts succeeded, %d failed, "
                    "headers=%d new_headers=%d invoice_candidates=%d processed_emails=%d "
                    "new_records=%d restored=%d duplicates=%d manual_review_required=%d failed_items=%d",
                    scan_summary.get("accounts_success", 0),
                    scan_summary.get("accounts_total", 0),
                    scan_summary.get("accounts_failed", 0),
                    scan_summary.get("scanned_headers", scan_summary.get("scanned", 0)),
                    scan_summary.get("new_email_headers", 0),
                    scan_summary.get("classified_invoice", 0),
                    scan_summary.get("downloaded_emails", scan_summary.get("downloaded", 0)),
                    scan_summary.get("new_invoice_records", scan_summary.get("new", 0)),
                    scan_summary.get("restored_deleted", 0),
                    scan_summary.get("duplicates", 0),
                    scan_summary.get("manual_review_required", scan_summary.get("pending_manual", 0)),
                    scan_summary.get("failed_count", 0),
                )

            if args.scan_only:
                _print_stats(db, excel_path)
                return
        except ConnectionError as exc:
            _log.error("Mailbox scan failed: %s", exc)
            sys.exit(1)
        except ValueError as exc:
            _log.error("%s", exc)
            sys.exit(1)

        # Export & stats
        export_excel(db.get_all_invoices(), excel_path)
        _print_stats(db, excel_path)



def _scan_mailboxes_with_db(
    db: InvoiceDB,
    db_path: Path,
    cfg: dict,
    months: int | None = None,
    limit: int | None = None,
    scan_only: bool = False,
    download_only: bool = False,
    headed: bool = False,
    retry_failed: bool = False,
    log_callback=None,
    no_ai: bool = False,
) -> dict:
    """Sequentially scan multiple enabled mailboxes and process pending invoices."""

    def emit(message: str) -> None:
        message = sanitize_log_message(str(message or ""))
        if log_callback:
            log_callback(message)
        else:
            _log.info(message)

    accounts = get_email_accounts(cfg)
    if not accounts:
        raise ValueError("至少需要配置一个启用的邮箱账号。")

    categories = cfg.get("categories", {})
    ai_cfg = cfg.get("ai", {})
    att_dir = db_path.parent / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    att_handler = AttachmentHandler(att_dir)
    parser = InvoiceParser()
    link_dl = LinkDownloader(att_dir, headed=headed)

    scanned_headers = 0
    new_email_headers = 0
    downloaded_emails = 0
    new_invoice_records = 0
    restored_deleted = 0
    classified_invoice = 0
    duplicates = 0
    pending_manual = 0
    failed = 0
    failed_summaries: list[str] = []
    rule_excluded = 0
    no_candidate_link = 0
    download_failed = 0
    parse_failed = 0
    ai_auth_failed = False
    ai_pending_classification = 0

    account_contexts: list[dict] = []
    for account in accounts:
        address = account.get("address", "")
        provider = account.get("provider", "")
        server = account.get("imap", {}).get("server", "")
        if is_outlook_like_account(provider, address, server):
            emit(f"⚠️ 跳过 Outlook/Microsoft 邮箱：当前版本需要 OAuth2，暂不支持扫描。邮箱：{mask_email(address)}")
            continue

        try:
            auth_code = get_auth_code(address)
        except SystemExit as exc:
            raise ValueError(f"未配置邮箱授权码安全凭证: {mask_email(address)}，请前往 [设置] 页面配置。") from exc
        account_contexts.append({**account, "auth_code": auth_code})


    if retry_failed:
        for account in account_contexts:
            mailbox_key = account.get("mailbox_key", "legacy")
            failed_invoices = db.get_failed_downloads(mailbox_key=mailbox_key)
            if failed_invoices:
                failed_uids = [inv["mail_uid"] for inv in failed_invoices if inv.get("mail_uid")]
                if failed_uids:
                    db.reset_emails_download_status(failed_uids, mailbox_key=mailbox_key)
                    db.delete_invoices_by_uid(failed_uids, mailbox_key=mailbox_key)
                    emit(f"Reset {len(failed_uids)} failed invoice emails for {mask_email(account.get('address', ''))}")
            else:
                emit(f"No failed invoice downloads to retry for {mask_email(account.get('address', ''))}")

    accounts_total = len(account_contexts)
    failed_account_keys: set[str] = set()

    if not download_only:
        for account in account_contexts:
            mailbox_key = account.get("mailbox_key", "legacy")
            email_addr = account.get("address", "")
            folder = account.get("search", {}).get("folder", "INBOX")

            provider = account.get("provider", "")
            server = account.get("imap", {}).get("server", "")
            if is_outlook_like_account(provider, email_addr, server):
                emit(f"⚠️ 跳过 Outlook/Microsoft 邮箱：当前版本需要 OAuth2，暂不支持扫描。邮箱：{mask_email(email_addr)}")
                continue
            months_back = int(account.get("search", {}).get("months_back", months or 3) or (months or 3))
            try:
                since = "" if folder != "INBOX" else db.get_last_scanned_date(mailbox_key=mailbox_key)
                if since:
                    emit(f"Incremental scan from {since} [{mask_email(email_addr)}]")
                else:
                    emit(f"Full scan of the most recent {months_back} months [{mask_email(email_addr)}]")

                known = db.get_all_email_uids(mailbox_key=mailbox_key)
                with MailFetcher(
                    address=email_addr,
                    auth_code=account["auth_code"],
                    server=account.get("imap", {}).get("server", "imap.qq.com"),
                    port=account.get("imap", {}).get("port", 993),
                ) as fetcher:
                    headers = fetcher.scan_headers(
                        folder=folder,
                        months_back=months_back,
                        since_date=since,
                        known_uids=known,
                        limit=limit,
                    )
                    scanned_headers += len(headers)
                    inserted_headers = db.bulk_upsert_emails(
                        headers,
                        mailbox_key=mailbox_key,
                    )
                    new_email_headers += inserted_headers
                    emit(
                        f"Scan complete for {mask_email(email_addr)}: "
                        f"{len(headers)} headers, {inserted_headers} new headers"
                    )
                    classify_result = _run_classify(
                        db,
                        ai_cfg,
                        no_ai or ai_auth_failed,
                        mailbox_key=mailbox_key,
                    ) or {}
                    if classify_result.get("auth_failed"):
                        ai_auth_failed = True
                        ai_pending_classification += int(
                            classify_result.get("pending_classification", 0) or 0
                        )
                        if ai_pending_classification:
                            emit(f"AI API Key 鉴权失败，请检查设置；当前应用会话已暂停 AI 分类，{ai_pending_classification} 封邮件待分类。")
                        else:
                            emit("AI API Key 鉴权失败，请检查设置；当前应用会话已暂停 AI 分类。")
            except Exception as exc:
                failed_account_keys.add(mailbox_key)
                failed_summaries.append(sanitize_log_message(f"scan failed for {mask_email(email_addr)}: {exc}"))
                emit(sanitize_log_message(f"Scan failed for {mask_email(email_addr)}: {exc}"))

    if not scan_only:
        for account in account_contexts:
            mailbox_key = account.get("mailbox_key", "legacy")
            email_addr = account.get("address", "")
            folder = account.get("search", {}).get("folder", "INBOX")

            provider = account.get("provider", "")
            server = account.get("imap", {}).get("server", "")
            if is_outlook_like_account(provider, email_addr, server):
                emit(f"⚠️ 跳过 Outlook/Microsoft 邮箱：当前版本需要 OAuth2，暂不支持扫描。邮箱：{mask_email(email_addr)}")
                continue

            pending_for_account: list[dict] = []
            handled_pending_uids: set[int] = set()
            try:
                pending_for_account = db.get_invoice_emails_to_download(
                    mailbox_key=mailbox_key,
                    bypass_cooldown=retry_failed,
                )
                if not pending_for_account:
                    emit(f"No invoice emails pending download for {mask_email(email_addr)}")
                    continue
                emit(f"Downloading {len(pending_for_account)} invoice emails for {mask_email(email_addr)}")
                with MailFetcher(
                    address=email_addr,
                    auth_code=account["auth_code"],
                    server=account.get("imap", {}).get("server", "imap.qq.com"),
                    port=account.get("imap", {}).get("port", 993),
                ) as fetcher:
                    for row in pending_for_account:
                        rule_result, rule_reason = rule_classify(
                            row.get("subject", ""),
                            row.get("sender", ""),
                        )
                        if rule_result == 0:
                            db.classify_email(
                                row["uid"],
                                False,
                                "rule_pre_download",
                                rule_reason,
                                mailbox_key=mailbox_key,
                            )
                            db.clear_email_download_failure(mailbox_key, row["uid"])
                            rule_excluded += 1
                            emit(
                                "Rule excluded historical false positive: "
                                f"{mask_uid(row.get('uid', 0))}"
                            )
                            handled_pending_uids.add(int(row["uid"]))
                            continue
                        classified_invoice += 1
                        try:
                            before_active_count = db.count_invoices()
                            before_total_count = db.count_invoices(include_deleted=True)
                            before_pending_manual = db.count_pending_manual_invoices()
                            outcome = _handle_pending_email(
                                row=row,
                                fetcher=fetcher,
                                folder=folder,
                                att_handler=att_handler,
                                parser=parser,
                                link_dl=link_dl,
                                db=db,
                                categories=categories,
                                config=cfg,
                            )
                            after_active_count = db.count_invoices()
                            after_total_count = db.count_invoices(include_deleted=True)
                            after_pending_manual = db.count_pending_manual_invoices()
                            if isinstance(outcome, PendingEmailResult):
                                outcome_status = outcome.status
                            else:
                                outcome_status = "recorded" if outcome else "download_failed"
                            if outcome:
                                db.clear_email_download_failure(mailbox_key, row["uid"])
                                downloaded_emails += 1
                                pending_manual += max(
                                    0,
                                    after_pending_manual - before_pending_manual,
                                )
                                if outcome_status == "manual_required" and after_pending_manual <= before_pending_manual:
                                    pending_manual += 1
                                new_delta = max(
                                    0,
                                    after_total_count - before_total_count,
                                )
                                restored_delta = max(
                                    0,
                                    (after_active_count - before_active_count) - new_delta,
                                )
                                new_invoice_records += new_delta
                                restored_deleted += restored_delta
                                if new_delta == 0 and restored_delta == 0:
                                    duplicates += 1
                            elif outcome_status == "no_candidate_link":
                                no_candidate_link += 1
                                db.record_email_download_failure(
                                    mailbox_key,
                                    row["uid"],
                                    "no_candidate_link",
                                    "No candidate invoice link or attachment",
                                )
                            else:
                                if outcome_status == "parse_failed":
                                    parse_failed += 1
                                else:
                                    download_failed += 1
                                failed += 1
                                db.record_email_download_failure(
                                    mailbox_key,
                                    row["uid"],
                                    outcome_status,
                                    f"Failed to process {mask_uid(row.get('uid', 0))}",
                                )
                                failed_summaries.append(
                                    f"{outcome_status}: {mask_uid(row.get('uid', 0))}"
                                )
                        except Exception as exc:
                            download_failed += 1
                            failed += 1
                            db.record_email_download_failure(
                                mailbox_key,
                                row["uid"],
                                "download_failed",
                                sanitize_log_message(str(exc)),
                            )
                            failed_summaries.append(sanitize_log_message(str(exc)))
                            emit(sanitize_log_message(f"Failed to process {mask_uid(row.get('uid', 0))}: {exc}"))
                        handled_pending_uids.add(int(row["uid"]))
            except Exception as exc:
                failed_account_keys.add(mailbox_key)
                unfinished_rows = [
                    row for row in pending_for_account
                    if int(row["uid"]) not in handled_pending_uids
                ]
                pending_count = len(unfinished_rows)
                if pending_count:
                    classified_invoice += pending_count
                    download_failed += pending_count
                    failed += pending_count
                    error_summary = sanitize_log_message(str(exc))
                    for row in unfinished_rows:
                        db.record_email_download_failure(
                            mailbox_key,
                            row["uid"],
                            "download_failed",
                            error_summary,
                        )
                    failed_summaries.append(
                        sanitize_log_message(
                            f"download failed for {mask_email(email_addr)}: "
                            f"{pending_count} pending invoice emails incomplete: {exc}"
                        )
                    )
                    emit(
                        sanitize_log_message(
                            f"Download failed for {mask_email(email_addr)}: "
                            f"{pending_count} pending invoice emails will retry: {exc}"
                        )
                    )
                else:
                    failed_summaries.append(sanitize_log_message(f"download failed for {mask_email(email_addr)}: {exc}"))
                    emit(sanitize_log_message(f"Download failed for {mask_email(email_addr)}: {exc}"))

    if ai_auth_failed:
        pending_total = len(db.get_unclassified_emails())
        if pending_total > ai_pending_classification:
            ai_pending_classification = pending_total
            emit(f"AI 已暂停，{ai_pending_classification} 封邮件待分类。")

    link_dl.close()
    accounts_failed = len(failed_account_keys)
    accounts_success = max(0, accounts_total - accounts_failed)
    return {
        "scanned": scanned_headers,
        "scanned_headers": scanned_headers,
        "new_email_headers": new_email_headers,
        "new": new_invoice_records,
        "new_invoice_records": new_invoice_records,
        "restored_deleted": restored_deleted,
        "classified_invoice": classified_invoice,
        "downloaded": downloaded_emails,
        "downloaded_emails": downloaded_emails,
        "duplicates": duplicates,
        "duplicate_invoices": duplicates,
        "pending_manual": pending_manual,
        "manual_review_required": pending_manual,
        "failed": failed,
        "failed_count": failed,
        "failed_summaries": failed_summaries,
        "rule_excluded": rule_excluded,
        "no_candidate_link": no_candidate_link,
        "download_failed": download_failed,
        "manual_required": pending_manual,
        "parse_failed": parse_failed,
        "pending_retry": download_failed + parse_failed,
        "ai_auth_failed": ai_auth_failed,
        "ai_pending_classification": ai_pending_classification,
        "accounts_total": accounts_total,
        "accounts_success": accounts_success,
        "accounts_failed": accounts_failed,
        "accounts": [
            {
                "name": a.get("name", ""),
                "address": mask_email(a.get("address", "")),
                "mailbox_key": a.get("mailbox_key", ""),
            }
            for a in account_contexts
        ],
    }

def _run_classify(
    db: InvoiceDB,
    ai_cfg: dict,
    no_ai: bool,
    mailbox_key: str | None = None,
) -> dict:
    """Run rule + AI classification on unclassified emails."""
    if mailbox_key is None:
        all_unclassified = db.get_unclassified_emails()
        if not all_unclassified:
            _log.info("没有未分类的邮件")
            return
        mailbox_keys = sorted({str(row.get("mailbox_key") or "legacy") for row in all_unclassified})
        if len(mailbox_keys) > 1:
            for key in mailbox_keys:
                _run_classify(db, ai_cfg, no_ai, mailbox_key=key)
            return
        mailbox_key = mailbox_keys[0]

    unclassified = db.get_unclassified_emails(mailbox_key=mailbox_key)
    if not unclassified:
        _log.info("没有未分类的邮件")
        return

    # Rule classification (including trusted senders)
    rule_results = []
    rule_count = 0
    for row in unclassified:
        row_mailbox_key = str(row.get("mailbox_key") or mailbox_key or "legacy")
        # 1. Run local keyword classifier first (exclusion rules take absolute highest priority)
        result, reason = rule_classify(row["subject"], row["sender"])
        if result == 0:
            # Blocked by local exclusion keywords (even if sender is whitelisted)
            rule_results.append({
                "uid": row["uid"], "is_invoice": False,
                "by": "rule", "reason": reason,
                "mailbox_key": row_mailbox_key,
            })
            rule_count += 1
            continue
        elif result == 1:
            # Confirmed by local positive keywords
            rule_results.append({
                "uid": row["uid"], "is_invoice": True,
                "by": "rule", "reason": reason,
                "mailbox_key": row_mailbox_key,
            })
            rule_count += 1
            continue

        # 2. Check trusted senders whitelist if rules are uncertain (-1)
        if db.is_trusted_sender(row["sender"]):
            rule_results.append({
                "uid": row["uid"], "is_invoice": True,
                "by": "whitelist", "reason": "发送者在白名单中",
                "mailbox_key": row_mailbox_key,
            })
            rule_count += 1
            continue

    if rule_results:
        db.bulk_classify(rule_results, mailbox_key=mailbox_key or "legacy")
    _log.info("规则/白名单分类: %d/%d", rule_count, len(unclassified))

    # AI classification
    still_unknown = db.get_unclassified_emails(mailbox_key=mailbox_key)
    provider = str(ai_cfg.get("provider", "none") or "none").strip().lower()

    from .ai_classifier import is_provider_session_paused
    if still_unknown and provider != "none" and is_provider_session_paused(provider):
        _log.warning("AI 已因鉴权失败暂停，请检查 API Key。")
        return {"auth_failed": True, "pending_classification": len(still_unknown)}

    ai_disabled = no_ai or provider in {"", "none", "off", "disabled"}
    if still_unknown and not ai_disabled:
        try:
            classifier_cls = globals().get("AIClassifier")
            if classifier_cls is None:
                from .ai_classifier import AIClassifier as classifier_cls
            ai = classifier_cls(
                provider=provider,
                model=ai_cfg.get("model", ""),
                batch_size=ai_cfg.get("batch_size", 20),
                profile_id=ai_cfg.get("profile_id", ""),
            )
            results = ai.classify_batch(still_unknown)
            auth_failed = bool(getattr(ai, "auth_failed", False))
            classified_results = [r for r in results if r.get("is_invoice") is not None]
            pending_count = len(results) - len(classified_results)
            db.bulk_classify([
                {"uid": r["uid"], "is_invoice": r["is_invoice"],
                 "by": provider, "reason": r.get("reason", ""),
                 "mailbox_key": mailbox_key or "legacy"}
                for r in classified_results
            ], mailbox_key=mailbox_key or "legacy")
            if pending_count and not auth_failed:
                _log.warning("⚠️ AI 分类 API 失败，%d 封邮件将在下次运行时重试", pending_count)

            if auth_failed:
                _log.error("AI API Key 鉴权失败，请检查设置")
                return {"auth_failed": True, "pending_classification": len(still_unknown)}

            # Save confirmed senders to whitelist
            uid_to_sender = {
                (str(r.get("mailbox_key") or mailbox_key or "legacy"), r["uid"]): r["sender"]
                for r in still_unknown
            }
            for r in classified_results:
                if r["is_invoice"]:
                    sender = uid_to_sender.get((str(mailbox_key or "legacy"), r["uid"]))
                    if sender:
                        db.add_trusted_sender(sender)

            _log.info("AI 分类: %d/%d", len(classified_results), len(still_unknown))
        except SystemExit as exc:
            _log.warning(
                "AI 分类不可用，保留 %d 封邮件待后续分类: %s",
                len(still_unknown),
                exc,
            )
        except Exception as exc:
            _log.warning(
                "AI 分类不可用，保留 %d 封邮件待后续分类: %s",
                len(still_unknown),
                exc,
            )
    elif still_unknown:
        _log.info("AI 分类已关闭: %d 封邮件保持未分类", len(still_unknown))

    stats = db.get_email_stats()
    _log.info("分类结果: 发票 %d, 非发票 %d, 未分类 %d",
              stats["invoice"], stats["not_invoice"], stats["unclassified"])
    return {"auth_failed": False}


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
    config: dict | None = None,
) -> PendingEmailResult:
    """Fetch and process one pending invoice email.

    Returns True only when at least one invoice record was created. This avoids
    hiding failed downloads from future retries.
    """
    msg = fetcher.fetch_by_uid(row["uid"], folder=folder)
    if not msg:
        _log.warning("  获取 %s 失败，跳过", mask_uid(row["uid"]))
        return PendingEmailResult("download_failed")
    if not msg.date:
        msg.date = row.get("mail_date", "")

    try:
        link_dl.last_download_diagnostics = {
            "found_links": 0,
            "candidate_links": 0,
            "attempted": 0,
            "failed": 0,
        }
        link_dl.last_process_outcome = ""
    except (AttributeError, TypeError):
        pass
    recorded = _process_email(
        msg,
        att_handler,
        parser,
        link_dl,
        db,
        categories,
        mailbox_key=row.get("mailbox_key", "legacy"),
        config=config,
    )
    process_outcome = str(
        getattr(link_dl, "last_process_outcome", "") or ""
    )
    if recorded > 0:
        db.mark_downloaded(row["uid"], mailbox_key=row.get("mailbox_key", "legacy"))
        if process_outcome in {
            "file_restored",
            "metadata_refreshed",
            "manual_required",
            "duplicate",
        }:
            return PendingEmailResult(process_outcome)
        return PendingEmailResult("recorded")

    if process_outcome in {
        "no_candidate_link",
        "download_failed",
        "parse_failed",
        "duplicate",
    }:
        return PendingEmailResult(process_outcome)

    diagnostics = getattr(link_dl, "last_download_diagnostics", {}) or {}
    candidate_links = int(diagnostics.get("candidate_links", 0) or 0)
    attempted = int(diagnostics.get("attempted", 0) or 0)
    failed = int(diagnostics.get("failed", 0) or 0)
    if candidate_links == 0:
        _log.info(
            "  %s 未找到候选发票链接或附件，不自动重试",
            mask_uid(row["uid"]),
        )
        return PendingEmailResult("no_candidate_link")
    if attempted > 0 and failed > 0:
        _log.warning(
            "  %s 候选链接下载失败，将按冷却策略重试",
            mask_uid(row["uid"]),
        )
        return PendingEmailResult("download_failed")
    _log.warning(
        "  %s 下载内容解析失败，将按冷却策略重试",
        mask_uid(row["uid"]),
    )
    return PendingEmailResult("parse_failed")


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


def _cmd_email_reprocess(args: argparse.Namespace, db: InvoiceDB):
    """Subcommand handler to reprocess emails."""
    # 1. 验证 limit 必须为正整数
    if args.limit is not None and args.limit <= 0:
        print("错误: --limit 必须为正整数。")
        sys.exit(1)

    # 2. apply 模式下的高强度安全保护校验
    if args.apply:
        # 必须提供 mailbox
        if not args.mailbox:
            print("错误: 在 apply 模式下，必须指定 --mailbox 邮箱账号。")
            sys.exit(1)
        # 必须至少提供一个筛选范围条件
        has_filter = (
            args.uid or
            args.uid_range or
            args.since or
            args.until or
            args.subject_contains or
            args.sender_contains
        )
        if not has_filter:
            print("错误: 在 apply 模式下，必须提供至少一个具体的筛选范围（如 --uid, --uid-range, --since, --until, --subject-contains, --sender-contains）以防误操作全局删除。")
            sys.exit(1)
        # 单次最大数量限制，除非显式指定 --force-large-batch
        if args.limit is not None and args.limit > 200 and not args.force_large_batch:
            print("错误: 单次处理数量限制为 200。如果确需处理大批量邮件，请显式提供 --force-large-batch 选项。")
            sys.exit(1)

    # 3. 验证 uid-range 并解析
    uid_range = None
    if args.uid_range:
        parts = args.uid_range.split("-")
        if len(parts) == 2:
            try:
                start = int(parts[0])
                end = int(parts[1])
                if start <= end and start >= 0:
                    uid_range = (start, end)
            except ValueError:
                pass
        if not uid_range:
            print("错误: --uid-range 格式必须为 START-END, 且满足 START <= END (均需为非负整数)。")
            sys.exit(1)

    # 4. 验证 since/until 的格式 (YYYY-MM-DD) 以及 since <= until
    import re as _re
    date_pat = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if args.since:
        if not date_pat.match(args.since):
            print("错误: --since 日期格式必须为 YYYY-MM-DD。")
            sys.exit(1)
    if args.until:
        if not date_pat.match(args.until):
            print("错误: --until 日期格式必须为 YYYY-MM-DD。")
            sys.exit(1)
    if args.since and args.until:
        if args.since > args.until:
            print("错误: --since 起始日期不能大于 --until 结束日期。")
            sys.exit(1)

    dry_run = args.dry_run or not args.apply

    records = db.find_emails_for_reprocess(
        mailbox_key=args.mailbox,
        uids=args.uid,
        uid_range=uid_range,
        since=args.since,
        until=args.until,
        subject_contains=args.subject_contains,
        sender_contains=args.sender_contains,
        only_downloaded=args.only_downloaded,
        limit=args.limit,
    )

    if not records:
        print("没有找到符合条件的候选邮件记录。")
        sys.exit(0)

    cfg = load_config(args.config)
    _reprocess_email_records(
        db=db,
        cfg=cfg,
        records=records,
        include_approved=args.include_approved,
        include_claimed=args.include_claimed,
        reclassify=args.reclassify,
        dry_run=dry_run,
        headed=args.headed,
    )


def _reprocess_email_records(
    db: InvoiceDB,
    cfg: dict,
    records: list[dict],
    include_approved: bool = False,
    include_claimed: bool = False,
    reclassify: bool = False,
    dry_run: bool = True,
    headed: bool = False,
):
    """Reprocess the selected email records."""
    import json as _json

    # 1. 预先扫描拟删除及跳过的 invoices 详情
    all_targets = []
    total_to_delete = 0
    total_skipped_approved = 0
    total_skipped_claimed = 0

    for r in records:
        mailbox_key = r["mailbox_key"]
        uid = r["uid"]
        invoices = db.get_invoices_by_mail_identity(mailbox_key, uid)

        record_targets = []
        for inv in invoices:
            is_approved = (inv.get("review_status") == "approved")
            is_claimed = inv.get("claim_id") is not None

            skip_reason = None
            if is_approved and not include_approved:
                total_skipped_approved += 1
                skip_reason = "approved"
            elif is_claimed and not include_claimed:
                total_skipped_claimed += 1
                skip_reason = "claimed"
            else:
                total_to_delete += 1

            record_targets.append({
                "inv": inv,
                "skip_reason": skip_reason
            })

        all_targets.append({
            "email": r,
            "targets": record_targets
        })

    # Dry-run 模式
    if dry_run:
        print("邮箱重处理预览：")
        print(f"- 候选邮件：{len(records)} 封")
        print(f"- 将删除旧发票记录：{total_to_delete} 条")
        print(f"- 跳过已通过：{total_skipped_approved} 条")
        print(f"- 跳过已归组：{total_skipped_claimed} 条")
        print("\n候选：")

        for idx, item in enumerate(all_targets, start=1):
            email = item["email"]
            masked_mailbox = mask_email(email["mailbox_key"])
            masked_uid = mask_uid(email["uid"])
            redacted_subject = redact_text(email["subject"] or "", "subject")
            print(f"[{idx}] mailbox={masked_mailbox} uid={masked_uid} date={email['mail_date']} subject={redacted_subject}")

            for tgt in item["targets"]:
                inv = tgt["inv"]
                inv_id = inv["id"]
                inv_num = mask_invoice_number(inv.get("invoice_number") or "")
                amount = inv.get("total_amount") or "0.00"
                status = inv.get("review_status") or "to_review"
                fallback_str = " (legacy fallback)" if inv.get("is_legacy_fallback") else ""

                try:
                    extra_paths_list = _json.loads(inv.get("extra_paths") or "[]")
                except Exception:
                    extra_paths_list = []
                extra_count = len(extra_paths_list)

                if tgt["skip_reason"] == "approved":
                    print(f"    [跳过] 已通过审核: invoice id={inv_id}{fallback_str} 发票号={inv_num} 金额={amount}")
                elif tgt["skip_reason"] == "claimed":
                    claim_id = inv.get("claim_id")
                    print(f"    [跳过] 已关联报销组: invoice id={inv_id}{fallback_str} 发票号={inv_num} 金额={amount} 报销组ID={claim_id}")
                else:
                    print(f"    将删除 invoice id={inv_id}{fallback_str} 发票号={inv_num} 金额={amount} 状态={status} extra={extra_count}")

        print("\n未执行修改。确认无误后加 --apply 执行。")
        return

    # Apply 真正执行模式
    print("正在执行邮箱重处理，请稍候...")
    deleted_invoices_total = 0
    skipped_approved_total = 0
    skipped_claimed_total = 0

    # 1) 删除及重置
    for r in records:
        mailbox_key = r["mailbox_key"]
        uid = r["uid"]

        stats = db.delete_invoices_for_reprocess(
            mailbox_key=mailbox_key,
            uid=uid,
            include_approved=include_approved,
            include_claimed=include_claimed,
        )
        deleted_invoices_total += stats["deleted"]
        skipped_approved_total += stats["skipped_approved"]
        skipped_claimed_total += stats["skipped_claimed"]

        db.reset_email_for_reprocess(
            mailbox_key=mailbox_key,
            uid=uid,
            reclassify=reclassify,
        )

    # 2) 重新分类 (如果启用 reclassify)
    mailbox_keys = {r["mailbox_key"] for r in records}
    if reclassify:
        ai_cfg = cfg.get("ai", {})
        import sys as _sys
        no_ai_arg = "--no-ai" in _sys.argv
        for m_key in mailbox_keys:
            _run_classify(db, ai_cfg, no_ai=no_ai_arg, mailbox_key=m_key)

    # 3) 获取邮箱配置并进行下载
    accounts = get_email_accounts(cfg)
    account_contexts = []
    for acc in accounts:
        addr = acc.get("address", "")
        auth_code = ""
        # 优先使用配置里已有的 auth_code（在单元测试的 mock 里可能已经定义了）
        if "auth_code" in acc:
            auth_code = acc["auth_code"]
        else:
            try:
                auth_code = get_auth_code(addr)
            except (Exception, SystemExit) as e:
                _log.warning("获取邮箱 %s 的授权码失败: %s", mask_email(addr), e)
        account_contexts.append({**acc, "auth_code": auth_code})
    account_by_key = {acc["mailbox_key"]: acc for acc in account_contexts}

    att_dir = db._path.parent / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    att_handler = AttachmentHandler(att_dir)
    parser = InvoiceParser()
    link_dl = LinkDownloader(att_dir, headed=headed)

    # ── Downgrade filename conflict logs during reprocess ──
    global _rename_source_mode
    prev_rename_mode = _rename_source_mode
    _rename_source_mode = "reprocess"

    reprocessed_count = 0
    failed_count = 0
    new_records_count = 0
    restored_deleted_count = 0
    duplicates_count = 0

    for m_key in mailbox_keys:
        selected_uids = {r["uid"] for r in records if r["mailbox_key"] == m_key}

        acc = account_by_key.get(m_key)
        if not acc:
            _log.warning("未在配置中找到 mailbox_key=%s 的邮箱配置，无法重新下载该邮箱下的邮件", m_key)
            pending_downloads = db.get_invoice_emails_to_download(mailbox_key=m_key)
            failed_uids = [row["uid"] for row in pending_downloads if row["uid"] in selected_uids]
            failed_count += len(failed_uids)
            reprocessed_count += (len(selected_uids) - len(failed_uids))
            continue

        pending = []
        try:
            pending = db.get_invoice_emails_to_download(mailbox_key=m_key)
            pending = [row for row in pending if row["uid"] in selected_uids]

            not_pending_uids = selected_uids - {row["uid"] for row in pending}
            reprocessed_count += len(not_pending_uids)

            if pending:
                if not acc.get("auth_code"):
                    _log.warning("获取邮箱 %s 的授权码为空，无法下载该邮箱下的 %d 封邮件", mask_email(acc["address"]), len(pending))
                    failed_count += len(pending)
                    continue

                provider = acc.get("provider", "")
                server = acc.get("imap", {}).get("server", "")
                if is_outlook_like_account(provider, acc["address"], server):
                    _log.warning("跳过 Outlook/Microsoft 邮箱：当前版本需要 OAuth2，暂不支持扫描。邮箱：%s", mask_email(acc["address"]))
                    failed_count += len(pending)
                    continue


                _log.info("正在连接邮箱 %s...", mask_email(acc["address"]))
                with MailFetcher(
                    address=acc["address"],
                    auth_code=acc["auth_code"],
                    server=acc.get("imap", {}).get("server", "imap.qq.com"),
                    port=acc.get("imap", {}).get("port", 993),
                ) as fetcher:
                    folder = acc.get("search", {}).get("folder", "INBOX")
                    for row in pending:
                        before_active_count = db.count_invoices()
                        before_total_count = db.count_invoices(include_deleted=True)

                        recorded = _handle_pending_email(
                            row=row,
                            fetcher=fetcher,
                            folder=folder,
                            att_handler=att_handler,
                            parser=parser,
                            link_dl=link_dl,
                            db=db,
                            categories=cfg.get("categories", {}),
                            config=cfg,
                        )

                        after_active_count = db.count_invoices()
                        after_total_count = db.count_invoices(include_deleted=True)

                        if recorded:
                            reprocessed_count += 1
                            new_delta = max(0, after_total_count - before_total_count)
                            restored_delta = max(0, (after_active_count - before_active_count) - new_delta)
                            new_records_count += new_delta
                            restored_deleted_count += restored_delta
                            if new_delta == 0 and restored_delta == 0:
                                duplicates_count += 1
                        else:
                            failed_count += 1
            else:
                pass
        except Exception as exc:
            _log.error("连接邮箱 %s 失败或下载过程中出错: %s", mask_email(acc["address"]), exc)
            failed_count += len(pending)

    link_dl.close()

    # ── Restore filename conflict log severity ──
    _rename_source_mode = prev_rename_mode

    print("\n邮箱重处理完成：")
    print(f"- 选中邮件：{len(records)} 封")
    print(f"- 删除旧记录：{deleted_invoices_total} 条")
    print(f"- 跳过已通过：{skipped_approved_total} 条")
    print(f"- 跳过已归组：{skipped_claimed_total} 条")
    print(f"- 重新处理成功：{reprocessed_count} 封")
    print(f"- 新增记录：{new_records_count} 条")
    print(f"- 恢复已删除记录：{restored_deleted_count} 条")
    print(f"- 重复：{duplicates_count} 条")
    print(f"- 失败：{failed_count} 封")


if __name__ == "__main__":
    main()
