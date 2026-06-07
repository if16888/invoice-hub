"""SQLite database — invoice records and processed-email tracking."""

from __future__ import annotations

import json
import logging
import sqlite3
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from . import review_status
from .log_privacy import mask_invoice_number

_log = logging.getLogger(__name__)


def is_pending_evidence_invoice(invoice: dict) -> bool:
    """Return True only for evidence that still needs a main invoice link."""
    return (
        str(invoice.get("invoice_type") or "") == "待关联证明材料"
        or "待关联证明材料" in str(invoice.get("parse_note") or "")
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_key     TEXT NOT NULL DEFAULT 'legacy',
    invoice_number  TEXT,
    invoice_code    TEXT,
    invoice_date    TEXT,
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


class InvoiceDB:
    """Thin wrapper around a SQLite database for invoice records."""

    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self.last_error = ""
        self._conn.executescript(_SCHEMA)
        _log.debug("数据库已打开: %s", self._path.name)

        # Run database migrations
        from .migrations import check_and_migrate
        check_and_migrate(self._conn)


    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def is_open(self) -> bool:
        """Return True if the database connection is open and active."""
        return self._conn is not None

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

    # ── Emails table (Phase 1: scan & classify) ──────────────────────

    def upsert_email(self, uid: int, subject: str,
                     sender: str, mail_date: str, mailbox_key: str = "legacy") -> bool:
        """Insert a scanned email header. Returns True if new."""
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        try:
            self._conn.execute(
                "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (mailbox_key, uid, subject, sender, mail_date),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def bulk_upsert_emails(self, rows: list[dict], mailbox_key: str = "legacy") -> int:
        """Batch insert scanned headers. Returns count of new rows."""
        mailbox_key = self._normalize_mailbox_key(mailbox_key)
        new = 0
        for r in rows:
            try:
                self._conn.execute(
                    "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (mailbox_key, r["uid"], r["subject"], r["sender"], r["date"]),
                )
                new += 1
            except sqlite3.IntegrityError:
                pass
        self._conn.commit()
        return new

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
        for r in results:
            row_mailbox_key = self._normalize_mailbox_key(r.get("mailbox_key", mailbox_key))
            self._conn.execute(
                "UPDATE emails SET is_invoice = ?, classify_by = ?, "
                "classify_reason = ? WHERE mailbox_key = ? AND uid = ?",
                (1 if r["is_invoice"] else 0,
                 r.get("by", ""), r.get("reason", ""), row_mailbox_key, r["uid"]),
            )
        self._conn.commit()

    def get_invoice_emails_to_download(self, mailbox_key: str | None = None) -> list[dict]:
        """Return emails marked as invoice but not yet downloaded."""
        if mailbox_key is None:
            rows = self._conn.execute(
                "SELECT mailbox_key, uid, subject, sender, mail_date "
                "FROM emails WHERE is_invoice = 1 AND downloaded = 0 "
                "ORDER BY mail_date DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT mailbox_key, uid, subject, sender, mail_date "
                "FROM emails WHERE is_invoice = 1 AND downloaded = 0 AND mailbox_key = ? "
                "ORDER BY mail_date DESC",
                (self._normalize_mailbox_key(mailbox_key),),
            ).fetchall()
        return [dict(r) for r in rows]

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
        """Check uniqueness on (number, amount, seller)."""
        invoice_number = (invoice_number or "").strip()
        total_amount = (total_amount or "").strip()
        seller_name = (seller_name or "").strip()

        cond = "" if include_deleted else " AND is_deleted = 0"

        if invoice_number:
            row = self._conn.execute(
                f"SELECT 1 FROM invoices WHERE invoice_number = ? AND total_amount = ?{cond}",
                (invoice_number, total_amount),
            ).fetchone()
            if row is not None:
                return True

        if seller_name and total_amount:
            row = self._conn.execute(
                f"SELECT 1 FROM invoices WHERE total_amount = ? AND seller_name = ?{cond}",
                (total_amount, seller_name),
            ).fetchone()
            return row is not None

        return False

    # ── Insert ───────────────────────────────────────────────────────

    def insert_invoice(self, rec: dict[str, Any]) -> int | None:
        """Insert an invoice record.  Returns the row id, or None on dup."""
        allowed_cols = {
            "mailbox_key",
            "invoice_number", "invoice_code", "invoice_date",
            "amount", "total_amount", "seller_name", "buyer_name",
            "invoice_type", "category", "has_extra", "extra_type",
            "missing_extra", "mail_uid", "mail_subject", "mail_date",
            "mail_sender", "parse_success", "parse_note",
            "attachment_path", "extra_paths", "download_url", "item_name",
            "review_status", "processing_status", "currency", "exchange_rate",
            "amount_home", "file_hash", "confirmed_at", "confirmed_note", "is_deleted",
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
            cur = self._conn.execute(
                f"INSERT INTO invoices ({col_names}) VALUES ({placeholders})",
                vals,
            )
            self._conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            _log.info("重复发票(DB约束): %s", mask_invoice_number(rec.get("invoice_number", "")))
            return None

    # ── Query ────────────────────────────────────────────────────────

    def get_all_invoices(self, include_deleted: bool = False) -> list[dict]:
        if include_deleted:
            rows = self._conn.execute(
                "SELECT * FROM invoices ORDER BY invoice_date DESC, id DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM invoices WHERE is_deleted = 0 ORDER BY invoice_date DESC, id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_invoice(self, invoice_id: int, include_deleted: bool = False) -> dict | None:
        """Fetch a single invoice record by ID."""
        sql = "SELECT * FROM invoices WHERE id = ?"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        row = self._conn.execute(sql, (invoice_id,)).fetchone()
        return dict(row) if row else None

    def find_invoice_by_number_and_amount(self, invoice_number: str, total_amount: str = "", include_deleted: bool = False) -> dict | None:
        """Find the most recent invoice with the same invoice number and amount."""
        if not invoice_number:
            return None
        sql = "SELECT * FROM invoices WHERE invoice_number = ? AND total_amount = ?"
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

    def restore_deleted_invoices_by_file_hashes(self, file_hashes: set[str]) -> set[str]:
        """Restore soft-deleted invoices matching any supplied file hash."""
        normalized = {str(value or "").strip() for value in file_hashes}
        normalized.discard("")
        if not normalized:
            return set()

        placeholders = ", ".join("?" for _ in normalized)
        rows = self._conn.execute(
            f"SELECT id, file_hash FROM invoices "
            f"WHERE is_deleted = 1 AND file_hash IN ({placeholders})",
            tuple(sorted(normalized)),
        ).fetchall()
        if not rows:
            return set()

        invoice_ids = [int(row["id"]) for row in rows]
        id_placeholders = ", ".join("?" for _ in invoice_ids)
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(invoices)").fetchall()
        }
        assignments = "is_deleted = 0"
        if "updated_at" in columns:
            assignments += ", updated_at = CURRENT_TIMESTAMP"
        self._conn.execute(
            f"UPDATE invoices SET {assignments} WHERE id IN ({id_placeholders})",
            tuple(invoice_ids),
        )
        self._conn.commit()
        return {str(row["file_hash"]) for row in rows}

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
        row = self._conn.execute("SELECT 1 FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            return False
        self._conn.execute("UPDATE invoices SET is_deleted = 1 WHERE id = ?", (invoice_id,))
        self._conn.commit()
        return True

    def delete_invoice_permanently(self, invoice_id: int) -> bool:
        """Delete an invoice row entirely."""
        row = self._conn.execute("SELECT 1 FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            return False
        self._conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
        self._conn.commit()
        return True

    def restore_invoice(self, invoice_id: int) -> bool:
        """Restore a soft-deleted invoice by setting is_deleted = 0."""
        row = self._conn.execute("SELECT 1 FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            return False
        self._conn.execute("UPDATE invoices SET is_deleted = 0 WHERE id = ?", (invoice_id,))
        self._conn.commit()
        return True


    def list_categories(self) -> list[str]:
        """Return distinct non-empty invoice categories already used in the database."""
        rows = self._conn.execute(
            "SELECT DISTINCT category FROM invoices "
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

    def update_invoice_fields(
        self,
        invoice_id: int,
        invoice_number: str,
        invoice_date: str,
        seller_name: str,
        total_amount: str,
        category: str,
        note: str = "",
        buyer_name: str | None = None,
    ) -> bool:
        """Update metadata fields of an invoice.

        Returns False if the invoice_id does not exist.
        """
        inv = self.get_invoice(invoice_id)
        if not inv:
            self._set_last_error("not_found")
            return False
        if buyer_name is None:
            buyer_name = str(inv.get("buyer_name") or "")

        try:
            self._conn.execute(
                "UPDATE invoices SET invoice_number=?, invoice_date=?, seller_name=?, buyer_name=?, "
                "total_amount=?, category=?, confirmed_note=? WHERE id=?",
                (invoice_number, invoice_date, seller_name, buyer_name, total_amount, category, note, invoice_id),
            )
            self._conn.commit()
            self._set_last_error("")
            return True
        except sqlite3.IntegrityError:
            self._set_last_error("unique_conflict")
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
    ) -> bool:
        """Refresh parsed metadata in-place without touching review status."""
        inv = self.get_invoice(invoice_id)
        if not inv:
            self._set_last_error("not_found")
            return False

        try:
            self._conn.execute(
                "UPDATE invoices SET invoice_number=?, invoice_code=?, invoice_date=?, amount=?, total_amount=?, "
                "seller_name=?, buyer_name=?, invoice_type=?, category=?, has_extra=?, extra_type=?, "
                "missing_extra=?, parse_success=?, parse_note=?, item_name=? WHERE id=?",
                (
                    invoice_number,
                    invoice_code,
                    invoice_date,
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
                    invoice_id,
                ),
            )
            self._conn.commit()
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

        values.append(invoice_id)
        self._conn.execute(
            f"UPDATE invoices SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        self._conn.commit()
        return True

    def update_invoice_extra_flags(
        self,
        invoice_id: int,
        *,
        has_extra: bool,
        missing_extra: bool,
    ) -> bool:
        """Synchronize evidence flags without changing parsed invoice metadata."""
        if not self.get_invoice(invoice_id):
            return False
        self._conn.execute(
            "UPDATE invoices SET has_extra = ?, missing_extra = ? WHERE id = ?",
            (int(bool(has_extra)), int(bool(missing_extra)), invoice_id),
        )
        self._conn.commit()
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

        self._conn.execute(
            f"UPDATE invoices SET attachment_path = ?{extra_sql} WHERE id = ?",
            values,
        )
        self._conn.commit()
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
                self._conn.execute(
                    f"UPDATE invoices SET {key} = ? WHERE id = ?",
                    (str(new_val).strip(), invoice_id),
                )
                self._conn.commit()
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
                "UPDATE invoices SET mail_sender=?, mail_subject=? WHERE file_hash=?",
                (sender, subject, file_hash),
            )
            updated += cur.rowcount
        self._conn.commit()
        return updated

    def list_invoices(self, status: str | None = None, limit: int | None = None, include_deleted: bool = False) -> list[dict]:
        """List invoices, optionally filtered by review status and limited to N records."""
        if status is not None and status not in review_status.ALL_STATUSES:
            raise ValueError(f"Invalid review status: '{status}'. Must be one of {review_status.ALL_STATUSES}")
        if limit is not None and limit <= 0:
            raise ValueError(f"Limit must be a positive integer. Got: {limit}")

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
        where_clauses = []
        params = []
        if not include_deleted:
            where_clauses.append("i.is_deleted = 0")
        if status is not None:
            where_clauses.append("i.review_status = ?")
            params.append(status)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY i.invoice_date DESC, i.id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def count_invoices(self, include_deleted: bool = False) -> int:
        if include_deleted:
            row = self._conn.execute("SELECT COUNT(*) AS cnt FROM invoices").fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS cnt FROM invoices WHERE is_deleted = 0").fetchone()
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

    def reset_invoices(self):
        """Clear the invoices table (full baseline reset)."""
        self._conn.execute("DELETE FROM invoices")
        self._conn.commit()
        _log.info("已清空已入库发票记录")

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
        if mailbox_key is None:
            self._conn.execute(
                f"DELETE FROM invoices WHERE mail_uid IN ({placeholders}) AND (attachment_path = '' OR attachment_path IS NULL)",
                uids
            )
        else:
            self._conn.execute(
                f"DELETE FROM invoices WHERE mailbox_key = ? AND mail_uid IN ({placeholders}) AND (attachment_path = '' OR attachment_path IS NULL)",
                [self._normalize_mailbox_key(mailbox_key), *uids],
            )
        self._conn.commit()

    # ── Claim Groups (CODE-004) ──────────────────────────────────────

    def create_claim_group(self, name: str, period_start: str = "", period_end: str = "") -> int:
        """Create a new claim group and return its auto-incremented ID."""
        cursor = self._conn.execute(
            "INSERT INTO claim_groups (name, period_start, period_end) VALUES (?, ?, ?)",
            (name, period_start, period_end)
        )
        self._conn.commit()
        return cursor.lastrowid

    def add_invoice_to_claim(self, claim_id: int, invoice_id: int, note: str = "") -> bool:
        """Map an invoice to a claim group. Returns False on IntegrityError (e.g. duplicate)."""
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            self._set_last_error("not_found")
            return False
        if is_pending_evidence_invoice(invoice):
            self._set_last_error("evidence_only")
            return False
        try:
            self._conn.execute(
                "INSERT INTO claim_group_items (claim_id, invoice_id, note) VALUES (?, ?, ?)",
                (claim_id, invoice_id, note)
            )
            self._conn.commit()
            self._set_last_error("")
            return True
        except sqlite3.IntegrityError:
            self._set_last_error("integrity_error")
            _log.info("Duplicate mapping: invoice_id %d already in claim_id %d", invoice_id, claim_id)
            return False

    def remove_invoice_from_claim(self, claim_id: int, invoice_id: int) -> bool:
        """Remove a mapped invoice from a claim group."""
        self._conn.execute(
            "DELETE FROM claim_group_items WHERE claim_id = ? AND invoice_id = ?",
            (claim_id, invoice_id)
        )
        self._conn.commit()
        return True

    def get_claim_group(self, claim_id: int) -> dict | None:
        """Fetch claim group details by ID."""
        row = self._conn.execute(
            "SELECT * FROM claim_groups WHERE id = ?",
            (claim_id,)
        ).fetchone()
        return dict(row) if row else None

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
        sql += " ORDER BY cgi.sort_order ASC, i.invoice_date DESC, i.id DESC"

        rows = self._conn.execute(sql, (claim_id,)).fetchall()
        return [dict(r) for r in rows]

    def add_export_run(self, claim_id: int, export_dir: str, export_type: str, item_count: int) -> int:
        """Log a claim export package generation run and return its ID."""
        cursor = self._conn.execute(
            "INSERT INTO export_runs (claim_id, export_dir, export_type, item_count) "
            "VALUES (?, ?, ?, ?)",
            (claim_id, export_dir, export_type, item_count)
        )
        self._conn.commit()
        return cursor.lastrowid

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
            if is_approved and not include_approved:
                skipped_approved += 1
                skip_reason = "approved"
            elif is_claimed and not include_claimed:
                skipped_claimed += 1
                skip_reason = "claimed"

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
            try:
                for inv_id in to_delete_ids:
                    # 先删除关联关系
                    self._conn.execute("DELETE FROM claim_group_items WHERE invoice_id = ?", (inv_id,))
                    # 后删除发票
                    self._conn.execute("DELETE FROM invoices WHERE id = ?", (inv_id,))
                self._conn.commit()
                deleted = len(to_delete_ids)
            except Exception as e:
                self._conn.rollback()
                raise e

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
                ORDER BY id ASC
            """
            rows = self._conn.execute(sql_fallback, (mail_uid,)).fetchall()
        return [dict(r) for r in rows]

    def link_evidence_to_invoice(self, invoice_id: int, evidence_id: int) -> bool:
        """Link a pending evidence record to an invoice in a transaction."""
        # 1. Fetch invoice & evidence
        invoice = self.get_invoice(invoice_id, include_deleted=False)
        if not invoice:
            _log.error("link_evidence_to_invoice: target invoice ID %s not found or deleted", invoice_id)
            return False

        evidence = self.get_invoice(evidence_id, include_deleted=False)
        if not evidence:
            _log.error("link_evidence_to_invoice: evidence record ID %s not found or deleted", evidence_id)
            return False

        if evidence.get("invoice_type") != "待关联证明材料":
            _log.error("link_evidence_to_invoice: record ID %s is not '待关联证明材料'", evidence_id)
            return False

        evidence_path = evidence.get("attachment_path")
        if not evidence_path:
            _log.error("link_evidence_to_invoice: evidence record ID %s has no attachment_path", evidence_id)
            return False

        # Check mail info match
        inv_mailbox = invoice.get("mailbox_key")
        inv_uid = invoice.get("mail_uid")
        ev_mailbox = evidence.get("mailbox_key")
        ev_uid = evidence.get("mail_uid")

        def norm_mailbox(key) -> str:
            if not key:
                return "legacy"
            k = str(key).strip().lower()
            if k in ("", "legacy"):
                return "legacy"
            return k

        # Check UID equivalence
        if inv_uid is None or ev_uid is None or int(inv_uid) != int(ev_uid) or norm_mailbox(inv_mailbox) != norm_mailbox(ev_mailbox):
            _log.warning(
                "link_evidence_to_invoice: Mail info mismatch! Target invoice (ID %s, mailbox: %s, UID: %s), Evidence (ID %s, mailbox: %s, UID: %s)",
                invoice_id, inv_mailbox, inv_uid, evidence_id, ev_mailbox, ev_uid
            )
            return False

        # 2. Extract and append evidence_path to invoice's extra_paths
        raw_extra = invoice.get("extra_paths")
        extra_paths = []
        if raw_extra:
            if isinstance(raw_extra, list):
                extra_paths = [str(p) for p in raw_extra if p]
            elif isinstance(raw_extra, str):
                try:
                    parsed = json.loads(raw_extra)
                    if isinstance(parsed, list):
                        extra_paths = [str(p) for p in parsed if p]
                    else:
                        extra_paths = [str(raw_extra)]
                except Exception:
                    extra_paths = [str(raw_extra)]
            else:
                extra_paths = [str(raw_extra)]

        # Deduplicate paths (ignoring case and path separators)
        seen_normalized = {str(p).lower().replace("\\", "/") for p in extra_paths}
        norm_ev_path = str(evidence_path).lower().replace("\\", "/")
        if norm_ev_path not in seen_normalized:
            extra_paths.append(str(evidence_path))

        # 3. Detect updated_at column availability
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(invoices)").fetchall()
        }

        # 4. Perform atomic updates in a transaction
        extra_paths_str = json.dumps(extra_paths, ensure_ascii=False)
        evidence_note = evidence.get("parse_note") or ""
        append_note = f"已关联到发票 ID {invoice_id}"
        new_evidence_note = f"{evidence_note}; {append_note}" if evidence_note else append_note

        try:
            # Update main invoice
            inv_sql = "UPDATE invoices SET extra_paths = ?, has_extra = 1, missing_extra = 0"
            inv_params = [extra_paths_str]
            if "updated_at" in columns:
                inv_sql += ", updated_at = CURRENT_TIMESTAMP"
            inv_sql += " WHERE id = ?"
            inv_params.append(invoice_id)
            self._conn.execute(inv_sql, tuple(inv_params))

            # Update evidence (soft delete)
            ev_sql = "UPDATE invoices SET is_deleted = 1, parse_note = ?"
            ev_params = [new_evidence_note]
            if "updated_at" in columns:
                ev_sql += ", updated_at = CURRENT_TIMESTAMP"
            ev_sql += " WHERE id = ?"
            ev_params.append(evidence_id)
            self._conn.execute(ev_sql, tuple(ev_params))

            self._conn.commit()
            return True
        except Exception as e:
            self._conn.rollback()
            _log.error("Failed to link evidence to invoice (transaction rolled back): %s", e)
            return False
