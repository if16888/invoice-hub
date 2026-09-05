"""Atomic database reconciliation for successful invoice reparsing.

Parsing and classification stay outside the transaction.  This module owns only
the short SQLite mutation that reconciles one successfully parsed invoice with
an existing active duplicate, preserving the current survivor policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sqlite3

from .db import InvoiceDB

_log = logging.getLogger(__name__)

UPDATED_CURRENT = "updated_current"
REPLACED_UNLINKED_DUPLICATE = "replaced_unlinked_duplicate"
MERGED_INTO_CLAIMED_DUPLICATE = "merged_into_claimed_duplicate"


@dataclass(frozen=True)
class ReparseReconciliationResult:
    """Persisted outcome of one invoice-level reparse reconciliation."""

    success: bool
    action: str
    target_invoice_id: int
    duplicate_invoice_id: int | None = None
    error: str = ""


def _failure(
    db: InvoiceDB,
    current_invoice_id: int,
    error: str,
    *,
    target_invoice_id: int | None = None,
    duplicate_invoice_id: int | None = None,
) -> ReparseReconciliationResult:
    db._set_last_error(error)
    return ReparseReconciliationResult(
        success=False,
        action="",
        target_invoice_id=(
            current_invoice_id if target_invoice_id is None else target_invoice_id
        ),
        duplicate_invoice_id=duplicate_invoice_id,
        error=error,
    )


def reconcile_reparsed_invoice(
    db: InvoiceDB,
    current_invoice_id: int,
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
    parse_success: bool,
    parse_note: str,
    item_name: str = "",
    expense_date: str = "",
    date_source: str = "",
) -> ReparseReconciliationResult:
    """Apply one successful reparse as one SQLite transaction.

    The existing business policy is preserved:
    - no active duplicate: update the current invoice;
    - unlinked active duplicate: delete that older duplicate and keep current;
    - claim-linked active duplicate: update the linked master and soft-delete current.

    Every mutation for one invoice is committed together or rolled back together.
    The caller must perform parsing/filesystem work before entering this function.
    """

    if not expense_date:
        expense_date = invoice_date
    if not date_source:
        date_source = "invoice_date"

    current_invoice_id = int(current_invoice_id)
    lookup_number = str(invoice_number or "").strip()
    lookup_amount = str(total_amount or "").strip()
    lookup_seller = str(seller_name or "").strip()

    conn = db._conn
    if conn is None:
        return _failure(db, current_invoice_id, "db_closed")
    if conn.in_transaction:
        # Do not commit or roll back a transaction owned by an unrelated caller.
        return _failure(db, current_invoice_id, "transaction_busy")

    duplicate_invoice_id: int | None = None
    target_invoice_id = current_invoice_id
    action = UPDATED_CURRENT

    try:
        conn.execute("BEGIN IMMEDIATE")

        current = conn.execute(
            "SELECT id FROM invoices WHERE id = ? AND is_deleted = 0",
            (current_invoice_id,),
        ).fetchone()
        if current is None:
            conn.rollback()
            return _failure(db, current_invoice_id, "not_found")

        # Match the exact active-record lookup currently used by the GUI.  Empty
        # invoice numbers intentionally never participate in business dedup.
        if lookup_number:
            duplicate = conn.execute(
                "SELECT id FROM invoices "
                "WHERE invoice_number = ? AND total_amount = ? AND seller_name = ? "
                "AND is_deleted = 0 ORDER BY id DESC LIMIT 1",
                (lookup_number, lookup_amount, lookup_seller),
            ).fetchone()
            if duplicate is not None:
                candidate_id = int(duplicate["id"])
                if candidate_id != current_invoice_id:
                    duplicate_invoice_id = candidate_id

        if duplicate_invoice_id is not None:
            claim_count_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM claim_group_items WHERE invoice_id = ?",
                (duplicate_invoice_id,),
            ).fetchone()
            duplicate_claim_count = (
                int(claim_count_row["cnt"]) if claim_count_row is not None else 0
            )

            if duplicate_claim_count == 0:
                # Delete first so the existing SQLite uniqueness constraint does
                # not reject the current record's metadata update.  The delete is
                # still provisional until the final commit below.
                deleted = conn.execute(
                    "DELETE FROM invoices WHERE id = ? AND is_deleted = 0",
                    (duplicate_invoice_id,),
                )
                if deleted.rowcount != 1:
                    conn.rollback()
                    return _failure(
                        db,
                        current_invoice_id,
                        "transaction_conflict",
                        duplicate_invoice_id=duplicate_invoice_id,
                    )
                action = REPLACED_UNLINKED_DUPLICATE
            else:
                target_invoice_id = duplicate_invoice_id
                action = MERGED_INTO_CLAIMED_DUPLICATE

        updated = conn.execute(
            "UPDATE invoices SET invoice_number=?, invoice_code=?, invoice_date=?, "
            "expense_date=?, date_source=?, amount=?, total_amount=?, seller_name=?, "
            "buyer_name=?, invoice_type=?, category=?, has_extra=?, extra_type=?, "
            "missing_extra=?, parse_success=?, parse_note=?, item_name=? "
            "WHERE id=? AND is_deleted=0",
            (
                invoice_number,
                invoice_code,
                invoice_date,
                expense_date,
                date_source,
                amount,
                total_amount,
                seller_name,
                buyer_name,
                invoice_type,
                category,
                int(bool(has_extra)),
                extra_type,
                int(bool(missing_extra)),
                int(bool(parse_success)),
                parse_note,
                item_name,
                target_invoice_id,
            ),
        )
        if updated.rowcount != 1:
            conn.rollback()
            return _failure(
                db,
                current_invoice_id,
                "not_found",
                target_invoice_id=target_invoice_id,
                duplicate_invoice_id=duplicate_invoice_id,
            )

        if action == MERGED_INTO_CLAIMED_DUPLICATE:
            merged = conn.execute(
                "UPDATE invoices SET is_deleted = 1 "
                "WHERE id = ? AND is_deleted = 0",
                (current_invoice_id,),
            )
            if merged.rowcount != 1:
                conn.rollback()
                return _failure(
                    db,
                    current_invoice_id,
                    "transaction_conflict",
                    target_invoice_id=target_invoice_id,
                    duplicate_invoice_id=duplicate_invoice_id,
                )

        conn.commit()
        db._set_last_error("")
        return ReparseReconciliationResult(
            success=True,
            action=action,
            target_invoice_id=target_invoice_id,
            duplicate_invoice_id=duplicate_invoice_id,
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        error = (
            "unique_conflict"
            if "UNIQUE constraint failed" in str(exc)
            else "integrity_error"
        )
        _log.warning(
            "Reparse reconciliation rolled back after integrity failure: "
            "current_id=%s error=%s",
            current_invoice_id,
            error,
        )
        return _failure(
            db,
            current_invoice_id,
            error,
            target_invoice_id=target_invoice_id,
            duplicate_invoice_id=duplicate_invoice_id,
        )
    except sqlite3.Error:
        conn.rollback()
        _log.exception(
            "Reparse reconciliation rolled back after SQLite failure: current_id=%s",
            current_invoice_id,
        )
        return _failure(
            db,
            current_invoice_id,
            "db_error",
            target_invoice_id=target_invoice_id,
            duplicate_invoice_id=duplicate_invoice_id,
        )
    except Exception:
        conn.rollback()
        _log.exception(
            "Reparse reconciliation rolled back after unexpected failure: current_id=%s",
            current_invoice_id,
        )
        return _failure(
            db,
            current_invoice_id,
            "reparse_transaction_failed",
            target_invoice_id=target_invoice_id,
            duplicate_invoice_id=duplicate_invoice_id,
        )


__all__ = [
    "MERGED_INTO_CLAIMED_DUPLICATE",
    "REPLACED_UNLINKED_DUPLICATE",
    "UPDATED_CURRENT",
    "ReparseReconciliationResult",
    "reconcile_reparsed_invoice",
]
