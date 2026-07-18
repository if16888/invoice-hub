"""Contracts for atomically replacing Qt PDF preview views."""

from __future__ import annotations

import inspect
import unittest

from scripts.invoice_fetch.gui.pdf_preview_controller import PdfPreviewController
from scripts.invoice_fetch.gui import preview_mixin


class PdfPreviewControllerContracts(unittest.TestCase):
    def test_controller_replaces_views_instead_of_detaching_documents(self):
        source = inspect.getsource(PdfPreviewController)
        self.assertIn("view.setDocument(document)", source)
        self.assertIn("self._stack.removeWidget(view)", source)
        self.assertIn("document.close()", source)
        self.assertNotIn("setDocument(None)", source)

    def test_preview_mixin_delegates_pdf_loading_to_controller(self):
        source = inspect.getsource(preview_mixin.PreviewMixin)
        self.assertIn("self.pdf_preview_controller.load(file_path)", source)
        self.assertNotIn("self.pdf_view.setDocument(None)", source)

    def test_generation_guard_prevents_stale_activation(self):
        source = inspect.getsource(PdfPreviewController._activate)
        self.assertIn("generation != self._generation", source)


if __name__ == "__main__":
    unittest.main()
