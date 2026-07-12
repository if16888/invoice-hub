import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from scripts.invoice_fetch.gui.app import InvoiceReviewApp


class SettingsFeedbackFixesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "settings-feedback.db")
        window.resize(1600, 900)
        window.show()
        for _ in range(8):
            self.app.processEvents()
        window._switch_main_page("settings")
        for _ in range(3):
            self.app.processEvents()
        return window

    def test_simple_settings_pages_have_one_heading_contract(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for index, attr in (
                    (2, "lbl_settings_runtime"),
                    (3, "lbl_settings_privacy"),
                    (4, "lbl_settings_data"),
                    (5, "lbl_settings_about"),
                ):
                    page = window.settings_tabs.widget(index)
                    surface = getattr(window, attr)
                    self.assertTrue(page.property("singleHeadingContract"), index)
                    self.assertTrue(surface.property("headerDeduplicated"), index)
                    duplicate_labels = [
                        label
                        for label in surface.findChildren(QLabel)
                        if label.property("class") in {"SettingsSurfaceTitle", "SettingsSurfaceHint"}
                    ]
                    self.assertTrue(duplicate_labels, index)
                    self.assertTrue(all(label.isHidden() for label in duplicate_labels), index)
            finally:
                window.close()

    def test_about_page_has_only_one_visible_about_heading(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.settings_tabs.setCurrentIndex(5)
                for _ in range(2):
                    self.app.processEvents()
                page = window.settings_tabs.widget(5)
                visible_about = [
                    label
                    for label in page.findChildren(QLabel)
                    if label.text().strip() == "关于" and not label.isHidden()
                ]
                self.assertEqual(len(visible_about), 1)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
