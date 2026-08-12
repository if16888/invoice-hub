import tempfile
import time
import unittest
import sqlite3
from contextlib import closing
from unittest.mock import patch
from datetime import datetime
from pathlib import Path

from scripts.invoice_fetch.db_backup import (
    create_database_backup,
    create_verified_database_backup,
    prune_database_backups,
    restore_verified_database_backup,
    validate_sqlite_database,
)


class DatabaseBackupTests(unittest.TestCase):
    @staticmethod
    def make_sqlite(path: Path, value: str) -> None:
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("CREATE TABLE sample (value TEXT NOT NULL)")
            conn.execute("CREATE TABLE invoices (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO sample(value) VALUES (?)", (value,))
            conn.commit()

    @staticmethod
    def read_value(path: Path) -> str:
        with closing(sqlite3.connect(path)) as conn:
            return conn.execute("SELECT value FROM sample").fetchone()[0]

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

    def test_verified_backup_uses_sqlite_online_backup_and_passes_integrity_check(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            self.make_sqlite(db_path, "before")

            backup = create_verified_database_backup(db_path, backup_dir=root / "backups")

            validate_sqlite_database(backup)
            self.assertEqual(self.read_value(backup), "before")

    def test_restore_replaces_database_and_keeps_selected_and_safety_backups(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            selected = root / "selected.db"
            self.make_sqlite(db_path, "current")
            self.make_sqlite(selected, "restored")

            safety = restore_verified_database_backup(selected, db_path, backup_dir=root / "backups")

            self.assertEqual(self.read_value(db_path), "restored")
            self.assertEqual(self.read_value(safety), "current")
            self.assertEqual(self.read_value(selected), "restored")
            self.assertEqual(list(root.glob(".*.restore-staging*")), [])

    def test_restore_rejects_invalid_backup_without_touching_live_database(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            invalid = root / "invalid.db"
            self.make_sqlite(db_path, "current")
            invalid.write_bytes(b"not sqlite")

            with self.assertRaises(ValueError):
                restore_verified_database_backup(invalid, db_path, backup_dir=root / "backups")

            self.assertEqual(self.read_value(db_path), "current")
            self.assertFalse((root / "backups").exists())

    def test_restore_rejects_healthy_non_invoice_hub_sqlite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            unrelated = root / "unrelated.db"
            self.make_sqlite(db_path, "current")
            with closing(sqlite3.connect(unrelated)) as conn:
                conn.execute("CREATE TABLE unrelated (value TEXT)")
                conn.commit()

            with self.assertRaisesRegex(ValueError, "Invoice Hub"):
                restore_verified_database_backup(unrelated, db_path, backup_dir=root / "backups")

            self.assertEqual(self.read_value(db_path), "current")

    def test_restore_copy_failure_keeps_live_database_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            selected = root / "selected.db"
            self.make_sqlite(db_path, "current")
            self.make_sqlite(selected, "restored")

            with patch("scripts.invoice_fetch.db_backup.shutil.copy2", side_effect=OSError("copy failed")):
                with self.assertRaises(OSError):
                    restore_verified_database_backup(selected, db_path, backup_dir=root / "backups")

            self.assertEqual(self.read_value(db_path), "current")
            self.assertEqual(list(root.glob(".*.restore-staging*")), [])

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
