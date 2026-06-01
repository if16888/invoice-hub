"""Reimbursement validation helpers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


BUYER_MISSING_WARNING = "购方抬头待核对"
BUYER_MISMATCH_WARNING = "购方抬头不匹配，可能导致退单"


def _norm_text(value: str) -> str:
    return "".join(str(value or "").split()).lower()


def buyer_warning(invoice: dict, cfg: dict | None) -> str:
    """Return a non-blocking reimbursement warning for buyer title mismatch."""
    reimbursement_cfg = (cfg or {}).get("reimbursement", cfg or {})
    if not reimbursement_cfg.get("strict_buyer_check", False):
        return ""

    expected = str(reimbursement_cfg.get("buyer_name") or "").strip()
    if not expected:
        return ""

    actual = str(invoice.get("buyer_name") or "").strip()
    if not actual:
        return BUYER_MISSING_WARNING
    if _norm_text(actual) != _norm_text(expected):
        return BUYER_MISMATCH_WARNING
    return ""


def amount_total(rows: list[dict]) -> tuple[int, Decimal, bool]:
    """Return count, total amount, and whether any row has missing/invalid amount."""
    total = Decimal("0")
    has_missing = False
    for row in rows:
        raw = str(row.get("total_amount") or "").strip().replace(",", "")
        if not raw:
            has_missing = True
            continue
        try:
            total += Decimal(raw)
        except (InvalidOperation, ValueError):
            has_missing = True
    return len(rows), total, has_missing


def format_amount_total(rows: list[dict]) -> str:
    count, total, has_missing = amount_total(rows)
    suffix = "｜部分金额缺失" if has_missing else ""
    return f"{count} 张｜合计 ¥{total:.2f}{suffix}"
