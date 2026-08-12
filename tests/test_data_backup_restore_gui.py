import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class DataBackupRestoreGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def make_window(self, root: Path) -> InvoiceReviewApp:
        window = InvoiceReviewApp(root / "invoices.db", splash=None)
        window.db._conn.execute("CREATE TABLE acceptance_marker (value TEXT NOT NULL)")
        window.db._conn.execute("INSERT INTO acceptance_marker(value) VALUES ('baseline')")
        window.db._conn.commit()
        return window

    def test_data_page_exposes_backup_restore_and_compact_secondary_actions(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(Path(td))
            try:
                labels = {button.text() for button in window.findChildren(QPushButton)}
                self.assertIn("创建数据库备份", labels)
                self.assertIn("恢复数据库备份", labels)
                self.assertIn("打开备份目录", labels)
                self.assertEqual(window.data_more.toolTip(), "更多数据操作")
            finally:
                window.close()

    def test_gui_backup_modify_restore_reloads_original_database_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            window = self.make_window(root)
            try:
                with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok):
                    window._create_database_backup_from_settings()
                backups = list((root / "backups").glob("*.db"))
                self.assertEqual(len(backups), 1)
                selected = backups[0]

                window.db._conn.execute("UPDATE acceptance_marker SET value = 'modified'")
                window.db._conn.commit()
                with (
                    patch(
                        "scripts.invoice_fetch.gui.app.QFileDialog.getOpenFileName",
                        return_value=(str(selected), ""),
                    ),
                    patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
                    patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
                ):
                    window._restore_database_backup_from_settings()

                value = window.db._conn.execute("SELECT value FROM acceptance_marker").fetchone()[0]
                self.assertEqual(value, "baseline")
                self.assertEqual(len(list((root / "backups").glob("*.db"))), 2)
            finally:
                window.close()

    def test_restore_is_blocked_while_an_owned_worker_is_running(self):
        class RunningWorker:
            @staticmethod
            def isRunning():
                return True

        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(Path(td))
            window.scan_worker = RunningWorker()
            try:
                with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok) as warning:
                    window._restore_database_backup_from_settings()
                self.assertIn("邮箱扫描", warning.call_args.args[2])
            finally:
                window.scan_worker = None
                window.close()

if __name__ == "__main__":
    unittest.main()
