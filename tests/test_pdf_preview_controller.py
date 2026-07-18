"""Contracts for atomically replacing Qt PDF preview views."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from scripts.invoice_fetch.gui.pdf_preview_controller import PdfPreviewController
from scripts.invoice_fetch.gui import preview_mixin


class PdfPreviewControllerContracts(unittest.TestCase):
    def test_controller_replaces_views_instead_of_detaching_documents(self):
        source = inspect.getsource(PdfPreviewController)
        self.assertIn("view.setDocument(document)", source)
        self.assertIn("self._stack.removeWidget(view)", source)
        self.assertIn("document.close()", source)
        self.assertIn("setDocument(None)", source)

    def test_preview_mixin_delegates_pdf_loading_to_controller(self):
        source = inspect.getsource(preview_mixin.PreviewMixin)
        self.assertIn("self.pdf_preview_controller.load(file_path)", source)
        self.assertNotIn("self.pdf_view.setDocument(None)", source)

    def test_generation_guard_prevents_stale_activation(self):
        source = inspect.getsource(PdfPreviewController._activate)
        self.assertIn("generation != self._generation", source)

    def test_duplicate_ready_activation_keeps_active_view_alive(self):
        app = QApplication.instance() or QApplication([])
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        view = QWidget(stack)
        document = object()

        controller._activate(0, view, document)
        controller._activate(0, view, document)

        self.assertIs(controller.active_view(), view)
        self.assertGreaterEqual(stack.indexOf(view), 0)
        app.processEvents()

    def test_dispose_ignores_already_deleted_qt_view(self):
        QApplication.instance() or QApplication([])
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        view = QWidget(stack)
        stack.addWidget(view)
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        # This is the Windows Qt failure mode: the wrapper is still reachable,
        # but its C++ QWidget has already gone away.
        controller._dispose(view, None)

    def test_rapid_invoice_switches_keep_only_latest_pdf(self):
        """Ten consecutive invoice changes must leave one current document."""
        app = QApplication.instance() or QApplication([])
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        for index in range(10):
            view = QWidget(stack)
            document = _FakeDocument(Path(f"invoice-{index}.pdf"))
            controller._generation += 1
            controller._activate(controller._generation, view, document)
        app.processEvents()
        self.assertEqual(controller.active_path(), Path("invoice-9.pdf"))
        self.assertLessEqual(stack.count(), 1)
        controller.clear()
        app.processEvents()
        self.assertIsNone(controller.active_document())


if __name__ == "__main__":
    unittest.main()


class _FakeDocument:
    def __init__(self, path: Path):
        self._invoice_hub_path = path

    def close(self):
        return None

    def deleteLater(self):
        return None
