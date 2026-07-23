"""Contracts for atomically replacing Qt PDF preview views."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from scripts.invoice_fetch.gui.pdf_preview_controller import PdfPreviewController
from scripts.invoice_fetch.gui import preview_mixin


class PdfPreviewControllerContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_controller_replaces_views_without_null_document_attachment(self):
        source = inspect.getsource(PdfPreviewController)
        self.assertIn("view.setDocument(document)", source)
        self.assertIn("self._stack.removeWidget(view)", source)
        self.assertIn("document.close()", source)
        self.assertNotIn("setDocument(None)", source)

    def test_preview_mixin_delegates_pdf_loading_to_controller(self):
        source = inspect.getsource(preview_mixin.PreviewMixin)
        self.assertIn("self.pdf_preview_controller.load(file_path)", source)
        self.assertNotIn("self.pdf_view.setDocument(None)", source)

    def test_failed_replacement_always_notifies_host(self):
        source = inspect.getsource(PdfPreviewController.load)
        self.assertIn("self.failed.emit(str(path))", source)
        self.assertNotIn("if self._view is None:", source)

    def test_failed_replacement_clears_previous_preview_before_error_state(self):
        target = SimpleNamespace(
            pdf_preview_controller=SimpleNamespace(clear=MagicMock()),
            _show_preview_status=MagicMock(),
            _set_zoom_buttons_enabled=MagicMock(),
            pdf_view=object(),
            pdf_document=object(),
        )

        preview_mixin.PreviewMixin._on_pdf_preview_failed(target, "broken.pdf")

        target.pdf_preview_controller.clear.assert_called_once_with()
        self.assertIsNone(target.pdf_view)
        self.assertIsNone(target.pdf_document)
        target._show_preview_status.assert_called_once_with("PDF 加载失败，暂不支持预览")

    def test_generation_guard_prevents_stale_activation(self):
        source = inspect.getsource(PdfPreviewController._activate)
        self.assertIn("generation != self._generation", source)

    def test_existing_preview_remains_active_until_replacement_activation(self):
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        old_view = QWidget(stack)
        old_document = _FakeDocument(Path("old.pdf"))
        controller._activate(0, old_view, old_document)

        controller._generation += 1  # replacement has started but is not Ready

        self.assertIs(controller.active_view(), old_view)
        self.assertIs(controller.active_document(), old_document)
        self.assertEqual(controller.active_path(), Path("old.pdf"))
        self.assertIs(stack.currentWidget(), old_view)

    def test_duplicate_ready_activation_keeps_active_view_alive(self):
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        view = QWidget(stack)
        document = _FakeDocument(Path("invoice.pdf"))

        controller._activate(0, view, document)
        controller._activate(0, view, document)

        self.assertIs(controller.active_view(), view)
        self.assertGreaterEqual(stack.indexOf(view), 0)
        self.app.processEvents()

    def test_dispose_ignores_already_deleted_qt_view(self):
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        view = QWidget(stack)
        stack.addWidget(view)
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        # Windows Qt may leave the Python wrapper reachable after C++ deletion.
        controller._dispose(view, None)

    def test_rapid_invoice_switches_keep_only_latest_pdf(self):
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        for index in range(10):
            view = QWidget(stack)
            document = _FakeDocument(Path(f"invoice-{index}.pdf"))
            controller._generation += 1
            controller._activate(controller._generation, view, document)

        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(controller.active_path(), Path("invoice-9.pdf"))
        self.assertEqual(stack.count(), 1)

        controller.clear()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertIsNone(controller.active_document())
        self.assertEqual(stack.count(), 0)


class _FakeDocument:
    def __init__(self, path: Path):
        self._invoice_hub_path = path
        self.closed = False
        self.deleted = False

    def close(self):
        self.closed = True

    def deleteLater(self):
        self.deleted = True


if __name__ == "__main__":
    unittest.main()
