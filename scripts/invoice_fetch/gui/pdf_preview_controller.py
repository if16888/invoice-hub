"""Atomic Qt PDF preview replacement.

Qt's PDF widgets can retain painted content when one ``QPdfView`` is reused
while its document is swapped.  This controller never detaches a document from
an existing view: every load owns a fresh document/view pair and replaces the
visible pair only after that document is ready.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QStackedWidget


class PdfPreviewController(QObject):
    ready = Signal()
    failed = Signal(str)
    page_changed = Signal(int, int)

    def __init__(self, stack: QStackedWidget, parent=None):
        super().__init__(parent or stack)
        self._stack = stack
        self._generation = 0
        self._view = None
        self._document = None

    def active_view(self):
        return self._view

    def active_document(self):
        return self._document

    def load(self, path: Path) -> None:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView

        self._generation += 1
        generation = self._generation
        document = QPdfDocument(self)
        view = QPdfView(self._stack)
        view.setDocument(document)
        if hasattr(QPdfView.PageMode, "MultiPage"):
            view.setPageMode(QPdfView.PageMode.MultiPage)
        else:
            view.setPageMode(QPdfView.PageMode.SinglePage)
        view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

        def status_changed(status):
            if generation != self._generation:
                self._dispose(view, document)
                return
            if status == QPdfDocument.Status.Ready:
                self._activate(generation, view, document)
            elif status == QPdfDocument.Status.Error:
                self._dispose(view, document)
                self.failed.emit(str(path))

        document.statusChanged.connect(status_changed)
        document.load(str(path))

    def clear(self) -> None:
        self._generation += 1
        old_view, old_document = self._view, self._document
        self._view = self._document = None
        self._dispose(old_view, old_document)

    def _activate(self, generation, view, document) -> None:
        if generation != self._generation:
            self._dispose(view, document)
            return
        old_view, old_document = self._view, self._document
        self._view, self._document = view, document
        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)
        try:
            document.pageNavigator().jump(0, 0.0, 0.0)
        except Exception:
            pass
        try:
            document.pageNavigator().currentPageChanged.connect(self._emit_page_changed)
        except Exception:
            pass
        self._dispose(old_view, old_document)
        self.ready.emit()

    def _emit_page_changed(self, page: int) -> None:
        document = self._document
        if document is not None:
            self.page_changed.emit(page, document.pageCount())

    def _dispose(self, view, document) -> None:
        if view is not None:
            if self._stack.indexOf(view) >= 0:
                self._stack.removeWidget(view)
            view.deleteLater()
        if document is not None:
            try:
                document.close()
            except Exception:
                pass
            document.deleteLater()
