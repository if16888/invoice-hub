"""Idempotent SQLite database migrations using PRAGMA user_version."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping

_log = logging.getLogger(__name__)

LATEST_SCHEMA_VERSION = 7


# The legacy contract describes the stable Invoice Hub identity that existed
# before the current migration chain.  It deliberately does not require the
# latest tables or columns because old backups must be allowed to enter the
# private staging migration path.
LEGACY_SCHEMA_CONTRACT: dict[str, frozenset[str]] = {
    "invoices": frozenset(
        {
            "id",
            "invoice_number",
            "invoice_date",
            "amount",
            "total_amount",
            "seller_name",
            "buyer_name",
            "attachment_path",
        }
    ),
    "emails": frozenset(
        {"uid", "subject", "sender", "mail_date", "is_invoice", "downloaded"}
    ),
    "processed_emails": frozenset(
        {"uid", "subject", "sender", "mail_date", "processed_at"}
    ),
    "trusted_senders": frozenset({"sender"}),
}


# This is the application schema after all migrations have completed.  The
# contract intentionally checks required columns, but permits additional
# columns so that additive, backward-compatible fields do not invalidate an
# otherwise usable database.
LATEST_SCHEMA_CONTRACT: dict[str, frozenset[str]] = {
    "invoices": frozenset(
        {
            "id",
            "mailbox_key",
            "invoice_number",
            "invoice_code",
            "invoice_date",
            "expense_date",
            "date_source",
            "amount",
            "total_amount",
            "seller_name",
            "buyer_name",
            "invoice_type",
            "category",
            "has_extra",
            "extra_type",
            "missing_extra",
            "mail_uid",
            "mail_subject",
            "mail_date",
            "mail_sender",
            "parse_success",
            "parse_note",
            "attachment_path",
            "extra_paths",
            "download_url",
            "item_name",
            "is_deleted",
            "created_at",
            "review_status",
            "processing_status",
            "currency",
            "exchange_rate",
            "amount_home",
            "file_hash",
            "confirmed_at",
            "confirmed_note",
        }
    ),
    "emails": frozenset(
        {
            "id",
            "mailbox_key",
            "uid",
            "subject",
            "sender",
            "mail_date",
            "is_invoice",
            "classify_by",
            "classify_reason",
            "downloaded",
            "scanned_at",
            "processed_at",
        }
    ),
    "processed_emails": frozenset(
        {
            "id",
            "mailbox_key",
            "uid",
            "subject",
            "sender",
            "mail_date",
            "processed_at",
        }
    ),
    "trusted_senders": frozenset({"sender", "added_at"}),
    "claim_groups": frozenset(
        {"id", "name", "period_start", "period_end", "status", "created_at"}
    ),
    "claim_group_items": frozenset(
        {"id", "claim_id", "invoice_id", "sort_order", "note"}
    ),
    "export_runs": frozenset(
        {"id", "claim_id", "export_dir", "export_type", "item_count", "created_at"}
    ),
    "email_download_failures": frozenset(
        {
            "mailbox_key",
            "uid",
            "reason_code",
            "fail_count",
            "next_retry_at",
            "last_error_at",
            "last_error_summary",
        }
    ),
}


def _schema_snapshot(conn: sqlite3.Connection) -> tuple[int, dict[str, set[str]]]:
    """Return the user version and columns for every user table."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    tables: dict[str, set[str]] = {}
    for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall():
        table = str(row[0])
        quoted_table = table.replace('"', '""')
        columns = {
            str(column[1])
            for column in conn.execute(
                f'PRAGMA table_info("{quoted_table}")'
            ).fetchall()
        }
        tables[table] = columns
    return version, tables


