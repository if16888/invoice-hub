"""Regression tests for the final P2 polish pass (preview frame, scrollbars)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PdfPreviewFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_pdf_views_are_frame_less_and_white(self):
        from PySide6.QtWidgets import QStackedWidget

        from scripts.invoice_fetch.gui.pdf_preview_controller import PdfPreviewController

        class StubView:
            PageMode = type("PageMode", (), {"MultiPage": 0, "SinglePage": 1})
            ZoomMode = type("ZoomMode", (), {"FitToWidth": 0})

            def __init__(self, parent):
                self.frame_shape = None
                self.style = ""
                self.document = None

            def setFrameShape(self, shape):
                self.frame_shape = shape

            def setStyleSheet(self, style):
                self.style = style

            def setDocument(self, document):
                self.document = document

            def setPageMode(self, mode):
                self.page_mode = mode

            def setZoomMode(self, mode):
                self.zoom_mode = mode

        stack = QStackedWidget()
        controller = PdfPreviewController(stack, stack)
        try:
            view = controller._make_view(StubView, object())
            from PySide6.QtWidgets import QFrame

            self.assertEqual(view.frame_shape, QFrame.NoFrame)
            self.assertIn("#FFFFFF", view.style)
        finally:
            controller.clear()
            stack.deleteLater()
            self.app.processEvents()


class UnifiedScrollbarTests(unittest.TestCase):
    def test_canonical_stylesheet_ships_one_scrollbar_treatment(self):
        from scripts.invoice_fetch.gui.styles import build_canonical_application_stylesheet

        stylesheet = build_canonical_application_stylesheet()
        self.assertIn("Unified scrollbars", stylesheet)
        self.assertIn("QScrollBar:vertical, QScrollBar:horizontal {", stylesheet)
        self.assertIn("border-radius: 999px;", stylesheet)
        self.assertIn("#D0D5DD", stylesheet)


if __name__ == "__main__":
    unittest.main()
