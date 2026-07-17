# -*- coding: utf-8 -*-
"""Regression tests for right-side invoice detail tab ownership."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import (
    QApplication,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from scripts.invoice_fetch.gui import ui_visibility_contracts
from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel


_QAPP = None


def _app() -> QApplication:
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


class ReviewDetailTabStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_single_invoice_refresh_preserves_reimbursement_tab(self):
        messages: list[str] = []

        def capture_message(_kind, _context, message):
            messages.append(str(message))

        previous_handler = qInstallMessageHandler(capture_message)
        panel = InvoiceDetailPanel()
        try:
            panel.show()
            self.app.processEvents()

            self.assertEqual(panel.right_stack.indexOf(panel.right_content_widget), -1)
            self.assertGreaterEqual(panel.right_stack.indexOf(panel.detail_page), 0)
            self.assertEqual(panel.detail_tabs.tabText(1), "报销信息")

            panel.detail_tabs.setCurrentIndex(1)
            panel.set_attachment_state(path="", source_url="", can_download=False)
            panel.set_single_selection_state()
            self.app.processEvents()

            self.assertEqual(panel.detail_tabs.currentIndex(), 1)
            self.assertIs(panel.detail_tabs.currentWidget(), panel.reimbursement_scroll)
            self.assertIs(panel.right_stack.currentWidget(), panel.detail_page)
            self.assertFalse(
                any("not contained in stack" in message for message in messages),
                messages,
            )
        finally:
            panel.close()
            panel.deleteLater()
            self.app.processEvents()
            qInstallMessageHandler(previous_handler)

    def test_reveal_widget_does_not_desynchronise_qtabwidget(self):
        tabs = QTabWidget()
        basic_page = QWidget()
        basic_layout = QVBoxLayout(basic_page)
        action = QPushButton("打开")
        basic_layout.addWidget(action)
        reimbursement_page = QWidget()
        tabs.addTab(basic_page, "基本信息")
        tabs.addTab(reimbursement_page, "报销信息")
        tabs.setCurrentIndex(1)
        try:
            ui_visibility_contracts._reveal_widget(action, boundary=tabs)
            self.app.processEvents()

            self.assertEqual(tabs.currentIndex(), 1)
            self.assertIs(tabs.currentWidget(), reimbursement_page)
        finally:
            tabs.close()
            tabs.deleteLater()
            self.app.processEvents()

    def test_reveal_widget_selects_owned_application_stack_page(self):
        stack = QStackedWidget()
        first_page = QWidget()
        first_layout = QVBoxLayout(first_page)
        action = QPushButton("补充")
        first_layout.addWidget(action)
        second_page = QWidget()
        stack.addWidget(first_page)
        stack.addWidget(second_page)
        stack.setCurrentWidget(second_page)
        try:
            ui_visibility_contracts._reveal_widget(action, boundary=stack)
            self.app.processEvents()

            self.assertIs(stack.currentWidget(), first_page)
        finally:
            stack.close()
            stack.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
