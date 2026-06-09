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


def _is_railway_or_travel_ticket(invoice: dict) -> bool:
    inv_type = str(invoice.get("invoice_type") or "").strip()
    seller_name = str(invoice.get("seller_name") or "").strip()
    category = str(invoice.get("category") or "").strip()

    # 1. 铁路电子客票
    if inv_type == "铁路电子客票" or seller_name == "中国国家铁路集团有限公司":
        return True
    if "铁路" in inv_type or "铁路" in seller_name:
        return True
    if "12306" in inv_type or "12306" in seller_name:
        return True

    # 2. 交通类且 seller_name/票据类型明显属于行程票据
    is_transport = category in ("交通", "过路费") or "交通" in category
    if is_transport:
        travel_kws = [
            "客运", "客运站", "地铁", "公交", "出租车", "打车", "滴滴", "出行",
            "机票", "车票", "船票", "客票", "过路", "高速", "公路", "大卡",
            "强生", "航旅", "航空", "捷运", "轨道交通", "运输"
        ]
        if any(kw in seller_name for kw in travel_kws):
            return True
        if any(kw in inv_type for kw in travel_kws):
            return True

    return False


def get_date_warning(invoice: dict) -> str:
    """Return a low-priority warning if expense date defaults to invoice date."""
    if not _is_railway_or_travel_ticket(invoice):
        return ""
    expense_date = str(invoice.get("expense_date") or "").strip()
    date_source = str(invoice.get("date_source") or "").strip()
    if expense_date and date_source in ("invoice_date", "legacy", "unknown", ""):
        return "未识别到费用发生日期，已使用开票日期。"
    return ""
