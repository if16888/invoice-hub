import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QMessageBox
from PySide6.QtCore import QAbstractAnimation

from scripts.invoice_fetch.gui.app import (
    DATA_STATUS_BADGES,
    REVIEW_STATUS_BADGES,
    InvoiceReviewApp,
)


class ReviewFeedbackPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_review_and_data_badges_include_semantic_color_and_icon(self):
        for badge_map in (REVIEW_STATUS_BADGES, DATA_STATUS_BADGES):
            for badge in badge_map.values():
                self.assertTrue(badge["icon"])
                self.assertTrue(badge["fill"].startswith("#"))
                self.assertTrue(badge["stroke"].startswith("#"))

    def test_approval_status_has_icon_and_short_feedback_pulse(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "feedback.db")
            try:
                window._detail_panel._update_status_badge("approved")
                self.assertEqual(window.lbl_sum_status.text(), "✓ 已通过")

                window._animate_approval_feedback()
                self.assertIsInstance(window._detail_panel.btn_app.graphicsEffect(), QGraphicsOpacityEffect)
                animation = window._approval_feedback_animation
                self.assertEqual(animation.duration(), 190)
                self.app.processEvents()
                self.assertEqual(animation.state(), QAbstractAnimation.State.Running)
                self.app.processEvents()
                animation.stop()
            finally:
                window.close()
                self.app.processEvents()

    def test_successful_batch_approval_triggers_the_same_feedback_pulse(self):
        with tempfile.TemporaryDirectory() as td:
            window = InvoiceReviewApp(Path(td) / "batch-feedback.db")
            try:
                window.center_stack.setCurrentWidget(window.review_page)
                window._selected_batch_invoice_ids = lambda: (7,)
                window._persist_invoice_note = Mock(return_value=True)
                window._capture_live_selection_invoice_id = Mock(return_value=7)
                window._load_invoices = Mock()
                window._refresh_overview_page = Mock()
                window._animate_approval_feedback = Mock()
                plan = SimpleNamespace(eligible_ids=(7,), skipped=(), requested_ids=(7,))
                outcome = SimpleNamespace(changed_ids=(7,), skipped=())
                with patch("scripts.invoice_fetch.batch_review.prepare_batch_approval", return_value=plan), \
                     patch("scripts.invoice_fetch.batch_review.apply_batch_approval", return_value=outcome), \
                     patch("scripts.invoice_fetch.gui.app.QMessageBox.question", return_value=QMessageBox.Yes):
                    result = window._run_batch_approval(all_matching=False)

                self.assertEqual(result["success"], 1)
                window._animate_approval_feedback.assert_called_once()
            finally:
                window.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
