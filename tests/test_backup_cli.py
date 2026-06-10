import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.invoice_fetch import backup_cli


class BackupCliTests(unittest.TestCase):
    def test_backup_cli_creates_backup_and_prunes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            backup_dir = root / "backups"
            db_path.write_bytes(b"db")

            result = backup_cli.main([
                "--db", str(db_path),
                "--backup-dir", str(backup_dir),
                "--reason", "cli-test",
                "--keep-backups", "3",
                "--quiet",
            ])

            self.assertEqual(result, 0)
            backups = list(backup_dir.glob("*.db"))
            self.assertEqual(len(backups), 1)
            self.assertIn("before-cli-test", backups[0].name)
            self.assertEqual(backups[0].read_bytes(), b"db")

    def test_backup_cli_returns_error_for_missing_database(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = backup_cli.main([
                "--db", str(root / "missing.db"),
                "--backup-dir", str(root / "backups"),
                "--quiet",
            ])

            self.assertEqual(result, 2)

    def test_backup_cli_rejects_zero_keep_without_no_prune(self):
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr"):
                backup_cli.main(["--keep-backups", "0"])

    def test_backup_cli_allows_zero_keep_with_no_prune(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "invoices.db"
            db_path.write_bytes(b"db")

            result = backup_cli.main([
                "--db", str(db_path),
                "--backup-dir", str(root / "backups"),
                "--keep-backups", "0",
                "--no-prune",
                "--quiet",
            ])

            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
