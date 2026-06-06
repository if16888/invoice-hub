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
from .reimbursement import buyer_warning

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


def _copy_into_attachments(src_value: str, runtime_dir: Path, attachments_dir: Path) -> str:
    if not src_value:
        return ""
    src_path = Path(src_value)
    if not src_path.is_absolute():
        src_path = runtime_dir / src_value
    if not src_path.exists() or not src_path.is_file():
        _log.warning("Attachment file not found at: %s (skipped)", mask_path(src_path))
        return ""

    dest_path = attachments_dir / src_path.name
    if dest_path.exists():
        stem = src_path.stem
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
        warning = buyer_warning(inv, reimbursement_config)
        inv_copy["warning"] = warning
        copied_relative_path = ""
        orig_attachment_path = inv.get("attachment_path", "")

        if orig_attachment_path:
            copied_relative_path = _copy_into_attachments(orig_attachment_path, runtime_dir, attachments_dir)
        else:
            _log.info("No attachment path found for invoice ID %s", inv.get("id"))

        raw_extra_paths = _normalize_path_list(inv.get("extra_paths"))
        copied_extra_paths = []
        for extra_path in raw_extra_paths:
            copied_extra_path = _copy_into_attachments(extra_path, runtime_dir, attachments_dir)
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
        "items": manifest_items
    }
    manifest_dest = export_dir / "manifest.json"
    with open(manifest_dest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    # 5. Log the export run in the DB
    db.add_export_run(claim_id, str(export_dir), "generic_excel", len(invoices))

    _log.info("Claim export package completed successfully under: %s", mask_path(export_dir))
    return export_dir
