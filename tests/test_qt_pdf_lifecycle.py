# -*- coding: utf-8 -*-
"""Regression tests for the Windows Qt PDF document lifecycle warning."""

from __future__ import annotations

import inspect
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch import gui
from scripts.invoice_fetch.gui import preview_mixin
from scripts.invoice_fetch.gui.qt_pdf_lifecycle import (
    install_qt_pdf_lifecycle_contract,
    stable_pdf_view_class,
)


_QAPP = None


def _app() -> QApplication:
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


class QtPdfLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        if not install_qt_pdf_lifecycle_contract():
            self.skipTest("Qt PDF modules are unavailable")

    def test_preview_cache_uses_stable_pdf_view(self):
        document_class, view_class = preview_mixin.get_qt_pdf_classes()
        self.assertIsNotNone(document_class)
        self.assertIs(view_class, stable_pdf_view_class())
        self.assertEqual(view_class.__name__, "InvoiceHubPdfView")

    def test_intermediate_none_keeps_existing_document_attached(self):
        document_class, view_class = preview_mixin.get_qt_pdf_classes()
        view = view_class()
        first = document_class(view)
        second = document_class(view)
        try:
            view.setDocument(first)
            self.assertIs(view.document(), first)

            view.setDocument(None)
            self.assertIs(view.document(), first)

            # Mirror the legacy refresh order: close/delete the old document,
            # then immediately assign the valid replacement.
            first.close()
            first.deleteLater()
            view.setDocument(second)
            self.app.processEvents()
            self.assertIs(view.document(), second)
        finally:
            view.close()
            view.deleteLater()
            second.close()
            second.deleteLater()
            self.app.processEvents()

    def test_replacement_emits_no_null_qpdf_link_model_warning(self):
        messages: list[str] = []

        def capture(_kind, _context, message):
            messages.append(str(message))

        previous = qInstallMessageHandler(capture)
        document_class, view_class = preview_mixin.get_qt_pdf_classes()
        view = view_class()
        first = document_class(view)
        second = document_class(view)
        try:
            view.setDocument(first)
            view.setDocument(None)
            first.close()
            first.deleteLater()
            view.setDocument(second)
            self.app.processEvents()

            self.assertFalse(
                any(
                    "QPdfLinkModel" in message and "invalid nullptr parameter" in message
                    for message in messages
                ),
                messages,
            )
        finally:
            view.close()
            view.deleteLater()
            second.close()
            second.deleteLater()
            self.app.processEvents()
            qInstallMessageHandler(previous)

    def test_desktop_launcher_installs_contract_before_app_import(self):
        source = inspect.getsource(gui.start_gui)
        install_pos = source.index("install_qt_pdf_lifecycle_contract()")
        app_import_pos = source.index("from .app import start_gui_app")
        self.assertLess(install_pos, app_import_pos)


if __name__ == "__main__":
    unittest.main()
