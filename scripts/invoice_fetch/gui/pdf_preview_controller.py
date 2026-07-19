"""Atomic Qt PDF preview replacement.

Every load owns a fresh ``QPdfDocument`` and ``QPdfView`` pair. The currently
visible pair remains attached until the replacement document reaches ``Ready``;
only then is the new view shown and the previous pair retired. This avoids both
blank-preview gaps and the native ``QPdfLinkModel`` warnings caused by briefly
attaching ``None`` as a document.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QStackedWidget


def _is_qobject_alive(value) -> bool:
    """Return whether a Qt wrapper still owns a live C++ object."""
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
        self._pending_document = None
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

        previous_pending = self._pending_document
        self._pending_document = None
        if previous_pending is not None and previous_pending is not self._document:
            self._dispose_document(previous_pending)

        document = document_class(self)
        document._invoice_hub_path = Path(path)
        self._pending_document = document
        activated = False

        def status_changed(status):
            nonlocal activated
            if activated:
                return
            if generation != self._generation:
                if self._pending_document is document:
                    self._pending_document = None
                self._dispose_document(document)
                return
            if status == QPdfDocument.Status.Ready:
                activated = True
                view = self._make_view(view_class, document)
                self._activate(generation, view, document)
            elif status == QPdfDocument.Status.Error:
                activated = True
                if self._pending_document is document:
                    self._pending_document = None
                self._dispose_document(document)
                # A failed replacement must not blank a previously valid PDF.
                if self._view is None:
                    self.failed.emit(str(path))

        if not hasattr(document, "statusChanged"):
            document.load(str(path))
            view = self._make_view(view_class, document)
            self._activate(generation, view, document)
            return

        document.statusChanged.connect(status_changed)
        document.load(str(path))
        # Qt may emit Ready synchronously or asynchronously depending on the
        # platform/plugin. Reading the current status makes both paths reliable.
        status_changed(document.status())

    def _make_view(self, view_class, document):
        """Create a replacement view without disturbing the active preview."""
        view = view_class(self._stack)
        view.setDocument(document)
        if hasattr(view_class.PageMode, "MultiPage"):
            view.setPageMode(view_class.PageMode.MultiPage)
        else:
            view.setPageMode(view_class.PageMode.SinglePage)
        view.setZoomMode(view_class.ZoomMode.FitToWidth)
        return view

    def clear(self) -> None:
        self._generation += 1

        pending = self._pending_document
        self._pending_document = None
        if pending is not None and pending is not self._document:
            self._dispose_document(pending)

        old_view, old_document = self._view, self._document
        self._view = self._document = None
        self._active_path = None
        self._retire_pair(old_view, old_document)

    def _activate(self, generation, view, document) -> None:
        if generation != self._generation:
            self._retire_pair(view, document)
            return
        if view is self._view and document is self._document:
            return
        if not _is_qobject_alive(view) or not _is_qobject_alive(document):
            return

        old_view, old_document = self._view, self._document
        self._view, self._document = view, document
        self._pending_document = None
        self._active_path = getattr(document, "_invoice_hub_path", None)

        if self._stack.indexOf(view) < 0:
            self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)
        view.show()

        try:
            navigator = view.pageNavigator()
            # Existing preview helpers historically ask the document for its
            # navigator. Expose the view navigator on the Python wrapper so both
            # old and new callers operate on the same live object.
            if not hasattr(document, "pageNavigator"):
                document.pageNavigator = view.pageNavigator
            navigator.jump(0, 0.0, 0.0)
            navigator.currentPageChanged.connect(self._emit_page_changed)
        except Exception:
            pass

        def refresh_viewport():
            if not _is_qobject_alive(view):
                return
            try:
                view.viewport().update()
                view.update()
            except Exception:
                pass

        refresh_viewport()
        QTimer.singleShot(0, refresh_viewport)

        # Only retire the old pair after the replacement is visible.
        self._retire_pair(old_view, old_document)
        self.ready.emit()

    def _emit_page_changed(self, page: int) -> None:
        document = self._document
        if document is not None:
            self.page_changed.emit(page, document.pageCount())

    def _close_document(self, document) -> None:
        """Synchronously stop rendering while the wrapper is still valid."""
        if not _is_qobject_alive(document):
            return
        try:
            document.close()
        except Exception:
            pass

    def _delete_document_later(self, document) -> None:
        if not _is_qobject_alive(document):
            return
        try:
            document.deleteLater()
        except Exception:
            pass

    def _dispose_document(self, document) -> None:
        self._close_document(document)
        self._delete_document_later(document)

    def _retire_pair(self, view, document) -> None:
        """Close a retired document now, then delete it after its view."""
        if not _is_qobject_alive(view):
            self._dispose_document(document)
            return

        if _is_qobject_alive(self._stack) and self._stack.indexOf(view) >= 0:
            self._stack.removeWidget(view)
        try:
            view.hide()
        except Exception:
            pass

        # Closing is synchronous and keeps the live document attached until the
        # old view is destroyed. This stops stale rendering without a null bind.
        self._close_document(document)
        deleted = False

        def finish_document_deletion(*_args):
            nonlocal deleted
            if deleted:
                return
            deleted = True
            self._delete_document_later(document)

        try:
            view.destroyed.connect(finish_document_deletion)
            view.deleteLater()
        except Exception:
            finish_document_deletion()

    # Compatibility entry point retained for focused tests and legacy callers.
    def _dispose(self, view, document) -> None:
        self._retire_pair(view, document)
