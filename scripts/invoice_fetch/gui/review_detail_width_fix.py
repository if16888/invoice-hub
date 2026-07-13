"""Responsive width contract for the review detail pane.

The physical Windows review found that collapsing the application sidebar made
more horizontal space available, but the detail pane stayed locked to the old
fixed width.  This module replaces that fixed-width resize hook with a bounded
splitter reflow that gives part of the reclaimed rail width to the detail pane
while preserving a useful invoice-table and preview area.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QSizePolicy, QWidget


DETAIL_MIN_WIDTH = 352
DETAIL_MAX_WIDTH = 520
COLLAPSED_NAV_THRESHOLD = 96
COLLAPSED_DETAIL_BONUS = 48
MIN_WORKSPACE_WIDTH = 720
COMPACT_DESKTOP_MAX_WIDTH = 1366


def _nav_is_collapsed(window) -> bool:
    nav = getattr(window, "workbench_nav", None)
    return nav is not None and nav.width() <= COLLAPSED_NAV_THRESHOLD


def _base_detail_width(window, available: int) -> int:
    """Return the normal detail width before applying the collapsed-rail bonus."""
    window_width = max(0, int(window.width()))
    if window_width <= COMPACT_DESKTOP_MAX_WIDTH or available <= 1160:
        return 352
    if window_width <= 1440 or available <= 1280:
        return 380
    return 400


def _target_detail_width(window) -> int:
    splitter = getattr(window, "main_splitter", None)
    if splitter is None:
        return DETAIL_MIN_WIDTH

    available = max(0, int(splitter.width()))
    window_width = max(0, int(window.width()))
    target = _base_detail_width(window, available)

    # A 1366-wide desktop is already space-constrained. Keep its historical
    # 352 px detail contract even when the rail defaults to icon-only; only use
    # reclaimed sidebar width on larger desktops.
    if window_width > COMPACT_DESKTOP_MAX_WIDTH and _nav_is_collapsed(window):
        target += COLLAPSED_DETAIL_BONUS

    # Never let the detail pane crowd out the dense review workspace.
    if available > 0:
        target = min(target, max(DETAIL_MIN_WIDTH, available - MIN_WORKSPACE_WIDTH))
    return max(DETAIL_MIN_WIDTH, min(DETAIL_MAX_WIDTH, target))


def _reflow_review_detail(window) -> None:
    """Apply the responsive detail width and consume the splitter's full width."""
    detail = getattr(window, "_detail_panel", None)
    splitter = getattr(window, "main_splitter", None)
    if detail is None or splitter is None or splitter.count() < 2:
        return

    target = _target_detail_width(window)
    detail.setMinimumWidth(DETAIL_MIN_WIDTH)
    detail.setMaximumWidth(DETAIL_MAX_WIDTH)
    detail.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 1)
    available = max(0, int(splitter.width()) - splitter.handleWidth() * (splitter.count() - 1))
    if available <= 0:
        return
    target = min(target, max(DETAIL_MIN_WIDTH, available - MIN_WORKSPACE_WIDTH))
    splitter.setSizes([max(MIN_WORKSPACE_WIDTH, available - target), target])


class _ReviewDetailWidthController(QObject):
    """Coalesce window, splitter, and sidebar resize events into one safe reflow."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self._pending = False

    def schedule(self) -> None:
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self._apply)

    def _apply(self) -> None:
        self._pending = False
        try:
            _reflow_review_detail(self.window)
        except RuntimeError:
            # The window can be destroyed while a queued resize callback exists.
            return

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.schedule()
        return False


def apply_review_detail_width_fix(page: QWidget) -> None:
    """Install the responsive width contract after the review page is complete."""
    if page is None or page.property("reviewDetailWidthFixApplied"):
        return
    window = page.window()
    if page is not getattr(window, "review_page", None):
        return
    detail = getattr(window, "_detail_panel", None)
    splitter = getattr(window, "main_splitter", None)
    nav = getattr(window, "workbench_nav", None)
    if detail is None or splitter is None:
        return

    page.setProperty("reviewDetailWidthFixApplied", True)

    # The earlier physical-review module fixed the pane to 352/380/400 px on
    # every window resize. Remove that hook so the reclaimed sidebar width can
    # be distributed by this bounded splitter contract instead.
    old_filter = getattr(window, "_review_feedback_resize_filter", None)
    if old_filter is not None:
        window.removeEventFilter(old_filter)
        old_filter.deleteLater()
        delattr(window, "_review_feedback_resize_filter")

    controller = _ReviewDetailWidthController(window)
    window.installEventFilter(controller)
    splitter.installEventFilter(controller)
    if nav is not None:
        nav.installEventFilter(controller)
    collapse_button = getattr(window, "btn_collapse_nav", None)
    if collapse_button is not None:
        collapse_button.clicked.connect(lambda _checked=False: controller.schedule())

    window._review_detail_width_controller = controller
    _reflow_review_detail(window)
    # A legacy single-shot resize callback may already have been queued before
    # its event filter was removed. Queue one final reflow so this contract wins.
    controller.schedule()


__all__ = [
    "DETAIL_MAX_WIDTH",
    "DETAIL_MIN_WIDTH",
    "apply_review_detail_width_fix",
    "_reflow_review_detail",
    "_target_detail_width",
]
