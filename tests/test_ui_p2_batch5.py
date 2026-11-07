"""Regression tests for P2 batch 5 (dialog shell, inspector title dedupe)."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_SPACING


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


_QAPP = None


class P2Batch5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_duplicate_and_seller_dialogs_share_the_shell(self):
        from scripts.invoice_fetch.gui.duplicate_review_dialog import DuplicateReviewDialog
        from scripts.invoice_fetch.gui.seller_preferences_dialog import SellerPreferencesDialog

        class StubDB:
            def list_duplicate_candidates(self, decision):
                return []

        expected_margins = (
            DESIGN_V1_SPACING["xl"],
            DESIGN_V1_SPACING["xl"],
            DESIGN_V1_SPACING["xl"],
            DESIGN_V1_SPACING["lg"],
        )
        duplicate = DuplicateReviewDialog(StubDB(), None, None, ())
        try:
            margins = duplicate.layout().contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                expected_margins,
            )
            titles = [
                label
                for label in duplicate.findChildren(QLabel)
                if label.text() == duplicate.windowTitle()
            ]
            self.assertEqual(len(titles), 1)
        finally:
            duplicate.deleteLater()

        seller = SellerPreferencesDialog([])
        try:
            margins = seller.layout().contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                expected_margins,
            )
            titles = [
                label
                for label in seller.findChildren(QLabel)
                if label.text() == seller.windowTitle()
            ]
            self.assertEqual(len(titles), 1)
        finally:
            seller.deleteLater()
        self.app.processEvents()

    def test_inspector_has_no_duplicate_visible_basic_info_heading(self):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "p2b5.db", splash=None)
            window.show()
            for _ in range(6):
                self.app.processEvents()
            try:
                detail = window._detail_panel
                headings = [
                    label
                    for label in detail.detail_core_section.findChildren(QLabel)
                    if label.text().strip() == "基本信息"
                ]
                self.assertEqual(headings, [])
            finally:
                window.db.close()
                window.hide()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
