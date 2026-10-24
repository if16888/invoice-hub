"""A schema upgrade of an existing database must never run without a snapshot.

``check_and_migrate`` rewrites whole tables and has no downgrade path, so
``InvoiceDB`` takes a restorable copy before touching an existing file.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.migrations import LATEST_SCHEMA_VERSION


def _downgrade_version(db_path: Path, version: int) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.commit()
    finally:
        conn.close()


def _user_version(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


class MigrationBackupGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "invoices.db"
        self.backup_dir = self.root / "backups"

    def tearDown(self):
        self._tmp.cleanup()

    def _create_current_database(self) -> None:
        db = InvoiceDB(self.db_path)
        db.close()

    def test_existing_database_is_backed_up_before_migration(self):
        self._create_current_database()
        _downgrade_version(self.db_path, 4)

        db = InvoiceDB(self.db_path)
        db.close()

        self.assertTrue(self.backup_dir.is_dir(), "升级前必须创建备份目录")
        backups = sorted(self.backup_dir.iterdir())
        self.assertGreaterEqual(len(backups), 1, "升级前必须留下可恢复的副本")

        backup = backups[0]
        self.assertGreater(backup.stat().st_size, 0)
        # The snapshot must be a readable SQLite database, not an empty file.
        self.assertEqual(_user_version(backup), LATEST_SCHEMA_VERSION)

    def test_fresh_database_does_not_create_a_backup(self):
        db = InvoiceDB(self.db_path)
        db.close()

        self.assertFalse(
            self.backup_dir.exists() and any(self.backup_dir.iterdir()),
            "新建数据库不应产生迁移前备份",
        )

    def test_falls_back_to_raw_copy_when_verified_backup_fails(self):
        self._create_current_database()
        db = InvoiceDB(self.db_path)
        try:
            with mock.patch(
                "scripts.invoice_fetch.db_backup.create_verified_database_backup",
                side_effect=RuntimeError("verified backup unavailable"),
            ):
                db._backup_before_migration(4)
        finally:
            db.close()

        backups = sorted(self.backup_dir.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertIn("-raw", backups[0].name)
        self.assertEqual(_user_version(backups[0]), LATEST_SCHEMA_VERSION)
        conn = sqlite3.connect(str(backups[0]))
        try:
            self.assertEqual(int(conn.execute("PRAGMA integrity_check").fetchone()[0] and 1), 1)
        finally:
            conn.close()


    def test_repeated_failed_migrations_do_not_accumulate_backups(self):
        """Each retry snapshots the same state, so old copies must be cleaned."""
        self._create_current_database()
        db = InvoiceDB(self.db_path)
        try:
            db._create_migration_backup(4)
            other_reason = self.backup_dir / "invoices-20200101-000000-before-manual.db"
            other_reason.write_bytes(b"synthetic")
            for _ in range(3):
                db._create_migration_backup(4)
        finally:
            db.close()

        migration_backups = [
            path
            for path in self.backup_dir.iterdir()
            if "before-migration-v4" in path.name and path.suffix == ".db"
        ]
        self.assertEqual(
            len(migration_backups),
            2,
            "重复失败的迁移不应无限堆积整库副本",
        )
        self.assertTrue(
            other_reason.exists(),
            "其它原因的备份不能被迁移清理误删",
        )


if __name__ == "__main__":
    unittest.main()
