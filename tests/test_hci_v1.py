import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QSignalBlocker
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QPushButton, QWidget

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.hci_v1 import (
    DateRangeDialog,
    HciTaskCard,
    HistoryRecheckWorker,
    _start_custom_range_recheck,
    _history_recheck_failed,
    _history_recheck_finished,
    _start_history_recheck,
)
from scripts.invoice_fetch.gui.hci_v1_closure import (
    _render_scan_active,
    _render_scan_terminal,
)
from scripts.invoice_fetch.gui.review_baseline_pipeline import (
    REVIEW_BASELINE_STAGES,
    REVIEW_HCI_STAGES,
)
from scripts.invoice_fetch.hci_v1_services import (
    _enabled_mailbox_keys,
    recheck_known_email_history,
)
from scripts.invoice_fetch.review_status import APPROVED, ERROR, IGNORED, TO_REVIEW


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

    def test_continuous_review_progress_refreshes_from_successful_mutations(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for index in range(5):
                    window.db.insert_invoice(
                        {
                            "invoice_number": f"HCI-{index}",
                            "total_amount": "10.00",
                            "seller_name": "Synthetic Seller",
                            "invoice_date": "2026-08-01",
                            "review_status": TO_REVIEW,
                        }
                    )
                window.db._conn.commit()
                window._is_first_load = False
                window._switch_main_page("review")
                window._change_filter(TO_REVIEW)
                self.app.processEvents()
                window._enter_hci_continuous_review()
                self.app.processEvents()
                self.assertIn("1 / 5", window.lbl_hci_review_progress.text())
                self.assertIn("还剩 5", window.lbl_hci_review_progress.text())

                with patch(
                    "scripts.invoice_fetch.gui.app.QMessageBox.question",
                    return_value=QMessageBox.Yes,
                ):
                    for status, expected in (
                        (APPROVED, ("2 / 5", "还剩 4")),
                        (IGNORED, ("3 / 5", "还剩 3")),
                        (ERROR, ("4 / 5", "还剩 2")),
                    ):
                        window._ensure_single_row_selection(0)
                        with QSignalBlocker(window.table):
                            result = window._set_selected_status(status)
                        self.assertEqual(result["success"], 1)
                        self.app.processEvents()
                        self.assertIn(expected[0], window.lbl_hci_review_progress.text())
                        self.assertIn(expected[1], window.lbl_hci_review_progress.text())

                    for expected in (("5 / 5", "还剩 1"), ("5 / 5", "本轮已完成")):
                        window._ensure_single_row_selection(0)
                        with QSignalBlocker(window.table):
                            result = window._set_selected_status(APPROVED)
                        self.assertEqual(result["success"], 1)
                        self.app.processEvents()
                        self.assertIn(expected[0], window.lbl_hci_review_progress.text())
                        self.assertIn(expected[1], window.lbl_hci_review_progress.text())

                window._exit_hci_continuous_review()
                for index in range(2):
                    window.db.insert_invoice(
                        {
                            "invoice_number": f"HCI-RESET-{index}",
                            "total_amount": "10.00",
                            "seller_name": "Synthetic Seller",
                            "invoice_date": "2026-08-01",
                            "review_status": TO_REVIEW,
                        }
                    )
                window.db._conn.commit()
                window._change_filter(TO_REVIEW)
                window._enter_hci_continuous_review()
                self.app.processEvents()
                self.assertIn("1 / 2", window.lbl_hci_review_progress.text())
                self.assertIn("还剩 2", window.lbl_hci_review_progress.text())
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

    def test_continuous_review_progress_does_not_advance_on_failed_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.db.insert_invoice(
                    {
                        "invoice_number": "HCI-FAILED",
                        "total_amount": "10.00",
                        "seller_name": "Synthetic Seller",
                        "invoice_date": "2026-08-01",
                        "review_status": TO_REVIEW,
                    }
                )
                window.db._conn.commit()
                window._is_first_load = False
                window._switch_main_page("review")
                window._change_filter(TO_REVIEW)
                self.app.processEvents()
                window._enter_hci_continuous_review()
                window._ensure_single_row_selection(0)
                with (
                    patch(
                        "scripts.invoice_fetch.gui.app.QMessageBox.question",
                        return_value=QMessageBox.Yes,
                    ),
                    patch.object(window.db, "update_invoice_review_status", return_value=False),
                ):
                    result = window._set_selected_status(APPROVED)
                self.assertEqual(result["success"], 0)
                self.app.processEvents()
                self.assertIn("1 / 1", window.lbl_hci_review_progress.text())
                self.assertIn("还剩 1", window.lbl_hci_review_progress.text())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_scan_hci_presentation_maps_active_and_terminal_states(self):
        class RecentCard:
            def __init__(self):
                self.title = ""
                self.hint = ""

            def set_title(self, value):
                self.title = value

            def set_hint(self, value):
                self.hint = value

        recent = RecentCard()
        window = SimpleNamespace(
            lbl_import_scan_status=QLabel(),
            import_mail_recent_card=recent,
            _hci_scan_terminal_stage=None,
            _scan_stage_counts={"processed": 4, "total": 10},
            _scan_started_at=time.monotonic() - 493.7,
        )
        _render_scan_active(window, "download", 493.7)
        self.assertIn("正在同步", window.lbl_import_scan_status.text())
        self.assertIn("下载附件", window.lbl_import_scan_status.text())
        self.assertIn("8分13秒", window.lbl_import_scan_status.text())
        window._hci_scan_terminal_stage = None
        _render_scan_active(window, "save", 535.6)
        self.assertIn("保存扫描结果", window.lbl_import_scan_status.text())

        _render_scan_terminal(
            window,
            "complete",
            elapsed=535.6,
            summary={
                "scanned_headers": 800,
                "classified_invoice": 39,
                "download_failed": 9,
            },
        )
        completed_text = window.lbl_import_scan_status.text()
        self.assertIn("✓ 同步完成", completed_text)
        self.assertNotIn("正在同步", completed_text)
        self.assertIn("8分55秒", completed_text)
        frozen = completed_text
        _render_scan_active(window, "save", 900)
        self.assertEqual(window.lbl_import_scan_status.text(), frozen)
        self.assertEqual(recent.title, "✓ 同步完成")

        _render_scan_terminal(window, "cancelled", elapsed=12.0, result={"cancelled": True})
        self.assertIn("同步已取消", window.lbl_import_scan_status.text())
        _render_scan_terminal(window, "failed", elapsed=13.0, reason="连接超时")
        self.assertIn("同步失败", window.lbl_import_scan_status.text())
        self.assertIn("连接超时", window.lbl_import_scan_status.text())

    def test_date_range_dialog_has_native_calendar_presets_and_validation(self):
        dialog = DateRangeDialog()
        today = QDate.currentDate()
        try:
            self.assertEqual(dialog.end_date_edit.date(), today)
            self.assertTrue(dialog.start_date_edit.calendarPopup())
            self.assertTrue(dialog.end_date_edit.calendarPopup())

            dialog._apply_preset("7d")
            self.assertEqual(dialog.start_date_edit.date(), today.addDays(-7))
            self.assertEqual(dialog.end_date_edit.date(), today)
            dialog._apply_preset("30d")
            self.assertEqual(dialog.start_date_edit.date(), today.addDays(-30))
            dialog._apply_preset("3m")
            self.assertEqual(dialog.start_date_edit.date(), today.addMonths(-3))

            dialog.start_date_edit.setDate(today)
            dialog.end_date_edit.setDate(today.addDays(-1))
            dialog.accept()
            self.assertEqual(dialog.result(), 0)
            self.assertEqual(dialog.error_label.text(), "起始日期不能晚于结束日期。")

            dialog.start_date_edit.setDate(today.addDays(-7))
            dialog.end_date_edit.setDate(today)
            dialog.accept()
            self.assertEqual(dialog.result(), QDialog.Accepted)
            self.assertEqual(
                dialog.date_range(),
                (today.addDays(-7).toString("yyyy-MM-dd"), today.toString("yyyy-MM-dd")),
            )
        finally:
            dialog.close()

    def test_custom_range_recheck_passes_dialog_iso_values_to_service(self):
        window = QWidget()
        try:
            with (
                patch("scripts.invoice_fetch.gui.hci_v1.DateRangeDialog") as dialog_cls,
                patch("scripts.invoice_fetch.gui.hci_v1._start_history_recheck") as start,
            ):
                dialog_cls.return_value.exec.return_value = QDialog.Accepted
                dialog_cls.return_value.date_range.return_value = (
                    "2026-07-01",
                    "2026-07-31",
                )
                _start_custom_range_recheck(window)

            start.assert_called_once_with(
                window,
                since="2026-07-01",
                until="2026-07-31",
            )
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_history_recheck_owns_and_releases_data_operation_gate(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                with (
                    patch(
                        "scripts.invoice_fetch.gui.hci_v1.QMessageBox.question",
                        return_value=QMessageBox.Yes,
                    ),
                    patch.object(HistoryRecheckWorker, "start", return_value=None),
                ):
                    _start_history_recheck(window, since="2026-08-01")

                self.assertEqual(
                    window._data_operation_gate.busy_reason(),
                    "历史记录重检",
                )
                self.assertFalse(
                    window._try_begin_data_operation("数据库备份", notify=False)
                )

                _history_recheck_finished(
                    window,
                    {"processed_emails": 1, "added_or_restored": 1},
                )
                self.assertEqual(window._data_operation_gate.busy_reason(), "")

                with (
                    patch(
                        "scripts.invoice_fetch.gui.hci_v1.QMessageBox.question",
                        return_value=QMessageBox.Yes,
                    ),
                    patch.object(HistoryRecheckWorker, "start", return_value=None),
                ):
                    _start_history_recheck(window, since="2026-08-01")

                self.assertEqual(
                    window._data_operation_gate.busy_reason(),
                    "历史记录重检",
                )
                with patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok):
                    _history_recheck_failed(window, "synthetic history failure")
                self.assertEqual(window._data_operation_gate.busy_reason(), "")
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_history_recheck_start_failure_releases_data_operation_gate(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                with (
                    patch(
                        "scripts.invoice_fetch.gui.hci_v1.QMessageBox.question",
                        return_value=QMessageBox.Yes,
                    ),
                    patch.object(
                        HistoryRecheckWorker,
                        "start",
                        side_effect=RuntimeError("synthetic start failure"),
                    ),
                    self.assertRaises(RuntimeError),
                ):
                    _start_history_recheck(window, since="2026-08-01")

                self.assertEqual(window._data_operation_gate.busy_reason(), "")
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
