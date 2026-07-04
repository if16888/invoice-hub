# -*- coding: utf-8 -*-
"""PreviewToolbar Component - Document Preview Controls Toolbar."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from ..theme import Theme


class PreviewToolbar(QWidget):
    """Standalone, non-stretching preview controls toolbar.

    Buttons: [-] 100% [+] | 适应宽度 | 适应页面 | 左旋 | 右旋 | 下载 | 打印 | 全屏
    Height: 40px, Button height: 32px, Spacing: 8px.
    """

    def __init__(
        self,
        *,
        on_zoom_out=None,
        on_zoom_100=None,
        on_zoom_in=None,
        on_fit_width=None,
        on_fit_page=None,
        on_rotate_left=None,
        on_rotate_right=None,
        on_download=None,
        on_print=None,
        on_fullscreen=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewToolbar")
        self.setFixedHeight(40)
        self.setStyleSheet(f"""
            QWidget#PreviewToolbar {{
                background-color: {Theme.BG_CARD};
                border-bottom: 1px solid {Theme.BORDER};
                border-top-left-radius: {Theme.RADIUS_CARD}px;
                border-top-right-radius: {Theme.RADIUS_CARD}px;
            }}
            QPushButton.PreviewToolBtn {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BORDER};
                border-radius: {Theme.RADIUS_SM}px;
                color: {Theme.TEXT_MAIN};
                font-size: 12px;
                font-weight: 500;
                padding: 0 10px;
                min-height: 32px;
                max-height: 32px;
            }}
            QPushButton.PreviewToolBtn:hover {{
                background-color: {Theme.BG_SUBTLE};
                border-color: {Theme.BORDER_STRONG};
            }}
            QPushButton.PreviewToolBtn:disabled {{
                background-color: {Theme.BG_SUBTLE};
                border-color: {Theme.BORDER};
                color: {Theme.TEXT_MUTED};
            }}
            QLabel.ToolbarSep {{
                color: {Theme.BORDER_STRONG};
                font-size: 12px;
                margin: 0 4px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(8)

        def make_sep():
            sep = QLabel("|")
            sep.setProperty("class", "ToolbarSep")
            return sep

        def make_btn(text: str, handler, min_width: int = 64):
            btn = QPushButton(text)
            btn.setProperty("class", "PreviewToolBtn")
            btn.setMinimumWidth(min_width)
            btn.setFixedHeight(32)
            if handler:
                btn.clicked.connect(handler)
            return btn

        self.btn_zoom_out = make_btn("-", on_zoom_out, min_width=32)
        self.btn_zoom_100 = make_btn("100%", on_zoom_100, min_width=52)
        self.btn_zoom_in = make_btn("+", on_zoom_in, min_width=28)
        self.btn_fit_width = make_btn("适应宽度", on_fit_width, min_width=72)
        self.btn_fit_page = make_btn("适应页面", on_fit_page, min_width=72)
        self.btn_rotate_left = make_btn("左旋", on_rotate_left, min_width=56)
        self.btn_rotate_right = make_btn("右旋", on_rotate_right, min_width=56)
        self.btn_download = make_btn("下载", on_download, min_width=56)
        self.btn_print = make_btn("打印", on_print, min_width=56)
        self.btn_fullscreen = make_btn("全屏", on_fullscreen, min_width=56)

        layout.addWidget(self.btn_zoom_out)
        layout.addWidget(self.btn_zoom_100)
        layout.addWidget(self.btn_zoom_in)
        layout.addWidget(make_sep())
        layout.addWidget(self.btn_fit_width)
        layout.addWidget(self.btn_fit_page)
        layout.addWidget(make_sep())
        layout.addWidget(self.btn_rotate_left)
        layout.addWidget(self.btn_rotate_right)
        layout.addWidget(make_sep())
        layout.addWidget(self.btn_download)
        layout.addWidget(self.btn_print)
        layout.addWidget(self.btn_fullscreen)
        layout.addStretch(1)
