"""Task-oriented HCI services for bounded mailbox history re-checks.

This module deliberately stays Qt-free so the history re-check policy can be
unit-tested independently of the desktop UI.
"""

from __future__ import annotations

from pathlib import Path

from .config import load_config_safe
from .db import InvoiceDB


def _enabled_mailbox_keys(cfg: dict) -> list[str]:
    """Return stable mailbox keys for enabled accounts, preserving order."""
    keys: list[str] = []
    for account in list(cfg.get("email_accounts") or []):
        if not account.get("enabled", True):
            continue
        key = str(account.get("mailbox_key") or account.get("address") or "").strip()
        if key and key not in keys:
            keys.append(key)

    if not keys:
        legacy = cfg.get("email") or {}
        key = str(legacy.get("mailbox_key") or legacy.get("address") or "").strip()
        if key:
            keys.append(key)
    return keys


def recheck_known_email_history(
    db_path: str | Path,
    *,
    since: str,
    until: str | None = None,
    selected_keys: list[str] | None = None,
    only_downloaded: bool = False,
    limit: int = 200,
) -> dict:
    """Reprocess a bounded set of already-known email records.

    Safety properties:
    - never clears the global processed-email table;
    - never performs the destructive CLI ``--reset`` path;
    - skips approved and claimed invoices by default;
    - requires an explicit date lower bound;
    - limits the batch to a finite size.

    The existing reprocess engine owns download/dedup semantics. This wrapper
    only selects a bounded, user-understandable history range.
    """
    since = str(since or "").strip()
    until = str(until or "").strip() or None
    if not since:
        raise ValueError("重新检查必须指定起始日期")
    if int(limit) <= 0:
        raise ValueError("重新检查数量上限必须大于 0")

    cfg = load_config_safe()
    mailbox_keys = [
        str(value or "").strip()
        for value in (selected_keys or _enabled_mailbox_keys(cfg))
        if str(value or "").strip()
    ]
    mailbox_keys = list(dict.fromkeys(mailbox_keys))
    if not mailbox_keys:
        raise ValueError("没有可重新检查的已启用邮箱")

    from .__main__ import _reprocess_email_records

    remaining = int(limit)
    records: list[dict] = []
    seen: set[tuple[str, int]] = set()

    with InvoiceDB(Path(db_path)) as db:
        for mailbox_key in mailbox_keys:
            if remaining <= 0:
                break
            matches = db.find_emails_for_reprocess(
                mailbox_key=mailbox_key,
                since=since,
                until=until,
                only_downloaded=bool(only_downloaded),
                limit=remaining,
            )
            for record in matches:
                identity = (
                    str(record.get("mailbox_key") or mailbox_key),
                    int(record.get("uid") or 0),
                )
                if identity in seen:
                    continue
                seen.add(identity)
                records.append(record)
                remaining -= 1
                if remaining <= 0:
                    break

        if not records:
            return {
                "candidate_emails": 0,
                "processed_emails": 0,
                "before_invoices": 0,
                "after_invoices": 0,
                "added_or_restored": 0,
                "removed_or_replaced": 0,
                "limit_reached": False,
            }

        before_rows = db.get_all_invoices(include_deleted=True)
        before_ids = {int(row["id"]) for row in before_rows if row.get("id") is not None}

        _reprocess_email_records(
            db=db,
            cfg=cfg,
            records=records,
            include_approved=False,
            include_claimed=False,
            reclassify=False,
            dry_run=False,
        )

        after_rows = db.get_all_invoices(include_deleted=True)
        after_ids = {int(row["id"]) for row in after_rows if row.get("id") is not None}

    return {
        "candidate_emails": len(records),
        "processed_emails": len(records),
        "before_invoices": len(before_ids),
        "after_invoices": len(after_ids),
        "added_or_restored": len(after_ids - before_ids),
        "removed_or_replaced": len(before_ids - after_ids),
        "limit_reached": len(records) >= int(limit),
    }


__all__ = ["_enabled_mailbox_keys", "recheck_known_email_history"]