def _validate_schema_snapshot(
    version: int,
    tables: Mapping[str, set[str]],
    contract: Mapping[str, frozenset[str]],
    *,
    expected_version: int | None = None,
) -> None:
    if version < 0 or version > LATEST_SCHEMA_VERSION:
        raise ValueError("所选数据库版本高于当前应用，无法安全恢复")
    if expected_version is not None and version != expected_version:
        raise ValueError("数据库未达到当前应用的架构版本")

    missing_tables = sorted(set(contract) - set(tables))
    missing_columns = {
        table: sorted(set(columns) - tables.get(table, set()))
        for table, columns in contract.items()
        if table in tables and set(columns) - tables.get(table, set())
    }
    if missing_tables or missing_columns:
        details: list[str] = []
        if missing_tables:
            details.append("缺少表 " + ", ".join(missing_tables))
        if missing_columns:
            details.extend(
                f"{table} 缺少字段 {', '.join(columns)}"
                for table, columns in sorted(missing_columns.items())
            )
        raise ValueError("Invoice Hub 数据库架构不完整：" + "；".join(details))


def validate_legacy_schema(conn: sqlite3.Connection) -> None:
    """Validate a supported pre-current-version Invoice Hub database."""
    version, tables = _schema_snapshot(conn)
    _validate_schema_snapshot(version, tables, LEGACY_SCHEMA_CONTRACT)


def validate_latest_schema(conn: sqlite3.Connection) -> None:
    """Validate the exact current version and required application schema."""
    version, tables = _schema_snapshot(conn)
    _validate_schema_snapshot(
        version,
        tables,
        LATEST_SCHEMA_CONTRACT,
        expected_version=LATEST_SCHEMA_VERSION,
    )


