"""SQLite database — invoice records and processed-email tracking."""

from __future__ import annotations

import json
import logging
import sqlite3
import re
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import review_status
from .log_privacy import mask_invoice_number
from .review_query import ReviewColumnFilter, ReviewQuery
from .evidence import (
    EvidenceStoreMixin, is_evidence_record, material_paths,
    refresh_material_projection, replace_material_paths, visible_invoice_sql,
)

_log = logging.getLogger(__name__)

SQLITE_BUSY_TIMEOUT_MS = 5_000
SQLITE_CONNECT_TIMEOUT_SECONDS = SQLITE_BUSY_TIMEOUT_MS / 1_000

_REVIEW_FILTER_KEYS = {
    "status", "expense_date", "total_amount", "invoice_number",
    "seller_name", "category", "source", "claim_name", "review_status",
    "missing_extra", "buyer_warning",
}


def _review_amount_compare(value: object, boundary: object, direction: int) -> int:
    try:
        amount = Decimal(str(value or "").strip().replace(",", ""))
        target = Decimal(str(boundary or "").strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return 0
    return int(amount >= target if direction > 0 else amount <= target)


def _review_amount_is_valid(value: object) -> int:
    try:
        Decimal(str(value or "").strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return 0
    return 1


def _review_text_contains(value: object, needle: object) -> int:
    return int(str(needle or "").lower() in str(value or "").lower())


def _configure_journal_mode(conn: sqlite3.Connection) -> str:
    """Prefer WAL, but keep the database usable on unsupported filesystems."""
    try:
        row = conn.execute("PRAGMA journal_mode = WAL").fetchone()
        mode = str(row[0] if row else "unknown").lower()
    except sqlite3.Error:
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            mode = str(row[0] if row else "unknown").lower()
        except sqlite3.Error:
            mode = "unknown"
        _log.warning(
            "无法启用 SQLite WAL 模式，继续使用兼容模式: journal_mode=%s",
            mode,
        )
        return mode
    if mode != "wal":
        _log.warning(
            "SQLite WAL 模式不可用，继续使用兼容模式: journal_mode=%s",
            mode,
        )
    return mode


def is_pending_evidence_invoice(invoice: dict) -> bool:
    """Compatibility guard: evidence is never an approvable financial invoice."""
    return is_evidence_record(invoice)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_key     TEXT NOT NULL DEFAULT 'legacy',
    invoice_number  TEXT,
    invoice_code    TEXT,
    invoice_date    TEXT,
    expense_date    TEXT,
    date_source     TEXT,
    amount          TEXT,
    total_amount    TEXT,
    seller_name     TEXT,
    buyer_name      TEXT,
    invoice_type    TEXT,
    category        TEXT DEFAULT '其他',
    has_extra       INTEGER DEFAULT 0,
    extra_type      TEXT DEFAULT '',
    missing_extra   INTEGER DEFAULT 0,
    mail_uid        INTEGER,
    mail_subject    TEXT,
    mail_date       TEXT,
    mail_sender     TEXT,
    parse_success   INTEGER DEFAULT 0,
    parse_note      TEXT DEFAULT '',
    attachment_path TEXT DEFAULT '',
    extra_paths     TEXT DEFAULT '[]',
    download_url    TEXT DEFAULT '',
    item_name       TEXT DEFAULT '',
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(invoice_number, total_amount, seller_name)
);

CREATE TABLE IF NOT EXISTS emails (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_key     TEXT NOT NULL DEFAULT 'legacy',
    uid             INTEGER NOT NULL,
    subject         TEXT NOT NULL DEFAULT '',
    sender          TEXT NOT NULL DEFAULT '',
    mail_date       TEXT NOT NULL DEFAULT '',
    is_invoice      INTEGER NOT NULL DEFAULT -1,
    classify_by     TEXT NOT NULL DEFAULT '',
    classify_reason TEXT NOT NULL DEFAULT '',
    downloaded      INTEGER NOT NULL DEFAULT 0,
    scanned_at      TEXT DEFAULT (datetime('now','localtime')),
    processed_at    TEXT,
    UNIQUE(mailbox_key, uid)
);

CREATE TABLE IF NOT EXISTS processed_emails (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_key  TEXT NOT NULL DEFAULT 'legacy',
    uid          INTEGER NOT NULL,
    subject      TEXT,
    sender       TEXT,
    mail_date    TEXT,
    processed_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(mailbox_key, uid)
);

CREATE TABLE IF NOT EXISTS trusted_senders (
    sender       TEXT PRIMARY KEY,
    added_at     TEXT DEFAULT (datetime('now','localtime'))
);
"""


class InvoiceDB(EvidenceStoreMixin):
    """Thin wrapper around a SQLite database for invoice records."""

    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Keep SQLite's default thread ownership.  Worker code must use its own
        # InvoiceDB instance rather than sharing this connection across threads.
        self._conn = sqlite3.connect(
            str(self._path),
            timeout=SQLITE_CONNECT_TIMEOUT_SECONDS,
        )
        self._conn.row_factory = sqlite3.Row
        self._buyer_warning_checker = None
        self._conn.create_function(
            "review_buyer_has_warning", 3, self._eval_buyer_warning, deterministic=False
        )
        self._conn.create_function(
            "review_amount_at_least", 2,
            lambda value, boundary: _review_amount_compare(value, boundary, 1),
            deterministic=True,
        )
        self._conn.create_function(
            "review_amount_at_most", 2,
            lambda value, boundary: _review_amount_compare(value, boundary, -1),
            deterministic=True,
        )
        self._conn.create_function(
            "review_text_contains", 2, _review_text_contains, deterministic=True,
        )
        self._conn.create_function(
            "review_amount_is_valid", 1, _review_amount_is_valid, deterministic=True,
        )
        self._conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        _configure_journal_mode(self._conn)
        self.last_error = ""
        self._conn.executescript(_SCHEMA)
        _log.debug("数据库已打开: %s", self._path.name)

        # Run database migrations
        from .migrations import check_and_migrate
        check_and_migrate(self._conn)
        self._conn.execute("PRAGMA foreign_keys = ON")


    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def is_open(self) -> bool:
        """Return True if the database connection is open and active."""
        return self._conn is not None

    def set_buyer_warning_checker(self, checker) -> None:
        """Register an in-memory predicate Callable[[dict], bool] to evaluate buyer warnings."""
        self._buyer_warning_checker = checker

    def _eval_buyer_warning(self, buyer_name: object, buyer_tax_id: object = None, buyer_tax_id_type: object = "unknown") -> int:
        checker = getattr(self, "_buyer_warning_checker", None)
        if callable(checker):
            try:
                return 1 if checker({"buyer_name": str(buyer_name or ""), "buyer_tax_id": buyer_tax_id, "buyer_tax_id_type": buyer_tax_id_type}) else 0
            except Exception:
                return 0
        return 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @staticmethod
    def _normalize_mailbox_key(mailbox_key: str | None = None) -> str:
        value = str(mailbox_key or "legacy").strip()
        return value or "legacy"

    def _set_last_error(self, code: str = "") -> None:
        self.last_error = code or ""

    def invoice_lock_reason(self, invoice_id: int) -> str:
        """Return why an invoice is immutable, or an empty string when editable."""
        row = self._conn.execute(
            "SELECT i.reimbursed_at, EXISTS(SELECT 1 FROM claim_group_items cgi "
            "JOIN claim_groups c ON c.id=cgi.claim_id WHERE cgi.invoice_id=i.id "
            "AND c.status IN ('exported','reimbursed')) OR EXISTS("
            "SELECT 1 FROM invoice_evidence_relations r "
            "JOIN claim_group_items cgi ON cgi.invoice_id=r.invoice_id "
            "JOIN claim_groups c ON c.id=cgi.claim_id WHERE r.evidence_id=i.id "
            "AND c.status IN ('exported','reimbursed')) AS claim_locked "
            "FROM invoices i WHERE i.id=?",
            (int(invoice_id),),
        ).fetchone()
        if not row:
            return "not_found"
        if row["reimbursed_at"]:
            return "invoice_reimbursed"
        if row["claim_locked"]:
            return "invoice_exported_locked"
        return ""

    def is_claim_editable(self, claim_id: int) -> bool:
        claim = self.get_claim_group(int(claim_id))
        return bool(claim and claim.get("status", "draft") == "draft")

    def _require_invoice_editable(self, invoice_id: int) -> bool:
        reason = self.invoice_lock_reason(invoice_id)
        if reason:
            self._set_last_error(reason)
            return False
        self._set_last_error("")
        return True

    # ── Emails table (Phase 1: scan & classify) ──────────────────────

    def upsert_email(self, uid: int, subject: str,
                     sender: str, mail_date: str, mailbox_key: str = "legacy") -> bool:
        """Insert a scanned email header. Returns True if new."""
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        try:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO emails (mailbox_key, uid, subject, sender, mail_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (mailbox_key, uid, subject, sender, mail_date),
            )
            self._conn.commit()
            return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            self._conn.rollback()
            return False

    def bulk_upsert_emails(self, rows: list[dict], mailbox_key: str = "legacy") -> int:
        """Batch insert scanned headers. Returns count of new rows."""
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        values = [
            (mailbox_key, r["uid"], r["subject"], r["sender"], r["date"])
            for r in rows
        ]
        before = self._conn.total_changes
        self._conn.executemany(
            "INSERT OR IGNORE INTO emails "
            "(mailbox_key, uid, subject, sender, mail_date) "
            "VALUES (?, ?, ?, ?, ?)",
            values,
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def get_all_email_uids(self, mailbox_key: str | None = None) -> set[int]:
        """Return all known UIDs in the emails table."""
        if mailbox_key is None:
            rows = self._conn.execute("SELECT uid FROM emails").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT uid FROM emails WHERE mailbox_key = ?",
                (self._normalize_mailbox_key(mailbox_key),),
            ).fetchall()
        return {r[0] for r in rows}

    def get_unclassified_emails(self, mailbox_key: str | None = None) -> list[dict]:
        """Return emails where is_invoice = -1 (unknown)."""
        if mailbox_key is None:
            rows = self._conn.execute(
                "SELECT mailbox_key, uid, subject, sender, mail_date "
                "FROM emails WHERE is_invoice = -1"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT mailbox_key, uid, subject, sender, mail_date "
                "FROM emails WHERE is_invoice = -1 AND mailbox_key = ?",
                (self._normalize_mailbox_key(mailbox_key),),
            ).fetchall()
        return [dict(r) for r in rows]

    def classify_email(self, uid: int, is_invoice: bool,
                       by: str, reason: str = "", mailbox_key: str = "legacy"):
        """Set classification result for a single email."""
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        self._conn.execute(
            "UPDATE emails SET is_invoice = ?, classify_by = ?, "
            "classify_reason = ? WHERE mailbox_key = ? AND uid = ?",
            (1 if is_invoice else 0, by, reason, mailbox_key, uid),
        )
        self._conn.commit()

    def bulk_classify(self, results: list[dict], mailbox_key: str = "legacy"):
        """Batch update classification results.

        Each dict: {uid, is_invoice (bool), by (str), reason (str)}
        """
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        values = [
            (
                1 if r["is_invoice"] else 0,
                r.get("by", ""),
                r.get("reason", ""),
                self._normalize_mailbox_key(r.get("mailbox_key", mailbox_key)),
                r["uid"],
            )
            for r in results
        ]
        self._conn.executemany(
            "UPDATE emails SET is_invoice = ?, classify_by = ?, "
            "classify_reason = ? WHERE mailbox_key = ? AND uid = ?",
            values,
        )
        self._conn.commit()

    def get_invoice_emails_to_download(
        self,
        mailbox_key: str | None = None,
        *,
        bypass_cooldown: bool = False,
    ) -> list[dict]:
        """Return emails marked as invoice but not yet downloaded."""
        cooldown_clause = ""
        if not bypass_cooldown:
            cooldown_clause = """
                AND NOT EXISTS (
                    SELECT 1
                    FROM email_download_failures f
                    WHERE f.mailbox_key = emails.mailbox_key
                      AND f.uid = emails.uid
                      AND (
                          f.reason_code = 'no_candidate_link'
                          OR COALESCE(f.next_retry_at, '') > datetime('now', 'localtime')
                      )
                )
            """
        if mailbox_key is None:
            rows = self._conn.execute(
                "SELECT mailbox_key, uid, subject, sender, mail_date "
                "FROM emails WHERE is_invoice = 1 AND downloaded = 0 "
                f"{cooldown_clause} "
                "ORDER BY mail_date DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT mailbox_key, uid, subject, sender, mail_date "
                "FROM emails WHERE is_invoice = 1 AND downloaded = 0 AND mailbox_key = ? "
                f"{cooldown_clause} "
                "ORDER BY mail_date DESC",
                (self._normalize_mailbox_key(mailbox_key),),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_email_download_failure(
        self,
        mailbox_key: str,
        uid: int,
        reason_code: str,
        error_summary: str = "",
    ) -> None:
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        row = self._conn.execute(
            "SELECT fail_count FROM email_download_failures "
            "WHERE mailbox_key = ? AND uid = ?",
            (mailbox_key, uid),
        ).fetchone()
        fail_count = int(row["fail_count"] if row else 0) + 1
        if reason_code == "no_candidate_link":
            next_retry_at = None
        else:
            hours = 1 if fail_count == 1 else 6 if fail_count == 2 else 24
            next_retry_at = (
                datetime.now() + timedelta(hours=hours)
            ).strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute(
            """
            INSERT INTO email_download_failures (
                mailbox_key, uid, reason_code, fail_count, next_retry_at,
                last_error_at, last_error_summary
            ) VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'), ?)
            ON CONFLICT(mailbox_key, uid) DO UPDATE SET
                reason_code = excluded.reason_code,
                fail_count = excluded.fail_count,
                next_retry_at = excluded.next_retry_at,
                last_error_at = excluded.last_error_at,
                last_error_summary = excluded.last_error_summary
            """,
            (
                mailbox_key,
                uid,
                reason_code,
                fail_count,
                next_retry_at,
                str(error_summary or "")[:500],
            ),
        )
        self._conn.commit()

    def clear_email_download_failure(self, mailbox_key: str, uid: int) -> None:
        self._conn.execute(
            "DELETE FROM email_download_failures WHERE mailbox_key = ? AND uid = ?",
            (self._normalize_mailbox_key(mailbox_key), uid),
        )
        self._conn.commit()

    def mark_downloaded(self, uid: int, mailbox_key: str = "legacy"):
        """Mark an email as downloaded/processed."""
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        self._conn.execute(
            "UPDATE emails SET downloaded = 1, "
            "processed_at = datetime('now','localtime') WHERE mailbox_key = ? AND uid = ?",
            (mailbox_key, uid),
        )
        self._conn.commit()

    @staticmethod
    def _extract_email(sender: str) -> str:
        if not sender:
            return ""
        m = re.search(r'<([^>]+)>', sender)
        if m:
            return m.group(1).lower()
        m = re.search(r'([\w\.-]+@[\w\.-]+)', sender)
        return m.group(1).lower() if m else sender.lower().strip()

    def is_trusted_sender(self, sender: str) -> bool:
        """Check if a sender is whitelisted as always sending invoices."""
        pure_email = self._extract_email(sender)
        if not pure_email:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM trusted_senders WHERE sender = ?", (pure_email,)
        ).fetchone()
        return row is not None

    def add_trusted_sender(self, sender: str):
        """Whitelist a sender."""
        pure_email = self._extract_email(sender)
        if not pure_email:
            return
        self._conn.execute(
            "INSERT OR IGNORE INTO trusted_senders (sender) VALUES (?)",
            (pure_email,)
        )
        self._conn.commit()

    def get_email_stats(self) -> dict:
        """Return classification/download statistics."""
        row = self._conn.execute("""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN is_invoice = 1 THEN 1 ELSE 0 END), 0) AS invoice,
                COALESCE(SUM(CASE WHEN is_invoice = 0 THEN 1 ELSE 0 END), 0) AS not_invoice,
                COALESCE(SUM(CASE WHEN is_invoice = -1 THEN 1 ELSE 0 END), 0) AS unclassified,
                COALESCE(SUM(CASE WHEN downloaded = 1 THEN 1 ELSE 0 END), 0) AS downloaded,
                COALESCE(SUM(CASE WHEN is_invoice = 1 AND downloaded = 0 THEN 1 ELSE 0 END), 0) AS pending
            FROM emails
        """).fetchone()
        return dict(row)

    # ── Legacy processed emails ──────────────────────────────────────

    def is_email_processed(self, uid: int, mailbox_key: str = "legacy") -> bool:
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        row = self._conn.execute(
            "SELECT 1 FROM processed_emails WHERE mailbox_key = ? AND uid = ?",
            (mailbox_key, uid)
        ).fetchone()
        return row is not None

    def get_processed_uids(self, mailbox_key: str | None = None) -> set[int]:
        if mailbox_key is None:
            rows = self._conn.execute("SELECT uid FROM processed_emails").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT uid FROM processed_emails WHERE mailbox_key = ?",
                (self._normalize_mailbox_key(mailbox_key),),
            ).fetchall()
        return {r[0] for r in rows}

    def mark_email_processed(self, uid: int, subject: str = "",
                             sender: str = "", mail_date: str = "", mailbox_key: str = "legacy"):
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_emails (mailbox_key, uid, subject, sender, mail_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (mailbox_key, uid, subject, sender, mail_date),
        )
        self._conn.commit()

    # ── Invoice dedup ────────────────────────────────────────────────

    def is_duplicate(self, invoice_number: str,
                     total_amount: str = "", seller_name: str = "", include_deleted: bool = False) -> bool:
        """Check duplicate status only when invoice number identity is available."""
        invoice_number = (invoice_number or "").strip()
        total_amount = (total_amount or "").strip()
        seller_name = (seller_name or "").strip()

        cond = "" if include_deleted else " AND is_deleted = 0"

        # Seller + amount is not a stable invoice identity: recurring invoices
        # from the same seller can legitimately share that pair.  Records with
        # no invoice number are intentionally allowed to coexist; exact-file
        # deduplication remains handled by the file-hash path.
        if not invoice_number:
            return False

        row = self._conn.execute(
            f"SELECT 1 FROM invoices WHERE invoice_number = ? AND total_amount = ?{cond}",
            (invoice_number, total_amount),
        ).fetchone()
        return row is not None

    # ── Insert ───────────────────────────────────────────────────────

    def insert_invoice(self, rec: dict[str, Any]) -> int | None:
        """Insert an invoice record.  Returns the row id, or None on dup."""
        rec = dict(rec)
        rec["record_role"] = "evidence" if is_evidence_record(rec) else "invoice"
        rec.setdefault("evidence_required", int(bool(rec.get("missing_extra") or rec.get("extra_type"))))
        if "invoice_date" in rec and "expense_date" not in rec:
            rec = dict(rec)
            rec["expense_date"] = rec["invoice_date"]
            if "date_source" not in rec:
                rec["date_source"] = "invoice_date"

        if rec.get("parse_success") in (True, 1, "1") and not is_pending_evidence_invoice(rec):
            rec = dict(rec)
            if rec.get("category_source") != "manual":
                rec["category"], rec["category_source"] = self.resolve_parsed_category(
                    rec.get("seller_name", ""), rec.get("category", "其他")
                )

        allowed_cols = {
            "mailbox_key",
            "invoice_number", "invoice_code", "invoice_date",
            "amount", "total_amount", "seller_name", "buyer_name",
            "invoice_type", "category", "category_source", "record_role", "evidence_required", "has_extra", "extra_type",
            "missing_extra", "mail_uid", "mail_subject", "mail_date",
            "mail_sender", "parse_success", "parse_note",
            "attachment_path", "extra_paths", "download_url", "item_name",
            "review_status", "processing_status", "currency", "exchange_rate",
            "amount_home", "file_hash", "confirmed_at", "confirmed_note", "is_deleted",
            "expense_date", "date_source", "custom_reason", "buyer_tax_id", "buyer_tax_id_type", "tax_amount", "tax_rate",
        }

        # Dynamically build the SQL statement containing only keys that are explicitly provided.
        # This allows SQLite's default schema values (like DEFAULT 'to_review') to be applied.
        insert_rec = {}
        for c in allowed_cols:
            if c in rec:
                v = rec[c]
                if c == "extra_paths" and isinstance(v, list):
                    v = json.dumps(v, ensure_ascii=False)
                elif isinstance(v, bool):
                    v = int(v)

                # Use None (NULL) for empty invoice_number to bypass UNIQUE constraint for non-standard receipts
                if c == "invoice_number" and not v:
                    v = None
                insert_rec[c] = v

        if not insert_rec:
            return None

        cols = sorted(insert_rec.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)
        vals = [insert_rec[c] for c in cols]

        try:
            with self._atomic_savepoint():
                cur = self._conn.execute(
                    f"INSERT INTO invoices ({col_names}) VALUES ({placeholders})", vals,
                )
                invoice_id = cur.lastrowid
                if material_paths(rec.get("extra_paths")) and rec["record_role"] == "invoice":
                    replace_material_paths(self._conn, invoice_id, rec["extra_paths"])
            return invoice_id
        except sqlite3.IntegrityError:
            _log.info("重复发票(DB约束): %s", mask_invoice_number(rec.get("invoice_number", "")))
            return None

    # ── Query ────────────────────────────────────────────────────────

    def get_all_invoices(self, include_deleted: bool = False) -> list[dict]:
        sql = "SELECT i.* FROM invoices i WHERE " + visible_invoice_sql()
        if not include_deleted:
            sql += " AND i.is_deleted=0"
        rows = self._conn.execute(sql + " ORDER BY i.expense_date DESC, i.id DESC").fetchall()
        return [dict(r) for r in rows]

    def get_invoice(self, invoice_id: int, include_deleted: bool = False) -> dict | None:
        """Fetch a single invoice record by ID."""
        sql = "SELECT * FROM invoices WHERE id = ?"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        row = self._conn.execute(sql, (invoice_id,)).fetchone()
        return self._with_evidence(dict(row)) if row else None

    def find_invoice_by_number_and_amount(self, invoice_number: str, total_amount: str = "", include_deleted: bool = False) -> dict | None:
        """Find the most recent invoice with the same invoice number and amount."""
        if not invoice_number:
            return None
        sql = "SELECT * FROM invoices WHERE invoice_number = ? AND total_amount = ?"
        sql += " AND record_role='invoice' AND COALESCE(invoice_type,'')!='待关联证明材料'"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        sql += " ORDER BY id DESC LIMIT 1"
        row = self._conn.execute(sql, (invoice_number, total_amount)).fetchone()
        return dict(row) if row else None

    def find_invoice_by_number(self, invoice_number: str, include_deleted: bool = False) -> dict | None:
        """Find the most recent invoice with the same invoice number."""
        if not invoice_number:
            return None
        sql = "SELECT * FROM invoices WHERE invoice_number = ?"
        sql += " AND record_role='invoice' AND COALESCE(invoice_type,'')!='待关联证明材料'"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        sql += " ORDER BY id DESC LIMIT 1"
        row = self._conn.execute(sql, (invoice_number,)).fetchone()
        return dict(row) if row else None

    def find_invoice_by_seller_and_amount(self, seller_name: str, total_amount: str = "", include_deleted: bool = False) -> dict | None:
        """Find the most recent invoice with the same seller and amount."""
        seller_name = (seller_name or "").strip()
        total_amount = (total_amount or "").strip()
        if not seller_name or not total_amount:
            return None
        sql = "SELECT * FROM invoices WHERE seller_name = ? AND total_amount = ?"
        sql += " AND record_role='invoice' AND COALESCE(invoice_type,'')!='待关联证明材料'"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        sql += " ORDER BY id DESC LIMIT 1"
        row = self._conn.execute(sql, (seller_name, total_amount)).fetchone()
        return dict(row) if row else None

    def find_invoice_by_file_hash(self, file_hash: str, include_deleted: bool = False) -> dict | None:
        """Find the most recent invoice imported from the same file content."""
        file_hash = (file_hash or "").strip()
        if not file_hash:
            return None
        sql = "SELECT * FROM invoices WHERE file_hash = ?"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        sql += " ORDER BY id DESC LIMIT 1"
        row = self._conn.execute(sql, (file_hash,)).fetchone()
        return dict(row) if row else None

    def restore_deleted_invoices_by_file_hashes(self, file_hashes: set[str]) -> list[int]:
        """Restore soft-deleted invoices matching any supplied file hash."""
        normalized = {str(value or "").strip() for value in file_hashes}
        normalized.discard("")
        if not normalized:
            return []

        placeholders = ", ".join("?" for _ in normalized)
        rows = self._conn.execute(
            f"SELECT id, file_hash FROM invoices "
            f"WHERE is_deleted = 1 AND reimbursed_at IS NULL "
            f"AND file_hash IN ({placeholders}) AND NOT EXISTS ("
            "SELECT 1 FROM claim_group_items cgi JOIN claim_groups c ON c.id=cgi.claim_id "
            "WHERE cgi.invoice_id=invoices.id AND c.status IN ('exported','reimbursed'))",
            tuple(sorted(normalized)),
        ).fetchall()
        if not rows:
            return []

        invoice_ids = [int(row["id"]) for row in rows]
        id_placeholders = ", ".join("?" for _ in invoice_ids)
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(invoices)").fetchall()
        }
        assignments = "is_deleted = 0"
        if "updated_at" in columns:
            assignments += ", updated_at = CURRENT_TIMESTAMP"
        with self._atomic_savepoint():
            self._conn.execute(
                f"UPDATE invoices SET {assignments} WHERE id IN ({id_placeholders})", tuple(invoice_ids),
            )
            for invoice_id in invoice_ids:
                self._refresh_evidence_consumers(invoice_id)
        return invoice_ids

    def find_receipt_by_source(
        self,
        mailbox_key: str,
        mail_uid: int,
        filename_hint: str = "",
        include_deleted: bool = False,
    ) -> dict | None:
        """Find a receipt-like invoice by mailbox source metadata."""
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        if not mailbox_key or mail_uid is None:
            return None

        hint = Path(filename_hint or "").stem
        hint = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in hint).strip("_")
        if len(hint) > 40:
            hint = hint[:40]

        sql = (
            "SELECT * FROM invoices WHERE mailbox_key = ? AND mail_uid = ? "
            "AND invoice_type = ?"
        )
        params: list[Any] = [mailbox_key, int(mail_uid), "海外凭证/收据"]
        if hint:
            sql += " AND attachment_path LIKE ?"
            params.append(f"%{hint}%")
        if not include_deleted:
            sql += " AND is_deleted = 0"
        sql += " ORDER BY id DESC LIMIT 1"
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def find_invoice_by_unique_fields(
        self,
        invoice_number: str,
        total_amount: str = "",
        seller_name: str = "",
        include_deleted: bool = False,
    ) -> dict | None:
        """Find an invoice with the exact unique key used by the table constraint."""
        invoice_number = (invoice_number or "").strip()
        total_amount = (total_amount or "").strip()
        seller_name = (seller_name or "").strip()
        if not invoice_number:
            return None

        sql = "SELECT * FROM invoices WHERE invoice_number = ? AND total_amount = ? AND seller_name = ?"
        sql += " AND record_role='invoice' AND COALESCE(invoice_type,'')!='待关联证明材料'"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        sql += " ORDER BY id DESC LIMIT 1"
        row = self._conn.execute(sql, (invoice_number, total_amount, seller_name)).fetchone()
        return dict(row) if row else None

    def count_claim_links(self, invoice_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM claim_group_items WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def soft_delete_invoice(self, invoice_id: int) -> bool:
        """Soft delete an invoice by setting is_deleted = 1."""
        if not self._require_invoice_editable(invoice_id):
            return False
        row = self._conn.execute("SELECT 1 FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            return False
        with self._atomic_savepoint():
            self._conn.execute("UPDATE invoices SET is_deleted = 1 WHERE id = ?", (invoice_id,))
            self._refresh_evidence_consumers(invoice_id)
        return True

    def delete_invoice_permanently(self, invoice_id: int) -> bool:
        """Delete an invoice row entirely."""
        if not self._require_invoice_editable(invoice_id):
            return False
        row = self._conn.execute("SELECT 1 FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            return False
        with self._atomic_savepoint():
            self._conn.execute("UPDATE invoices SET id=id WHERE 0")
            if self.evidence_consumers(invoice_id):
                self._set_last_error("evidence_in_use")
                return False
            self._conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
        return True

    def restore_invoice(self, invoice_id: int) -> bool:
        """Restore a soft-deleted invoice by setting is_deleted = 0."""
        if not self._require_invoice_editable(invoice_id):
            return False
        row = self._conn.execute("SELECT 1 FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            return False
        with self._atomic_savepoint():
            self._conn.execute("UPDATE invoices SET is_deleted = 0 WHERE id = ?", (invoice_id,))
            self._refresh_evidence_consumers(invoice_id)
        return True


    @staticmethod
    def _seller_preference_key(seller_name: str) -> str:
        # Match complete names only; retain internal spaces, punctuation and case.
        return unicodedata.normalize("NFC", str(seller_name or "").strip())

    def get_seller_category(self, seller_name: str) -> str:
        key = self._seller_preference_key(seller_name)
        if not key:
            return ""
        row = self._conn.execute(
            "SELECT preferred_category FROM seller_category_preferences WHERE seller_name=?",
            (key,),
        ).fetchone()
        return str(row[0]) if row else ""

    def list_seller_category_preferences(self) -> list[dict]:
        return [dict(row) for row in self._conn.execute(
            "SELECT seller_name, preferred_category, updated_at "
            "FROM seller_category_preferences ORDER BY seller_name"
        )]

    def forget_seller_categories(self, seller_names) -> int:
        keys = tuple(dict.fromkeys(self._seller_preference_key(name) for name in seller_names))
        with self._atomic_savepoint():
            cursor = self._conn.executemany(
                "DELETE FROM seller_category_preferences WHERE seller_name=?",
                [(key,) for key in keys if key],
            )
            return cursor.rowcount

    def _remember_seller_category(self, seller_name: str, category: str) -> None:
        self._conn.execute(
            "INSERT INTO seller_category_preferences (seller_name, preferred_category, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(seller_name) DO UPDATE SET "
            "preferred_category=excluded.preferred_category, updated_at=excluded.updated_at",
            (self._seller_preference_key(seller_name), category,
             datetime.now().isoformat(timespec="microseconds")),
        )

    def resolve_parsed_category(
        self, seller_name: str, category: str, *, existing: dict | None = None,
        use_seller_preference: bool = True,
        preserve_finalized: bool = True,
    ) -> tuple[str, str]:
        """Preserve explicit choices; prefer learned labels for automatic classification."""
        if existing and (existing.get("category_source") == "manual"
                         or (preserve_finalized and (existing.get("review_status") == review_status.APPROVED
                                                    or self.count_claim_links(existing["id"]) > 0))):
            return str(existing.get("category") or ""), str(existing.get("category_source") or "unknown")
        if use_seller_preference:
            preferred = self.get_seller_category(seller_name)
            if preferred:
                return preferred, "seller_preference"
        if existing and not use_seller_preference and category == existing.get("category"):
            return category, str(existing.get("category_source") or "unknown")
        return category, "rule"

    def list_categories(self) -> list[str]:
        """Return distinct non-empty invoice categories already used in the database."""
        rows = self._conn.execute(
            "SELECT DISTINCT category FROM (SELECT category FROM invoices "
            "UNION SELECT preferred_category AS category FROM seller_category_preferences) "
            "WHERE TRIM(COALESCE(category, '')) != '' "
            "ORDER BY category COLLATE NOCASE"
        ).fetchall()
        return [str(row["category"]) for row in rows]

    def update_invoice_review_status(self, invoice_id: int, status: str, note: str = "") -> bool:
        """Update the review status of an invoice.

        Raises ValueError if the status is invalid.
        Returns False if the invoice_id does not exist.
        """
        if status not in review_status.ALL_STATUSES:
            raise ValueError(f"Invalid review status: '{status}'. Must be one of {review_status.ALL_STATUSES}")

        # Check existence
        inv = self.get_invoice(invoice_id)
        if not inv:
            self._set_last_error("not_found")
            return False
        if not self._require_invoice_editable(invoice_id):
            return False

        if status == review_status.APPROVED and is_pending_evidence_invoice(inv):
            self._set_last_error("evidence_only")
            return False

        if status == review_status.TO_REVIEW:
            confirmed_at = ""
        else:
            confirmed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self._conn.execute(
            "UPDATE invoices SET review_status = ?, confirmed_note = ?, confirmed_at = ? WHERE id = ?",
            (status, note, confirmed_at, invoice_id)
        )
        self._conn.commit()
        self._set_last_error("")
        return True

    @contextmanager
    def _atomic_savepoint(self):
        """Keep nested domain operations from committing their caller's writes."""
        name = "invoice_hub_" + uuid4().hex
        self._conn.execute(f"SAVEPOINT {name}")
        try:
            yield
            self._conn.execute(f"RELEASE {name}")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute(f"ROLLBACK TO {name}")
                self._conn.execute(f"RELEASE {name}")
            raise

    @contextmanager
    def batch_review_transaction(self):
        """Reserve the SQLite writer before rechecking and approving a batch."""
        if self._conn.in_transaction:
            raise RuntimeError("Batch review requires a connection without pending writes")
        with self._atomic_savepoint():
            self._conn.execute("UPDATE invoices SET id=id WHERE 0")
            yield

    def apply_review_batch_status(self, invoice_ids: tuple[int, ...], status: str) -> None:
        """Apply validated batch changes inside a transaction, preserving notes."""
        if status not in {review_status.APPROVED, review_status.IGNORED}:
            raise ValueError("Unsupported batch review status")
        if not self._conn.in_transaction:
            raise RuntimeError("Batch review changes require a transaction")
        if any(self.invoice_lock_reason(invoice_id) for invoice_id in invoice_ids):
            raise RuntimeError("已导出或已报销的发票不能修改审核状态")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pending_sql = " AND review_status=?" if status == review_status.APPROVED else ""
        cursor = self._conn.executemany(
            "UPDATE invoices SET review_status=?, confirmed_at=? "
            "WHERE id=? AND is_deleted=0" + pending_sql,
            [(status, stamp, invoice_id) + ((review_status.TO_REVIEW,) if pending_sql else ())
             for invoice_id in invoice_ids],
        )
        if cursor.rowcount != len(invoice_ids):
            raise RuntimeError("Review records changed during batch approval")

    def update_invoice_note(self, invoice_id: int, note: str) -> bool:
        """Persist a note without rewriting parsed or edited financial fields."""
        if not self._require_invoice_editable(invoice_id):
            return False
        try:
            cursor = self._conn.execute(
                "UPDATE invoices SET confirmed_note=? WHERE id=?", (note, invoice_id)
            )
            self._conn.commit()
            self._set_last_error("" if cursor.rowcount else "not_found")
            return cursor.rowcount == 1
        except sqlite3.Error:
            self._conn.rollback()
            self._set_last_error("write_failed")
            return False

    def update_invoice_fields(
        self,
        invoice_id: int,
        invoice_number: str,
        expense_date: str,
        seller_name: str,
        total_amount: str,
        category: str,
        note: str = "",
        buyer_name: str | None = None,
        *,
        remember_seller_category: bool = False,
    ) -> bool:
        """Save manual fields and optional seller learning as one atomic change."""
        new_expense_date = str(expense_date or "").strip()
        category = str(category or "").strip()
        try:
            with self._atomic_savepoint():
                self._conn.execute("UPDATE invoices SET id=id WHERE 0")
                if not self._require_invoice_editable(invoice_id):
                    return False
                inv = self.get_invoice(invoice_id)
                if not inv:
                    self._set_last_error("not_found")
                    return False
                if buyer_name is None:
                    buyer_name = str(inv.get("buyer_name") or "")
                old_expense_date = str(inv.get("expense_date") or "").strip()
                new_date_source = ("manual" if new_expense_date != old_expense_date
                                   else str(inv.get("date_source") or ""))
                category_changed = category != str(inv.get("category") or "").strip()
                source = str(inv.get("category_source") or "unknown")
                if (category_changed or self._seller_preference_key(seller_name)
                        != self._seller_preference_key(inv.get("seller_name"))):
                    source = "manual"
                self._conn.execute(
                    "UPDATE invoices SET invoice_number=?, expense_date=?, date_source=?, seller_name=?, buyer_name=?, "
                    "total_amount=?, category=?, category_source=?, confirmed_note=? WHERE id=?",
                    (invoice_number, new_expense_date, new_date_source, seller_name, buyer_name, total_amount,
                     category, source, note, invoice_id),
                )
                if (remember_seller_category and category_changed and self._seller_preference_key(seller_name)
                        and category not in ("", "未分类") and not is_pending_evidence_invoice(inv)):
                    self._remember_seller_category(seller_name, category)
            self._set_last_error("")
            return True
        except sqlite3.IntegrityError as exc:
            self._set_last_error("unique_conflict" if "UNIQUE constraint failed" in str(exc) else "write_failed")
            return False
        except sqlite3.Error:
            self._set_last_error("write_failed")
            return False

    def update_invoice_parsed_metadata(
        self,
        invoice_id: int,
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
        parse_note: str = "",
        item_name: str = "",
        expense_date: str = "",
        date_source: str = "",
        buyer_tax_id: str | None = None,
        tax_amount: str | None = None,
        tax_rate: str | None = None,
        use_seller_preference: bool = True,
        evidence_required: bool | None = None,
    ) -> bool:
        """Refresh parsed metadata in-place without touching review status."""
        try:
            with self._atomic_savepoint():
                self._conn.execute("UPDATE invoices SET id=id WHERE 0")
                if not self._require_invoice_editable(invoice_id):
                    return False
                inv = self.get_invoice(invoice_id)
                if not inv:
                    self._set_last_error("not_found")
                    return False

                parsed_is_evidence = is_evidence_record({"invoice_type": invoice_type, "parse_note": parse_note})
                if is_evidence_record(inv) and not parsed_is_evidence and self.evidence_consumers(invoice_id):
                    self._set_last_error("evidence_in_use")
                    return False
                if (parsed_is_evidence and not is_evidence_record(inv)
                        and (self.list_invoice_evidence(invoice_id) or self.count_claim_links(invoice_id))):
                    self._set_last_error("evidence_role_conflict")
                    return False

                if not expense_date:
                    expense_date = invoice_date
                if not date_source:
                    date_source = "invoice_date"

                category_source = str(inv.get("category_source") or "unknown")
                if parse_success and not is_pending_evidence_invoice({"invoice_type": invoice_type, "parse_note": parse_note}):
                    category, category_source = self.resolve_parsed_category(
                        seller_name, category, existing=inv, use_seller_preference=use_seller_preference,
                    )

                self._conn.execute(
                    "UPDATE invoices SET invoice_number=?, invoice_code=?, invoice_date=?, expense_date=?, date_source=?, amount=?, total_amount=?, "
                    "seller_name=?, buyer_name=?, invoice_type=?, category=?, category_source=?, has_extra=?, extra_type=?, "
                    "missing_extra=?, parse_success=?, parse_note=?, item_name=?, "
                    "buyer_tax_id=COALESCE(?, buyer_tax_id), tax_amount=COALESCE(?, tax_amount), "
                    "tax_rate=COALESCE(?, tax_rate), record_role=?, evidence_required=? WHERE id=?",
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
                        category_source,
                        int(bool(has_extra)),
                        extra_type,
                        int(bool(missing_extra)),
                        int(bool(parse_success)),
                        parse_note,
                        item_name,
                        buyer_tax_id, tax_amount, tax_rate,
                        "evidence" if parsed_is_evidence else "invoice",
                        int(bool(missing_extra or extra_type) if evidence_required is None else evidence_required),
                        invoice_id,
                    ),
                )
                if self.list_invoice_evidence(invoice_id):
                    refresh_material_projection(self._conn, invoice_id)
            self._set_last_error("")
            return True
        except sqlite3.IntegrityError:
            self._set_last_error("unique_conflict")
            return False

    def update_invoice_file_paths(
        self,
        invoice_id: int,
        attachment_path: str | None = None,
        extra_paths: list[str] | None = None,
        file_hash: str | None = None,
    ) -> bool:
        """Update stored attachment paths for an invoice."""
        fields: list[str] = []
        values: list[Any] = []

        if attachment_path is not None:
            fields.append("attachment_path = ?")
            values.append(attachment_path)
        if extra_paths is not None:
            fields.append("extra_paths = ?")
            values.append(json.dumps(extra_paths, ensure_ascii=False))
        if file_hash is not None:
            fields.append("file_hash = ?")
            values.append(file_hash)

        if not fields:
            return False

        with self._atomic_savepoint():
            self._conn.execute("UPDATE invoices SET id=id WHERE 0")
            if not self._require_invoice_editable(invoice_id):
                return False
            if not self.get_invoice(invoice_id, include_deleted=True):
                return False
            values.append(invoice_id)
            self._conn.execute(f"UPDATE invoices SET {', '.join(fields)} WHERE id = ?", values)
            if extra_paths is not None:
                replace_material_paths(self._conn, invoice_id, extra_paths)
            if attachment_path is not None:
                self._refresh_evidence_consumers(invoice_id)
        return True

    def update_invoice_extra_flags(
        self,
        invoice_id: int,
        *,
        has_extra: bool,
        missing_extra: bool,
    ) -> bool:
        """Synchronize evidence flags without changing parsed invoice metadata."""
        if not self._require_invoice_editable(invoice_id):
            return False
        if not self.get_invoice(invoice_id):
            return False
        with self._atomic_savepoint():
            self._conn.execute(
                "UPDATE invoices SET has_extra=?, missing_extra=?, "
                "evidence_required=MAX(evidence_required,?) WHERE id=?",
                (int(bool(has_extra)), int(bool(missing_extra)), int(bool(missing_extra)), invoice_id),
            )
            if self.list_invoice_evidence(invoice_id):
                refresh_material_projection(self._conn, invoice_id)
        return True

    def update_invoice_attachment_path_if_missing(
        self, invoice_id: int, attachment_path: str, file_hash: str | None = None
    ) -> bool:
        """Backfill attachment_path only when the existing record lacks a valid local file.

        Returns True if a backfill was performed.
        """
        inv = self.get_invoice(invoice_id)
        if not inv:
            return False
        if not self._require_invoice_editable(invoice_id):
            return False

        existing_path = str(inv.get("attachment_path") or "").strip()
        if existing_path:
            from pathlib import Path as _Path
            from .gui.helpers import resolve_stored_path
            from .config import RUNTIME_DIR
            resolved = resolve_stored_path(existing_path, RUNTIME_DIR)
            if resolved and resolved.exists():
                return False  # already has a valid file

        values = [attachment_path]
        extra_sql = ""
        if file_hash:
            extra_sql = ", file_hash = ?"
            values.append(file_hash)
        values.append(invoice_id)

        self.update_invoice_file_paths(invoice_id, attachment_path=attachment_path, file_hash=file_hash or None)
        _log.debug("重复发票已有记录缺少原件，已回填附件路径: existing_id=%d", invoice_id)
        return True

    def update_invoice_missing_fields(
        self,
        invoice_id: int,
        fields: dict,
        *,
        only_if_empty: bool = True,
        allow_review_statuses: tuple = ("to_review", "error"),
    ) -> dict:
        """Safely backfill missing fields on an existing invoice.

        Returns ``{"updated_fields": [...], "skipped_fields": [...]}``.
        """
        inv = self.get_invoice(invoice_id)
        if not inv:
            return {"updated_fields": [], "skipped_fields": []}

        ALLOWED_FIELDS = {
            "seller_name",
            "buyer_name",
            "invoice_date",
            "amount",
            "total_amount",
            "category",
            "invoice_type",
            "attachment_path",
            "file_hash",
            "extra_paths",
            "item_name",
            "parse_note",
        }

        review_status = str(inv.get("review_status") or "to_review")
        is_claimed = self.count_claim_links(invoice_id) > 0
        updated: list[str] = []
        skipped: list[str] = []

        for key, new_val in fields.items():
            if key not in ALLOWED_FIELDS:
                skipped.append(key)
                continue
            if self.invoice_lock_reason(invoice_id):
                skipped.append(key)
                continue

            if key == "category" and inv.get("category_source") == "manual":
                skipped.append(key)
                continue
            if key == "invoice_type" and is_evidence_record(inv) and self.evidence_consumers(invoice_id):
                skipped.append(key)
                continue

            if new_val is None or str(new_val).strip() == "":
                skipped.append(key)
                continue

            existing_val = str(inv.get(key) or "").strip()
            if only_if_empty and existing_val:
                skipped.append(key)
                continue

            # Never backfill business fields on approved/claimed invoices
            # Only allow path/hash/meta updates for approved or claimed invoices.
            if key not in ("attachment_path", "file_hash", "parse_note", "item_name"):
                if review_status not in allow_review_statuses or is_claimed:
                    skipped.append(key)
                    continue

            try:
                with self._atomic_savepoint():
                    self._conn.execute("UPDATE invoices SET id=id WHERE 0")
                    if key == "invoice_type":
                        current = self.get_invoice(invoice_id)
                        if current and is_evidence_record(current) and self.evidence_consumers(invoice_id):
                            skipped.append(key)
                            continue
                        if (current and new_val == "待关联证明材料"
                                and (self.list_invoice_evidence(invoice_id) or self.count_claim_links(invoice_id))):
                            skipped.append(key)
                            continue
                    value = json.dumps(material_paths(new_val), ensure_ascii=False) if key == "extra_paths" else str(new_val).strip()
                    self._conn.execute(f"UPDATE invoices SET {key} = ? WHERE id = ?", (value, invoice_id))
                    if key == "extra_paths":
                        replace_material_paths(self._conn, invoice_id, new_val)
                    elif key == "attachment_path":
                        self._refresh_evidence_consumers(invoice_id)
                    elif key == "invoice_type" and new_val != "待关联证明材料":
                        self._conn.execute("UPDATE invoices SET record_role='invoice' WHERE id=?", (invoice_id,))
                updated.append(key)
                _log.info("重复发票缺少%s，已从本次解析结果回填: existing_id=%d", key, invoice_id)
            except Exception:
                skipped.append(key)

        return {"updated_fields": updated, "skipped_fields": skipped}

    def update_invoice_source_by_hashes(self, hash_to_subject: dict[str, str], sender: str) -> int:
        """Update source metadata for imported files matched by SHA256."""
        updated = 0
        for file_hash, subject in hash_to_subject.items():
            if not file_hash:
                continue
            cur = self._conn.execute(
                "UPDATE invoices SET mail_sender=?, mail_subject=? WHERE file_hash=? "
                "AND reimbursed_at IS NULL AND NOT EXISTS ("
                "SELECT 1 FROM claim_group_items cgi JOIN claim_groups c ON c.id=cgi.claim_id "
                "WHERE cgi.invoice_id=invoices.id AND c.status IN ('exported','reimbursed'))",
                (sender, subject, file_hash),
            )
            updated += cur.rowcount
        self._conn.commit()
        return updated

    def list_invoices(self, status: str | None = None, limit: int | None = None, include_deleted: bool = False, offset: int = 0) -> list[dict]:
        """List invoices, optionally filtered by review status, limited to N records, with offset."""
        if status is not None and status not in review_status.ALL_STATUSES:
            raise ValueError(f"Invalid review status: '{status}'. Must be one of {review_status.ALL_STATUSES}")
        if limit is not None and limit <= 0:
            raise ValueError(f"Limit must be a positive integer. Got: {limit}")
        if offset < 0:
            raise ValueError(f"Offset must be a non-negative integer. Got: {offset}")
        if offset > 0 and limit is None:
            raise ValueError("Cannot specify offset without limit")

        query = """
            SELECT i.*, cg.name AS claim_name
            FROM invoices i
            LEFT JOIN (
                SELECT invoice_id, MAX(claim_id) AS claim_id
                FROM claim_group_items
                GROUP BY invoice_id
            ) cgi ON i.id = cgi.invoice_id
            LEFT JOIN claim_groups cg ON cgi.claim_id = cg.id
        """
        where_clauses = [visible_invoice_sql()]
        params = []
        if not include_deleted:
            where_clauses.append("i.is_deleted = 0")
        if status is not None:
            where_clauses.append("i.review_status = ?")
            params.append(status)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY i.expense_date DESC, i.id DESC"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.append(limit)
            params.append(offset)

        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def list_invoices_by_ids(
        self,
        invoice_ids: list[int] | tuple[int, ...],
        *,
        status: str | None = None,
        include_deleted: bool = False,
    ) -> list[dict]:
        """Return the requested invoices through the normal query layer.

        The caller owns the transient scope, while this database boundary owns
        parameterisation and deleted/status semantics.  Preserve the supplied
        ID order so a just-imported batch remains stable during review.
        """
        if status is not None and status not in review_status.ALL_STATUSES:
            raise ValueError(f"Invalid review status: '{status}'. Must be one of {review_status.ALL_STATUSES}")
        normalized_ids = tuple(dict.fromkeys(int(invoice_id) for invoice_id in invoice_ids if int(invoice_id) > 0))
        if not normalized_ids:
            return []
        placeholders = ", ".join("?" for _ in normalized_ids)
        query = f"""
            SELECT i.*, cg.name AS claim_name
            FROM invoices i
            LEFT JOIN (
                SELECT invoice_id, MAX(claim_id) AS claim_id
                FROM claim_group_items
                GROUP BY invoice_id
            ) cgi ON i.id = cgi.invoice_id
            LEFT JOIN claim_groups cg ON cgi.claim_id = cg.id
            WHERE i.id IN ({placeholders})
        """
        params: list[object] = list(normalized_ids)
        query += " AND " + visible_invoice_sql()
        if not include_deleted:
            query += " AND i.is_deleted = 0"
        if status is not None:
            query += " AND i.review_status = ?"
            params.append(status)
        rows = self._conn.execute(query, params).fetchall()
        by_id = {int(row["id"]): dict(row) for row in rows}
        return [by_id[invoice_id] for invoice_id in normalized_ids if invoice_id in by_id]

    def count_invoices(self, include_deleted: bool = False) -> int:
        return self.count_invoices_for_status(include_deleted=include_deleted)

    def count_invoices_for_status(self, status: str | None = None, include_deleted: bool = False) -> int:
        """Count invoices, optionally filtered by review status, without hydrating rows."""
        if status is not None and status not in review_status.ALL_STATUSES:
            raise ValueError(f"Invalid review status: '{status}'. Must be one of {review_status.ALL_STATUSES}")

        query = "SELECT COUNT(*) AS cnt FROM invoices i"
        where_clauses = [visible_invoice_sql()]
        params = []
        if not include_deleted:
            where_clauses.append("is_deleted = 0")
        if status is not None:
            where_clauses.append("review_status = ?")
            params.append(status)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        row = self._conn.execute(query, params).fetchone()
        return int(row["cnt"] if row else 0)

    @staticmethod
    def _review_value_expression(key: str) -> str:
        expressions = {
            "expense_date": "COALESCE(NULLIF(TRIM(i.expense_date), ''), TRIM(i.invoice_date), '')",
            "total_amount": "TRIM(COALESCE(i.total_amount, ''))",
            "invoice_number": "TRIM(COALESCE(i.invoice_number, ''))",
            "seller_name": "TRIM(COALESCE(i.seller_name, ''))",
            "category": "TRIM(COALESCE(i.category, ''))",
            "claim_name": "TRIM(COALESCE(cg.name, ''))",
            "review_status": """
                CASE COALESCE(NULLIF(i.review_status, ''), 'to_review')
                    WHEN 'approved' THEN '已通过'
                    WHEN 'ignored' THEN '已忽略'
                    WHEN 'error' THEN '异常'
                    ELSE '待审核'
                END
            """,
            "source": """
                CASE
                    WHEN COALESCE(i.mail_sender, '') = 'mobile_qr' THEN '手机'
                    WHEN COALESCE(i.attachment_path, '') <> '' AND i.mail_uid IS NOT NULL THEN '邮箱+本地'
                    WHEN COALESCE(i.attachment_path, '') <> '' THEN '本地'
                    WHEN COALESCE(i.download_url, '') <> '' THEN '链接'
                    WHEN i.mail_uid IS NOT NULL THEN '邮箱'
                    ELSE '未知'
                END
            """,
            "status": """
                CASE
                    WHEN TRIM(COALESCE(i.invoice_number, '')) = ''
                         AND TRIM(COALESCE(i.total_amount, '')) = ''
                         AND TRIM(COALESCE(i.seller_name, '')) = '' THEN '未识别'
                    WHEN TRIM(COALESCE(i.invoice_number, '')) = ''
                         OR TRIM(COALESCE(i.total_amount, '')) = ''
                         OR COALESCE(NULLIF(TRIM(i.expense_date), ''), TRIM(i.invoice_date), '') = ''
                         OR TRIM(COALESCE(i.seller_name, '')) = '' THEN '待补全'
                    WHEN TRIM(COALESCE(i.attachment_path, '')) = '' THEN '缺原件'
                    WHEN COALESCE(i.missing_extra, 0) <> 0 THEN '缺证明'
                    ELSE '正常'
                END
            """,
            "missing_extra": """
                CASE
                    WHEN COALESCE(i.missing_extra, 0) <> 0 THEN '缺证明'
                    ELSE '正常'
                END
            """,
            "buyer_warning": """
                CASE
                    WHEN review_buyer_has_warning(COALESCE(i.buyer_name, ''), i.buyer_tax_id, i.buyer_tax_id_type) = 1 THEN '异常'
                    ELSE '正常'
                END
            """,
        }
        if key not in expressions:
            raise ValueError(f"Unsupported review filter key: {key}")
        return " ".join(expressions[key].split())

    @staticmethod
    def _review_join_sql() -> str:
        return """
            FROM invoices i
            LEFT JOIN (
                SELECT invoice_id, MAX(claim_id) AS claim_id
                FROM claim_group_items
                GROUP BY invoice_id
            ) cgi ON i.id = cgi.invoice_id
            LEFT JOIN claim_groups cg ON cgi.claim_id = cg.id
        """

    def _build_review_where(self, query: ReviewQuery) -> tuple[str, list[object]]:
        if query.status is not None and query.status not in review_status.ALL_STATUSES:
            raise ValueError(f"Invalid review status: '{query.status}'. Must be one of {review_status.ALL_STATUSES}")
        clauses: list[str] = [visible_invoice_sql()]
        params: list[object] = []
        if not query.include_deleted:
            clauses.append("i.is_deleted = 0")
        if query.status is not None:
            clauses.append("i.review_status = ?")
            params.append(query.status)
        if query.invoice_ids:
            placeholders = ", ".join("?" for _ in query.invoice_ids)
            clauses.append(f"i.id IN ({placeholders})")
            params.extend(query.invoice_ids)
        needle = str(query.search_text or "").strip()
        if needle:
            clauses.append("""
                review_text_contains(
                    COALESCE(i.invoice_number, '') || ' ' ||
                    COALESCE(i.seller_name, '') || ' ' ||
                    COALESCE(i.buyer_name, '') || ' ' ||
                    COALESCE(i.total_amount, '') || ' ' ||
                    COALESCE(i.mail_subject, '') || ' ' ||
                    COALESCE(i.category, '') || ' ' ||
                    COALESCE(i.attachment_path, '') || ' ' ||
                    COALESCE(cg.name, ''), ?
                ) = 1
            """)
            params.append(needle)
        for column_filter in query.column_filters:
            if column_filter.key not in _REVIEW_FILTER_KEYS:
                raise ValueError(f"Unsupported review filter key: {column_filter.key}")
            expression = self._review_value_expression(column_filter.key)
            if column_filter.values is not None:
                if not column_filter.values:
                    clauses.append("0 = 1")
                else:
                    placeholders = ", ".join("?" for _ in column_filter.values)
                    clauses.append(f"COALESCE(NULLIF({expression}, ''), '(空白)') IN ({placeholders})")
                    params.extend(column_filter.values)
            if column_filter.quick:
                today = query.today
                if today is None:
                    raise ValueError("ReviewQuery.today is required for quick date filters")
                if column_filter.quick == "today":
                    start = end = today
                elif column_filter.quick == "week":
                    start, end = today - timedelta(days=today.weekday()), today
                elif column_filter.quick == "month":
                    start = today.replace(day=1)
                    end = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                elif column_filter.quick == "last_30_days":
                    start, end = today - timedelta(days=29), today
                else:
                    raise ValueError(f"Unsupported quick date filter: {column_filter.quick}")
                clauses.append(f"date(substr({expression}, 1, 10)) BETWEEN date(?) AND date(?)")
                params.extend((start.isoformat(), end.isoformat()))
            if column_filter.key == "total_amount":
                clauses.append(f"review_amount_is_valid({expression}) = 1")
                if column_filter.minimum:
                    if _review_amount_is_valid(column_filter.minimum):
                        clauses.append(f"review_amount_at_least({expression}, ?) = 1")
                        params.append(column_filter.minimum)
                if column_filter.maximum:
                    if _review_amount_is_valid(column_filter.maximum):
                        clauses.append(f"review_amount_at_most({expression}, ?) = 1")
                        params.append(column_filter.maximum)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def list_review_invoices(self, query: ReviewQuery) -> list[dict]:
        """Return one deterministic review page after SQLite filtering."""
        if query.limit <= 0:
            raise ValueError(f"Limit must be a positive integer. Got: {query.limit}")
        if query.offset < 0:
            raise ValueError(f"Offset must be a non-negative integer. Got: {query.offset}")
        where_sql, params = self._build_review_where(query)
        sql = "SELECT i.*, cg.name AS claim_name " + self._review_join_sql() + where_sql
        if query.invoice_ids:
            sql += " ORDER BY CASE i.id " + " ".join(
                f"WHEN ? THEN {index}" for index, _invoice_id in enumerate(query.invoice_ids)
            ) + f" ELSE {len(query.invoice_ids)} END, i.id DESC"
            params.extend(query.invoice_ids)
        else:
            sql += " ORDER BY i.expense_date DESC, i.id DESC"
        sql += " LIMIT ? OFFSET ?"
        params.extend((query.limit, query.offset))
        return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def count_review_invoices(self, query: ReviewQuery) -> int:
        """Count the same review predicate used by list_review_invoices."""
        where_sql, params = self._build_review_where(query)
        sql = "SELECT COUNT(*) AS cnt " + self._review_join_sql() + where_sql
        row = self._conn.execute(sql, params).fetchone()
        return int(row["cnt"] if row else 0)

    def list_review_invoice_ids(self, query: ReviewQuery) -> tuple[int, ...]:
        """Capture the entire current filter without loading or selecting table pages."""
        where_sql, params = self._build_review_where(query)
        rows = self._conn.execute(
            "SELECT i.id " + self._review_join_sql() + where_sql
            + " ORDER BY i.expense_date DESC, i.id DESC", params,
        ).fetchall()
        return tuple(int(row["id"]) for row in rows)

    def get_review_batch_invoices(self, invoice_ids: tuple[int, ...]) -> dict[int, dict]:
        records = {}
        for offset in range(0, len(invoice_ids), 500):
            chunk = invoice_ids[offset:offset + 500]
            placeholders = ",".join("?" for _ in chunk)
            for row in self._conn.execute(
                f"SELECT * FROM invoices WHERE id IN ({placeholders})", chunk,
            ):
                records[int(row["id"])] = dict(row)
        return records

    def review_duplicate_flags(self) -> dict[int, set[str]]:
        """Read duplicate flags after the caller reconciles current weak fingerprints."""
        flags: dict[int, set[str]] = {}
        rows = self._conn.execute(
            "SELECT id FROM invoices WHERE is_deleted=0 "
            "AND TRIM(COALESCE(invoice_number,'')) IN ("
            "SELECT TRIM(invoice_number) FROM invoices WHERE is_deleted=0 "
            "AND TRIM(COALESCE(invoice_number,''))<>'' "
            "GROUP BY TRIM(invoice_number) HAVING COUNT(*)>1)",
        )
        for row in rows:
            flags.setdefault(int(row["id"]), set()).add("number_duplicate")
        rows = self._conn.execute(
            "SELECT c.invoice_id, c.reference_id, c.decision FROM duplicate_review_candidates c "
            "JOIN invoices i ON i.id=c.invoice_id JOIN invoices r ON r.id=c.reference_id "
            "WHERE c.decision IN ('pending','duplicate') AND i.is_deleted=0 AND r.is_deleted=0 "
            "AND i.soft_fingerprint=c.fingerprint AND r.soft_fingerprint=c.fingerprint",
        )
        for row in rows:
            if row["decision"] == "pending":
                for invoice_id in (row["invoice_id"], row["reference_id"]):
                    flags.setdefault(int(invoice_id), set()).add("soft_pending")
            else:
                flags.setdefault(int(row["invoice_id"]), set()).add("soft_duplicate")
        return flags

    def list_review_filter_values(self, key: str, *, include_deleted: bool = False) -> list[str]:
        """Return distinct popup values without hydrating invoice rows."""
        expression = self._review_value_expression(key)
        where_sql, params = self._build_review_where(ReviewQuery(include_deleted=include_deleted))
        sql = (
            f"SELECT DISTINCT COALESCE(NULLIF({expression}, ''), '(空白)') AS value "
            + self._review_join_sql() + where_sql + " ORDER BY value COLLATE NOCASE"
        )
        values = [str(row["value"]) for row in self._conn.execute(sql, params).fetchall()]
        return sorted(values, key=str.casefold)

    def refresh_duplicate_candidates(self) -> None:
        """Reconcile current weak keys and queue candidates without changing invoices' status."""
        from .duplicate_review import soft_invoice_fingerprint
        groups = {}
        rows = self._conn.execute("SELECT * FROM invoices WHERE is_deleted=0 ORDER BY id").fetchall()
        with self._atomic_savepoint():
            for row in rows:
                invoice = dict(row)
                fingerprint = soft_invoice_fingerprint(invoice)
                if fingerprint != invoice.get("soft_fingerprint"):
                    self._conn.execute("UPDATE invoices SET soft_fingerprint=? WHERE id=?",
                                       (fingerprint, invoice["id"]))
                if fingerprint:
                    groups.setdefault(fingerprint, []).append(invoice["id"])
            decisions = {
                (row["invoice_id"], row["reference_id"], row["fingerprint"]): row["decision"]
                for row in self._conn.execute("SELECT * FROM duplicate_review_candidates")
            }
            group_ids = {fingerprint: set(ids) for fingerprint, ids in groups.items()}
            confirmed = {(invoice_id, fingerprint) for (invoice_id, ref, fingerprint), decision in decisions.items()
                         if decision == "duplicate" and invoice_id in group_ids.get(fingerprint, ())
                         and ref in group_ids.get(fingerprint, ())}
            for fingerprint, ids in groups.items():
                for invoice_id in ids[1:]:
                    if (invoice_id, fingerprint) in confirmed:
                        continue
                    # Expose one comparison at a time. If a pair is distinct,
                    # compare against the next peer rather than assuming the
                    # whole group is distinct. Do not eagerly create N squared rows.
                    for reference_id in ids:
                        if reference_id == invoice_id:
                            break
                        if decisions.get((invoice_id, reference_id, fingerprint)) == "distinct":
                            continue
                        self._conn.execute(
                            "INSERT OR IGNORE INTO duplicate_review_candidates "
                            "(invoice_id, reference_id, fingerprint) VALUES (?, ?, ?)",
                            (invoice_id, reference_id, fingerprint),
                        )
                        break

    def list_duplicate_candidates(self, decision: str = "pending") -> list[dict]:
        if decision not in {"pending", "distinct", "duplicate"}:
            raise ValueError("无效的疑似重复复核结果")
        self.refresh_duplicate_candidates()
        rows = self._conn.execute(
            "SELECT c.*, i.seller_name, i.expense_date, i.invoice_date, i.total_amount, "
            "i.currency, i.attachment_path, r.attachment_path AS reference_path "
            "FROM duplicate_review_candidates c "
            "JOIN invoices i ON i.id=c.invoice_id JOIN invoices r ON r.id=c.reference_id "
            "WHERE c.decision=? AND i.is_deleted=0 AND r.is_deleted=0 "
            "AND i.soft_fingerprint=c.fingerprint AND r.soft_fingerprint=c.fingerprint "
            "ORDER BY c.id", (decision,),
        ).fetchall()
        return [dict(row) for row in rows]

    def resolve_duplicate_candidate(self, candidate_id: int, decision: str) -> bool:
        if decision not in {"distinct", "duplicate"}:
            raise ValueError("请选择确认重复或不同票据")
        active = {row["id"] for row in self.list_duplicate_candidates()}
        if candidate_id not in active:
            return False
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE duplicate_review_candidates SET decision=?, "
                "resolved_at=datetime('now','localtime') WHERE id=? AND decision='pending'",
                (decision, candidate_id),
            )
        return cursor.rowcount > 0

    def reset_duplicate_candidate(self, candidate_id: int) -> bool:
        active = {row["id"] for decision in ("distinct", "duplicate")
                  for row in self.list_duplicate_candidates(decision)}
        if candidate_id not in active:
            return False
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE duplicate_review_candidates SET decision='pending', resolved_at=NULL "
                "WHERE id=? AND decision<>'pending'", (candidate_id,),
            )
        return cursor.rowcount > 0

    def count_active_duplicates_by_invoice_number(self, invoice_number: str, exclude_id: int) -> int:
        """Count other active (not deleted) invoices with the same invoice_number."""
        if not invoice_number:
            return 0
        row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM invoices WHERE invoice_number = ? AND is_deleted = 0 AND id != ?",
            (invoice_number.strip(), exclude_id)
        ).fetchone()
        return int(row["cnt"] if row else 0)

    def count_pending_manual_invoices(self) -> int:
        """Count active records that still require manual review or completion."""
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM invoices
            WHERE is_deleted = 0
              AND (
                parse_success = 0
                OR invoice_type IN (
                    '图片待识别',
                    '待关联证明材料',
                    '海外凭证/收据',
                    '本地导入待处理'
                )
                OR parse_note LIKE '%待关联证明材料%'
              )
            """
        ).fetchone()
        return int(row["cnt"] if row else 0)

    def count_processed(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM processed_emails").fetchone()[0]

    # ── Reset & dates ────────────────────────────────────────────────

    def get_last_scanned_date(self, mailbox_key: str | None = None) -> str:
        """Most recent mail_date in the emails table."""
        if mailbox_key is None:
            row = self._conn.execute(
                "SELECT mail_date FROM emails "
                "WHERE mail_date != '' ORDER BY mail_date DESC LIMIT 1"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT mail_date FROM emails "
                "WHERE mailbox_key = ? AND mail_date != '' ORDER BY mail_date DESC LIMIT 1",
                (self._normalize_mailbox_key(mailbox_key),),
            ).fetchone()
        return row[0] if row else ""

    def get_last_processed_date(self, mailbox_key: str | None = None) -> str:
        """Return the most recent mail_date among processed emails (YYYY-MM-DD)."""
        if mailbox_key is None:
            row = self._conn.execute(
                "SELECT mail_date FROM processed_emails "
                "WHERE mail_date != '' ORDER BY mail_date DESC LIMIT 1"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT mail_date FROM processed_emails "
                "WHERE mailbox_key = ? AND mail_date != '' ORDER BY mail_date DESC LIMIT 1",
                (self._normalize_mailbox_key(mailbox_key),),
            ).fetchone()
        return row[0] if row else ""

    def reset_emails(self):
        """Clear the emails table (full re-scan)."""
        self._conn.execute("DELETE FROM emails")
        self._conn.commit()
        _log.info("已清空邮件扫描记录")

    def reset_processed(self):
        """Clear the processed-emails table (re-scan mode)."""
        self._conn.execute("DELETE FROM processed_emails")
        self._conn.commit()
        _log.info("已清空已处理邮件记录")

    def remove_mailbox_scan_state(self, mailbox_key: str) -> None:
        """Remove scan cursor/sync state (emails and processed_emails) for the given mailbox_key.

        This does NOT delete any invoice rows in the invoices table.
        """
        if not mailbox_key:
            return
        m_key = self._normalize_mailbox_key(mailbox_key)
        self._conn.execute("DELETE FROM emails WHERE mailbox_key = ?", (m_key,))
        self._conn.execute("DELETE FROM processed_emails WHERE mailbox_key = ?", (m_key,))
        self._conn.commit()
        _log.info("已清空邮箱 %s 的邮件扫描与处理同步状态", m_key)


    def reset_invoices(self):
        """Clear the invoices table (full baseline reset)."""
        locked = self._conn.execute(
            "SELECT 1 FROM invoices i WHERE i.reimbursed_at IS NOT NULL OR EXISTS ("
            "SELECT 1 FROM claim_group_items cgi JOIN claim_groups c ON c.id=cgi.claim_id "
            "WHERE cgi.invoice_id=i.id AND c.status IN ('exported','reimbursed')) LIMIT 1"
        ).fetchone()
        if locked:
            self._set_last_error("invoice_exported_locked")
            return False
        self._conn.execute("DELETE FROM invoices")
        self._conn.commit()
        _log.info("已清空已入库发票记录")
        self._set_last_error("")
        return True

    def get_failed_downloads(self, mailbox_key: str | None = None) -> list[dict]:
        """Return invoices where attachment_path is empty or NULL,
        or emails marked as invoice but have no record in invoices table.
        """
        mailbox_filter = None if mailbox_key is None else self._normalize_mailbox_key(mailbox_key)
        results: list[dict] = []
        seen: set[tuple[str, int]] = set()

        if mailbox_filter is None:
            invoice_rows = self._conn.execute(
                "SELECT DISTINCT mailbox_key, mail_uid FROM invoices WHERE attachment_path = '' OR attachment_path IS NULL"
            ).fetchall()
            email_rows = self._conn.execute(
                "SELECT mailbox_key, uid FROM emails WHERE is_invoice = 1 AND downloaded = 1"
            ).fetchall()
        else:
            invoice_rows = self._conn.execute(
                "SELECT DISTINCT mailbox_key, mail_uid FROM invoices WHERE (attachment_path = '' OR attachment_path IS NULL) AND mailbox_key = ?",
                (mailbox_filter,),
            ).fetchall()
            email_rows = self._conn.execute(
                "SELECT mailbox_key, uid FROM emails WHERE is_invoice = 1 AND downloaded = 1 AND mailbox_key = ?",
                (mailbox_filter,),
            ).fetchall()

        for row in invoice_rows:
            uid = row["mail_uid"]
            if uid is None:
                continue
            key = (str(row["mailbox_key"] or mailbox_filter or "legacy"), int(uid))
            if key not in seen:
                results.append({"mailbox_key": key[0], "mail_uid": key[1]})
                seen.add(key)

        for row in email_rows:
            uid = row["uid"]
            mailbox = str(row["mailbox_key"] or mailbox_filter or "legacy")
            inv = self._conn.execute(
                "SELECT 1 FROM invoices WHERE mail_uid = ? AND mailbox_key = ?",
                (uid, mailbox),
            ).fetchone()
            if not inv:
                key = (mailbox, int(uid))
                if key not in seen:
                    results.append({"mailbox_key": mailbox, "mail_uid": int(uid)})
                    seen.add(key)

        return results

    def reset_emails_download_status(self, uids: list[int], mailbox_key: str | None = None):
        """Reset downloaded = 0 for a list of email UIDs."""
        if not uids:
            return
        placeholders = ", ".join("?" for _ in uids)
        if mailbox_key is None:
            self._conn.execute(
                f"UPDATE emails SET downloaded = 0 WHERE uid IN ({placeholders})",
                uids
            )
        else:
            self._conn.execute(
                f"UPDATE emails SET downloaded = 0 WHERE mailbox_key = ? AND uid IN ({placeholders})",
                [self._normalize_mailbox_key(mailbox_key), *uids],
            )
        self._conn.commit()

    def delete_invoices_by_uid(self, uids: list[int], mailbox_key: str | None = None):
        """Delete invoice records for a list of email UIDs where attachment_path is empty."""
        if not uids:
            return
        placeholders = ", ".join("?" for _ in uids)
        lock_clause = (
            " AND reimbursed_at IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM claim_group_items cgi JOIN claim_groups c ON c.id=cgi.claim_id "
            "WHERE cgi.invoice_id=invoices.id AND c.status IN ('exported','reimbursed'))"
        )
        if mailbox_key is None:
            self._conn.execute(
                f"DELETE FROM invoices WHERE mail_uid IN ({placeholders}) "
                f"AND (attachment_path = '' OR attachment_path IS NULL){lock_clause}",
                uids
            )
        else:
            self._conn.execute(
                f"DELETE FROM invoices WHERE mailbox_key = ? AND mail_uid IN ({placeholders}) "
                f"AND (attachment_path = '' OR attachment_path IS NULL){lock_clause}",
                [self._normalize_mailbox_key(mailbox_key), *uids],
            )
        self._conn.commit()

    # ── Claim Groups (CODE-004) ──────────────────────────────────────

    def create_claim_group(
        self, name: str, period_start: str = "", period_end: str = "", *,
        reason_category: str = "", reason_detail: str = "",
        applicant_name: str = "", department: str = "",
    ) -> int:
        """Create a new claim group and return its auto-incremented ID."""
        cursor = self._conn.execute(
            "INSERT INTO claim_groups (name, period_start, period_end, reason_category, "
            "reason_detail, applicant_name, department) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, period_start, period_end, reason_category.strip(), reason_detail.strip(),
             applicant_name.strip(), department.strip())
        )
        self._conn.commit()
        return cursor.lastrowid

    def update_claim_reason(
        self, claim_id: int, *, reason_category: str | None = None,
        reason_detail: str | None = None, applicant_name: str | None = None,
        department: str | None = None,
    ) -> bool:
        """Update supplied group fields; omitted fields and overrides remain intact."""
        values = {
            key: value.strip() for key, value in {
                "reason_category": reason_category, "reason_detail": reason_detail,
                "applicant_name": applicant_name, "department": department,
            }.items() if value is not None
        }
        if not values:
            return self.get_claim_group(claim_id) is not None
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE claim_groups SET {assignments} WHERE id=? AND status='draft'",
                (*values.values(), claim_id),
            )
        if cursor.rowcount == 0:
            self._set_last_error(
                "not_found" if self.get_claim_group(claim_id) is None else "claim_exported_locked"
            )
        return cursor.rowcount > 0

    def update_invoice_financial_fields(
        self, invoice_id: int, *, amount: str | None, buyer_tax_id: str | None,
        tax_amount: str | None, tax_rate: str | None, invoice_code: str,
        buyer_tax_id_type: str | None = None,
    ) -> bool:
        """Save explicit financial data together; NULL retains unknown semantics."""
        from .financial_validation import normalize_tax_rate
        from .tax_id_validation import TAX_ID_TYPES
        if buyer_tax_id_type is not None and buyer_tax_id_type not in TAX_ID_TYPES:
            raise ValueError("购方税号类型无效")
        if not self._require_invoice_editable(invoice_id):
            return False
        normalized_rate = normalize_tax_rate(tax_rate)
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE invoices SET amount=?, buyer_tax_id=?, tax_amount=?, tax_rate=?, "
                "invoice_code=?, buyer_tax_id_type=COALESCE(?, buyer_tax_id_type) WHERE id=? AND is_deleted=0",
                (amount, buyer_tax_id, tax_amount, normalized_rate, invoice_code.strip(), buyer_tax_id_type, invoice_id),
            )
        return cursor.rowcount > 0

    def update_invoice_reason(self, invoice_id: int, custom_reason: str | None) -> bool:
        """Set an explicit override, or NULL to resume inheritance."""
        if not self._require_invoice_editable(invoice_id):
            return False
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE invoices SET custom_reason=? WHERE id=? AND is_deleted=0",
                (None if custom_reason is None else custom_reason.strip(), invoice_id),
            )
        return cursor.rowcount > 0

    def get_invoice_reason(self, invoice_id: int) -> str:
        from .claim_reason import resolve_claim_reason
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            return ""
        claim_id = self.get_invoice_claim_id(invoice_id)
        claim = self.get_claim_group(claim_id) if claim_id is not None else None
        return resolve_claim_reason(invoice, claim)

    def get_invoice_claim_id(self, invoice_id: int) -> int | None:
        """Return the claim_id this invoice belongs to, or None."""
        row = self._conn.execute(
            "SELECT claim_id FROM claim_group_items WHERE invoice_id = ? LIMIT 1",
            (invoice_id,)
        ).fetchone()
        return int(row["claim_id"]) if row else None

    def add_invoice_to_claim(self, claim_id: int, invoice_id: int, note: str = "") -> bool:
        """Map an invoice to a claim group. Returns False on duplicate or error."""
        if not self.is_claim_editable(claim_id):
            self._set_last_error(
                "not_found" if self.get_claim_group(claim_id) is None else "claim_exported_locked"
            )
            return False
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            self._set_last_error("not_found")
            return False
        if not self._require_invoice_editable(invoice_id):
            return False
        if is_pending_evidence_invoice(invoice):
            self._set_last_error("evidence_only")
            return False

        # Cross-claim check: an invoice can belong to at most one claim group
        existing_other = self._conn.execute(
            "SELECT claim_id FROM claim_group_items WHERE invoice_id = ? AND claim_id != ?",
            (invoice_id, claim_id)
        ).fetchone()
        if existing_other:
            self._set_last_error("already_in_other_claim")
            _log.info(
                "Cross-claim duplicate: invoice_id %d already in claim_id %d, cannot add to claim_id %d",
                invoice_id, existing_other[0], claim_id
            )
            return False

        try:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO claim_group_items (claim_id, invoice_id, note) VALUES (?, ?, ?)",
                (claim_id, invoice_id, note)
            )
            self._conn.commit()
            if cursor.rowcount == 0:
                self._set_last_error("integrity_error")
                _log.info("Duplicate mapping: invoice_id %d already in claim_id %d", invoice_id, claim_id)
                return False
            self._set_last_error("")
            return True
        except sqlite3.IntegrityError:
            self._conn.rollback()
            self._set_last_error("integrity_error")
            _log.info("Duplicate mapping: invoice_id %d already in claim_id %d", invoice_id, claim_id)
            return False

    def remove_invoice_from_claim(self, claim_id: int, invoice_id: int) -> bool:
        """Remove a mapped invoice from a claim group."""
        if not self.is_claim_editable(claim_id):
            self._set_last_error(
                "not_found" if self.get_claim_group(claim_id) is None else "claim_exported_locked"
            )
            return False
        cursor = self._conn.execute(
            "DELETE FROM claim_group_items WHERE claim_id = ? AND invoice_id = ?",
            (claim_id, invoice_id)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_claim_group(self, claim_id: int) -> dict | None:
        """Fetch claim group details by ID."""
        row = self._conn.execute(
            "SELECT * FROM claim_groups WHERE id = ?",
            (claim_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_claim_group_if_empty(self, claim_id: int) -> bool:
        """Delete a claim group only when no invoice records reference it."""
        claim = self.get_claim_group(claim_id)
        if not claim:
            self._set_last_error("not_found")
            return False
        if claim.get("status", "draft") != "draft":
            self._set_last_error("claim_exported_locked")
            return False
        with self._conn:
            self._conn.execute(
                """
                DELETE FROM claim_group_items
                WHERE claim_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM invoices WHERE invoices.id = claim_group_items.invoice_id
                  )
                """,
                (claim_id,),
            )
            cursor = self._conn.execute(
                """
                DELETE FROM claim_groups
                WHERE id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM claim_group_items WHERE claim_id = ?
                  )
                """,
                (claim_id, claim_id),
            )
        if cursor.rowcount <= 0:
            self._set_last_error("not_empty")
            return False
        self._set_last_error("")
        return True

    def list_claim_groups(self) -> list[dict]:
        """List all claim groups ordered by ID descending."""
        rows = self._conn.execute("SELECT * FROM claim_groups ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def get_claim_invoices(self, claim_id: int, include_deleted: bool = False) -> list[dict]:
        """Fetch all invoices inside a claim group, ordered by sort_order and invoice_date."""
        sql = """
            SELECT i.*, cgi.sort_order, cgi.note AS claim_note
            FROM invoices i
            JOIN claim_group_items cgi ON i.id = cgi.invoice_id
            WHERE cgi.claim_id = ?
        """
        if not include_deleted:
            sql += " AND i.is_deleted = 0"
        sql += " ORDER BY cgi.sort_order ASC, i.expense_date DESC, i.id DESC"

        rows = self._conn.execute(sql, (claim_id,)).fetchall()
        from .claim_reason import resolve_claim_reason
        claim = self.get_claim_group(claim_id)
        invoices = [self._with_evidence(dict(r)) for r in rows]
        for invoice in invoices:
            invoice["reimbursement_reason"] = resolve_claim_reason(invoice, claim)
        return invoices

    def add_export_run(
        self,
        claim_id: int,
        export_dir: str,
        export_type: str,
        item_count: int,
        invoice_ids: tuple[int, ...] | list[int] = (),
    ) -> int:
        """Persist a successful export and freeze its claim membership atomically."""
        claim = self.get_claim_group(claim_id)
        if not claim:
            raise ValueError("报销组不存在")
        status = str(claim.get("status") or "draft")
        if status == "reimbursed":
            raise ValueError("该报销组已标记报销，不能再次导出")
        if status not in {"draft", "exported"}:
            raise ValueError("报销组状态无效，无法导出")
        item_ids = tuple(dict.fromkeys(int(value) for value in invoice_ids))
        if item_count < 0 or len(item_ids) != item_count:
            raise ValueError("导出记录的发票数量不一致")
        if item_ids:
            placeholders = ",".join("?" for _ in item_ids)
            rows = self._conn.execute(
                f"SELECT invoice_id FROM claim_group_items WHERE claim_id=? "
                f"AND invoice_id IN ({placeholders})",
                (claim_id, *item_ids),
            ).fetchall()
            if {int(row[0]) for row in rows} != set(item_ids):
                raise ValueError("导出发票已不属于当前报销组，请刷新后重试")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._atomic_savepoint():
            reserved = self._conn.execute(
                "UPDATE claim_groups SET id=id WHERE id=? AND status=?",
                (claim_id, status),
            ).rowcount
            if reserved != 1:
                raise ValueError("报销组状态已变化，请刷新后重新导出")
            if item_ids:
                placeholders = ",".join("?" for _ in item_ids)
                blocked = self._conn.execute(
                    f"SELECT 1 FROM invoices WHERE id IN ({placeholders}) AND "
                    "(reimbursed_at IS NOT NULL OR EXISTS ("
                    "SELECT 1 FROM claim_group_items cgi JOIN claim_groups c ON c.id=cgi.claim_id "
                    "WHERE cgi.invoice_id=invoices.id AND c.id!=? "
                    "AND c.status IN ('exported','reimbursed'))) LIMIT 1",
                    (*item_ids, claim_id),
                ).fetchone()
                if blocked:
                    raise ValueError("報銷組包含已導出鎖定或已報銷的發票，無法再次導出")
            cursor = self._conn.execute(
                "INSERT INTO export_runs (claim_id, export_dir, export_type, item_count) "
                "VALUES (?, ?, ?, ?)",
                (claim_id, export_dir, export_type, item_count),
            )
            export_run_id = int(cursor.lastrowid)
            self._conn.executemany(
                "INSERT INTO export_run_items (export_run_id, invoice_id) VALUES (?, ?)",
                [(export_run_id, invoice_id) for invoice_id in item_ids],
            )
            if status == "draft":
                changed = self._conn.execute(
                    "UPDATE claim_groups SET status='exported', exported_at=? "
                    "WHERE id=? AND status='draft'",
                    (stamp, claim_id),
                ).rowcount
                if changed != 1:
                    raise ValueError("报销组状态已变化，请刷新后重新导出")
                self._conn.execute(
                    "INSERT INTO claim_status_events "
                    "(claim_id, from_status, to_status, occurred_at, export_run_id, note) "
                    "VALUES (?, 'draft', 'exported', ?, ?, 'Export package created')",
                    (claim_id, stamp, export_run_id),
                )
        self._set_last_error("")
        return export_run_id

    def get_export_run_items(self, export_run_id: int) -> list[int]:
        rows = self._conn.execute(
            "SELECT invoice_id FROM export_run_items WHERE export_run_id=? ORDER BY id",
            (int(export_run_id),),
        ).fetchall()
        return [int(row[0]) for row in rows]

    def mark_claim_reimbursed(self, claim_id: int, export_run_id: int | None = None) -> bool:
        """Mark the exact invoice set from a successful export as reimbursed."""
        claim = self.get_claim_group(claim_id)
        if not claim:
            self._set_last_error("not_found")
            return False
        if claim.get("status") != "exported":
            self._set_last_error("claim_not_exported")
            return False
        if export_run_id is None:
            row = self._conn.execute(
                "SELECT id FROM export_runs WHERE claim_id=? ORDER BY id DESC LIMIT 1",
                (claim_id,),
            ).fetchone()
            export_run_id = int(row[0]) if row else None
        if export_run_id is None:
            self._set_last_error("export_run_missing")
            return False
        run = self._conn.execute(
            "SELECT id FROM export_runs WHERE id=? AND claim_id=?",
            (int(export_run_id), claim_id),
        ).fetchone()
        invoice_ids = self.get_export_run_items(int(export_run_id))
        if not run or not invoice_ids:
            self._set_last_error("export_run_items_missing")
            return False
        placeholders = ",".join("?" for _ in invoice_ids)
        current_members = {
            int(row[0]) for row in self._conn.execute(
                f"SELECT invoice_id FROM claim_group_items WHERE claim_id=? "
                f"AND invoice_id IN ({placeholders})",
                (claim_id, *invoice_ids),
            ).fetchall()
        }
        if current_members != set(invoice_ids):
            self._set_last_error("export_run_items_mismatch")
            return False
        conflict = self._conn.execute(
            f"SELECT 1 FROM invoices WHERE id IN ({placeholders}) "
            "AND reimbursed_group_id IS NOT NULL AND reimbursed_group_id != ? LIMIT 1",
            (*invoice_ids, claim_id),
        ).fetchone()
        if conflict:
            self._set_last_error("invoice_reimbursed_elsewhere")
            return False

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._atomic_savepoint():
            reserved = self._conn.execute(
                "UPDATE claim_groups SET id=id WHERE id=? AND status='exported'",
                (claim_id,),
            ).rowcount
            if reserved != 1:
                self._set_last_error("claim_state_changed")
                return False
            conflict = self._conn.execute(
                f"SELECT 1 FROM invoices WHERE id IN ({placeholders}) "
                "AND reimbursed_group_id IS NOT NULL AND reimbursed_group_id != ? LIMIT 1",
                (*invoice_ids, claim_id),
            ).fetchone()
            if conflict:
                self._set_last_error("invoice_reimbursed_elsewhere")
                return False
            changed = self._conn.execute(
                "UPDATE claim_groups SET status='reimbursed', reimbursed_at=? "
                "WHERE id=? AND status='exported'",
                (stamp, claim_id),
            ).rowcount
            if changed != 1:
                self._set_last_error("claim_state_changed")
                return False
            self._conn.execute(
                f"UPDATE invoices SET reimbursed_at=COALESCE(reimbursed_at, ?), "
                f"reimbursed_group_id=? WHERE id IN ({placeholders})",
                (stamp, claim_id, *invoice_ids),
            )
            self._conn.execute(
                "INSERT INTO claim_status_events "
                "(claim_id, from_status, to_status, occurred_at, export_run_id, note) "
                "VALUES (?, 'exported', 'reimbursed', ?, ?, 'Marked reimbursed from exported package')",
                (claim_id, stamp, int(export_run_id)),
            )
        self._set_last_error("")
        return True

    def get_claim_status_events(self, claim_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM claim_status_events WHERE claim_id=? ORDER BY id",
            (int(claim_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_export_runs(self, claim_id: int = None) -> list:
        """Get all logged export runs, optionally filtered by claim_id."""
        if claim_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM export_runs WHERE claim_id = ? ORDER BY id DESC",
                (claim_id,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM export_runs ORDER BY id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_export_runs(self, claim_id: int = None) -> list:
        """Get all logged export runs (helper/alias)."""
        return self.get_export_runs(claim_id)

    def find_emails_for_reprocess(
        self,
        mailbox_key: str | None = None,
        uids: list[int] | None = None,
        uid_range: tuple[int, int] | None = None,
        since: str | None = None,
        until: str | None = None,
        subject_contains: str | None = None,
        sender_contains: str | None = None,
        only_downloaded: bool = True,
        limit: int = 50,
    ) -> list[dict]:
        """Query emails for reprocessing with filters."""
        query = "SELECT mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded FROM emails WHERE 1=1"
        params = []

        if mailbox_key:
            query += " AND LOWER(mailbox_key) = ?"
            params.append(mailbox_key.strip().lower())

        if uids:
            placeholders = ",".join("?" for _ in uids)
            query += f" AND uid IN ({placeholders})"
            params.extend(uids)

        if uid_range:
            query += " AND uid >= ? AND uid <= ?"
            params.extend(uid_range)

        if since:
            query += " AND mail_date >= ?"
            params.append(since)

        if until:
            query += " AND mail_date <= ?"
            params.append(until)

        if subject_contains:
            query += " AND subject LIKE ?"
            params.append(f"%{subject_contains}%")

        if sender_contains:
            query += " AND sender LIKE ?"
            params.append(f"%{sender_contains}%")

        if only_downloaded:
            query += " AND downloaded = 1"

        query += " ORDER BY mail_date DESC, uid DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_invoices_by_mail_identity(self, mailbox_key: str, uid: int) -> list[dict]:
        """Find invoices matching mailbox_key and uid, with a fallback to legacy mailbox_key."""
        # 1. 精确查询，使用 LEFT JOIN 获取 claim_id 字段
        query = (
            "SELECT i.id, i.invoice_number, i.invoice_date, i.seller_name, i.total_amount, "
            "i.review_status, i.attachment_path, i.extra_paths, i.mailbox_key, i.mail_uid, "
            "cgi.claim_id AS claim_id "
            "FROM invoices i "
            "LEFT JOIN claim_group_items cgi ON i.id = cgi.invoice_id "
            "WHERE i.mailbox_key = ? AND i.mail_uid = ? AND i.is_deleted = 0"
        )
        rows = self._conn.execute(query, (mailbox_key, uid)).fetchall()
        results = [dict(r) for r in rows]

        # 2. 如果精确查询为空，且 mailbox_key 并非 'legacy'，进行 legacy fallback 匹配
        if not results and mailbox_key != "legacy":
            query_fallback = (
                "SELECT i.id, i.invoice_number, i.invoice_date, i.seller_name, i.total_amount, "
                "i.review_status, i.attachment_path, i.extra_paths, i.mailbox_key, i.mail_uid, "
                "cgi.claim_id AS claim_id "
                "FROM invoices i "
                "LEFT JOIN claim_group_items cgi ON i.id = cgi.invoice_id "
                "WHERE i.mailbox_key IN ('', 'legacy') AND i.mail_uid = ? AND i.is_deleted = 0"
            )
            rows_fb = self._conn.execute(query_fallback, (uid,)).fetchall()
            for r in rows_fb:
                d = dict(r)
                d["is_legacy_fallback"] = True
                results.append(d)

        # 增加 claim_group_id 的 key 兼容
        for r in results:
            r["claim_group_id"] = r["claim_id"]

        return results

    def delete_invoices_for_reprocess(
        self,
        mailbox_key: str,
        uid: int,
        include_approved: bool = False,
        include_claimed: bool = False,
    ) -> dict:
        """Safely delete invoices associated with a given email and return statistics."""
        invoices = self.get_invoices_by_mail_identity(mailbox_key, uid)

        # 1. 结果按发票 ID 进行去重，防止重复统计和处理
        unique_invoices = {}
        for inv in invoices:
            inv_id = inv["id"]
            if inv_id not in unique_invoices:
                unique_invoices[inv_id] = inv
        unique_list = list(unique_invoices.values())

        deleted = 0
        skipped_approved = 0
        skipped_claimed = 0
        skipped = []
        to_delete_ids = []

        for inv in unique_list:
            inv_id = inv["id"]
            is_approved = (inv.get("review_status") == "approved")
            is_claimed = inv.get("claim_id") is not None

            skip_reason = None
            lock_reason = self.invoice_lock_reason(inv_id)
            if lock_reason in {"invoice_reimbursed", "invoice_exported_locked"}:
                skipped_claimed += 1
                skip_reason = "exported_or_reimbursed"
            elif is_approved and not include_approved:
                skipped_approved += 1
                skip_reason = "approved"
            elif is_claimed and not include_claimed:
                skipped_claimed += 1
                skip_reason = "claimed"
            elif self.evidence_consumers(inv_id):
                # Reprocessing a source email must preserve a shared material,
                # including references held by invoices in the recycle bin.
                skip_reason = "evidence_in_use"

            if skip_reason:
                skipped.append({
                    "id": inv_id,
                    "invoice_number": inv.get("invoice_number", ""),
                    "reason": skip_reason
                })
            else:
                to_delete_ids.append(inv_id)

        # 2. 事务级原子删除：先删除 claim_group_items 关联，再物理删除 invoices
        if to_delete_ids:
            with self._atomic_savepoint():
                self._conn.execute("UPDATE invoices SET id=id WHERE 0")
                for inv_id in to_delete_ids:
                    if self.evidence_consumers(inv_id):
                        raise ValueError("邮件重处理发现材料仍被引用，请刷新后重试。")
                    # 先删除关联关系
                    self._conn.execute("DELETE FROM claim_group_items WHERE invoice_id = ?", (inv_id,))
                    # 后删除发票
                    self._conn.execute("DELETE FROM invoices WHERE id = ?", (inv_id,))
                deleted = len(to_delete_ids)

        return {
            "deleted": deleted,
            "skipped_approved": skipped_approved,
            "skipped_claimed": skipped_claimed,
            "skipped": skipped
        }

    def reset_email_for_reprocess(
        self,
        mailbox_key: str,
        uid: int,
        reclassify: bool = False,
    ):
        """Reset an email's downloaded and processing state, and optionally its classification."""
        if reclassify:
            self._conn.execute(
                "UPDATE emails SET downloaded = 0, processed_at = NULL, "
                "is_invoice = -1, classify_by = '', classify_reason = '' "
                "WHERE mailbox_key = ? AND uid = ?",
                (mailbox_key, uid)
            )
        else:
            self._conn.execute(
                "UPDATE emails SET downloaded = 0, processed_at = NULL "
                "WHERE mailbox_key = ? AND uid = ?",
                (mailbox_key, uid)
            )
        # 还要从 processed_emails 表里清除该邮件，防止被当作“已扫描”忽略
        self._conn.execute(
            "DELETE FROM processed_emails WHERE mailbox_key = ? AND uid = ?",
            (mailbox_key, uid)
        )
        self._conn.commit()

    def list_pending_evidence_for_mail(self, mailbox_key: str, mail_uid: int) -> list[dict]:
        """Query all active (undeleted) pending evidence records for a specific email."""
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        sql = """
            SELECT * FROM invoices
            WHERE mailbox_key = ?
              AND mail_uid = ?
              AND invoice_type = '待关联证明材料'
              AND is_deleted = 0
              AND attachment_path IS NOT NULL
              AND attachment_path != ''
              AND NOT EXISTS (SELECT 1 FROM invoice_evidence_relations r
                              JOIN invoices parent ON parent.id=r.invoice_id
                              WHERE r.evidence_id=invoices.id AND parent.is_deleted=0)
            ORDER BY id ASC
        """
        rows = self._conn.execute(sql, (mailbox_key, mail_uid)).fetchall()
        if not rows and mailbox_key not in ("legacy", ""):
            # Fallback to legacy or empty key
            sql_fallback = """
                SELECT * FROM invoices
                WHERE mailbox_key IN ('legacy', '')
                  AND mail_uid = ?
                  AND invoice_type = '待关联证明材料'
                  AND is_deleted = 0
                  AND attachment_path IS NOT NULL
                  AND attachment_path != ''
                  AND NOT EXISTS (SELECT 1 FROM invoice_evidence_relations r
                                  JOIN invoices parent ON parent.id=r.invoice_id
                                  WHERE r.evidence_id=invoices.id AND parent.is_deleted=0)
                ORDER BY id ASC
            """
            rows = self._conn.execute(sql_fallback, (mail_uid,)).fetchall()
        return [dict(r) for r in rows]
