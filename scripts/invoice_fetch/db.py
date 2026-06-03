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

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(invoice_number, total_amount, seller_name)
);

CREATE TABLE IF NOT EXISTS emails (
    uid             INTEGER PRIMARY KEY,
    subject         TEXT NOT NULL DEFAULT '',
    sender          TEXT NOT NULL DEFAULT '',
    mail_date       TEXT NOT NULL DEFAULT '',
    is_invoice      INTEGER NOT NULL DEFAULT -1,
    classify_by     TEXT NOT NULL DEFAULT '',
    classify_reason TEXT NOT NULL DEFAULT '',
    downloaded      INTEGER NOT NULL DEFAULT 0,
    scanned_at      TEXT DEFAULT (datetime('now','localtime')),
    processed_at    TEXT
);

CREATE TABLE IF NOT EXISTS processed_emails (
    uid          INTEGER PRIMARY KEY,
    subject      TEXT,
    sender       TEXT,
    mail_date    TEXT,
    processed_at TEXT DEFAULT (datetime('now','localtime'))
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
        self._conn.executescript(_SCHEMA)
        _log.info("数据库已打开: %s", self._path.name)

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

    # ── Emails table (Phase 1: scan & classify) ──────────────────────

    def upsert_email(self, uid: int, subject: str,
                     sender: str, mail_date: str) -> bool:
        """Insert a scanned email header. Returns True if new."""
        try:
            self._conn.execute(
                "INSERT INTO emails (uid, subject, sender, mail_date) "
                "VALUES (?, ?, ?, ?)",
                (uid, subject, sender, mail_date),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def bulk_upsert_emails(self, rows: list[dict]) -> int:
        """Batch insert scanned headers. Returns count of new rows."""
        new = 0
        for r in rows:
            try:
                self._conn.execute(
                    "INSERT INTO emails (uid, subject, sender, mail_date) "
                    "VALUES (?, ?, ?, ?)",
                    (r["uid"], r["subject"], r["sender"], r["date"]),
                )
                new += 1
            except sqlite3.IntegrityError:
                pass
        self._conn.commit()
        return new

    def get_all_email_uids(self) -> set[int]:
        """Return all known UIDs in the emails table."""
        rows = self._conn.execute("SELECT uid FROM emails").fetchall()
        return {r[0] for r in rows}

    def get_unclassified_emails(self) -> list[dict]:
        """Return emails where is_invoice = -1 (unknown)."""
        rows = self._conn.execute(
            "SELECT uid, subject, sender, mail_date "
            "FROM emails WHERE is_invoice = -1"
        ).fetchall()
        return [dict(r) for r in rows]

    def classify_email(self, uid: int, is_invoice: bool,
                       by: str, reason: str = ""):
        """Set classification result for a single email."""
        self._conn.execute(
            "UPDATE emails SET is_invoice = ?, classify_by = ?, "
            "classify_reason = ? WHERE uid = ?",
            (1 if is_invoice else 0, by, reason, uid),
        )
        self._conn.commit()

    def bulk_classify(self, results: list[dict]):
        """Batch update classification results.

        Each dict: {uid, is_invoice (bool), by (str), reason (str)}
        """
        for r in results:
            self._conn.execute(
                "UPDATE emails SET is_invoice = ?, classify_by = ?, "
                "classify_reason = ? WHERE uid = ?",
                (1 if r["is_invoice"] else 0,
                 r.get("by", ""), r.get("reason", ""), r["uid"]),
            )
        self._conn.commit()

    def get_invoice_emails_to_download(self) -> list[dict]:
        """Return emails marked as invoice but not yet downloaded."""
        rows = self._conn.execute(
            "SELECT uid, subject, sender, mail_date "
            "FROM emails WHERE is_invoice = 1 AND downloaded = 0 "
            "ORDER BY mail_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_downloaded(self, uid: int):
        """Mark an email as downloaded/processed."""
        self._conn.execute(
            "UPDATE emails SET downloaded = 1, "
            "processed_at = datetime('now','localtime') WHERE uid = ?",
            (uid,),
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

    def is_email_processed(self, uid: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM processed_emails WHERE uid = ?", (uid,)
        ).fetchone()
        return row is not None

    def get_processed_uids(self) -> set[int]:
        rows = self._conn.execute("SELECT uid FROM processed_emails").fetchall()
        return {r[0] for r in rows}

    def mark_email_processed(self, uid: int, subject: str = "",
                             sender: str = "", mail_date: str = ""):
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_emails (uid, subject, sender, mail_date) "
            "VALUES (?, ?, ?, ?)",
            (uid, subject, sender, mail_date),
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
            "invoice_number", "invoice_code", "invoice_date",
            "amount", "total_amount", "seller_name", "buyer_name",
            "invoice_type", "category", "has_extra", "extra_type",
            "missing_extra", "mail_uid", "mail_subject", "mail_date",
            "mail_sender", "parse_success", "parse_note",
            "attachment_path", "extra_paths", "download_url",
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
        # Check existence
        inv = self.get_invoice(invoice_id)
        if not inv:
            return False
        if buyer_name is None:
            buyer_name = str(inv.get("buyer_name") or "")

        self._conn.execute(
            "UPDATE invoices SET invoice_number=?, invoice_date=?, seller_name=?, buyer_name=?, "
            "total_amount=?, category=?, confirmed_note=? WHERE id=?",
            (invoice_number, invoice_date, seller_name, buyer_name, total_amount, category, note, invoice_id)
        )
        self._conn.commit()
        return True

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
    ) -> bool:
        """Refresh parsed metadata in-place without touching review status."""
        inv = self.get_invoice(invoice_id)
        if not inv:
            return False

        self._conn.execute(
            "UPDATE invoices SET invoice_number=?, invoice_code=?, invoice_date=?, amount=?, total_amount=?, "
            "seller_name=?, buyer_name=?, invoice_type=?, category=?, has_extra=?, extra_type=?, "
            "missing_extra=?, parse_success=?, parse_note=? WHERE id=?",
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
                invoice_id,
            ),
        )
        self._conn.commit()
        return True

    def update_invoice_file_paths(
        self,
        invoice_id: int,
        attachment_path: str | None = None,
        extra_paths: list[str] | None = None,
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

        if not fields:
            return False

        values.append(invoice_id)
        self._conn.execute(
            f"UPDATE invoices SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        self._conn.commit()
        return True

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
            return self._conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
        else:
            return self._conn.execute("SELECT COUNT(*) FROM invoices WHERE is_deleted = 0").fetchone()[0]

    def count_processed(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM processed_emails").fetchone()[0]

    # ── Reset & dates ────────────────────────────────────────────────

    def get_last_scanned_date(self) -> str:
        """Most recent mail_date in the emails table."""
        row = self._conn.execute(
            "SELECT mail_date FROM emails "
            "WHERE mail_date != '' ORDER BY mail_date DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else ""

    def get_last_processed_date(self) -> str:
        """Return the most recent mail_date among processed emails (YYYY-MM-DD)."""
        row = self._conn.execute(
            "SELECT mail_date FROM processed_emails "
            "WHERE mail_date != '' ORDER BY mail_date DESC LIMIT 1"
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

    def get_failed_downloads(self) -> list[dict]:
        """Return invoices where attachment_path is empty or NULL,
        or emails marked as invoice but have no record in invoices table.
        """
        # 1. From invoices table where attachment_path is empty/NULL
        rows1 = self._conn.execute(
            "SELECT DISTINCT mail_uid FROM invoices WHERE attachment_path = '' OR attachment_path IS NULL"
        ).fetchall()
        uids = {r["mail_uid"] for r in rows1 if r["mail_uid"] is not None}

        # 2. From emails table where is_invoice = 1 AND downloaded = 1, but no invoices entry exists
        rows2 = self._conn.execute(
            "SELECT uid FROM emails WHERE is_invoice = 1 AND downloaded = 1"
        ).fetchall()
        for r in rows2:
            uid = r["uid"]
            inv = self._conn.execute(
                "SELECT 1 FROM invoices WHERE mail_uid = ?", (uid,)
            ).fetchone()
            if not inv:
                uids.add(uid)

        return [{"mail_uid": uid} for uid in sorted(uids)]

    def reset_emails_download_status(self, uids: list[int]):
        """Reset downloaded = 0 for a list of email UIDs."""
        if not uids:
            return
        placeholders = ", ".join("?" for _ in uids)
        self._conn.execute(
            f"UPDATE emails SET downloaded = 0 WHERE uid IN ({placeholders})",
            uids
        )
        self._conn.commit()

    def delete_invoices_by_uid(self, uids: list[int]):
        """Delete invoice records for a list of email UIDs where attachment_path is empty."""
        if not uids:
            return
        placeholders = ", ".join("?" for _ in uids)
        self._conn.execute(
            f"DELETE FROM invoices WHERE mail_uid IN ({placeholders}) AND (attachment_path = '' OR attachment_path IS NULL)",
            uids
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
        try:
            self._conn.execute(
                "INSERT INTO claim_group_items (claim_id, invoice_id, note) VALUES (?, ?, ?)",
                (claim_id, invoice_id, note)
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
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
