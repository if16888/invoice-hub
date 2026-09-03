# -*- coding: utf-8 -*-
"""Regression tests for deterministic list selection/focus styling."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QStyle,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from scripts.invoice_fetch.gui.column_filters import ColumnFilterPopup
from scripts.invoice_fetch.gui.page_layouts import DashboardPageLayout
from scripts.invoice_fetch.gui.selection_surfaces import (
    SelectionSurfaceDelegate,
    install_selection_surface_contracts,
)
from scripts.invoice_fetch.gui.ui_components import EntityList, SecondaryNavStack


_QAPP = None


def _app() -> QApplication:
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


class SelectionSurfaceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _flush(self):
        self.app.processEvents()
        self.app.processEvents()

    def test_delegate_removes_only_native_focus_rect(self):
        option = QStyleOptionViewItem()
        option.state |= QStyle.StateFlag.State_HasFocus
        option.state |= QStyle.StateFlag.State_Selected

        normalized = SelectionSurfaceDelegate.normalized_option(option)

        self.assertFalse(bool(normalized.state & QStyle.StateFlag.State_HasFocus))
        self.assertTrue(bool(normalized.state & QStyle.StateFlag.State_Selected))

    def test_entity_list_uses_property_driven_selected_row(self):
        entity_list = EntityList()
        item = entity_list.add_entity_row(
            "202601-06",
            "2 张发票 · ¥51.90",
            status_badge="可导出",
            user_data=1,
        )
        row = entity_list.itemWidget(item)
        row.setObjectName("ClaimGroupRow")
        try:
            install_selection_surface_contracts(entity_list)
            entity_list.setCurrentItem(item)
            item.setSelected(True)
            self._flush()

            self.assertIsInstance(entity_list.itemDelegate(), SelectionSurfaceDelegate)
            self.assertFalse(entity_list.alternatingRowColors())
            self.assertEqual(row.objectName(), "ClaimGroupRow")
            self.assertEqual(row.property("selectionSurfaceRow"), "true")
            self.assertEqual(row.property("selected"), "true")
            self.assertGreaterEqual(row.minimumHeight(), 68)
            self.assertGreaterEqual(item.sizeHint().height(), 68)
            margins = row.layout().contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                (8, 6, 8, 6),
            )
            qss = entity_list.styleSheet()
            self.assertIn('QWidget[selectionSurfaceRow="true"][selected="true"]', qss)
            self.assertIn("QListWidget#EntityList::item:selected:active", qss)
            self.assertIn("outline: 0", qss)
        finally:
            entity_list.close()
            entity_list.deleteLater()
            self._flush()

    def test_entity_row_text_click_changes_current_item(self):
        entity_list = EntityList()
        first = entity_list.add_entity_row("First claim", "1 张发票", user_data=1)
        second = entity_list.add_entity_row("Second claim", "2 张发票", user_data=2)
        try:
            install_selection_surface_contracts(entity_list)
            entity_list.resize(360, 180)
            entity_list.show()
            entity_list.setCurrentItem(first)
            self._flush()

            entity_list.setFocus(Qt.OtherFocusReason)
            QTest.keyClick(entity_list, Qt.Key_Down)
            self._flush()
            self.assertEqual(entity_list.currentRow(), 1)
            self.assertIs(entity_list.currentItem(), second)

            entity_list.setCurrentItem(first)
            self._flush()

            second_row = entity_list.itemWidget(second)
            second_title = second_row.findChildren(QLabel)[0]
            QTest.mouseClick(second_title, Qt.LeftButton, pos=second_title.rect().center())
            self._flush()

            self.assertEqual(entity_list.currentRow(), 1)
            self.assertIs(entity_list.currentItem(), second)
        finally:
            entity_list.close()
            entity_list.deleteLater()
            self._flush()

    def test_rows_inserted_after_install_are_decorated(self):
        entity_list = EntityList()
        try:
            install_selection_surface_contracts(entity_list)
            item = entity_list.add_entity_row("Late row", "Inserted after contract")
            row = entity_list.itemWidget(item)
            row.setObjectName("MailboxAccountRow")
            entity_list.setCurrentItem(item)
            item.setSelected(True)
            self._flush()

            self.assertEqual(row.objectName(), "MailboxAccountRow")
            self.assertEqual(row.property("selectionSurfaceRow"), "true")
            self.assertEqual(row.property("selected"), "true")
            self.assertGreaterEqual(item.sizeHint().height(), 68)
        finally:
            entity_list.close()
            entity_list.deleteLater()
            self._flush()

    def test_secondary_navigation_uses_same_focus_rect_delegate(self):
        nav = SecondaryNavStack()
        try:
            nav.addTab(QWidget(), "邮箱账户")
            nav.addTab(QWidget(), "开票信息")
            install_selection_surface_contracts(nav)
            self._flush()

            self.assertIsInstance(nav.nav_list.itemDelegate(), SelectionSurfaceDelegate)
            self.assertEqual(nav.nav_list.property("selectionSurfaceContract"), "secondary-nav")
            qss = nav.nav_list.styleSheet()
            self.assertIn("QListWidget#SecondaryNavList::item:selected:active", qss)
            self.assertIn("outline: 0", qss)
        finally:
            nav.close()
            nav.deleteLater()
            self._flush()

    def test_filter_popup_value_list_uses_shared_selection_contract(self):
        popup = ColumnFilterPopup(
            "seller_name",
            ["供应商 A", "供应商 B"],
            {},
            lambda _key, _spec: None,
        )
        try:
            self._flush()
            value_list = popup.value_list
            self.assertEqual(value_list.objectName(), "FilterValueList")
            self.assertIsInstance(value_list.itemDelegate(), SelectionSurfaceDelegate)
            self.assertEqual(value_list.property("selectionSurfaceContract"), "filter-values")
            qss = value_list.styleSheet()
            self.assertIn("QListWidget#FilterValueList::item:selected:active", qss)
            self.assertIn("outline: 0", qss)
        finally:
            popup.close()
            popup.deleteLater()
            self._flush()

    def test_page_layout_schedules_contract_for_child_lists(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        entity_list = EntityList(page)
        layout.addWidget(entity_list)
        item = entity_list.add_entity_row("Claim", "Ready")
        try:
            DashboardPageLayout.apply(page, layout)
            entity_list.setCurrentItem(item)
            item.setSelected(True)
            self._flush()

            row = entity_list.itemWidget(item)
            self.assertEqual(entity_list.property("selectionSurfaceContract"), "entity")
            self.assertEqual(row.property("selectionSurfaceRow"), "true")
            self.assertEqual(row.property("selected"), "true")
        finally:
            page.close()
            page.deleteLater()
            self._flush()

    def test_page_watcher_handles_lists_created_after_layout_apply(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        try:
            DashboardPageLayout.apply(page, layout)
            entity_list = EntityList(page)
            layout.addWidget(entity_list)
            item = entity_list.add_entity_row("Deferred claim", "Ready")
            entity_list.setCurrentItem(item)
            item.setSelected(True)
            self._flush()

            row = entity_list.itemWidget(item)
            self.assertEqual(entity_list.property("selectionSurfaceContract"), "entity")
            self.assertEqual(row.property("selectionSurfaceRow"), "true")
            self.assertEqual(row.property("selected"), "true")
        finally:
            page.close()
            page.deleteLater()
            self._flush()


if __name__ == "__main__":
    unittest.main()
