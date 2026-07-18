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


def _is_qobject_alive(value) -> bool:
    """Return whether a Qt wrapper still owns a live C++ object.

    Qt may deliver a final PDF status notification after ``deleteLater`` has
    destroyed the old view.  Calling a Qt API on that Python wrapper raises
    ``RuntimeError: Internal C++ object ... already deleted``.  Non-Qt test
    doubles are deliberately considered live here.
    """
    if value is None:
        return False
    if not isinstance(value, QObject):
        return True
    try:
        from shiboken6 import isValid

        return bool(isValid(value))
    except RuntimeError:
        return False


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
        self.document_class = None
        self.view_class = None

    def active_view(self):
        return self._view

    def active_document(self):
        return self._document

    def load(self, path: Path) -> None:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView

        document_class = self.document_class or QPdfDocument
        view_class = self.view_class or QPdfView

        self._generation += 1
        generation = self._generation
        document = document_class(self)
        view = view_class(self._stack)
        view.setDocument(document)
        if hasattr(view_class.PageMode, "MultiPage"):
            view.setPageMode(view_class.PageMode.MultiPage)
        else:
            view.setPageMode(view_class.PageMode.SinglePage)
        view.setZoomMode(view_class.ZoomMode.FitToWidth)
        # A fresh view can render while the document is loading. Make it the
        # visible stack page immediately; this avoids a blank preview when a
        # Windows Qt build delays or drops the Ready notification. The old
        # view remains a separate widget until activation disposes it.
        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)

        def status_changed(status):
            if generation != self._generation:
                self._dispose(view, document)
                return
            if status == QPdfDocument.Status.Ready:
                self._activate(generation, view, document)
            elif status == QPdfDocument.Status.Error:
                self._dispose(view, document)
                self.failed.emit(str(path))

        if not hasattr(document, "statusChanged"):
            document.load(str(path))
            self._activate(generation, view, document)
            return
        document.statusChanged.connect(status_changed)
        document.load(str(path))
        # ``statusChanged`` is asynchronous on some Qt builds but is emitted
        # synchronously before the event loop on others. Read the final state
        # once as well so a freshly-loaded local PDF is immediately usable.
        status_changed(document.status())

    def clear(self) -> None:
        self._generation += 1
        old_view, old_document = self._view, self._document
        self._view = self._document = None
        self._dispose(old_view, old_document)

    def _activate(self, generation, view, document) -> None:
        if generation != self._generation:
            self._dispose(view, document)
            return
        # ``statusChanged(Ready)`` and the immediate post-load status read can
        # both reach this method.  The second call must not retire the active
        # pair merely because it is also the "old" pair.
        if view is self._view and document is self._document:
            return
        if not _is_qobject_alive(view) or not _is_qobject_alive(document):
            return
        old_view, old_document = self._view, self._document
        self._view, self._document = view, document
        if self._stack.indexOf(view) < 0:
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
        if _is_qobject_alive(view):
            if _is_qobject_alive(self._stack) and self._stack.indexOf(view) >= 0:
                self._stack.removeWidget(view)
            view.deleteLater()
        if _is_qobject_alive(document):
            try:
                document.close()
            except Exception:
                pass
            document.deleteLater()
