import tempfile
import time
import unittest
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.db_backup import (
    DatabaseBackupError,
    DatabaseRestoreError,
    create_database_backup,
    create_verified_database_backup,
    prune_database_backups,
    restore_verified_database_backup,
    validate_sqlite_database,
)
from scripts.invoice_fetch.migrations import LATEST_SCHEMA_VERSION, validate_latest_schema


class DatabaseBackupTests(unittest.TestCase):
    @staticmethod
    def make_database(path: Path, value: str = "current") -> None:
        db = InvoiceDB(path)
        db._conn.execute("CREATE TABLE acceptance_marker (value TEXT NOT NULL)")
        db._conn.execute("INSERT INTO acceptance_marker(value) VALUES (?)", (value,))
        db._conn.commit()
        db.close()

    @staticmethod
    def read_value(path: Path) -> str:
        with closing(sqlite3.connect(path)) as conn:
            return conn.execute("SELECT value FROM acceptance_marker").fetchone()[0]

    @staticmethod
    def make_legacy_database(path: Path) -> None:
        """Create the initial public-release schema before migrations ran."""
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(
                """
                CREATE TABLE invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT,
                    invoice_code TEXT,
                    invoice_date TEXT,
                    amount TEXT,
                    total_amount TEXT,
                    seller_name TEXT,
                    buyer_name TEXT,
                    invoice_type TEXT,
                    category TEXT DEFAULT '其他',
                    has_extra INTEGER DEFAULT 0,
                    extra_type TEXT DEFAULT '',
                    missing_extra INTEGER DEFAULT 0,
                    mail_uid INTEGER,
                    mail_subject TEXT,
                    mail_date TEXT,
                    mail_sender TEXT,
                    parse_success INTEGER DEFAULT 0,
                    parse_note TEXT DEFAULT '',
                    attachment_path TEXT DEFAULT '',
                    extra_paths TEXT DEFAULT '[]',
                    download_url TEXT DEFAULT '',
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    UNIQUE(invoice_number, total_amount, seller_name)
                );
                CREATE TABLE emails (
                    uid INTEGER PRIMARY KEY,
                    subject TEXT NOT NULL DEFAULT '',
                    sender TEXT NOT NULL DEFAULT '',
                    mail_date TEXT NOT NULL DEFAULT '',
                    is_invoice INTEGER NOT NULL DEFAULT -1,
                    classify_by TEXT NOT NULL DEFAULT '',
                    classify_reason TEXT NOT NULL DEFAULT '',
                    downloaded INTEGER NOT NULL DEFAULT 0,
                    scanned_at TEXT DEFAULT (datetime('now','localtime')),
                    processed_at TEXT
                );
                CREATE TABLE processed_emails (
                    uid INTEGER PRIMARY KEY,
                    subject TEXT,
                    sender TEXT,
                    mail_date TEXT,
                    processed_at TEXT DEFAULT (datetime('now','localtime'))
                );
                CREATE TABLE trusted_senders (
                    sender TEXT PRIMARY KEY,
                    added_at TEXT DEFAULT (datetime('now','localtime'))
                );
                PRAGMA user_version = 0;
                """
            )
            conn.commit()

    def test_verified_backup_accepts_legacy_schema_and_migrates_private_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = root / "legacy.db"
            self.make_legacy_database(legacy)

            backup = create_verified_database_backup(
                legacy,
                backup_dir=root / "backups",
            )

            with closing(sqlite3.connect(backup)) as conn:
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    LATEST_SCHEMA_VERSION,
                )
                validate_latest_schema(conn)

    def test_create_database_backup_copies_file_with_sanitized_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            backup_dir = root / "backups"
            db_path.write_bytes(b"sqlite-db-content")

            backup_path = create_database_backup(
                db_path,
                backup_dir=backup_dir,
                reason="before mobile import / unsafe chars",
                now=datetime(2026, 6, 9, 12, 34, 56),
            )

            self.assertEqual(backup_path.read_bytes(), b"sqlite-db-content")
            self.assertEqual(backup_path.parent, backup_dir)
            self.assertEqual(
                backup_path.name,
                "invoices-20260609-123456-before-before-mobile-import-unsafe-chars.db",
            )

    def test_create_database_backup_does_not_overwrite_existing_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            backup_dir = root / "backups"
            db_path.write_bytes(b"first")

            first = create_database_backup(
                db_path,
                backup_dir=backup_dir,
                reason="migration",
                now=datetime(2026, 6, 9, 12, 0, 0),
            )
            db_path.write_bytes(b"second")
            second = create_database_backup(
                db_path,
                backup_dir=backup_dir,
                reason="migration",
                now=datetime(2026, 6, 9, 12, 0, 0),
            )

            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), b"first")
            self.assertEqual(second.read_bytes(), b"second")
            self.assertTrue(second.name.endswith("-1.db"))

    def test_create_database_backup_rejects_missing_database(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.db"

            with self.assertRaises(FileNotFoundError):
                create_database_backup(missing, backup_dir=Path(td) / "backups")

    def test_verified_backup_uses_sqlite_online_backup_and_migrates_private_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            self.make_database(db_path, "before")

            backup = create_verified_database_backup(db_path, backup_dir=root / "backups")

            validate_sqlite_database(backup)
            self.assertEqual(self.read_value(backup), "before")
            with closing(sqlite3.connect(backup)) as conn:
                self.assertEqual(
                    conn.execute("PRAGMA user_version").fetchone()[0],
                    LATEST_SCHEMA_VERSION,
                )
                validate_latest_schema(conn)

    def test_restore_rejects_latest_database_missing_business_table_without_touching_live_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            selected = root / "selected.db"
            self.make_database(db_path, "current")
            self.make_database(selected, "invalid")
            with closing(sqlite3.connect(selected)) as conn:
                conn.execute("DROP TABLE claim_groups")
                conn.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}")
                conn.commit()

            live_before = db_path.read_bytes()
            with self.assertRaises(DatabaseBackupError) as caught:
                restore_verified_database_backup(
                    selected,
                    db_path,
                    backup_dir=root / "backups",
                )

            self.assertIn("架构不完整", str(caught.exception))
            self.assertEqual(db_path.read_bytes(), live_before)
            self.assertEqual(self.read_value(db_path), "current")
            self.assertEqual(list(root.glob(".*.restore-*.tmp")), [])

    def test_restore_rejects_latest_database_with_malformed_invoices_without_touching_live_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            selected = root / "selected.db"
            self.make_database(db_path, "current")
            self.make_database(selected, "invalid")
            with closing(sqlite3.connect(selected)) as conn:
                conn.execute("DROP TABLE invoices")
                conn.execute("CREATE TABLE invoices (id INTEGER)")
                conn.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}")
                conn.commit()

            live_before = db_path.read_bytes()
            with self.assertRaises(ValueError) as caught:
                restore_verified_database_backup(
                    selected,
                    db_path,
                    backup_dir=root / "backups",
                )

            self.assertIn("架构不完整", str(caught.exception))
            self.assertEqual(db_path.read_bytes(), live_before)
            self.assertEqual(self.read_value(db_path), "current")
            self.assertEqual(list(root.glob(".*.restore-*.tmp")), [])

    def test_restore_replaces_database_and_keeps_selected_and_safety_backups(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            selected = root / "selected.db"
            self.make_database(db_path, "current")
            self.make_database(selected, "restored")

            safety = restore_verified_database_backup(selected, db_path, backup_dir=root / "backups")

            self.assertEqual(self.read_value(db_path), "restored")
            self.assertEqual(self.read_value(safety), "current")
            self.assertEqual(self.read_value(selected), "restored")
            self.assertEqual(list(root.glob(".*.restore-*.tmp")), [])

    def test_restore_sidecar_protection_failure_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            selected = root / "selected.db"
            self.make_database(db_path, "current")
            self.make_database(selected, "restored")
            with patch(
                "scripts.invoice_fetch.db_backup._move_existing_sidecars",
                side_effect=DatabaseRestoreError("synthetic sidecar failure"),
            ):
                with self.assertRaises(DatabaseRestoreError):
                    restore_verified_database_backup(selected, db_path, backup_dir=root / "backups")

            self.assertEqual(self.read_value(db_path), "current")
            self.assertEqual(list(root.glob(".*.restore-*.tmp")), [])

    def test_restore_reopen_failure_rolls_back_database_and_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            selected = root / "selected.db"
            self.make_database(db_path, "current")
            self.make_database(selected, "restored")
            wal = db_path.with_name(db_path.name + "-wal")
            moved_wal = root / ".invoices.db.restore-sidecar-wal.tmp"
            moved_wal.write_text("wal-sentinel", encoding="utf-8")

            def fail_reopen(_path):
                raise RuntimeError("synthetic reopen failure")

            with patch(
                "scripts.invoice_fetch.db_backup._move_existing_sidecars",
                return_value={wal: moved_wal},
            ):
                with self.assertRaises(DatabaseRestoreError) as caught:
                    restore_verified_database_backup(
                        selected,
                        db_path,
                        backup_dir=root / "backups",
                        reopen_validator=fail_reopen,
                    )

            self.assertEqual(wal.read_text(encoding="utf-8"), "wal-sentinel")
            self.assertEqual(self.read_value(db_path), "current")
            self.assertNotIn(str(root), str(caught.exception))
            self.assertEqual(list(root.glob(".*.restore-*.tmp")), [])

    def test_restore_copy_failure_keeps_live_database_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            selected = root / "selected.db"
            self.make_database(db_path, "current")
            self.make_database(selected, "restored")

            with patch("scripts.invoice_fetch.db_backup.shutil.copy2", side_effect=OSError("copy failed")):
                with self.assertRaises(DatabaseRestoreError):
                    restore_verified_database_backup(selected, db_path, backup_dir=root / "backups")

            self.assertEqual(self.read_value(db_path), "current")
            self.assertEqual(list(root.glob(".*.restore-*.tmp")), [])

    def test_prune_database_backups_keeps_newest_files(self):
        with tempfile.TemporaryDirectory() as td:
            backup_dir = Path(td) / "backups"
            backup_dir.mkdir()
            files = []
            for idx in range(5):
                path = backup_dir / f"invoices-{idx}.db"
                path.write_text(str(idx), encoding="utf-8")
                mtime = time.time() + idx
                path.touch()
                path_stat_time = mtime
                import os
                os.utime(path, (path_stat_time, path_stat_time))
                files.append(path)
            ignored = backup_dir / "notes.txt"
            ignored.write_text("keep", encoding="utf-8")

            removed = prune_database_backups(backup_dir, keep=2)

            self.assertEqual({p.name for p in removed}, {"invoices-0.db", "invoices-1.db", "invoices-2.db"})
            self.assertTrue((backup_dir / "invoices-3.db").exists())
            self.assertTrue((backup_dir / "invoices-4.db").exists())
            self.assertTrue(ignored.exists())

    def test_prune_database_backups_rejects_negative_keep(self):
        with self.assertRaises(ValueError):
            prune_database_backups(keep=-1)


if __name__ == "__main__":
    unittest.main()
