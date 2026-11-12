"""Real-window visual contracts, including the deferred page-owner boundary."""

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.design_tokens import DESIGN_V1_COLORS
from scripts.invoice_fetch.gui.review_layout import PREVIEW_MIN_HEIGHT
from scripts.invoice_fetch.gui import workbench_settings as settings_module


class DesktopVisualIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def settle(self):
        for _ in range(6):
            self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    @contextmanager
    def window(self, size=(1440, 900), *, deferred=True):
        with tempfile.TemporaryDirectory() as td, patch.object(settings_module, "RUNTIME_DIR", Path(td)):
            settings = settings_module.workbench_settings()
            settings.setValue("migration/legacy_qsettings_v1", True)
            settings.sync()
            path = Path(td) / "visual.db"
            original = Path(td) / "original.xml"
            original.write_text("<invoice>synthetic</invoice>", encoding="utf-8")
            with InvoiceDB(path) as db:
                claim = db.create_claim_group("Visual verification")
                for index, status in enumerate(("to_review", "approved")):
                    invoice = db.insert_invoice({
                        "invoice_number": f"VISUAL-{index}", "invoice_date": "2026-11-06",
                        "seller_name": "Synthetic supplier", "buyer_name": "Synthetic buyer",
                        "total_amount": "20.00", "review_status": status,
                        "attachment_path": str(original),
                    })
                    db.add_invoice_to_claim(claim, invoice)
            window = InvoiceReviewApp(path, splash=None)
            if deferred:
                window._deferred_init()
            window.resize(*size)
            window.show()
            window.activateWindow()
            self.settle()
            try:
                yield window
            finally:
                window.close()
                window.deleteLater()
                self.settle()

    def test_real_review_applies_owner_styles_and_fits_keyboard_filters(self):
        with self.window() as window:
            window._switch_main_page("review")
            window._change_filter("all")
            self.settle()
            self.assertEqual(window.workbench_nav.property("visualLanguage"), "design-v1.1")
            bar = window.filter_bar_widget
            self.assertEqual(bar.property("visualRole"), "segmented-filter")
            for size in ((1440, 900), (1280, 800), (1150, 850), (1040, 700), (1248, 672)):
                window.resize(*size)
                self.settle()
                for card in window.filter_buttons.values():
                    bounds = QRect(card.mapTo(bar, QPoint()), card.size())
                    self.assertTrue(bar.rect().contains(bounds), (size, bounds, bar.rect()))
                for button in (window.btn_review_previous_page, window.btn_review_next_page,
                               window.btn_review_batch_menu, window.btn_toggle_review_detail):
                    self.assertTrue(window.record_header.rect().contains(button.geometry()), (size, button.geometry()))
                self.assertGreaterEqual(window.preview_panel.height(), PREVIEW_MIN_HEIGHT)
                title = window.preview_title
                self.assertTrue(title.isVisible())
                self.assertTrue(window.preview_panel.contentsRect().contains(title.geometry()))
                self.assertGreaterEqual(title.height(), title.fontMetrics().height())
            approved = window.filter_buttons["approved"]
            self.assertEqual(approved.focusPolicy(), Qt.StrongFocus)
            approved.setFocus()
            self.settle()
            QTest.keyClick(approved, Qt.Key_Return)
            self.settle()
            self.assertEqual(window.current_filter_status, "approved")
            self.assertEqual(window.status_segment_control.selected(), "approved")
            self.assertEqual(window.db.count_invoices_for_status("to_review"), 1)
            QTest.keyClick(approved, Qt.Key_Right)
            self.settle()
            self.assertEqual(window.current_filter_status, "ignored")
            self.assertFalse(window.btn_soft_duplicate_review.isVisible())
            self.assertIn(window.action_soft_duplicate_review, window.more_menu.actions())
            window._change_filter("all")
            normal_header_max = window.review_header.maximumHeight()
            window._enter_hci_continuous_review()
            self.settle()
            subtitle = window.review_header.lbl_subtitle
            self.assertTrue(subtitle.isVisible())
            self.assertTrue(window.review_header.rect().contains(subtitle.geometry()))
            window._exit_hci_continuous_review()
            self.settle()
            self.assertEqual(window.review_header.maximumHeight(), normal_header_max)
            self.assertFalse(subtitle.isVisible())

    def test_enter_activates_focused_review_controls_instead_of_approving(self):
        with self.window() as window:
            window._switch_main_page("review")
            window._change_filter("all")
            self.settle()
            invoice_id = next(inv["id"] for inv in window.invoices_list if inv["review_status"] == "to_review")
            for key in (Qt.Key_Return, Qt.Key_Enter):
                for button, expected in ((window.btn_ign, "ignored"), (window.btn_err, "error")):
                    with self.subTest(key=key, status=expected):
                        window.db.update_invoice_review_status(invoice_id, "to_review")
                        window._load_invoices(preserve_invoice_id=invoice_id)
                        button.setFocus(Qt.TabFocusReason)
                        self.settle()
                        self.assertTrue(button.hasFocus())
                        QTest.keyClick(button, key)
                        self.settle()
                        self.assertEqual(window.db.get_invoice(invoice_id)["review_status"], expected)

            window.db.update_invoice_review_status(invoice_id, "to_review")
            window._load_invoices(preserve_invoice_id=invoice_id)
            for key in (Qt.Key_Return, Qt.Key_Enter):
                before = window._review_detail_collapsed
                window.btn_toggle_review_detail.setFocus(Qt.TabFocusReason)
                self.settle()
                QTest.keyClick(window.btn_toggle_review_detail, key)
                self.settle()
                self.assertEqual(window._review_detail_collapsed, not before)
                self.assertEqual(window.db.get_invoice(invoice_id)["review_status"], "to_review")

            tabs = window._detail_panel.detail_tabs.tabBar()
            tabs.setFocus(Qt.TabFocusReason)
            self.settle()
            QTest.keyClick(tabs, Qt.Key_Return)
            self.settle()
            self.assertEqual(window.db.get_invoice(invoice_id)["review_status"], "to_review")
            window.btn_review_batch_menu.setFocus(Qt.TabFocusReason)
            self.settle()
            QTest.keyClick(window.btn_review_batch_menu, Qt.Key_Return)
            self.settle()
            menu = self.app.activePopupWidget()
            self.assertIsNotNone(menu)
            menu.hide()
            self.assertEqual(window.db.get_invoice(invoice_id)["review_status"], "to_review")

            # Table Enter remains the deliberate single-invoice approval action.
            window.table.setFocus(Qt.OtherFocusReason)
            self.settle()
            QTest.keyClick(window.table, Qt.Key_Return)
            self.settle()
            self.assertEqual(window.db.get_invoice(invoice_id)["review_status"], "approved")

    def test_invoice_currency_survives_review_selection_and_export_rows(self):
        from scripts.invoice_fetch.gui.selection_surfaces import INVOICE_ROW_ROLE

        with self.window() as window:
            window._switch_main_page("review")
            window._change_filter("all")
            self.settle()
            invoice_id = next(inv["id"] for inv in window.invoices_list if inv["review_status"] == "to_review")
            window.db._conn.execute("UPDATE invoices SET currency='USD' WHERE id=?", (invoice_id,))
            window.db._conn.commit()
            window._load_invoices(preserve_invoice_id=invoice_id)
            self.settle()
            self.assertEqual(window._detail_panel.lbl_sum_amount.text(), "USD 20.00")
            self.assertIn("USD 20.00", window.lbl_claim_total.text())
            other = next(inv["id"] for inv in window.invoices_list if inv["id"] != invoice_id)
            window._select_invoice_by_id(other)
            self.settle()
            self.assertEqual(window._detail_panel.lbl_sum_amount.text(), "¥20.00")
            window._select_invoice_by_id(invoice_id)
            self.settle()
            self.assertEqual(window._detail_panel.lbl_sum_amount.text(), "USD 20.00")
            window._switch_main_page("export")
            self.settle()
            rows = {window.export_invoice_list.item(i).data(Qt.UserRole): window.export_invoice_list.item(i)
                    for i in range(window.export_invoice_list.count())}
            self.assertEqual(rows[invoice_id].data(INVOICE_ROW_ROLE)["amount"], "USD 20.00")
            self.assertIn("USD 20.00", rows[invoice_id].text())
            self.assertEqual(rows[other].data(INVOICE_ROW_ROLE)["amount"], "¥20.00")

    def test_ai_status_uses_credential_values_and_separates_pause_from_enablement(self):
        from scripts.dev.capture_design_v1 import _synthetic_config
        from scripts.invoice_fetch import credentials

        cfg = _synthetic_config()
        cfg["ai_profiles"] = [dict(profile_id="review-ai", name="Review AI", provider="deepseek",
                                   model="deepseek-chat", enabled=True)]
        with patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=cfg), self.window() as window:
            window._switch_main_page("settings")
            window.settings_tabs.setCurrentIndex(1)
            for source, paused, enabled, expected in (
                ("profile", False, True, "已启用"),
                ("provider", False, True, "已启用"),
                ("env", False, True, "已启用"),
                ("missing", False, True, "待补 Key"),
                ("profile", True, True, "已暂停"),
                ("profile", False, False, "未启用"),
            ):
                with self.subTest(source=source, paused=paused, enabled=enabled), \
                     patch.object(credentials, "get_ai_api_key_source", return_value=source), \
                     patch("scripts.invoice_fetch.ai_classifier.is_provider_session_paused", return_value=paused):
                    cfg["ai_profiles"][0]["enabled"] = enabled
                    window._refresh_settings_page()
                    self.settle()
                    self.assertEqual(window.lbl_settings_ai_enabled.text(), expected)
                    self.assertEqual(window.lbl_settings_ai_status_badge.text(), expected)
                    self.assertNotIn(source, window.lbl_settings_ai_key_status.text())
                    self.assertEqual(window.lbl_settings_ai_session_state.text(), "已暂停" if paused else "未暂停")
                    self.assertEqual(cfg["ai_profiles"][0]["enabled"], enabled)

    def test_export_cards_align_and_primary_action_remains_usable(self):
        with self.window() as window:
            window._switch_main_page("export")
            self.settle()
            for size in ((1440, 900), (1280, 800), (1150, 850)):
                window.resize(*size)
                self.settle()
                cards = (window.export_group_card, window.export_invoices_card, window.export_integrity_card)
                tops = [card.mapTo(window.export_scroll.widget(), QPoint()).y() for card in cards]
                self.assertLessEqual(max(tops) - min(tops), 2, (size, tops))
                self.assertGreaterEqual(window.btn_run_export_page.width(), window.export_integrity_card.body.width() - 2)
                self.assertTrue(window.btn_run_export_page.isEnabled())
            window.export_scope.setFocus()
            self.settle()
            QTest.keyClick(window.export_scope, Qt.Key_Down)
            self.settle()
            self.assertTrue(window.export_scope.currentData())
            self.assertTrue(window.btn_run_export_page.isEnabled())

    def test_dashboard_zero_metric_is_quiet_and_import_route_works(self):
        with self.window() as window:
            window._switch_main_page("overview")
            self.settle()
            error = window.hci_dashboard_task_cards["parse_error"].lbl_value
            self.assertEqual(error.text(), "0")
            self.assertEqual(error.palette().color(QPalette.WindowText), QColor(DESIGN_V1_COLORS["muted"]))
            self.assertGreater(window.overview_content_host.width(), window.overview_page.width() * 0.85)
            card = window.hci_dashboard_task_cards["to_review"]
            card.setFocus()
            self.settle()
            QTest.keyClick(card, Qt.Key_Return)
            self.settle()
            self.assertEqual(window._current_page_key(), "review")
            self.assertEqual(window.db.count_invoices_for_status("to_review"), 1)
            window._switch_main_page("overview")
            self.settle()
            window.btn_hci_dashboard_import.click()
            self.settle()
            self.assertEqual(window._current_page_key(), "imports")

    def test_mail_account_viewport_fits_rows_and_long_names_remain_selectable(self):
        from scripts.invoice_fetch.gui.hci_v1 import _checked_mailbox_keys

        with self.window() as window:
            window._switch_main_page("imports")
            for count in (1, 8):
                window.config = {"email_accounts": [
                    {"mailbox_key": f"account-{i}", "name": "Long synthetic account " * 12,
                     "address": f"account-{i}@example.invalid", "enabled": True,
                     "provider": "custom", "is_default": i == 0,
                     "imap": {"server": "imap.example.invalid", "port": 993, "ssl": True}}
                    for i in range(count)
                ]}
                window._refresh_imports_page()
                self.settle()
                viewport = window.import_mail_accounts_scroll.viewport()
                first = window.mail_account_checkboxes[0]
                bounds = QRect(first.mapTo(viewport, QPoint()), first.size())
                self.assertTrue(viewport.rect().contains(bounds), (bounds, viewport.rect()))
                self.assertEqual(_checked_mailbox_keys(window), ["account-0"])
                first.setFocus()
                self.settle()
                QTest.keyClick(first, Qt.Key_Space)
                self.assertEqual(_checked_mailbox_keys(window), [])
                self.assertIn("Long synthetic", first.accessibleName())
                if count > 1:
                    self.assertGreater(window.import_mail_accounts_scroll.verticalScrollBar().maximum(), 0)

    def test_export_disclosure_keeps_blockers_visible_and_invoice_identity(self):
        with self.window() as window:
            window._switch_main_page("export")
            self.settle()
            self.assertFalse(window.export_check_missing_attach.isVisible())
            self.assertTrue(window.btn_export_passed_checks.isVisible())
            window._set_export_preflight_pending()
            self.assertTrue(window.export_check_missing_attach.isVisible())
            self.assertEqual(window.export_check_missing_attach.lbl_value.text(), "检查中…")
            self.assertFalse(window.btn_run_export_page.isEnabled())
            window._refresh_export_page()
            self.settle()
            window.btn_export_passed_checks.click()
            self.settle()
            self.assertTrue(window.export_check_missing_attach.isVisible())
            window.btn_export_passed_checks.click()
            item = window.export_invoice_list.item(0)
            self.assertIsNotNone(window.db.get_invoice(item.data(Qt.UserRole)))
            from scripts.invoice_fetch.gui.selection_surfaces import INVOICE_ROW_ROLE
            self.assertIn("¥", item.data(INVOICE_ROW_ROLE)["amount"])
            self.assertIn(item.data(INVOICE_ROW_ROLE)["title"], item.toolTip())
            self.assertIn(item.data(INVOICE_ROW_ROLE)["amount"].removeprefix("¥"), item.toolTip())
            claim_id = window.export_group_list.currentItem().data(Qt.UserRole)
            invoice_id = window.db.insert_invoice({
                "invoice_number": "MISSING-ORIGINAL", "total_amount": "25.00",
                "seller_name": "Synthetic supplier", "review_status": "approved",
            })
            window.db.add_invoice_to_claim(claim_id, invoice_id)
            window._refresh_export_page()
            QTest.qWait(80)
            self.settle()
            self.assertTrue(window.export_check_missing_attach.isVisible())
            self.assertNotEqual(window.export_check_missing_attach.lbl_value.text(), "无")
            self.assertTrue(window.export_check_dir.isVisible())
            self.assertFalse(window.btn_run_export_page.isEnabled())

    def test_settings_groups_keep_routes_and_preview_controls_do_not_cover_document(self):
        from scripts.invoice_fetch.gui.selection_surfaces import NAV_GROUP_ROLE

        with self.window() as window:
            window._switch_main_page("settings")
            self.settle()
            self.assertTrue(window.bottom_panel.isHidden())
            nav = window.settings_tabs.nav_list
            self.assertEqual(nav.item(0).data(NAV_GROUP_ROLE), "常用")
            self.assertEqual(nav.item(2).data(NAV_GROUP_ROLE), "高级")
            for index in range(window.settings_tabs.count()):
                target = window.settings_tabs.widget(index)
                window.settings_tabs.setCurrentIndex(index)
                self.assertIs(window.settings_tabs.currentWidget(), target)
            window._switch_main_page("review")
            self.settle()
            window._show_overlay_toolbar()
            self.settle()
            self.assertFalse(window.bottom_panel.isHidden())
            toolbar = window.overlay_toolbar
            self.assertGreaterEqual(window.preview_stack.y(), toolbar.y() + toolbar.height())
            for name, action in window.preview_actions.items():
                self.assertTrue(action.accessibleName(), name)
                if name != "zoom_100":
                    self.assertFalse(action.icon().isNull(), name)

    def test_review_actions_have_consistent_bounds_and_reduced_motion_stays_opaque(self):
        with self.window() as window:
            window._switch_main_page("review")
            self.settle()
            row = window._detail_panel.btn_app.parentWidget()
            for button in (window._detail_panel.btn_app, window._detail_panel.btn_ign,
                           window._detail_panel.btn_err):
                self.assertLessEqual(button.minimumHeight(), button.maximumHeight())
                self.assertTrue(row.rect().contains(button.geometry()))
            with patch("scripts.invoice_fetch.gui.app.motion_duration", return_value=150):
                window._animate_approval_feedback()
            with patch("scripts.invoice_fetch.gui.app.motion_duration", return_value=0):
                window._animate_approval_feedback()
            self.assertEqual(window._detail_panel.btn_app.graphicsEffect().opacity(), 1.0)
