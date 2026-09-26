"""Strict parsing helpers for user-entered and exported monetary amounts."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


_AMOUNT_PATTERN = re.compile(
    r"^[+-]?(?:(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d*)?|\.\d+)$"
)


def parse_amount(value) -> Decimal:
    """Parse a finite decimal amount, allowing only correctly grouped commas."""
    text = str(value or "").strip()
    if not text or not _AMOUNT_PATTERN.fullmatch(text):
        raise ValueError("金额格式无效。")
    try:
        amount = Decimal(text.replace(",", ""))
    except InvalidOperation:
        raise ValueError("金额格式无效。") from None
    if not amount.is_finite():
        raise ValueError("金额必须是有限数值。")
    try:
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError("金额最多保留两位小数。")
    except InvalidOperation:
        raise ValueError("金额精度无效。") from None
    return amount