def check_and_migrate(conn: sqlite3.Connection):
    """Run database migrations in a safe, idempotent way using PRAGMA user_version."""
    cursor = conn.cursor()

    # 1. Fetch current schema version
    cursor.execute("PRAGMA user_version")
    version = cursor.fetchone()[0]

    _log.debug("Current database user_version: %d", version)

    # 2. Migration to V1: Add invoice review and multi-currency fields
    if version < 1:
        _log.info("Migrating database schema: V0 -> V1")
        try:
            # 2.1 Use PRAGMA table_info to inspect existing columns for invoices table
            cursor.execute("PRAGMA table_info(invoices)")
            existing_cols = {row[1] for row in cursor.fetchall()}

            # Columns requested for invoice review & currency metadata
            required_invoice_fields = [
                ("review_status", "TEXT NOT NULL DEFAULT 'to_review'"),
                ("processing_status", "TEXT NOT NULL DEFAULT ''"),
                ("currency", "TEXT NOT NULL DEFAULT ''"),
                ("exchange_rate", "TEXT NOT NULL DEFAULT ''"),
                ("amount_home", "TEXT NOT NULL DEFAULT ''"),
                ("file_hash", "TEXT NOT NULL DEFAULT ''"),
                ("confirmed_at", "TEXT NOT NULL DEFAULT ''"),
                ("confirmed_note", "TEXT NOT NULL DEFAULT ''"),
            ]

            # Idempotently add each missing column to invoices table
            for col_name, col_def in required_invoice_fields:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE invoices ADD COLUMN {col_name} {col_def}")
                    _log.info("Added database column [invoices.%s]", col_name)

            # 2.2 Only update PRAGMA user_version to 1 after successful migration
            cursor.execute("PRAGMA user_version = 1")
            conn.commit()
            _log.info("Database migration to V1 completed successfully.")
        except Exception as e:
            # Note: DDL statements (like ALTER TABLE) are autocommitted in SQLite and cannot be rolled back.
            # We call rollback() here only to roll back any open DML transaction state if applicable.
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass
            _log.exception("CRITICAL: Database migration to V1 failed! Error: %s", e)
            raise e

    # 3. Migration to V2: Add claim group, claim group items, and export runs
    if version < 2:
        _log.info("Migrating database schema: V1 -> V2")
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS claim_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    period_start TEXT DEFAULT '',
                    period_end TEXT DEFAULT '',
                    status TEXT DEFAULT 'draft',
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS claim_group_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id INTEGER NOT NULL,
                    invoice_id INTEGER NOT NULL,
                    sort_order INTEGER DEFAULT 0,
                    note TEXT DEFAULT '',
                    UNIQUE(claim_id, invoice_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS export_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id INTEGER,
                    export_dir TEXT NOT NULL,
                    export_type TEXT NOT NULL DEFAULT 'generic_excel',
                    item_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)

            cursor.execute("PRAGMA user_version = 2")
            conn.commit()
            _log.info("Database migration to V2 completed successfully.")
        except Exception as e:
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass
            _log.exception("CRITICAL: Database migration to V2 failed! Error: %s", e)
            raise e

    # 4. Migration to V3: Add is_deleted column to invoices table
    if version < 3:
        _log.info("Migrating database schema: V2 -> V3")
        try:
            cursor.execute("PRAGMA table_info(invoices)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "is_deleted" not in existing_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
                _log.info("Added database column [invoices.is_deleted]")
            cursor.execute("PRAGMA user_version = 3")
            conn.commit()
            _log.info("Database migration to V3 completed successfully.")
        except Exception as e:
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass
            _log.exception("CRITICAL: Database migration to V3 failed! Error: %s", e)
            raise e

    # 5. Migration to V4: mailbox namespace support for multiple IMAP accounts
    if version < 4:
        _log.info("Migrating database schema: V3 -> V4")
        try:
            cursor.execute("PRAGMA table_info(emails)")
            email_cols = {row[1] for row in cursor.fetchall()}
            if "mailbox_key" not in email_cols or "id" not in email_cols:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS emails_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        mailbox_key TEXT NOT NULL DEFAULT 'legacy',
                        uid INTEGER NOT NULL,
                        subject TEXT NOT NULL DEFAULT '',
                        sender TEXT NOT NULL DEFAULT '',
                        mail_date TEXT NOT NULL DEFAULT '',
                        is_invoice INTEGER NOT NULL DEFAULT -1,
                        classify_by TEXT NOT NULL DEFAULT '',
                        classify_reason TEXT NOT NULL DEFAULT '',
                        downloaded INTEGER NOT NULL DEFAULT 0,
                        scanned_at TEXT DEFAULT (datetime('now', 'localtime')),
                        processed_at TEXT,
                        UNIQUE(mailbox_key, uid)
                    )
                """)
                if "mailbox_key" in email_cols:
                    cursor.execute("""
                        INSERT OR IGNORE INTO emails_new (
                            mailbox_key, uid, subject, sender, mail_date,
                            is_invoice, classify_by, classify_reason,
                            downloaded, scanned_at, processed_at
                        )
                        SELECT
                            COALESCE(mailbox_key, 'legacy'),
                            uid, subject, sender, mail_date,
                            is_invoice, classify_by, classify_reason,
                            downloaded, scanned_at, processed_at
                        FROM emails
                    """)
                else:
                    cursor.execute("""
                        INSERT OR IGNORE INTO emails_new (
                            mailbox_key, uid, subject, sender, mail_date,
                            is_invoice, classify_by, classify_reason,
                            downloaded, scanned_at, processed_at
                        )
                        SELECT
                            'legacy',
                            uid, subject, sender, mail_date,
                            is_invoice, classify_by, classify_reason,
                            downloaded, scanned_at, processed_at
                        FROM emails
                    """)
                cursor.execute("DROP TABLE emails")
                cursor.execute("ALTER TABLE emails_new RENAME TO emails")
                _log.info("Rebuilt emails table with mailbox_key namespace")

            cursor.execute("PRAGMA table_info(processed_emails)")
            processed_cols = {row[1] for row in cursor.fetchall()}
            if "mailbox_key" not in processed_cols or "id" not in processed_cols:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_emails_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        mailbox_key TEXT NOT NULL DEFAULT 'legacy',
                        uid INTEGER NOT NULL,
                        subject TEXT,
                        sender TEXT,
                        mail_date TEXT,
                        processed_at TEXT DEFAULT (datetime('now', 'localtime')),
                        UNIQUE(mailbox_key, uid)
                    )
                """)
                if "mailbox_key" in processed_cols:
                    cursor.execute("""
                        INSERT OR IGNORE INTO processed_emails_new (
                            mailbox_key, uid, subject, sender, mail_date, processed_at
                        )
                        SELECT
                            COALESCE(mailbox_key, 'legacy'),
                            uid, subject, sender, mail_date, processed_at
                        FROM processed_emails
                    """)
                else:
                    cursor.execute("""
                        INSERT OR IGNORE INTO processed_emails_new (
                            mailbox_key, uid, subject, sender, mail_date, processed_at
                        )
                        SELECT
                            'legacy',
                            uid, subject, sender, mail_date, processed_at
                        FROM processed_emails
                    """)
                cursor.execute("DROP TABLE processed_emails")
                cursor.execute("ALTER TABLE processed_emails_new RENAME TO processed_emails")
                _log.info("Rebuilt processed_emails table with mailbox_key namespace")

            cursor.execute("PRAGMA table_info(invoices)")
            invoice_cols = {row[1] for row in cursor.fetchall()}
            if "mailbox_key" not in invoice_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN mailbox_key TEXT NOT NULL DEFAULT 'legacy'")
                cursor.execute("UPDATE invoices SET mailbox_key = 'legacy' WHERE COALESCE(mailbox_key, '') = ''")
                _log.info("Added database column [invoices.mailbox_key]")

            cursor.execute("PRAGMA user_version = 4")
            conn.commit()
            _log.info("Database migration to V4 completed successfully.")
        except Exception as e:
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass
            _log.exception("CRITICAL: Database migration to V4 failed! Error: %s", e)
            raise e

    # 6. Migration to V5: Add item_name column to invoices table
    if version < 5:
        _log.info("Migrating database schema: V4 -> V5")
        try:
            cursor.execute("PRAGMA table_info(invoices)")
            invoice_cols = {row[1] for row in cursor.fetchall()}
            if "item_name" not in invoice_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN item_name TEXT NOT NULL DEFAULT ''")
                _log.info("Added database column [invoices.item_name]")
            cursor.execute("PRAGMA user_version = 5")
            conn.commit()
            _log.info("Database migration to V5 completed successfully.")
        except Exception as e:
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass
            _log.exception("CRITICAL: Database migration to V5 failed! Error: %s", e)
            raise e

    # 7. Migration to V6: Add expense_date and date_source columns to invoices table
    if version < 6:
        _log.info("Migrating database schema: V5 -> V6")
        try:
            cursor.execute("PRAGMA table_info(invoices)")
            invoice_cols = {row[1] for row in cursor.fetchall()}
            if "expense_date" not in invoice_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN expense_date TEXT")
                _log.info("Added database column [invoices.expense_date]")
            if "date_source" not in invoice_cols:
                cursor.execute("ALTER TABLE invoices ADD COLUMN date_source TEXT")
                _log.info("Added database column [invoices.date_source]")

            # Backfill legacy/existing data
            cursor.execute("UPDATE invoices SET expense_date = invoice_date WHERE expense_date IS NULL OR expense_date = ''")
            cursor.execute("UPDATE invoices SET date_source = 'legacy' WHERE date_source IS NULL OR date_source = ''")

            cursor.execute("PRAGMA user_version = 6")
            conn.commit()
            _log.info("Database migration to V6 completed successfully.")
        except Exception as e:
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass
            _log.exception("CRITICAL: Database migration to V6 failed! Error: %s", e)
            raise e

    # 8. Migration to V7: Persist email download retry cooldowns
    if version < 7:
        _log.info("Migrating database schema: V6 -> V7")
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_download_failures (
                    mailbox_key TEXT NOT NULL DEFAULT 'legacy',
                    uid INTEGER NOT NULL,
                    reason_code TEXT NOT NULL DEFAULT '',
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT,
                    last_error_at TEXT NOT NULL DEFAULT '',
                    last_error_summary TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(mailbox_key, uid)
                )
            """)
            cursor.execute("PRAGMA user_version = 7")
            conn.commit()
            _log.info("Database migration to V7 completed successfully.")
        except Exception as e:
            try:
                conn.rollback()
            except sqlite3.OperationalError:
                pass
            _log.exception("CRITICAL: Database migration to V7 failed! Error: %s", e)
            raise e
