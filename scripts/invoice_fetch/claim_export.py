"""Export reimbursement package folders from invoice claim groups."""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import InvoiceDB

from . import review_status
from .config import load_config_safe
from .db import is_pending_evidence_invoice
from .excel_export import export_excel
from .log_privacy import mask_path
from .reimbursement import buyer_warning, get_date_warning

_log = logging.getLogger(__name__)


def _sanitize_dirname(name: str) -> str:
    """Sanitize user input to be a valid Windows/cross-platform directory name."""
    # Replace illegal characters with underscore
    cleaned = re.sub(r'[\\/:*?"<>|]', '_', name)
    # Remove control characters
    cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '_', cleaned)
    # Collapse multiple underscores
    cleaned = re.sub(r'_+', '_', cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        cleaned = "unnamed_claim"
    # Truncate to maximum 50 characters to prevent path length issues
    return cleaned[:50]


def _normalize_path_list(raw_value) -> list[str]:
    if not raw_value:
        return []
    if isinstance(raw_value, list):
        items = raw_value
    elif isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            items = parsed if isinstance(parsed, list) else [raw_value]
        except json.JSONDecodeError:
            items = [raw_value]
    else:
        try:
            items = list(raw_value)
        except TypeError:
            items = [raw_value]
    normalized = []
    for item in items:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_export_date_prefix(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return "unknown-date"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    text = re.sub(r"[^\dA-Za-z-]+", "-", text).strip("-")
    return text or "unknown-date"


def _prefix_export_filename(filename: str, date_prefix: str) -> str:
    basename = Path(str(filename or "")).name
    safe_prefix = _normalize_export_date_prefix(date_prefix)

    if safe_prefix != "unknown-date":
        if basename.startswith("unknown-date_"):
            basename = basename[len("unknown-date_"):]

    if re.match(r"^\d{4}-\d{2}-\d{2}_", basename):
        return basename

    return f"{safe_prefix}_{basename}"


def _copy_into_attachments(
    src_value: str,
    runtime_dir: Path,
    attachments_dir: Path,
    *,
    date_prefix: str = "",
) -> str:
    if not src_value:
        return ""
    src_path = Path(src_value)
    if not src_path.is_absolute():
        src_path = runtime_dir / src_value
    if not src_path.exists() or not src_path.is_file():
        _log.warning("Attachment file not found at: %s (skipped)", mask_path(src_path))
        return ""

    dest_name = _prefix_export_filename(src_path.name, date_prefix)
    dest_path = attachments_dir / dest_name
    if dest_path.exists():
        stem = dest_path.stem
        ext = src_path.suffix
        counter = 1
        while True:
            candidate = attachments_dir / f"{stem}_{counter}{ext}"
            if not candidate.exists():
                dest_path = candidate
                break
            counter += 1

    shutil.copy2(src_path, dest_path)
    copied_relative_path = f"attachments/{dest_path.name}"
    _log.info("Copied export file: %s -> %s", mask_path(src_path), mask_path(copied_relative_path))
    return copied_relative_path



def _invoice_sort_key(inv: dict) -> tuple:
    inv_date = inv.get("invoice_date") or ""
    exp_date = inv.get("expense_date") or ""
    mail_date = inv.get("mail_date") or ""
    inv_id = inv.get("id") or 0
    return (
        0 if inv_date else 1, inv_date,
        0 if exp_date else 1, exp_date,
        0 if mail_date else 1, mail_date,
        inv_id
    )


def export_claim_package(
    db: InvoiceDB,
    claim_id: int,
    project_root: Path,
    runtime_dir: Path,
    include_to_review: bool = False,
    reimbursement_config: dict | None = None,
) -> Path:
    """Export all invoices in a claim group to exports/<sanitized-claim-name>_<timestamp>/

    Includes reimbursement.xlsx, manifest.json, and copied attachments/.
    """
    claim = db.get_claim_group(claim_id)
    if not claim:
        raise ValueError(f"报销组 ID {claim_id} 不存在。")

    all_invoices = db.get_claim_invoices(claim_id)
    if not all_invoices:
        raise ValueError(f"报销组“{claim['name']}”没有可导出的发票。")

    # Status filtering setup
    included_statuses = [review_status.APPROVED]
    if include_to_review:
        included_statuses.append(review_status.TO_REVIEW)

    export_filter = "approved_and_to_review" if include_to_review else "approved_only"
    always_excluded_statuses = [review_status.IGNORED, review_status.ERROR]

    invoices = []
    skipped_counts = {
        review_status.TO_REVIEW: 0,
        review_status.APPROVED: 0,
        review_status.IGNORED: 0,
        review_status.ERROR: 0,
        "pending_evidence": 0,
        "unknown": 0
    }

    for inv in all_invoices:
        if is_pending_evidence_invoice(inv):
            skipped_counts["pending_evidence"] += 1
            continue
        status = inv.get("review_status") or review_status.TO_REVIEW
        if status in included_statuses:
            invoices.append(inv)
        else:
            if status in skipped_counts:
                skipped_counts[status] += 1
            else:
                skipped_counts["unknown"] += 1

    if not invoices:
        raise ValueError(f"报销组“{claim['name']}”筛选后没有符合条件的可导出发票。")

    invoices.sort(key=_invoice_sort_key)

    if reimbursement_config is None:
        reimbursement_config = load_config_safe().get("reimbursement", {})

    # 1. Setup export directory with timestamp to avoid stale files from repeated exports
    sanitized_name = _sanitize_dirname(claim["name"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    export_dir = project_root / "exports" / f"{sanitized_name}_{timestamp}"
    export_dir.mkdir(parents=True, exist_ok=True)

    attachments_dir = export_dir / "attachments"
    attachments_dir.mkdir(exist_ok=True)

    # We will copy invoices list to avoid mutating items in-memory that other code might use
    export_invoices = []
    manifest_items = []

    # 2. Process attachments
    for inv in invoices:
        inv_copy = dict(inv)
        b_warning = buyer_warning(inv, reimbursement_config)
        d_warning = get_date_warning(inv)
        if b_warning and d_warning:
            warning = f"{b_warning}；{d_warning}"
        elif b_warning:
            warning = b_warning
        else:
            warning = d_warning
        inv_copy["warning"] = warning
        copied_relative_path = ""
        orig_attachment_path = inv.get("attachment_path", "")
        export_date_prefix = inv.get("invoice_date") or inv.get("expense_date") or "unknown-date"

        if orig_attachment_path:
            copied_relative_path = _copy_into_attachments(
                orig_attachment_path,
                runtime_dir,
                attachments_dir,
                date_prefix=export_date_prefix,
            )
        else:
            _log.info("No attachment path found for invoice ID %s", inv.get("id"))

        raw_extra_paths = _normalize_path_list(inv.get("extra_paths"))
        copied_extra_paths = []
        for extra_path in raw_extra_paths:
            copied_extra_path = _copy_into_attachments(
                extra_path,
                runtime_dir,
                attachments_dir,
                date_prefix=export_date_prefix,
            )
            if copied_extra_path:
                copied_extra_paths.append(copied_extra_path)

        # Update the row's attachment path so that the exported Excel file points relatively to the copied file
        inv_copy["attachment_path"] = copied_relative_path
        inv_copy["extra_paths"] = copied_extra_paths
        export_invoices.append(inv_copy)

        # Build manifest item details
        manifest_items.append({
            "invoice_id": inv.get("id"),
            "invoice_number": inv.get("invoice_number"),
            "invoice_date": inv.get("invoice_date"),
            "expense_date": inv.get("expense_date") or inv.get("invoice_date"),
            "date_source": inv.get("date_source", ""),
            "category": inv.get("category"),
            "total_amount": inv.get("total_amount"),
            "currency": inv.get("currency", ""),
            "extra_type": inv.get("extra_type", ""),
            "has_extra": bool(inv.get("has_extra")),
            "missing_extra": bool(inv.get("missing_extra")),
            "parse_note": inv.get("parse_note", ""),
            "confirmed_note": inv.get("confirmed_note", ""),
            "attachment_path": copied_relative_path,
            "copied_attachment_path": copied_relative_path,
            "extra_paths": copied_extra_paths,
            "copied_extra_paths": copied_extra_paths,
            "review_status": inv.get("review_status", ""),
            "warning": warning,
        })

    # 3. Generate reimbursement.xlsx
    xlsx_dest = export_dir / "reimbursement.xlsx"
    export_excel(export_invoices, xlsx_dest)

    # 3.5 Generate claim_quality_report.md
    qa_warnings_count = _generate_quality_report(
        export_dir=export_dir,
        claim_name=claim["name"],
        export_invoices=export_invoices,
        original_invoices=invoices,
        all_invoices=all_invoices,
        db=db,
        runtime_dir=runtime_dir,
    )

    # 4. Generate manifest.json
    manifest_data = {
        "claim_id": claim_id,
        "claim_name": claim["name"],
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "export_filter": {
            "type": export_filter,
            "include_to_review": include_to_review,
            "included_statuses": included_statuses,
            "always_excluded_statuses": always_excluded_statuses
        },
        "skipped_counts": skipped_counts,
        "item_count": len(manifest_items),
        "qa_warnings_count": qa_warnings_count,
        "items": manifest_items
    }
    manifest_dest = export_dir / "manifest.json"
    with open(manifest_dest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    # 5. Log the export run in the DB
    db.add_export_run(claim_id, str(export_dir), "generic_excel", len(invoices))

    _log.info("Claim export package completed successfully under: %s", mask_path(export_dir))
    return export_dir


def _escape_md_inline(text: str) -> str:
    """Escape Markdown control characters for safe table/inline display."""
    if not text:
        return ""
    escaped = str(text)
    escaped = escaped.replace("\\", "\\\\")
    escaped = escaped.replace("|", "\\|")
    for char in ("*", "_", "`", "#", "[", "]", "(", ")"):
        escaped = escaped.replace(char, f"\\{char}")
    escaped = escaped.replace("\r", " ").replace("\n", " ")
    return escaped


def _generate_quality_report(
    export_dir: Path,
    claim_name: str,
    export_invoices: list[dict],
    original_invoices: list[dict],
    all_invoices: list[dict],
    db: InvoiceDB,
    runtime_dir: Path,
) -> int:
    """Generate claim_quality_report.md inside export_dir and return qa_warnings_count."""
    # 1. Missing originals (using export_invoices rewritten attachment_path)
    missing_originals = sum(1 for inv in export_invoices if not inv.get("attachment_path"))

    # 2. Empty seller names
    empty_sellers = sum(1 for inv in export_invoices if not (inv.get("seller_name") or "").strip())

    # 3. Empty amounts
    empty_amounts = sum(1 for inv in export_invoices if not (inv.get("total_amount") or "").strip())

    # 4. Empty dates
    empty_dates = sum(1 for inv in export_invoices if not (inv.get("expense_date") or inv.get("invoice_date") or "").strip())

    # 5. Category is "其他"
    category_others = sum(1 for inv in export_invoices if (inv.get("category") or "").strip() == "其他")

    # 6. Evidence required but missing
    missing_extras = sum(1 for inv in export_invoices if bool(inv.get("missing_extra")))

    # 7. Personal notes
    filled_confirmed_notes = sum(1 for inv in export_invoices if (inv.get("confirmed_note") or "").strip())

    # 8. Evidence files missing in source (using original_invoices)
    missing_evidence_files = 0
    for inv in original_invoices:
        raw_extra_paths = _normalize_path_list(inv.get("extra_paths"))
        for extra_path in raw_extra_paths:
            src_path = Path(extra_path)
            if not src_path.is_absolute():
                src_path = runtime_dir / extra_path
            if not src_path.exists() or not src_path.is_file():
                missing_evidence_files += 1

    # 9. Suspected duplicate items
    suspected_duplicates = 0
    for inv in original_invoices:
        num = inv.get("invoice_number")
        if num and num.strip():
            count = db.count_active_duplicates_by_invoice_number(num, inv["id"])
            if count > 0:
                suspected_duplicates += 1

    # 10. Status statistics (from all_invoices in the claim group)
    status_counts = {
        "approved": 0,
        "to_review": 0,
        "ignored": 0,
        "error": 0
    }
    for inv in all_invoices:
        status = inv.get("review_status") or "to_review"
        if status in status_counts:
            status_counts[status] += 1

    qa_warnings_count = (
        missing_originals
        + empty_sellers
        + empty_amounts
        + empty_dates
        + category_others
        + missing_extras
        + missing_evidence_files
        + suspected_duplicates
    )

    # status indicators
    status_missing_originals = f"⚠️ 发现 {missing_originals} 张缺失原件" if missing_originals > 0 else "✅ 合格"
    status_empty_sellers = f"⚠️ 发现 {empty_sellers} 张销售方为空" if empty_sellers > 0 else "✅ 合格"
    status_empty_amounts = f"⚠️ 发现 {empty_amounts} 张金额为空" if empty_amounts > 0 else "✅ 合格"
    status_empty_dates = f"⚠️ 发现 {empty_dates} 张日期为空" if empty_dates > 0 else "✅ 合格"
    status_category_others = f"⚠️ 发现 {category_others} 张消费类型为“其他”" if category_others > 0 else "✅ 合格"
    status_missing_extras = f"⚠️ 发现 {missing_extras} 张缺少证明材料" if missing_extras > 0 else "✅ 合格"
    status_filled_confirmed_notes = f"已填写 {filled_confirmed_notes} 项" if filled_confirmed_notes > 0 else "未填写"
    status_missing_evidence_files = f"⚠️ 发现 {missing_evidence_files} 个证明材料文件不存在" if missing_evidence_files > 0 else "✅ 合格"
    status_suspected_duplicates = f"⚠️ 发现 {suspected_duplicates} 张疑似重复发票" if suspected_duplicates > 0 else "✅ 合格"

    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    escaped_claim_name = _escape_md_inline(claim_name)

    # Generate report
    report_content = f"""# 报销包质量检查报告

- **导出的报销组**: {escaped_claim_name}
- **导出时间**: {export_time}

## 质量检查摘要

| 检查项目 | 数量 | 状态/说明 |
| --- | --- | --- |
| 1. 原件文件缺失 | {missing_originals} | {status_missing_originals} |
| 2. 销售方为空 | {empty_sellers} | {status_empty_sellers} |
| 3. 金额为空 | {empty_amounts} | {status_empty_amounts} |
| 4. 日期为空 | {empty_dates} | {status_empty_dates} |
| 5. 消费类型为“其他” | {category_others} | {status_category_others} |
| 6. 有证明材料要求但未关联 | {missing_extras} | {status_missing_extras} |
| 7. 已填写个人备注 | {filled_confirmed_notes} | {status_filled_confirmed_notes} |
| 8. 证明材料文件不存在 | {missing_evidence_files} | {status_missing_evidence_files} |
| 9. 重复发票疑似项 | {suspected_duplicates} | {status_suspected_duplicates} |

## 报销组发票状态统计

- **已审核 (approved)**: {status_counts["approved"]} 张
- **待审核 (to_review)**: {status_counts["to_review"]} 张
- **已忽略 (ignored)**: {status_counts["ignored"]} 张
- **异常 (error)**: {status_counts["error"]} 张

---
*注：此报告由系统自动生成，旨在帮助您在提交报销前进行最后核对。*
"""

    report_path = export_dir / "claim_quality_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    return qa_warnings_count
