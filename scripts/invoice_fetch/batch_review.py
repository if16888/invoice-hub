"""Preview and recheck conservative batch approvals without changing manual review."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

from .amount_utils import parse_amount
from .claim_export import inspect_extra_material, inspect_original_attachment
from .db import is_pending_evidence_invoice
from .financial_validation import check_tax_balance
from .reimbursement import buyer_warning
from .review_status import APPROVED, IGNORED, TO_REVIEW


@dataclass(frozen=True)
class BatchSkip:
    invoice_id: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BatchReviewPlan:
    requested_ids: tuple[int, ...]
    snapshots: tuple[tuple[int, tuple], ...]
    skipped: tuple[BatchSkip, ...]
    target_status: str = APPROVED

    @property
    def eligible_ids(self) -> tuple[int, ...]:
        return tuple(invoice_id for invoice_id, _ in self.snapshots)


@dataclass(frozen=True)
class BatchReviewResult:
    changed_ids: tuple[int, ...]
    skipped: tuple[BatchSkip, ...]


def _snapshot(invoice: dict) -> tuple:
    # The weak-key cache is derived data, not an edit requiring user consent.
    return tuple(sorted((key, value) for key, value in invoice.items() if key != "soft_fingerprint"))


def _approval_reasons(invoice: dict, flags: set[str], config: dict, runtime_dir: Path) -> tuple[str, ...]:
    reasons = []
    if invoice.get("is_deleted"):
        return ("记录已删除",)
    if invoice.get("review_status") != TO_REVIEW:
        return ("不是待审核状态",)
    if is_pending_evidence_invoice(invoice):
        return ("待关联证明材料",)
    if not str(invoice.get("invoice_number") or "").strip():
        reasons.append("票号缺失，需逐张确认")
    if not str(invoice.get("seller_name") or "").strip():
        reasons.append("销售方缺失")
    try:
        parse_amount(invoice.get("total_amount"))
    except ValueError:
        reasons.append("金额缺失或无效")
    try:
        date.fromisoformat(str(invoice.get("expense_date") or invoice.get("invoice_date") or "").strip())
    except ValueError:
        reasons.append("费用日期缺失或无效")
    if invoice.get("parse_success") in (0, False, "0"):
        reasons.append("解析结果需逐张核对")
    if buyer_warning(invoice, config):
        reasons.append("购买方或税号异常")
    balance = check_tax_balance(invoice)
    if balance.blocking:
        reasons.append(balance.message)
    if not inspect_original_attachment(invoice, runtime_dir)["available"]:
        reasons.append("原件缺失或不可用")
    extra = inspect_extra_material(invoice, runtime_dir)
    if extra["missing_extra"]:
        reasons.append("缺证明材料")
    if extra["unavailable_extra"]:
        reasons.append("证明材料不可用")
    for flag, message in (
        ("number_duplicate", "票号重复"),
        ("soft_pending", "疑似重复待复核"),
        ("soft_duplicate", "已确认重复"),
    ):
        if flag in flags:
            reasons.append(message)
    return tuple(reasons)


def prepare_batch_approval(db, invoice_ids, config: dict, runtime_dir: Path) -> BatchReviewPlan:
    ids = tuple(dict.fromkeys(int(value) for value in invoice_ids))
    if not ids:
        return BatchReviewPlan((), (), ())
    db.refresh_duplicate_candidates()
    records = db.get_review_batch_invoices(ids)
    duplicate_flags = db.review_duplicate_flags()
    snapshots, skipped = [], []
    for invoice_id in ids:
        invoice = records.get(invoice_id)
        reasons = (("记录不存在",) if invoice is None else
                   _approval_reasons(invoice, duplicate_flags.get(invoice_id, set()), config, runtime_dir))
        if reasons:
            skipped.append(BatchSkip(invoice_id, reasons))
        else:
            snapshots.append((invoice_id, _snapshot(invoice)))
    return BatchReviewPlan(ids, tuple(snapshots), tuple(skipped))


def prepare_batch_ignore(db, invoice_ids) -> BatchReviewPlan:
    ids = tuple(dict.fromkeys(int(value) for value in invoice_ids))
    records = db.get_review_batch_invoices(ids)
    snapshots, skipped = [], []
    for invoice_id in ids:
        invoice = records.get(invoice_id)
        if invoice is None or invoice.get("is_deleted"):
            skipped.append(BatchSkip(invoice_id, ("记录不存在或已删除",)))
        elif invoice.get("review_status") == IGNORED:
            skipped.append(BatchSkip(invoice_id, ("已忽略，无需重复处理",)))
        else:
            snapshots.append((invoice_id, _snapshot(invoice)))
    return BatchReviewPlan(ids, tuple(snapshots), tuple(skipped), IGNORED)


def _apply_batch_plan(db, plan, prepare_fresh) -> BatchReviewResult:
    """Recheck only consented records and commit all surviving approvals together."""
    if not plan.eligible_ids:
        return BatchReviewResult((), plan.skipped)
    with db.batch_review_transaction():
        fresh = prepare_fresh(plan.eligible_ids)
        originals = dict(plan.snapshots)
        approved, changed = [], []
        for invoice_id, snapshot in fresh.snapshots:
            if snapshot != originals[invoice_id]:
                changed.append(BatchSkip(invoice_id, ("确认后记录已变更，请重新审核",)))
            else:
                approved.append(invoice_id)
        db.apply_review_batch_status(tuple(approved), plan.target_status)
    return BatchReviewResult(tuple(approved), plan.skipped + fresh.skipped + tuple(changed))


def apply_batch_approval(db, plan: BatchReviewPlan, config: dict, runtime_dir: Path) -> BatchReviewResult:
    if plan.target_status != APPROVED:
        raise ValueError("Expected an approval plan")
    return _apply_batch_plan(db, plan, lambda ids: prepare_batch_approval(db, ids, config, runtime_dir))


def apply_batch_ignore(db, plan: BatchReviewPlan) -> BatchReviewResult:
    if plan.target_status != IGNORED:
        raise ValueError("Expected an ignore plan")
    return _apply_batch_plan(db, plan, lambda ids: prepare_batch_ignore(db, ids))


def batch_skip_summary(skipped: tuple[BatchSkip, ...]) -> str:
    counts = Counter(reason for item in skipped for reason in item.reasons)
    return "；".join(f"{reason} {count} 张" for reason, count in counts.items())


def batch_amount_summary(rows: list[dict]) -> str:
    """Show selected totals per currency, preserving Decimal arithmetic."""
    totals = defaultdict(lambda: Decimal("0"))
    unknown = 0
    for row in rows:
        if is_pending_evidence_invoice(row):
            continue
        try:
            amount = parse_amount(row.get("total_amount"))
        except ValueError:
            unknown += 1
            continue
        currency = str(row.get("currency") or "").strip().upper() or "CNY"
        if currency in {"人民币", "RMB"}:
            currency = "CNY"
        with localcontext() as context:
            context.prec = 256
            totals[currency] += amount
    parts = [f"{'¥' if currency == 'CNY' else currency + ' '}{amount:.2f}"
             for currency, amount in sorted(totals.items())]
    if unknown:
        parts.append(f"{unknown} 张金额待核对")
    return " / ".join(parts)
