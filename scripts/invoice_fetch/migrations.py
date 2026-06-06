"""Idempotent SQLite database migrations using PRAGMA user_version."""

from __future__ import annotations

import logging
import sqlite3

_log = logging.getLogger(__name__)


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
