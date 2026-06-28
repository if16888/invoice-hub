# -*- coding: utf-8 -*-
"""
Workbench Layout Metrics.

Pure functions for calculating responsive layout breakpoints and clamping
vertical splitter sizes.  No Qt or database imports; fully unit-testable.
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
      ≤ 1366 × 768  → compact, collapsed navigation (laptop / small monitor)
      ≤ 1440 × 900  → compact, full navigation (medium monitor)
      > 1440 × 900  → full density (1920×1080 target)
    """
    if width <= 1366 or height <= 768:
        return WorkbenchMetrics(
            nav_width=56,
            nav_collapsed=True,
            detail_width=370,
            record_height=300,
            thumbnail_width=88,
            compact=True,
        )
    if width <= 1440 or height <= 900:
        return WorkbenchMetrics(
            nav_width=56,
            nav_collapsed=True,
            detail_width=380,
            record_height=320,
            thumbnail_width=88,
            compact=True,
        )
    return WorkbenchMetrics(
        nav_width=56,
        nav_collapsed=True,
        detail_width=390,
        record_height=340,
        thumbnail_width=88,
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
