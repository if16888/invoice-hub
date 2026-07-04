# -*- coding: utf-8 -*-
"""PreviewToolbar Component - Floating Document Preview Controls Toolbar."""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget
from ..theme import Theme


class PreviewToolbar(QFrame):
    """Floating, translucent preview controls toolbar.

    Buttons: [−] [100%] [+] | 适宽 适页 | 左旋 右旋 | 下载 打印 全屏
    Height: 36px, Button height: 28px, Translucent floating bar.
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
        self.setObjectName("PreviewFloatingToolbar")
        self.setFixedHeight(40)
        self.setStyleSheet("""
            QFrame#PreviewFloatingToolbar {
                background: rgba(255, 255, 255, 235);
                border: 1px solid #D9E2EF;
                border-radius: 12px;
            }
            QToolButton.PreviewToolBtn {
                min-height: 28px;
                max-height: 28px;
                padding: 0 8px;
                border-radius: 7px;
                border: none;
                color: #344054;
                background: transparent;
                font-size: 12px;
                font-weight: 500;
            }
            QToolButton.PreviewToolBtn:hover {
                background: #EEF4FF;
                color: #2563EB;
            }
            QToolButton.PreviewToolBtn[iconOnly="true"] {
                min-width: 30px;
                max-width: 30px;
                padding: 0;
                font-size: 16px;
                font-weight: 600;
            }
            QToolButton.PreviewToolBtn:disabled {
                color: #98A2B3;
                background: transparent;
            }
            QToolButton.PreviewToolBtn::menu-indicator {
                image: none;
                width: 0px;
            }
            QLabel.ToolbarSep {
                color: #D0D5DD;
                font-size: 12px;
                margin: 0 4px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(4)

        def make_sep():
            sep = QLabel("|")
            sep.setProperty("class", "ToolbarSep")
            return sep

        def make_btn(
            text: str,
            handler,
            *,
            icon_only: bool = False,
            tooltip: str = "",
            min_w: int | None = None,
            fixed_w: int | None = None,
        ):
            btn = QToolButton()
            btn.setText(text)
            btn.setProperty("class", "PreviewToolBtn")
            if icon_only:
                btn.setProperty("iconOnly", "true")
                btn.setFixedSize(30, 28)
            else:
                btn.setFixedHeight(28)
                if fixed_w:
                    btn.setFixedWidth(fixed_w)
                elif min_w:
                    btn.setMinimumWidth(min_w)
            btn.setAutoRaise(True)
            if tooltip:
                btn.setToolTip(tooltip)
            if handler:
                btn.clicked.connect(handler)
            return btn

        # Math minus '−' (\u2212) & plus '+'
        self.btn_zoom_out = make_btn("−", on_zoom_out, icon_only=True, tooltip="缩小 (Ctrl + -)")
        self.btn_zoom_100 = make_btn("100%", on_zoom_100, min_w=48, tooltip="原始大小")
        self.btn_zoom_in = make_btn("+", on_zoom_in, icon_only=True, tooltip="放大 (Ctrl + +)")

        self.btn_fit_width = make_btn("适宽", on_fit_width, min_w=44, tooltip="适应宽度")
        self.btn_fit_page = make_btn("适页", on_fit_page, min_w=44, tooltip="适应页面")

        self.btn_rotate_left = make_btn("左旋", on_rotate_left, min_w=44, tooltip="向左旋转")
        self.btn_rotate_right = make_btn("右旋", on_rotate_right, min_w=44, tooltip="向右旋转")

        self.btn_download = make_btn("下载", on_download, min_w=44, tooltip="下载原件")
        self.btn_print = make_btn("打印", on_print, min_w=44, tooltip="打印原件")
        self.btn_fullscreen = make_btn("全屏", on_fullscreen, min_w=44, tooltip="全屏预览 (双击原件)")

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
