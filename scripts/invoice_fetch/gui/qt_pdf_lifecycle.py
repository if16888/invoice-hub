# -*- coding: utf-8 -*-
"""Qt PDF lifecycle contract for the desktop preview.

Qt's ``QPdfView`` owns an internal ``QPdfLinkModel``.  Passing ``None`` to
``QPdfView.setDocument`` while replacing a document makes that model attempt to
connect to a null ``QPdfDocument`` on some Windows/PySide6 builds, producing:

``QObject::connect(QPdfDocument, QPdfLinkModel): invalid nullptr parameter``

The application replaces one valid document with another immediately, so a
transient null document is unnecessary.  ``StablePdfView`` keeps the current
valid document attached until the replacement is ready.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("invoice_fetch.gui.qt_pdf_lifecycle")
_INSTALLED = False
_STABLE_VIEW_CLASS = None


def install_qt_pdf_lifecycle_contract() -> bool:
    """Install the stable QPdfView class used by ``preview_mixin``.

    Returns ``False`` when the optional Qt PDF modules are unavailable.  The
    function is idempotent and does not modify Qt's global warning handler.
    """
    global _INSTALLED, _STABLE_VIEW_CLASS
    if _INSTALLED:
        return True

    try:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
    except ImportError:
        return False

    from . import preview_mixin

    class StablePdfView(QPdfView):
        """QPdfView that never exposes an intermediate null document."""

        def setDocument(self, document):  # noqa: N802 - Qt API name
            if document is None:
                # The legacy preview path used ``None`` only as an intermediate
                # detach step.  Keep the old document attached until the next
                # valid document is assigned in the same refresh operation.
                return None
            return super().setDocument(document)

    StablePdfView.__name__ = "InvoiceHubPdfView"
    StablePdfView.__qualname__ = "InvoiceHubPdfView"

    _STABLE_VIEW_CLASS = StablePdfView
    preview_mixin._QPDF_CLASSES = (QPdfDocument, StablePdfView)
    preview_mixin.HAS_QT_PDF = True
    _INSTALLED = True
    _log.debug("Installed stable Qt PDF document lifecycle contract")
    return True


def stable_pdf_view_class():
    """Return the installed view class for diagnostics and tests."""
    return _STABLE_VIEW_CLASS


__all__ = [
    "install_qt_pdf_lifecycle_contract",
    "stable_pdf_view_class",
]
