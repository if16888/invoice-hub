# -*- coding: utf-8 -*-
"""Regression tests for the Design System v1.1 interaction language."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from scripts.invoice_fetch.gui.design_system_v11 import (
    apply_design_system_v11,
    apply_review_status_segmented_control,
    apply_sidebar_visual_language,
)
from scripts.invoice_fetch.gui.design_tokens import DESIGN_TOKEN_VERSION, DESIGN_V1_COLORS, DESIGN_V1_METRICS
from scripts.invoice_fetch.gui.review_baseline_pipeline import REVIEW_BASELINE_STAGES
from scripts.invoice_fetch.gui.ui.components import SegmentControl
from scripts.invoice_fetch.gui.ui_components import CompactStatCard


_QAPP = None


def _app() -> QApplication:
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


class DesignSystemV11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window_fixture(self):
        window = QWidget()
        root = QVBoxLayout(window)

        nav = QFrame(window)
        nav.setObjectName("WorkbenchNav")
        nav_layout = QVBoxLayout(nav)
        page_button = QPushButton("发票审核", nav)
        page_button.setProperty("class", "WorkbenchNavButton")
        page_button.setCheckable(True)
        page_button.setChecked(True)
        collapse = QPushButton("‹ 收起侧边栏", nav)
        nav_layout.addWidget(page_button)
        nav_layout.addWidget(collapse)
        root.addWidget(nav)

        filter_bar = QFrame(window)
        filter_bar.setObjectName("ExistingReviewFilterBar")
        filter_layout = QHBoxLayout(filter_bar)
        cards = {
            "all": CompactStatCard("全部", "259", state="info", parent=filter_bar),
            "to_review": CompactStatCard("待审核", "245", state="warning", parent=filter_bar),
            "approved": CompactStatCard("已通过", "14", state="success", parent=filter_bar),
            "ignored": CompactStatCard("已忽略", "0", state="muted", parent=filter_bar),
            "error": CompactStatCard("异常", "0", state="danger", parent=filter_bar),
        }
        cards["all"].set_selected(True)
        for card in cards.values():
            filter_layout.addWidget(card)
        root.addWidget(filter_bar)

        window.workbench_nav = nav
        window.filter_bar_widget = filter_bar
        window.filter_buttons = cards
        return window, nav, collapse, filter_bar, cards

    def _filter_state_fixture(self):
        window = QWidget()
        root = QVBoxLayout(window)
        bar = QFrame(window)
        layout = QHBoxLayout(bar)
        segment = SegmentControl(
            {
                "all": "全部",
                "to_review": "待审核",
                "approved": "已通过",
                "ignored": "已忽略",
                "error": "异常",
            },
            selected="all",
            parent=bar,
        )
        layout.addWidget(segment)
        root.addWidget(bar)

        search = QLineEdit(window)
        reset = QPushButton("清除筛选", window)
        empty_reset = QPushButton("重置筛选", window)
        root.addWidget(search)
        root.addWidget(reset)
        root.addWidget(empty_reset)

        window.filter_bar_widget = bar
        window.filter_buttons = segment.buttons
        window.status_segment_control = segment
        window.current_filter_status = None
        window.column_filters = {}
        window.txt_search = search
        window.btn_reset_filters = reset
        window.empty_btn_reset_filters = empty_reset
        window._refresh_column_filter_headers = lambda: None

        def change_filter(status: str) -> None:
            window.current_filter_status = None if status == "all" else status

        def reset_filters() -> None:
            window.current_filter_status = None
            window.column_filters.clear()
            window.txt_search.clear()

        segment.changed.connect(change_filter)
        window._reset_invoice_filters = reset_filters
        reset.clicked.connect(window._reset_invoice_filters)
        empty_reset.clicked.connect(window._reset_invoice_filters)
        return window, segment, reset, empty_reset

    def test_authoritative_tokens_include_interaction_metrics(self):
        self.assertEqual(DESIGN_TOKEN_VERSION, "design-v1.3-visual-language")
        self.assertEqual(DESIGN_V1_METRICS["icon_button_size"], 32)
        self.assertEqual(DESIGN_V1_METRICS["segmented_control_height"], 36)
        self.assertEqual(DESIGN_V1_METRICS["segmented_item_height"], 30)
        self.assertEqual(DESIGN_V1_METRICS["segmented_item_gap"], 4)

    def test_sidebar_uses_fill_states_without_decorative_outlines(self):
        window, nav, collapse, _bar, _cards = self._window_fixture()
        try:
            apply_sidebar_visual_language(window)

            self.assertEqual(nav.property("visualLanguage"), "design-v1.1")
            self.assertEqual(collapse.property("navigationControl"), "collapse")
            self.assertTrue(collapse.isFlat())
            self.assertEqual(collapse.maximumHeight(), DESIGN_V1_METRICS["icon_button_size"])
            qss = nav.styleSheet()
            self.assertIn('QPushButton[navigationControl="collapse"]', qss)
            self.assertIn("QPushButton.WorkbenchNavButton:checked", qss)
            self.assertIn("background-color: #EFF6FF", qss)
            self.assertIn("border: none", qss)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_review_statuses_form_one_neutral_segmented_control(self):
        window, _nav, _collapse, bar, cards = self._window_fixture()
        try:
            apply_review_status_segmented_control(window)

            self.assertEqual(bar.objectName(), "ExistingReviewFilterBar")
            self.assertEqual(bar.property("visualRole"), "segmented-filter")
            self.assertEqual(bar.height(), DESIGN_V1_METRICS["segmented_control_height"])
            self.assertIn('QFrame[visualRole="segmented-filter"]', bar.styleSheet())
            self.assertIn(DESIGN_V1_COLORS["surface_secondary"], bar.styleSheet())
            self.assertIn(DESIGN_V1_COLORS["border_subtle"], bar.styleSheet())

            status_only_colors = {
                DESIGN_V1_COLORS["warning"],
                DESIGN_V1_COLORS["warning_border"],
                DESIGN_V1_COLORS["success"],
                DESIGN_V1_COLORS["success_border"],
                DESIGN_V1_COLORS["danger"],
                DESIGN_V1_COLORS["danger_border"],
            }
            for status, card in cards.items():
                self.assertEqual(card.property("visualRole"), "status-segment")
                self.assertEqual(card.property("statusKey"), status)
                self.assertEqual(card.height(), DESIGN_V1_METRICS["segmented_item_height"])
                self.assertIn('QFrame#CompactStatCard[selected="true"]', card.styleSheet())
                self.assertIn("border: none", card.styleSheet())
                for color in status_only_colors:
                    self.assertNotIn(color, card.styleSheet())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_segment_selection_refreshes_title_and_value_colors(self):
        window = QWidget()
        root = QVBoxLayout(window)
        bar = QFrame(window)
        bar_layout = QHBoxLayout(bar)
        segment = SegmentControl(
            {
                "all": "全部",
                "to_review": "待审核",
                "approved": "已通过",
                "ignored": "已忽略",
                "error": "异常",
            },
            selected="all",
            parent=bar,
        )
        segment.set_value("all", 259)
        segment.set_value("to_review", 245)
        bar_layout.addWidget(segment)
        root.addWidget(bar)
        window.filter_bar_widget = bar
        window.filter_buttons = segment.buttons

        try:
            apply_review_status_segmented_control(window)
            window.show()
            self.app.processEvents()

            segment.set_selected("all")
            self.app.processEvents()
            all_card = segment.buttons["all"]
            review_card = segment.buttons["to_review"]
            self.assertEqual(
                all_card._lbl_title.palette().color(QPalette.WindowText).name().upper(),
                DESIGN_V1_COLORS["accent_hover"].upper(),
            )
            self.assertEqual(
                all_card._lbl_value.palette().color(QPalette.WindowText).name().upper(),
                DESIGN_V1_COLORS["accent_hover"].upper(),
            )
            self.assertEqual(
                review_card._lbl_title.palette().color(QPalette.WindowText).name().upper(),
                DESIGN_V1_COLORS["text_secondary"].upper(),
            )
            self.assertEqual(
                review_card._lbl_value.palette().color(QPalette.WindowText).name().upper(),
                DESIGN_V1_COLORS["text"].upper(),
            )

            segment.set_selected("to_review")
            self.app.processEvents()
            self.assertEqual(
                all_card._lbl_title.palette().color(QPalette.WindowText).name().upper(),
                DESIGN_V1_COLORS["text_secondary"].upper(),
            )
            self.assertEqual(
                all_card._lbl_value.palette().color(QPalette.WindowText).name().upper(),
                DESIGN_V1_COLORS["text"].upper(),
            )
            self.assertEqual(
                review_card._lbl_title.palette().color(QPalette.WindowText).name().upper(),
                DESIGN_V1_COLORS["accent_hover"].upper(),
            )
            self.assertEqual(
                review_card._lbl_value.palette().color(QPalette.WindowText).name().upper(),
                DESIGN_V1_COLORS["accent_hover"].upper(),
            )
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_reset_filter_restores_all_segment_and_hides_clear_action(self):
        window, segment, reset, empty_reset = self._filter_state_fixture()
        try:
            apply_review_status_segmented_control(window)
            window.show()
            self.app.processEvents()

            segment.buttons["ignored"].clicked.emit()
            self.app.processEvents()
            self.assertEqual(window.current_filter_status, "ignored")
            self.assertEqual(segment.selected(), "ignored")
            self.assertTrue(segment.buttons["ignored"].property("selected"))
            self.assertFalse(reset.isHidden())

            reset.click()
            self.app.processEvents()
            self.assertIsNone(window.current_filter_status)
            self.assertEqual(segment.selected(), "all")
            self.assertTrue(segment.buttons["all"].property("selected"))
            self.assertFalse(segment.buttons["ignored"].property("selected"))
            self.assertTrue(reset.isHidden())

            segment.buttons["ignored"].clicked.emit()
            self.app.processEvents()
            empty_reset.click()
            self.app.processEvents()
            self.assertEqual(segment.selected(), "all")
            self.assertTrue(segment.buttons["all"].property("selected"))
            self.assertFalse(segment.buttons["ignored"].property("selected"))
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_direct_reset_callback_uses_same_filter_state_contract(self):
        window, segment, _reset, _empty_reset = self._filter_state_fixture()
        try:
            apply_review_status_segmented_control(window)
            segment.buttons["ignored"].clicked.emit()
            self.app.processEvents()
            self.assertEqual(segment.selected(), "ignored")

            window._reset_invoice_filters()

            self.assertIsNone(window.current_filter_status)
            self.assertEqual(segment.selected(), "all")
            self.assertTrue(segment.buttons["all"].property("selected"))
            self.assertFalse(segment.buttons["ignored"].property("selected"))
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_shared_application_is_idempotent(self):
        window, nav, collapse, bar, cards = self._window_fixture()
        try:
            apply_design_system_v11(window)
            first_nav_qss = nav.styleSheet()
            first_bar_qss = bar.styleSheet()
            first_card_qss = cards["all"].styleSheet()

            apply_design_system_v11(window)

            self.assertEqual(nav.styleSheet(), first_nav_qss)
            self.assertEqual(bar.styleSheet(), first_bar_qss)
            self.assertEqual(cards["all"].styleSheet(), first_card_qss)
            self.assertEqual(collapse.property("navigationControl"), "collapse")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_visual_language_is_final_review_pipeline_stage(self):
        self.assertEqual(REVIEW_BASELINE_STAGES[-1][0], "visual_language_v11")
        self.assertIs(REVIEW_BASELINE_STAGES[-1][1], apply_design_system_v11)


if __name__ == "__main__":
    unittest.main()
