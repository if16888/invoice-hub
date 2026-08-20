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

    def test_settings_long_text_wraps_and_paths_keep_middle_tooltip(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                privacy = window.lbl_settings_privacy
                explanatory = privacy.values["配置与日志"]
                self.assertTrue(explanatory.wordWrap())
                self.assertEqual(
                    explanatory.sizePolicy().verticalPolicy(),
                    QSizePolicy.Preferred,
                )
                self.assertGreater(explanatory.maximumHeight(), 1000)

                data_path = window.lbl_settings_data.values["数据目录"]
                self.assertIsInstance(data_path, MiddleElidedTextLabel)
                data_path.set_value("C:/Users/example/Documents/Invoice Hub/attachments")
                self.assertEqual(
                    data_path.toolTip(),
                    "C:/Users/example/Documents/Invoice Hub/attachments",
                )
            finally:
                window.close()
                self.app.processEvents()

    def test_settings_responsive_contract_stacks_narrow_shells(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window._apply_workbench_metrics(1000, 700)
                self.assertEqual(
                    window.settings_mailbox_shell.direction(),
                    QBoxLayout.TopToBottom,
                )
                self.assertEqual(window.mailbox_detail_surface.minimumWidth(), 0)
                self.assertEqual(window.settings_tabs.minimumWidth(), 0)

                window._apply_workbench_metrics(1366, 768)
                self.assertEqual(
                    window.settings_mailbox_shell.direction(),
                    QBoxLayout.LeftToRight,
                )
                self.assertEqual(window.mailbox_detail_surface.minimumWidth(), 560)
            finally:
                window.close()
                self.app.processEvents()

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

    def test_activity_timeline_details_are_accessible_and_bounded(self):
        timeline = ActivityTimeline()
        row = timeline.add_structured_entry(
            "23:28",
            "邮箱扫描",
            [("检查邮件", "21"), ("识别发票候选", "9"), ("失败", "0")],
            state="success",
        )
        labels = {label.text() for label in row.findChildren(QLabel)}
        self.assertTrue({"检查邮件", "识别发票候选", "失败", "21", "9", "0"}.issubset(labels))
        self.assertEqual(row.property("state"), "success")

    def test_wrapped_text_label_uses_preferred_height(self):
        label = WrappedTextLabel("隐私边界说明：" + "不会发送正文、附件或本地路径。" * 4)
        self.assertTrue(label.wordWrap())
        self.assertEqual(label.sizePolicy().verticalPolicy(), QSizePolicy.Preferred)
        self.assertGreater(label.maximumHeight(), 1000)


if __name__ == "__main__":
    unittest.main()
