"""Query parameters for the invoice review workspace."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ReviewColumnFilter:
    key: str
    values: tuple[str, ...] | None = None
    quick: str = ""
    minimum: str = ""
    maximum: str = ""


@dataclass(frozen=True)
class ReviewQuery:
    status: str | None = None
    include_deleted: bool = False
    search_text: str = ""
    column_filters: tuple[ReviewColumnFilter, ...] = ()
    invoice_ids: tuple[int, ...] = ()
    limit: int = 50
    offset: int = 0
    today: date | None = None
    sort_key: str = ""
    sort_descending: bool = False


def recent_three_months_start(today: date) -> date:
    """Shift back three calendar months, clamping to the target month's end."""
    year, month_index = divmod(today.year * 12 + today.month - 4, 12)
    month = month_index + 1
    return date(year, month, min(today.day, monthrange(year, month)[1]))


__all__ = ["ReviewColumnFilter", "ReviewQuery", "recent_three_months_start"]
