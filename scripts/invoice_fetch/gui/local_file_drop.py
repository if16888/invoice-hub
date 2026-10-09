"""Route local invoice-file drops anywhere in the main window to local import."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget


LOCAL_IMPORT_SUFFIXES = frozenset(
    {".pdf", ".ofd", ".xml", ".zip", ".png", ".jpg", ".jpeg", ".heic"}
)


def local_import_paths(mime_data) -> tuple[Path, ...]:
    """Return unique, existing supported local files from a drag payload."""

    if mime_data is None or not mime_data.hasUrls():
        return ()

    paths: dict[str, Path] = {}
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        raw_path = url.toLocalFile()
        if not raw_path:
            continue
        try:
            path = Path(raw_path).expanduser().resolve(strict=True)
            if not path.is_file() or path.suffix.lower() not in LOCAL_IMPORT_SUFFIXES:
                continue
        except (OSError, RuntimeError, ValueError):
            continue
        paths.setdefault(os.path.normcase(str(path)), path)
    return tuple(sorted(paths.values(), key=lambda item: os.path.normcase(str(item))))


class LocalFileDropFilter(QObject):
    """Handle supported file drops on the main window and all its child widgets."""

    _DROP_EVENTS = frozenset(
        {QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop}
    )

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._drop_target_refresh_timer = QTimer(self)
        self._drop_target_refresh_timer.setSingleShot(True)
        self._drop_target_refresh_timer.timeout.connect(self._refresh_drop_targets)
        self._enable_window_drop_targets(window)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _enable_window_drop_targets(self, parent: QWidget) -> None:
        """Make descendants eligible for Qt drag events, not only the shell."""
        for child in parent.children():
            if not isinstance(child, QWidget):
                continue
            # Do not opt modal or auxiliary top-level windows into file drops.
            if child.isWindow():
                continue
            child.setAcceptDrops(True)
            self._enable_window_drop_targets(child)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ChildAdded and isinstance(watched, QWidget):
            window = self._window
            if window is not None:
                try:
                    belongs_to_window = watched.window() is window
                except RuntimeError:
                    belongs_to_window = False
                if belongs_to_window:
                    # ChildAdded may arrive while a QWidget subclass is only
                    # partially constructed. Do not retain event.child() past
                    # this callback; coalesce additions and rescan the window
                    # after Qt finishes the current construction/event batch.
                    if not self._drop_target_refresh_timer.isActive():
                        self._drop_target_refresh_timer.start(0)
            return False
        if event.type() not in self._DROP_EVENTS:
            return False
        window = self._window
        if window is None or getattr(window, "_shutdown_requested", False):
            return False
        if not isinstance(watched, QWidget):
            return False
        try:
            if watched.window() is not window:
                return False
        except RuntimeError:
            return False
        if QApplication.activeModalWidget() is not None:
            return False

        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return False
        paths = local_import_paths(mime_data)

        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if paths:
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
            return True

        if paths:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            window._start_local_import_paths(paths)
        else:
            event.ignore()
        return True

    def _refresh_drop_targets(self) -> None:
        window = self._window
        try:
            if window is not None and not getattr(window, "_shutdown_requested", False):
                self._enable_window_drop_targets(window)
        except RuntimeError:
            # The window may be deleted while a coalesced refresh is pending.
            return
