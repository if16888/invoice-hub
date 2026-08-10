import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.hci_v1 import HciTaskCard, HistoryRecheckWorker
from scripts.invoice_fetch.gui.review_baseline_pipeline import (
    REVIEW_BASELINE_STAGES,
    REVIEW_HCI_STAGES,
)
from scripts.invoice_fetch.hci_v1_services import (
    _enabled_mailbox_keys,
    recheck_known_email_history,
)


class HciV1PurePolicyTests(unittest.TestCase):
    def test_enabled_mailbox_keys_are_stable_and_skip_disabled(self):
        cfg = {
            "email_accounts": [
                {"enabled": True, "mailbox_key": "a", "address": "a@example.com"},
                {"enabled": False, "mailbox_key": "b", "address": "b@example.com"},
                {"enabled": True, "mailbox_key": "a", "address": "duplicate@example.com"},
                {"enabled": True, "address": "c@example.com"},
            ]
        }
        self.assertEqual(_enabled_mailbox_keys(cfg), ["a", "c@example.com"])

    def test_history_recheck_is_bounded_and_does_not_use_global_reset(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "hci-history.db"
            with InvoiceDB(db_path) as db:
                db._conn.execute(
                    "INSERT INTO emails "
                    "(mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
                    "VALUES ('a', 101, 'Synthetic invoice', 'sender', '2026-08-01', 1, 1)"
                )
                db._conn.execute(
                    "INSERT INTO invoices "
                    "(mailbox_key, mail_uid, invoice_number, total_amount, review_status, is_deleted) "
                    "VALUES ('a', 101, 'SYN-101', '10.00', 'to_review', 1)"
                )
                db._conn.commit()

            cfg = {
                "email_accounts": [
                    {"enabled": True, "mailbox_key": "a", "address": "a@example.com"}
                ]
            }
            with patch(
                "scripts.invoice_fetch.hci_v1_services.load_config_safe",
                return_value=cfg,
            ), patch(
                "scripts.invoice_fetch.__main__._reprocess_email_records"
            ) as reprocess:
                result = recheck_known_email_history(
                    db_path,
                    since="2026-07-15",
                    selected_keys=["a"],
                    limit=20,
                )

            self.assertEqual(result["candidate_emails"], 1)
            self.assertFalse(result["limit_reached"])
            reprocess.assert_called_once()
            kwargs = reprocess.call_args.kwargs
            self.assertFalse(kwargs["include_approved"])
            self.assertFalse(kwargs["include_claimed"])
            self.assertFalse(kwargs["dry_run"])

    def test_history_recheck_requires_explicit_lower_bound(self):
        with self.assertRaises(ValueError):
            recheck_known_email_history("unused.db", since="")


class HciV1DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "hci-v1.db")
        window.resize(1600, 900)
        window.show()
        for _ in range(8):
            self.app.processEvents()
        return window

    def test_review_baseline_keeps_visual_final_then_runs_hci(self):
        self.assertEqual(REVIEW_BASELINE_STAGES[-1][0], "visual_language_v11")
        self.assertEqual(
            [name for name, _stage in REVIEW_HCI_STAGES],
            ["hci_v1_task_flow", "hci_v1_closure"],
        )

    def test_dashboard_exposes_task_cards_and_single_review_cta(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertTrue(window.overview_page.property("hciV1DashboardApplied"))
                self.assertTrue(window.overview_page.property("hciV1DashboardClosureApplied"))
                self.assertEqual(window.overview_header.lbl_title.text(), "今天需要处理什么")
                self.assertEqual(
                    set(window.hci_dashboard_task_cards),
                    {"to_review", "missing_evidence", "buyer_mismatch", "parse_error"},
                )
                self.assertTrue(
                    all(
                        isinstance(card, HciTaskCard)
                        for card in window.hci_dashboard_task_cards.values()
                    )
                )
                self.assertTrue(window.btn_hci_continue_tasks.text())
                duplicate_review_actions = [
                    button
                    for button in window.overview_page.findChildren(QPushButton)
                    if button.text().strip() == "开始审核" and button.isVisible()
                ]
                self.assertEqual(duplicate_review_actions, [])
                self.assertIn("重新检查", window.lbl_overview_next_actions.text())
                self.assertEqual(
                    window.overview_activity_card.lbl_title.text(),
                    "今天已完成",
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_continuous_review_retires_list_and_restores_it(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertTrue(window.review_page.property("reviewHciPipelineApplied"))
                self.assertTrue(window.review_page.property("hciV1ReviewApplied"))
                self.assertTrue(window.review_page.property("hciV1ReviewClosureApplied"))
                self.assertFalse(window.review_page.property("hciContinuousReview"))
                self.assertFalse(window._hci_shortcut_e.isEnabled())
                self.assertFalse(window._hci_shortcut_g.isEnabled())

                window._switch_main_page("review")
                self.app.processEvents()
                self.assertTrue(window.left_upper_widget.isVisible())

                window._enter_hci_continuous_review()
                self.app.processEvents()
                self.assertTrue(window.review_page.property("hciContinuousReview"))
                self.assertEqual(window.review_header.lbl_title.text(), "连续审核")
                self.assertFalse(window.left_upper_widget.isVisible())
                self.assertTrue(window.lbl_hci_review_progress.isVisible())
                self.assertTrue(window.btn_hci_review_later.isVisible())

                window._exit_hci_continuous_review()
                self.app.processEvents()
                self.assertFalse(window.review_page.property("hciContinuousReview"))
                self.assertEqual(window.review_header.lbl_title.text(), "发票审核")
                self.assertTrue(window.left_upper_widget.isVisible())
                self.assertFalse(window.btn_hci_review_later.isVisible())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_import_uses_visible_sync_cta_and_stable_scan_control(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertTrue(window.imports_page.property("hciV1ImportApplied"))
                self.assertTrue(window.imports_page.property("hciV1ImportClosureApplied"))
                self.assertIn(
                    window.btn_import_scan_selected.text(),
                    {"开始扫描", "补授权码"},
                )
                self.assertTrue(hasattr(window, "btn_hci_sync_new_mail"))
                self.assertIn(
                    window.btn_hci_sync_new_mail.text(),
                    {"同步新邮件", "补授权码"},
                )
                self.assertIs(
                    window.import_mail_command_bar.primary_action,
                    window.btn_hci_sync_new_mail,
                )
                self.assertTrue(hasattr(window, "btn_hci_import_recheck"))
                menu = window.btn_hci_import_recheck.menu()
                self.assertIsNotNone(menu)
                labels = [action.text() for action in menu.actions() if not action.isSeparator()]
                self.assertIn("重新检查最近 30 天", labels)
                self.assertIn("重新检查指定时间范围", labels)
                self.assertIn("重新处理最近 30 天已知附件", labels)
                self.assertTrue(hasattr(window, "btn_hci_import_review_result"))
                self.assertTrue(hasattr(window, "_hci_history_close_filter"))
                self.assertTrue(getattr(HistoryRecheckWorker, "_hci_safe_delete_installed", False))
                self.assertEqual(window.import_mail_recent_card.lbl_title.text(), "本次运行")
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
