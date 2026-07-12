# -*- coding: utf-8 -*-
"""
Workbench Layout Metrics.

Pure functions for calculating responsive layout breakpoints and clamping
vertical splitter sizes. No Qt or database imports; fully unit-testable.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkbenchMetrics:
    """Immutable layout snapshot computed from the current window dimensions."""

    nav_width: int
    nav_collapsed: bool
    detail_width: int
    record_height: int
    thumbnail_width: int
    compact: bool


def metrics_for_size(width: int, height: int) -> WorkbenchMetrics:
    """Return the appropriate WorkbenchMetrics for the given window size.

    Breakpoints (width × height, inclusive upper bound):
      <= 1366 × 768  -> compact, collapsed navigation (laptop / small monitor)
      <= 1440 × 900  -> compact, expanded navigation (medium monitor)
      > 1440 × 900   -> full density (1920×1080 target)

    The detail rail is deliberately wider than the legacy 344–352px range.
    Physical Windows review showed that amount/date, long parties, the primary
    review action and reimbursement controls cannot remain legible in that
    width. The preview keeps the remaining flexible space.
    """
    if width <= 1366 or (width <= 1440 and height <= 768):
        return WorkbenchMetrics(
            nav_width=56,
            nav_collapsed=True,
            detail_width=360,
            record_height=332,
            thumbnail_width=96,
            compact=True,
        )
    if width <= 1440:
        return WorkbenchMetrics(
            nav_width=180,
            nav_collapsed=False,
            detail_width=380,
            record_height=336,
            thumbnail_width=96,
            compact=True,
        )
    return WorkbenchMetrics(
        nav_width=180,
        nav_collapsed=False,
        detail_width=400,
        record_height=390,
        thumbnail_width=104,
        compact=False,
    )


def clamp_vertical_split(
    total: int,
    record: int,
    *,
    record_min: int,
    preview_min: int,
) -> tuple[int, int]:
    """Clamp a restored vertical splitter value so both panes stay usable.

    Args:
        total:       Total available height shared by the two panes.
        record:      Requested record-list pane height (e.g., from QSettings).
        record_min:  Minimum height allowed for the record-list pane.
        preview_min: Minimum height allowed for the preview pane.

    Returns:
        (record_height, preview_height) tuple that satisfies both minimums.
    """
    record = max(record_min, min(record, total - preview_min))
    return record, total - record
