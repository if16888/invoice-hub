import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from scripts.invoice_fetch.db_backup import create_database_backup


class DatabaseBackupTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
