"""Query parameters for the invoice review workspace."""

from __future__ import annotations

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


__all__ = ["ReviewColumnFilter", "ReviewQuery"]
