import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QBoxLayout, QSizePolicy

from scripts.invoice_fetch.gui.app import ImportActivity, InvoiceReviewApp
from scripts.invoice_fetch.gui.ui_components import (
    ActivityTimeline,
    MiddleElidedTextLabel,
    WrappedTextLabel,
)


class V016ResponsiveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "v016-responsive.db")
        window.resize(1366, 768)
        window.show()
        for _ in range(6):
            self.app.processEvents()
        window._switch_main_page("settings")
        for _ in range(4):
            self.app.processEvents()
        return window


    def test_import_activity_is_structured_for_complete_cancelled_and_failed(self):
        complete = ImportActivity(
            datetime.now(), "mail", scanned=21, classified=9, added=0,
            restored=0, duplicates=9, failed=0, status="complete",
        )
        cancelled = ImportActivity(datetime.now(), "mail", scanned=4, status="cancelled")
        failed = ImportActivity(datetime.now(), "mail", failed=1, status="failed")
        self.assertIn(("识别发票候选", "9"), InvoiceReviewApp._structured_import_fields(complete))
        self.assertIn(("状态", "已取消"), InvoiceReviewApp._structured_import_fields(cancelled))
        self.assertIn(("状态", "失败"), InvoiceReviewApp._structured_import_fields(failed))


if __name__ == "__main__":
    unittest.main()
