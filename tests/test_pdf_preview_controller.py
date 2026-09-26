"""Contracts for atomically replacing Qt PDF preview views."""

from __future__ import annotations

import inspect
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import QCoreApplication, QEvent, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from scripts.invoice_fetch.gui.pdf_preview_controller import PdfPreviewController
from scripts.invoice_fetch.gui import preview_mixin


def _make_pdf(path: Path) -> None:
    """Write a tiny valid PDF for native QtPdf lifecycle tests."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Contents 4 0 R /Resources << >> >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode("ascii"))
        data.extend(body)
        data.extend(b"\nendobj\n")
    xref_offset = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(data)


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
        self.assertIsNone(controller.active_view())

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

    def test_repeated_real_pdf_switches_emit_no_known_qt_lifecycle_warnings(self):
        try:
            from PySide6.QtPdf import QPdfDocument  # noqa: F401
        except ImportError:
            self.skipTest("QtPdf is unavailable")

        messages: list[str] = []

        def capture_message(_kind, _context, message):
            messages.append(str(message))

        previous_handler = qInstallMessageHandler(capture_message)
        stack = QStackedWidget()
        controller = PdfPreviewController(stack)
        try:
            with tempfile.TemporaryDirectory() as td:
                paths = [Path(td) / "first.pdf", Path(td) / "second.pdf"]
                for path in paths:
                    _make_pdf(path)

                for _ in range(5):
                    for path in paths:
                        controller.load(path)
                        deadline = time.monotonic() + 2.0
                        while controller.active_path() != path and time.monotonic() < deadline:
                            self.app.processEvents()
                            QTest.qWait(5)
                        self.assertEqual(controller.active_path(), path)

                controller.clear()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.app.processEvents()
        finally:
            qInstallMessageHandler(previous_handler)

        blocked = (
            "QObject::connect(QPdfDocument, QPdfLinkModel): invalid nullptr parameter",
            "QFont::setPointSize: Point size <= 0",
        )
        offenders = [message for message in messages if any(token in message for token in blocked)]
        self.assertEqual(offenders, [], "\n".join(offenders))


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
