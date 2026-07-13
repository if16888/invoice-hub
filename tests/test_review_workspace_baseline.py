import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSizePolicy

from scripts.invoice_fetch.gui.app import InvoiceReviewApp
from scripts.invoice_fetch.gui.review_detail_width_fix import (
    COLLAPSED_DETAIL_BONUS,
    DETAIL_MAX_WIDTH,
    _reflow_review_detail,
)
from scripts.invoice_fetch.gui.review_workspace_baseline import _sync_selection_contract


class ReviewWorkspaceBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, td):
        window = InvoiceReviewApp(Path(td) / "review-baseline.db")
        window.resize(1366, 768)
        window.show()
        for _ in range(5):
            self.app.processEvents()
        window._switch_main_page("review")
        self.app.processEvents()
        return window

    def test_review_workspace_baseline_is_applied(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertTrue(window.review_page.property("reviewWorkspaceBaselineApplied"))
                self.assertTrue(window.review_page.property("reviewDetailWidthFixApplied"))
                self.assertTrue(hasattr(window, "_review_detail_width_controller"))
                self.assertFalse(hasattr(window, "_review_feedback_resize_filter"))
                self.assertEqual(window._detail_panel.minimumWidth(), 352)
                self.assertLessEqual(window._detail_panel.maximumWidth(), DETAIL_MAX_WIDTH)
                self.assertEqual(window._detail_panel.sizePolicy().horizontalPolicy(), QSizePolicy.Expanding)
                self.assertEqual(window._detail_panel.sizePolicy().verticalPolicy(), QSizePolicy.Expanding)
            finally:
                window.close()

    def test_collapsed_sidebar_reclaims_width_for_review_detail(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.resize(1700, 900)
                window.workbench_nav.setMinimumWidth(180)
                window.workbench_nav.setMaximumWidth(180)
                for _ in range(3):
                    self.app.processEvents()
                _reflow_review_detail(window)
                self.app.processEvents()
                expanded_detail_width = window.main_splitter.sizes()[1]

                window.workbench_nav.setMinimumWidth(56)
                window.workbench_nav.setMaximumWidth(56)
                for _ in range(3):
                    self.app.processEvents()
                _reflow_review_detail(window)
                self.app.processEvents()
                collapsed_sizes = window.main_splitter.sizes()
                collapsed_detail_width = collapsed_sizes[1]

                self.assertGreaterEqual(
                    collapsed_detail_width,
                    expanded_detail_width + COLLAPSED_DETAIL_BONUS - 2,
                )
                usable_width = (
                    window.main_splitter.width()
                    - window.main_splitter.handleWidth() * (window.main_splitter.count() - 1)
                )
                self.assertLessEqual(abs(sum(collapsed_sizes) - usable_width), 2)
                self.assertLessEqual(collapsed_detail_width, DETAIL_MAX_WIDTH)
            finally:
                window.close()

    def test_filter_cards_do_not_render_unicode_decorations(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                for card in window.filter_buttons.values():
                    self.assertTrue(card.property("decorativeIconRemoved"))
                    self.assertEqual(card.icon_text(), "")
                    self.assertFalse(card._lbl_icon.isVisible())
                    self.assertGreaterEqual(card.minimumWidth(), 86)
                    self.assertLessEqual(card.maximumWidth(), 92)
                    self.assertTrue(card.accessibleName())
            finally:
                window.close()

    def test_no_selection_copy_and_state_are_truthful(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.table.setRowCount(1)
                window.current_invoice = None
                window.table.clearSelection()
                _sync_selection_contract(window)
                self.app.processEvents()
                self.assertEqual(window.lbl_right_empty_title.text(), "未选择发票")
                self.assertIn("选择一张发票", window.lbl_right_empty_desc.text())
                self.assertIs(window.right_stack.currentWidget(), window.right_empty_widget)
            finally:
                window.close()

    def test_empty_query_copy_is_truthful(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                window.table.setRowCount(0)
                window.current_invoice = None
                window.table.clearSelection()
                _sync_selection_contract(window)
                self.app.processEvents()
                self.assertEqual(window.lbl_right_empty_title.text(), "当前没有发票记录")
                self.assertIn("导入发票后", window.lbl_right_empty_desc.text())
            finally:
                window.close()

    def test_review_table_and_search_keep_dense_workspace_contract(self):
        with tempfile.TemporaryDirectory() as td:
            window = self.make_window(td)
            try:
                self.assertEqual(window.table.textElideMode(), Qt.ElideRight)
                self.assertEqual(window.table.verticalHeader().defaultSectionSize(), 24)
                self.assertGreaterEqual(window.txt_search.minimumWidth(), 260)
                self.assertEqual(window.txt_search.accessibleName(), "搜索发票")
                self.assertEqual(window.btn_advanced_filter.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
