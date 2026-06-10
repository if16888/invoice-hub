import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from scripts.invoice_fetch.db_backup import create_database_backup, prune_database_backups


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
