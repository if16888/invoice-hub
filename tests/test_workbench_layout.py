# -*- coding: utf-8 -*-
"""
Tests for workbench_layout.py — pure metrics and splitter clamping.

No Qt or database required; all assertions are plain Python.
"""

import unittest
from decimal import Decimal
from pathlib import Path

from scripts.invoice_fetch.gui.workbench_layout import (
    WorkbenchMetrics,
    clamp_vertical_split,
    metrics_for_size,
)


class TestMetricsForSize(unittest.TestCase):
    """Verify responsive breakpoint logic for metrics_for_size()."""

    def test_1920_layout_uses_full_density(self):
        metrics = metrics_for_size(1920, 1080)
        self.assertEqual(metrics.nav_width, 180)
        self.assertEqual(metrics.detail_width, 352)
        self.assertEqual(metrics.record_height, 390)
        self.assertEqual(metrics.thumbnail_width, 104)
        self.assertFalse(metrics.compact)

    def test_1366_layout_collapses_navigation(self):
        metrics = metrics_for_size(1366, 768)
        self.assertTrue(metrics.nav_collapsed)
        self.assertEqual(metrics.nav_width, 56)
        self.assertEqual(metrics.detail_width, 344)
        self.assertEqual(metrics.record_height, 332)

    def test_1440_900_is_compact_but_not_collapsed(self):
        metrics = metrics_for_size(1440, 900)
        self.assertFalse(metrics.nav_collapsed)
        self.assertTrue(metrics.compact)
        self.assertEqual(metrics.nav_width, 180)
        self.assertEqual(metrics.detail_width, 352)
        self.assertEqual(metrics.record_height, 336)

    def test_1280_720_collapses_navigation(self):
        """Sub-1366 width also triggers the collapsed tier."""
        metrics = metrics_for_size(1280, 720)
        self.assertTrue(metrics.nav_collapsed)
        self.assertTrue(metrics.compact)

    def test_metrics_are_frozen(self):
        metrics = metrics_for_size(1920, 1080)
        with self.assertRaises(Exception):
            metrics.nav_width = 999  # type: ignore[misc]

    def test_returns_workbench_metrics_instance(self):
        self.assertIsInstance(metrics_for_size(1920, 1080), WorkbenchMetrics)


class TestClampVerticalSplit(unittest.TestCase):
    """Verify splitter boundary clamping."""

    def test_lower_boundary_clamped_to_record_min(self):
        record, preview = clamp_vertical_split(
            900, 50, record_min=280, preview_min=300
        )
        self.assertEqual(record, 280)
        self.assertEqual(preview, 620)

    def test_upper_boundary_clamped_to_preview_min(self):
        record, preview = clamp_vertical_split(
            900, 850, record_min=280, preview_min=300
        )
        self.assertEqual(record, 600)
        self.assertEqual(preview, 300)

    def test_in_range_value_passes_through(self):
        record, preview = clamp_vertical_split(
            900, 400, record_min=280, preview_min=300
        )
        self.assertEqual(record, 400)
        self.assertEqual(preview, 500)

    def test_total_always_equals_sum(self):
        for requested in (0, 100, 400, 800, 1000):
            record, preview = clamp_vertical_split(
                900, requested, record_min=280, preview_min=300
            )
            self.assertEqual(record + preview, 900)


# ---------------------------------------------------------------------------
# Integration tests — require PySide6 and InvoiceReviewApp
# ---------------------------------------------------------------------------

try:
    from PySide6.QtCore import QPoint, Qt, QSettings
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QLineEdit,
        QPushButton,
        QSizePolicy,
        QSplitter,
        QWidget,
    )
    from scripts.invoice_fetch.gui.workbench_settings import workbench_settings

    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False

import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

_QAPP = None


def _get_app():
    global _QAPP
    if not _HAS_PYSIDE6:
        return None
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


