"""Atomic Qt PDF preview replacement.

Qt's PDF widgets can retain painted content when one ``QPdfView`` is reused
while its document is swapped. Every load owns a fresh document/view pair;
the old view is explicitly detached before its document is closed.
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
        self._active_path: Path | None = None
        self.document_class = None
        self.view_class = None

    def active_view(self):
        return self._view

    def active_document(self):
        return self._document

    def active_path(self) -> Path | None:
        return self._active_path

    def load(self, path: Path) -> None:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView

        document_class = self.document_class or QPdfDocument
        view_class = self.view_class or QPdfView

        self._generation += 1
        generation = self._generation
        old_view, old_document = self._view, self._document
        self._view = self._document = None
        self._active_path = None
        self._dispose(old_view, old_document)
        document = document_class(self)
        document._invoice_hub_path = Path(path)

        def status_changed(status):
            if generation != self._generation:
                self._dispose(None, document)
                return
            if status == QPdfDocument.Status.Ready:
                view = self._make_view(view_class, document)
                self._activate(generation, view, document)
            elif status == QPdfDocument.Status.Error:
                self._dispose(None, document)
                self.failed.emit(str(path))

        if not hasattr(document, "statusChanged"):
            document.load(str(path))
            view = self._make_view(view_class, document)
            self._activate(generation, view, document)
            return
        document.statusChanged.connect(status_changed)
        document.load(str(path))
        # ``statusChanged`` is asynchronous on some Qt builds but is emitted
        # synchronously before the event loop on others. Read the final state
        # once as well so a freshly-loaded local PDF is immediately usable.
        status_changed(document.status())

    def _make_view(self, view_class, document):
        """Bind a fresh viewer only after the document has loaded successfully."""
        view = view_class(self._stack)
        view.setDocument(document)
        if hasattr(view_class.PageMode, "MultiPage"):
            view.setPageMode(view_class.PageMode.MultiPage)
        else:
            view.setPageMode(view_class.PageMode.SinglePage)
        view.setZoomMode(view_class.ZoomMode.FitToWidth)
        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)
        return view

    def clear(self) -> None:
        self._generation += 1
        old_view, old_document = self._view, self._document
        self._view = self._document = None
        self._active_path = None
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
        self._active_path = getattr(document, "_invoice_hub_path", None)
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
            # Detach before closing/deleting the document. This prevents the
            # native QPdfLinkModel from retaining a pointer to the old file.
            try:
                view.setDocument(None)
            except Exception:
                pass
            if _is_qobject_alive(self._stack) and self._stack.indexOf(view) >= 0:
                self._stack.removeWidget(view)
            view.deleteLater()
        if _is_qobject_alive(document):
            try:
                document.close()
            except Exception:
                pass
            document.deleteLater()
