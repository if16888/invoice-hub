# -*- coding: utf-8 -*-
"""
Invoice Hub Reusable UI Helper Components.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QLabel, QFrame, QHBoxLayout


def make_button(text: str, variant: str = "secondary", min_width: int = None, tooltip: str = None) -> QPushButton:
    """
    Create a styled QPushButton using global QSS properties.
    """
    btn = QPushButton(text)
    btn.setProperty("variant", variant)
    btn.setAutoDefault(False)
    btn.setDefault(False)

    # Apply height constraints
    if variant == "toolbar":
        btn.setFixedHeight(30)
    elif variant == "chip":
        pass
    else:
        btn.setFixedHeight(28)

    # Determine default min_width based on text and variant
    char_count = len(text)
    if min_width is not None:
        default_w = min_width
    else:
        if char_count <= 2:
            if variant == "primary":
                default_w = 76
            elif variant == "danger":
                default_w = 56
            else:
                default_w = 56
        else:
            default_w = btn.sizeHint().width() + 16

    btn.setMinimumWidth(max(default_w, btn.sizeHint().width()))

    if tooltip:
        btn.setToolTip(tooltip)

    return btn


def make_badge(text: str, variant: str = "muted", min_width: int = None, tooltip: str = None) -> QLabel:
    """
    Create a QLabel styled as a StatusBadge using QSS.
    """
    lbl = QLabel(text)
    lbl.setProperty("class", "StatusBadge")
    lbl.setProperty("variant", variant)
    lbl.setAlignment(Qt.AlignCenter)

    default_w = min_width or 0
    lbl.setMinimumWidth(max(default_w, lbl.sizeHint().width() + 12))

    if tooltip:
        lbl.setToolTip(tooltip)

    return lbl


def make_filter_chip(text: str, tooltip: str = None) -> QPushButton:
    """
    Create a QPushButton styled as a filter chip (variant="chip") with a close mark.
    """
    display_text = text if text.endswith(" ×") else f"{text} ×"
    btn = make_button(display_text, variant="chip", tooltip=tooltip)
    btn.setMaximumWidth(120)
    return btn


def build_action_cluster(widgets: list, min_width: int = None) -> QFrame:
    """
    Group multiple widgets horizontally in a right-aligned action cluster.
    """
    frame = QFrame()
    frame.setProperty("class", "ActionCluster")
    
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    
    for w in widgets:
        layout.addWidget(w)
        
    if min_width is not None:
        frame.setMinimumWidth(min_width)
        
    return frame