class TestWorkbenchShellIntegration(unittest.TestCase):
    """Integration tests for the composed workbench shell (Task 3).

    These tests spin up InvoiceReviewApp with a temporary database, resize
    to a target resolution, process events, then assert structural contracts.
    All tests are skipped gracefully when PySide6 is not available.
    """

    def setUp(self):
        if not _HAS_PYSIDE6:
            self.skipTest("PySide6 not available")
        self._settings_dir = tempfile.TemporaryDirectory(
            prefix="invoice-hub-workbench-settings-"
        )
        self.addCleanup(self._settings_dir.cleanup)
        self._settings_patch = patch(
            "scripts.invoice_fetch.gui.app.workbench_settings",
            side_effect=lambda runtime_dir=None: workbench_settings(
                runtime_dir or Path(self._settings_dir.name)
            ),
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)
        _get_app()
        settings = self._settings()
        settings.remove("nav_collapsed_manual")
        settings.remove("shortcut_help_expanded")
        settings.sync()

    def tearDown(self):
        if _HAS_PYSIDE6:
            QApplication.processEvents()
            settings = self._settings()
            settings.remove("nav_collapsed_manual")
            settings.remove("shortcut_help_expanded")
            settings.sync()

    def _settings(self):
        return workbench_settings(Path(self._settings_dir.name))

    def _make_window(self, td: str):
        """Create a minimal InvoiceReviewApp against a temp database."""
        try:
            from scripts.invoice_fetch.gui.app import InvoiceReviewApp
        except ImportError as exc:
            self.skipTest(f"InvoiceReviewApp import failed: {exc}")
        db_path = Path(td) / "workbench_test.db"
        window = InvoiceReviewApp(db_path, splash=None)
        return window

    def _visible_primary_buttons(self, root):
        from scripts.invoice_fetch.gui.ui_components import is_visual_primary
        return [
            button
            for button in root.findChildren(QPushButton)
            if button.isVisible() and is_visual_primary(button)
        ]

    def test_workbench_settings_use_explicit_writable_ini_store(self):
        settings = self._settings()
        self.assertEqual(settings.format(), QSettings.IniFormat)
        self.assertEqual(
            Path(settings.fileName()).parent,
            Path(self._settings_dir.name),
        )
        self.assertNotIn("HKEY_", settings.fileName())
        settings.setValue("__test_write_probe", True)
        settings.sync()
        self.assertEqual(settings.status(), QSettings.NoError)
        settings.remove("__test_write_probe")
        settings.sync()

    # ------------------------------------------------------------------
    # Splitter hierarchy and orientation
    # ------------------------------------------------------------------

    def test_main_splitter_is_horizontal(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                QApplication.processEvents()
                self.assertEqual(
                    window.main_splitter.orientation(), Qt.Horizontal
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_left_splitter_is_vertical(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                QApplication.processEvents()
                self.assertEqual(
                    window.left_splitter.orientation(), Qt.Vertical
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_left_splitter_children(self):
        """widget(0) = left_upper_widget, widget(1) = preview_panel."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                QApplication.processEvents()
                self.assertIs(
                    window.left_splitter.widget(0), window.left_upper_widget
                )
                self.assertIs(
                    window.left_splitter.widget(1), window.preview_panel
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_detail_panel_minimum_width_at_1920(self):
        """At 1920×1080 the decision panel stays within the compact token width."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                active_metrics = metrics_for_size(window.width(), window.height())
                self.assertGreaterEqual(
                    window._detail_panel.minimumWidth(),
                    active_metrics.detail_width,
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_detail_panel_minimum_width_at_1366(self):
        """At 1366×768 the compact detail panel remains usable at 340-352px."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1366, 768)
                QApplication.processEvents()
                self.assertGreaterEqual(window._detail_panel.minimumWidth(), 340)
                self.assertLessEqual(window._detail_panel.minimumWidth(), 352)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_table_header_is_visible(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                window.left_stack.setCurrentWidget(window.table)
                QApplication.processEvents()
                self.assertFalse(window.table.horizontalHeader().isHidden())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_main_splitter_stretch_factors(self):
        """Left pane stretches; right detail pane has zero stretch."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                # Both splitter children must have positive size
                sizes = window.main_splitter.sizes()
                self.assertEqual(len(sizes), 2)
                self.assertTrue(all(s > 0 for s in sizes))
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_left_splitter_sizes_nonzero(self):
        """Both vertical panes must have positive size after construction."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                sizes = window.left_splitter.sizes()
                self.assertEqual(len(sizes), 2)
                self.assertTrue(all(s > 0 for s in sizes))
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_compact_status_cards_fit_the_filter_bar(self):
        from scripts.invoice_fetch.gui.ui_components import CompactStatCard

        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                self.assertLessEqual(window.filter_bar_widget.maximumHeight(), 72)
                self.assertEqual(len(window.filter_buttons), 5)
                self.assertTrue(all(isinstance(card, CompactStatCard) for card in window.filter_buttons.values()))
                self.assertTrue(all(card.maximumWidth() <= 160 for card in window.filter_buttons.values()))
                self.assertTrue(all(card.sizeHint().height() <= 48 for card in window.filter_buttons.values()))
                self.assertTrue(all("\n" not in card.text() for card in window.filter_buttons.values()))
            finally:
                window.db.close()
                window.close()

    def test_final_workbench_shell_has_left_nav_and_top_toolbar(self):
        """0.1.4 visual shell must expose the design-aligned nav and toolbar."""
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                self.assertTrue(window.workbench_nav.isVisible())
                self.assertEqual(window.workbench_nav.objectName(), "WorkbenchNav")
                self.assertIn(window.workbench_nav.minimumWidth(), (56, 180))

                self.assertTrue(window.workbench_top_toolbar.isVisible())
                self.assertEqual(window.workbench_top_toolbar.objectName(), "WorkbenchTopToolbar")
                self.assertEqual(window.txt_search.parentWidget(), window.workbench_top_toolbar)
                self.assertIn("Ctrl + F", window.txt_search.placeholderText())
                self.assertNotEqual(window.btn_import_local.property("emphasis"), "primary")
                self.assertFalse(window.btn_mobile_upload.isVisible())
                self.assertFalse(window.btn_scan_email.isVisible())
                self.assertFalse(window.btn_toolbar_export.isVisible())

                visible_nav_buttons = [
                    button for button in window.workbench_nav_buttons.values()
                    if button.isVisible()
                ]
                self.assertGreaterEqual(len(visible_nav_buttons), 1)
                self.assertFalse(window.workbench_nav_buttons["review"].icon().isNull())
                expected_nav_focus = Qt.NoFocus if window.workbench_nav.width() <= 72 else Qt.TabFocus
                self.assertEqual(window.workbench_nav_buttons["overview"].focusPolicy(), expected_nav_focus)
                self.assertEqual(window.btn_scan_email.text(), "扫描邮箱")
                self.assertEqual(window.btn_toolbar_export.text(), "导出")
                self.assertFalse(window.btn_toolbar_help.isVisible())
                self.assertFalse(window.btn_toolbar_notify.isVisible())
                self.assertTrue(hasattr(window, "btn_toolbar_user"))
                self.assertEqual(window.btn_toolbar_user.text(), "本地模式 ▾")
                self.assertNotIn("张伟", window.btn_toolbar_user.text())
                self.assertTrue(window.btn_more.menu() is not None)
                self.assertIn(window.action_mobile_upload, window.btn_more.menu().actions())
                self.assertIn(window.action_scan_email, window.btn_more.menu().actions())
                self.assertIn(window.action_toolbar_export, window.btn_more.menu().actions())
                self.assertFalse(window.btn_collapse_nav.icon().isNull())
                self.assertTrue(window.btn_collapse_nav.toolTip())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_inactive_nav_items_do_not_allow_false_page_selection(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                for key in ("overview", "imports"):
                    button = window.workbench_nav_buttons[key]
                    self.assertTrue(button.isVisible(), f"{key} should be visible")
                    self.assertTrue(button.isEnabled(), f"{key} should be enabled")
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_nav_action_entries_do_not_steal_review_selection(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                window._load_invoices()
                QApplication.processEvents()

                review_button = window.workbench_nav_buttons["review"]
                original_widget = window.left_stack.currentWidget()
                self.assertTrue(review_button.isChecked())

                expected_labels = {
                    "overview": "今日工作台",
                    "review": "发票审核",
                    "imports": "导入中心",
                    "export": "报销组与导出",
                    "settings": "系统设置",
                }
                for key, label in expected_labels.items():
                    button = window.workbench_nav_buttons[key]
                    self.assertTrue(button.isVisible(), f"{key} should be visible in navigation")
                    self.assertEqual(button.text(), label)
                    self.assertIs(window.left_stack.currentWidget(), original_widget)
                self.assertFalse(window.workbench_nav_buttons["logs"].isVisible())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_navigation_keeps_exactly_one_checked_page_after_mouse_switch(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                window.workbench_nav_buttons["overview"].click()
                QApplication.processEvents()
                selectable = ("overview", "review", "imports", "export", "settings")
                self.assertEqual(
                    [key for key in selectable if window.workbench_nav_buttons[key].isChecked()],
                    ["overview"],
                )
                if window.workbench_nav.width() <= 72:
                    self.assertTrue(
                        all(not window.workbench_nav_buttons[key].hasFocus() for key in selectable)
                    )

                window.workbench_nav_buttons["review"].click()
                QApplication.processEvents()
                self.assertEqual(
                    [key for key in selectable if window.workbench_nav_buttons[key].isChecked()],
                    ["review"],
                )

                window._nav_collapsed_manual = True
                window._apply_workbench_metrics(1920, 1080)
                window.workbench_nav_buttons["export"].click()
                QApplication.processEvents()
                self.assertEqual(window.workbench_nav.width(), 56)
                self.assertEqual(
                    [key for key in selectable if window.workbench_nav_buttons[key].isChecked()],
                    ["export"],
                )
                self.assertTrue(
                    all(window.workbench_nav_buttons[key].focusPolicy() == Qt.NoFocus for key in selectable)
                )
                self.assertTrue(
                    all(not window.workbench_nav_buttons[key].hasFocus() for key in selectable)
                )

                window._nav_collapsed_manual = False
                window._apply_workbench_metrics(1920, 1080)
                self.assertTrue(
                    all(window.workbench_nav_buttons[key].focusPolicy() == Qt.TabFocus for key in selectable)
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_preview_empty_state_uses_shared_styled_label(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                self.assertEqual(window.lbl_preview_status.property("class"), "PreviewEmptyState")
                self.assertEqual(window.lbl_preview_status.styleSheet(), "")
                self.assertLessEqual(window.lbl_preview_status.maximumWidth(), 560)
                self.assertEqual(window.preview_stack.objectName(), "PreviewSurface")
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_preview_toolbar_and_thumbnail_rail_stay_compact(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                self.assertLessEqual(window.overlay_toolbar.height(), 40)
                self.assertLessEqual(window.thumbnail_rail.width(), 104)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_invoice_table_default_columns_match_review_workbench_design(self):
        """The list is for fast switching, so default columns stay compact."""
        from scripts.invoice_fetch.gui.column_filters import VISIBLE_COLUMN_DEFINITIONS

        expected = (
            "review_status",
            "status",
            "expense_date",
            "total_amount",
            "seller_name",
            "invoice_number",
        )
        self.assertEqual(tuple(key for key, _label in VISIBLE_COLUMN_DEFINITIONS), expected)

    def test_invoice_table_uses_dense_row_height(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                self.assertLessEqual(window.table.verticalHeader().defaultSectionSize(), 40)
                self.assertLessEqual(window.table.font().pointSize(), 12)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_invoice_record_header_exists_and_stays_compact(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                self.assertEqual(window.lbl_record_section_title.text(), "发票记录")
                self.assertLessEqual(window.record_header.height(), 28)
                self.assertGreaterEqual(window.record_header.height(), 24)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_review_page_primary_buttons_stay_within_one(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1600, 900)
                QApplication.processEvents()
                self.assertLessEqual(len(self._visible_primary_buttons(window.workbench_top_toolbar)), 1)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_imports_page_has_summary_strip_and_short_actions(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window._switch_main_page("imports")
                QApplication.processEvents()
                self.assertFalse(hasattr(window, "imports_summary_strip"))
                self.assertIn(window.btn_import_scan_selected.text(), ("开始扫描", "补授权码"))
                self.assertEqual(window.btn_import_scan_default.text(), "扫默认")
                action_texts = [action.text() for action in window.import_mail_more_menu.actions()]
                self.assertEqual(action_texts, ["管理邮箱", "失败明细"])
                self.assertEqual(window.import_source_card.lbl_title.text(), "来源选择")
                self.assertTrue(window.import_mail_accounts_card.lbl_title.text())
                self.assertEqual(window.import_mail_recent_card.lbl_title.text(), "本次运行")
                self.assertTrue(hasattr(window, "btn_settings_mailbox_add"))
                self.assertLessEqual(len(self._visible_primary_buttons(window.imports_page)), 1)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_settings_mailbox_page_keeps_read_only_detail_and_single_primary(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window._switch_main_page("settings", sub_tab=1)
                QApplication.processEvents()
                self.assertFalse(hasattr(window, "stat_box_overview"))
                self.assertEqual(window.settings_mailbox_list.width(), 280)
                self.assertTrue(hasattr(window, "lbl_detail_email"))
                self.assertTrue(hasattr(window.settings_tabs, "nav_list"))
                self.assertEqual(window.btn_settings_mailbox_edit_config.text(), "编辑")
                self.assertEqual(window.btn_settings_mailbox_scan.text(), "立即扫描")
                self.assertLessEqual(len(self._visible_primary_buttons(window.settings_tabs.currentWidget())), 1)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_settings_ai_page_is_read_only_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window._switch_main_page("settings", sub_tab=2)
                QApplication.processEvents()
                current = window.settings_tabs.currentWidget()
                self.assertEqual(current.findChildren(QComboBox), [])
                self.assertEqual(current.findChildren(QLineEdit), [])
                button_texts = [button.text() for button in current.findChildren(QPushButton)]
                self.assertNotIn("保存设置", button_texts)
                self.assertEqual(window.btn_settings_ai_edit.text(), "编辑配置")
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_settings_has_single_full_surface_and_no_placeholder_pages(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window._switch_main_page("settings")
                labels = [window.settings_tabs.tabText(i) for i in range(window.settings_tabs.count())]
                self.assertEqual(
                    labels,
                    ["邮箱账户", "AI 配置", "运行状态", "安全与隐私", "数据与备份", "关于"],
                )
                window._open_settings_dialog(1)
                self.assertIs(window.center_stack.currentWidget(), window.settings_page)
                self.assertEqual(window.settings_tabs.currentIndex(), 0)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_import_page_hides_raw_runtime_log_and_uses_purpose_widths(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1366, 768)
                window._switch_main_page("imports")
                QApplication.processEvents()
                self.assertFalse(hasattr(window, "txt_import_records"))
                self.assertLessEqual(window.import_source_card.maximumWidth(), 300)
                self.assertGreaterEqual(window.import_mail_recent_card.minimumWidth(), 300)
                self.assertLessEqual(len(self._visible_primary_buttons(window.imports_page)), 1)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_import_source_has_single_selected_state(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window._switch_main_page("imports")
                calls = []
                window._import_local_clicked = lambda: calls.append("local")
                window._select_import_source("local")
                selected = [key for key, card in window.import_source_cards.items() if card.property("selected")]
                self.assertEqual(selected, ["local"])
                self.assertIs(window.import_task_stack.currentWidget(), window.import_local_task_card)
                self.assertFalse(window.import_mail_recent_card.isHidden())
                self.assertEqual(calls, [])
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_dashboard_accepts_decimal_month_total(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                metrics = {
                    "today_imported": 1,
                    "to_review": 2,
                    "error": 0,
                    "needs_fix": 0,
                    "month_total": Decimal("28.90"),
                    "export_ready": 1,
                    "total": 2,
                }
                window._collect_overview_metrics = lambda: metrics
                window._refresh_overview_page()
                self.assertIs(window.overview_state_stack.stack.currentWidget(), window.overview_state_stack.content)
                self.assertEqual(window.overview_value_labels["to_review"].value(), "2 张")
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_import_results_use_structured_activities_not_runtime_logs(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window._read_recent_runtime_logs = lambda: ["unrelated diagnostic entry"]
                window._import_activities = []
                window._refresh_imports_page()
                self.assertIs(window.import_recent_state_stack.stack.currentWidget(), window.import_recent_state_stack.empty)
                window._record_import_activity("local", added=2, duplicates=1)
                window._refresh_imports_page()
                self.assertIs(window.import_recent_state_stack.stack.currentWidget(), window.import_recent_state_stack.content)
                self.assertEqual(window.import_recent_timeline.layout().count(), 1)
                self.assertFalse(hasattr(window, "txt_import_records"))
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_dashboard_summary_uses_actionable_work_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                titles = [card.text().rsplit(" ", 1)[0] for card in window.overview_value_labels.values()]
                self.assertEqual(titles, ["待审核", "缺材料", "异常", "可导出组"])
                self.assertTrue(hasattr(window, "overview_timeline"))
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_export_preflight_uses_product_facing_copy(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                copy = window._format_claim_export_preflight_text(
                    {"approved": 2, "to_review": 1, "missing_attachment": 0, "missing_amount": 0}
                )
                self.assertIn("已通过发票", copy)
                self.assertNotIn("approved:", copy)
                self.assertNotIn("to_review:", copy)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_ai_page_uses_single_detail_surface_without_summary_duplication(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window._switch_main_page("settings", sub_tab=2)
                QApplication.processEvents()
                self.assertFalse(window.settings_ai_profile_list.isVisible())
                self.assertFalse(hasattr(window, "settings_ai_summary_strip"))
                self.assertIs(window.settings_tabs.currentWidget(), window.settings_tabs.widget(1))
                self.assertFalse(window.settings_ai_detail_panel.isHidden())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_export_page_uses_claims_invoices_and_integrity_three_columns(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window._switch_main_page("export")
                QApplication.processEvents()
                self.assertEqual(window.export_group_card.lbl_title.text(), "报销组")
                self.assertEqual(window.export_invoices_card.lbl_title.text(), "组内发票")
                self.assertEqual(window.export_integrity_card.lbl_title.text(), "完整性检查与导出")
                self.assertFalse(hasattr(window, "combo_export_claims"))
                self.assertLessEqual(len(self._visible_primary_buttons(window.export_page)), 1)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_app_ui_copy_does_not_contain_common_mojibake_markers(self):
        text = Path("scripts/invoice_fetch/gui/app.py").read_text(encoding="utf-8")
        for marker in ["浠", "瀵", "閰", "鈥", "�", "涓", "鏃", "鍏", "绠"]:
            self.assertNotIn(marker, text)

    def test_review_table_shows_at_least_seven_dense_rows_at_1366(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1366, 768)
                QApplication.processEvents()
                visible_rows = window.table.viewport().height() // window.table.verticalHeader().defaultSectionSize()
                self.assertGreaterEqual(visible_rows, 7)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_workbench_core_surfaces_do_not_overflow_at_target_widths(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                for width in (1366, 1600, 1920):
                    window.resize(width, 900)
                    window.show()
                    QApplication.processEvents()
                    self.assertLessEqual(window.workbench_top_toolbar.width(), width)
                    self.assertLessEqual(window.filter_bar_widget.width(), width)
                    self.assertLessEqual(window.record_header.width(), width)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_workbench_version_is_016(self):
        from scripts.invoice_fetch.version import APP_VERSION, VERSION

        self.assertEqual(VERSION, "0.1.6")
        self.assertEqual(APP_VERSION, "v0.1.6")

    def test_status_bar_shortcut_copy_uses_chinese_punctuation(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                self.assertEqual(window.btn_shortcut_help.text(), "")
                self.assertTrue(window.btn_shortcut_help.toolTip())
                self.assertTrue(window.btn_shortcut_help.accessibleName())
            finally:
                window.db.close()
                window.close()

    def test_shortcut_disclosure_defaults_collapsed_without_resizing_splitter(self):
        settings = self._settings()
        settings.remove("shortcut_help_expanded")
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.resize(1920, 1080)
                window.show()
                QApplication.processEvents()
                QApplication.processEvents()
                self.assertFalse(window.shortcut_disclosure.is_expanded())
                before = window.main_splitter.sizes()
                window._toggle_shortcut_disclosure()
                QApplication.processEvents()
                self.assertTrue(window.shortcut_disclosure.is_expanded())
                self.assertEqual(window.main_splitter.sizes(), before)
            finally:
                window.shortcut_disclosure.hide()
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    # ------------------------------------------------------------------
    # Restored-state clamp (plan Step 4 verification)
    # ------------------------------------------------------------------

    def test_restored_splitter_sizes_are_clamped(self):
        """Sizes restored from QSettings must pass through clamp_vertical_split."""
        # Patch QSettings to return an out-of-bounds stored value
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()
                # Use a stable synthetic persisted total. The live Qt splitter
                # can report a transient platform-dependent height while the
                # window is being shown, which is not the preference contract
                # this test is intended to cover.
                total = 900
                # Capture the value handed to Qt instead of reading the live
                # splitter back after layout polish, which can normalize sizes
                # differently across Windows runners.
                captured = []
                with patch.object(
                    window.left_splitter,
                    "setSizes",
                    side_effect=lambda values: captured.append(list(values)),
                ):
                    window._restore_left_splitter_sizes([total - 10, 10])
                self.assertEqual(len(captured), 1)
                record, preview = captured[0]
                self.assertEqual(record + preview, total)
                self.assertGreaterEqual(record, 280)
                self.assertGreaterEqual(preview, 180)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_user_adjusted_left_splitter_is_not_reset_by_resize(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                # Earlier integration cases may leave hidden top-level test
                # windows alive in this shared QApplication. Close those
                # stale Invoice Hub windows before exercising this window so
                # their pending layout/timer work cannot affect the contract.
                for other in QApplication.topLevelWidgets():
                    if (
                        isinstance(other, QWidget)
                        and other is not window
                        and other.windowTitle().startswith("Invoice Hub")
                    ):
                        other.close()
                        other.deleteLater()
                QApplication.processEvents()
                window.show()
                window.showNormal()
                window.raise_()
                window.activateWindow()
                # Keep the test window inside the native desktop work area.
                # On hosted Windows, requesting a 1920x1080 normal window on
                # a smaller desktop can leave the window apparently at that
                # size until the next resize, when the window manager restores
                # it to the available geometry.  That turns a width-only
                # request into an unrelated height resize before the product
                # can be evaluated.
                screen = QApplication.primaryScreen()
                available = (
                    screen.availableGeometry()
                    if screen is not None
                    else window.geometry()
                )
                if window.minimumWidth() > available.width():
                    # Some hosted Windows images expose a 1024px desktop
                    # while the product's compact minimum is 1040px. Relax
                    # only the top-level test window constraint so the
                    # vertical splitter can still be exercised in a real
                    # native window instead of skipping the contract.
                    window.setMinimumWidth(0)
                target_width = min(1200, max(0, available.width() - 40))
                target_height = min(900, max(0, available.height() - 10))
                target_width = max(target_width, window.minimumWidth() + 1)
                target_height = max(target_height, window.minimumHeight() + 1)
                self.assertLessEqual(
                    target_width,
                    available.width(),
                    "native desktop is narrower than the workbench minimum: "
                    f"available={available.width()}x{available.height()}, "
                    f"minimum={window.minimumWidth()}x{window.minimumHeight()}",
                )
                self.assertLessEqual(
                    target_height,
                    available.height(),
                    "native desktop is shorter than the workbench minimum: "
                    f"available={available.width()}x{available.height()}, "
                    f"minimum={window.minimumWidth()}x{window.minimumHeight()}",
                )
                window.resize(target_width, target_height)
                # Construction starts with a compatibility shim and then
                # installs the real QSplitter from a deferred callback. Wait
                # for the actual handle/geometry instead of assuming a fixed
                # delay or interacting with the shim.  Compact native
                # desktops may legitimately compress the panes below their
                # ideal minimumSizeHint; that must not prevent exercising the
                # real handle path.
                deadline = time.monotonic() + 2.0
                splitter = None
                while time.monotonic() < deadline:
                    QApplication.processEvents()
                    candidate = getattr(window, "left_splitter", None)
                    middle = getattr(window, "middle_workspace", None)
                    if middle is not None and middle.layout() is not None:
                        middle.layout().activate()
                    if candidate is not None:
                        parent = candidate.parentWidget()
                        if parent is not None and parent.layout() is not None:
                            parent.layout().activate()
                        candidate.updateGeometry()
                    if (
                        isinstance(candidate, QSplitter)
                        and candidate.count() == 2
                        and candidate.handle(1) is not None
                        and len(candidate.sizes()) == 2
                        and all(int(size) > 0 for size in candidate.sizes())
                    ):
                        splitter = candidate
                        break
                    QTest.qWait(20)
                self.assertIsNotNone(
                    splitter,
                    "real vertical splitter handle did not become available",
                )
                assert splitter is not None

                initial_sizes = splitter.sizes()
                total_before = sum(initial_sizes)
                record_widget = splitter.widget(0)
                preview_widget = splitter.widget(1)
                record_min = int(record_widget.minimumHeight())
                record_max = min(
                    int(record_widget.maximumHeight()),
                    total_before - int(preview_widget.minimumHeight()),
                )
                current_record = int(initial_sizes[0])
                down_room = max(0, current_record - record_min)
                up_room = max(0, record_max - current_record)
                if down_room:
                    delta = -min(40, down_room)
                else:
                    delta = min(40, up_room)
                self.assertNotEqual(
                    delta,
                    0,
                    "native splitter has no feasible user-adjustment range: "
                    f"sizes={initial_sizes}, total={total_before}, "
                    f"record_min={record_min}, record_max={record_max}",
                )

                moved_positions = []
                splitter.splitterMoved.connect(
                    lambda position, _index: moved_positions.append(int(position))
                )
                handle = splitter.handle(1)
                start = handle.rect().center()
                end = QPoint(start.x(), start.y() + delta)
                # setSizes() changes pixels but does not establish the native
                # user-adjusted state. Exercise the same handle path as a user.
                QTest.mousePress(handle, Qt.LeftButton, pos=start)
                QTest.qWait(20)
                QTest.mouseMove(handle, end, 50)
                QTest.mouseRelease(handle, Qt.LeftButton, pos=end)
                QApplication.processEvents()
                moved_sizes = splitter.sizes()

                self.assertTrue(
                    moved_positions,
                    "real splitter handle drag did not emit splitterMoved",
                )
                self.assertNotEqual(
                    moved_sizes[0],
                    initial_sizes[0],
                    "native handle drag did not move the record pane: "
                    f"initial={initial_sizes}, moved={moved_sizes}",
                )

                # Keep the native height constant.  A large width delta can
                # make the Windows window manager clamp the requested height
                # to the available desktop, turning this into a height resize
                # and legitimately rebalancing the panes.  Use the smallest
                # feasible width change so this contract remains width-only.
                before_resize_width = window.width()
                before_resize_height = window.height()
                if before_resize_width <= window.minimumWidth():
                    window.setMinimumWidth(0)
                resized_width = (
                    before_resize_width - 1
                    if before_resize_width > 1
                    else before_resize_width + 1
                )
                self.assertNotEqual(resized_width, before_resize_width)
                window.resize(resized_width, before_resize_height)
                QApplication.processEvents()
                # Hosted Windows runners can deliver the final splitter/layout
                # geometry one event-loop turn after the resize event.  Read
                # the user-adjusted state only after that native layout pass.
                QTest.qWait(50)
                QApplication.processEvents()
                self.assertEqual(
                    window.height(),
                    before_resize_height,
                    "requested width-only resize changed the native window height: "
                    f"before={before_resize_width}x{before_resize_height}, "
                    f"after={window.width()}x{window.height()}, "
                    f"requested_width={resized_width}",
                )
                resized_sizes = splitter.sizes()

                # QSplitter preserves the user-adjusted pane in native pixels;
                # compare the actual user-selected pixel position rather than
                # an impossible fixed target or a platform-dependent ratio.
                self.assertAlmostEqual(
                    resized_sizes[0],
                    moved_sizes[0],
                    delta=8,
                    msg=(
                        "user splitter position changed after width-only resize: "
                        f"window={window.width()}x{window.height()}, "
                        f"splitter={splitter.width()}x{splitter.height()}, "
                        f"initial={initial_sizes}, moved={moved_sizes}, "
                        f"resized={resized_sizes}, "
                        f"upper_minmax=({record_widget.minimumHeight()},"
                        f"{record_widget.maximumHeight()}), "
                        f"preview_min={preview_widget.minimumHeight()}, "
                        "baseline="
                        f"{window.review_page.property('reviewBaselinePipelineApplied')}, "
                        "scheduled="
                        f"{window.review_page.property('reviewBaselinePipelineScheduled')}"
                    ),
                )
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_compact_density_shortens_search_placeholder(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1366, 768)
                QApplication.processEvents()
                self.assertIn("Ctrl + F", window.txt_search.placeholderText())
                self.assertNotIn("邮件主题", window.txt_search.placeholderText())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_compact_nav_collapses_to_icons_only(self):
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1366, 768)
                QApplication.processEvents()
                self.assertFalse(window.workbench_nav_title.isVisible())
                self.assertFalse(window.workbench_nav_subtitle.isVisible())
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "")
                self.assertTrue(window.btn_collapse_nav.isVisible())
                self.assertGreater(window.workbench_nav.maximumWidth(), 40)
                self.assertLessEqual(window.workbench_nav.maximumWidth(), 72)
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_default_nav_is_expanded_at_1920(self):
        settings = self._settings()
        settings.remove("nav_collapsed_manual")
        settings.sync()
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                self.assertEqual(window.workbench_nav.maximumWidth(), 180)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "发票审核")
                self.assertTrue(window.btn_collapse_nav.isVisible())
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_nav_collapse_toggle_works_at_large_size(self):
        settings = self._settings()
        settings.remove("nav_collapsed_manual")
        settings.sync()
        with tempfile.TemporaryDirectory() as td:
            window = self._make_window(td)
            try:
                window.show()
                window.resize(1920, 1080)
                QApplication.processEvents()

                # Default: expanded at the desktop token width.
                self.assertEqual(window.workbench_nav.maximumWidth(), 180)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "发票审核")
                self.assertTrue(window.btn_collapse_nav.isVisible())

                # Click collapse: should collapse to 52px
                window.btn_collapse_nav.click()
                QApplication.processEvents()
                settings.sync()
                self.assertEqual(window.workbench_nav.maximumWidth(), 56)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "")
                self.assertTrue(settings.value("nav_collapsed_manual", False, type=bool))

                # Click again: should expand back to 180px.
                window.btn_collapse_nav.click()
                QApplication.processEvents()
                settings.sync()
                self.assertEqual(window.workbench_nav.maximumWidth(), 180)
                self.assertEqual(window.workbench_nav_buttons["review"].text(), "发票审核")
                self.assertFalse(settings.value("nav_collapsed_manual", True, type=bool))
            finally:
                window.db.close()
                window.close()
                window.deleteLater()
                QApplication.processEvents()

    def test_nav_collapsed_state_persists_on_restart(self):
        settings = self._settings()
        settings.remove("nav_collapsed_manual")
        settings.sync()
        with tempfile.TemporaryDirectory() as td:
            first = self._make_window(td)
            try:
                first.show()
                first.resize(1920, 1080)
                QApplication.processEvents()
                # Default: expanded
                self.assertEqual(first.workbench_nav.maximumWidth(), 180)
                # Collapse it
                first.btn_collapse_nav.click()
                QApplication.processEvents()
                self.assertEqual(first.workbench_nav.maximumWidth(), 56)
                first._save_splitter_prefs()
                first.close()
                first.deleteLater()
                QApplication.processEvents()

                # Second window should remember collapsed state
                second = self._make_window(td)
                try:
                    second.show()
                    second.resize(1920, 1080)
                    QApplication.processEvents()
                    self.assertEqual(second.workbench_nav.maximumWidth(), 56)
                    self.assertEqual(second.workbench_nav_buttons["review"].text(), "")
                finally:
                    second.db.close()
                    second.close()
                    second.deleteLater()
                    QApplication.processEvents()
            finally:
                if getattr(first, "db", None) is not None and first.db.is_open:
                    first.db.close()

    def test_default_nav_does_not_persist_manual_state(self):
        settings = self._settings()
        settings.remove("nav_collapsed_manual")
        settings.sync()
        with tempfile.TemporaryDirectory() as td:
            first = self._make_window(td)
            try:
                first.show()
                first.resize(1920, 1080)
                QApplication.processEvents()
                # Default: expanded at the desktop token width, no manual pref persisted.
                self.assertEqual(first.workbench_nav.maximumWidth(), 180)
                self.assertIsNone(first._nav_collapsed_manual)

                first.close()
                first.deleteLater()
                QApplication.processEvents()

                self.assertFalse(settings.contains("nav_collapsed_manual"))

                second = self._make_window(td)
                try:
                    second.show()
                    second.resize(1920, 1080)
                    QApplication.processEvents()
                    self.assertEqual(second.workbench_nav.maximumWidth(), 180)
                    self.assertEqual(second.workbench_nav_buttons["review"].text(), "发票审核")
                    self.assertFalse(settings.contains("nav_collapsed_manual"))
                    self.assertIsNone(second._nav_collapsed_manual)
                finally:
                    second.db.close()
                    second.close()
                    second.deleteLater()
                    QApplication.processEvents()

            finally:
                if getattr(first, "db", None) is not None and first.db.is_open:
                    first.db.close()
                first.close()
                first.deleteLater()
                QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()
