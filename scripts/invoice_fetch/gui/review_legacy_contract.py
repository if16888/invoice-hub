"""Narrow compatibility objects for legacy review geometry assertions.

The redesigned reimbursement section no longer uses the old summary row, but a
few app integrations still inspect that layout object. Keep a hidden, empty live
layout behind the legacy attribute until those integrations move to the new
claim action row.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout


def install_claim_summary_layout_compatibility(window) -> None:
    detail = getattr(window, "_detail_panel", None)
    if detail is None or hasattr(detail, "claim_summary_compat_frame"):
        return

    frame = QFrame(detail.claim_setup_section)
    frame.setObjectName("LegacyClaimSummaryLayoutAdapter")
    frame.hide()
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    detail.claim_summary_compat_frame = frame
    detail.claim_summary_row = layout


__all__ = ["install_claim_summary_layout_compatibility"]
