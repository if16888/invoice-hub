# -*- coding: utf-8 -*-
"""PreviewToolbar component for document preview controls."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from ..preview_toolbar_style import build_preview_toolbar_qss


class PreviewToolbar(QFrame):
    """Compact document preview toolbar rendered from Design v1 tokens.

    Buttons: [−] [100%] [+] | 适宽 适页 | 左旋 右旋 | 下载 打印 全屏
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
        self.setStyleSheet(build_preview_toolbar_qss())
        self.setAccessibleName("原件预览工具栏")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(4)

        def make_sep() -> QLabel:
            sep = QLabel("|")
            sep.setProperty("class", "ToolbarSep")
            sep.setAccessibleName("工具分隔符")
            return sep

        def make_btn(
            action_name: str,
            text: str,
            handler,
            *,
            icon_only: bool = False,
            tooltip: str = "",
            min_w: int | None = None,
            fixed_w: int | None = None,
        ) -> QToolButton:
            button = QToolButton(self)
            button.setObjectName(f"PreviewAction_{action_name}")
            button.setText(text)
            button.setProperty("class", "PreviewToolBtn")
            button.setFocusPolicy(Qt.StrongFocus)
            button.setAccessibleName(tooltip or text)
            if icon_only:
                button.setProperty("iconOnly", "true")
                button.setFixedSize(30, 28)
            else:
                button.setFixedHeight(28)
                if fixed_w:
                    button.setFixedWidth(fixed_w)
                elif min_w:
                    button.setMinimumWidth(min_w)
            button.setAutoRaise(False)
            if tooltip:
                button.setToolTip(tooltip)
            if handler:
                button.clicked.connect(handler)
            return button

        self.btn_zoom_out = make_btn(
            "zoom_out", "−", on_zoom_out, icon_only=True, tooltip="缩小 (Ctrl + -)"
        )
        self.btn_zoom_100 = make_btn(
            "zoom_100", "100%", on_zoom_100, min_w=48, tooltip="原始大小"
        )
        self.btn_zoom_in = make_btn(
            "zoom_in", "+", on_zoom_in, icon_only=True, tooltip="放大 (Ctrl + +)"
        )

        self.btn_fit_width = make_btn(
            "fit_width", "适宽", on_fit_width, min_w=44, tooltip="适应宽度"
        )
        self.btn_fit_page = make_btn(
            "fit_page", "适页", on_fit_page, min_w=44, tooltip="适应页面"
        )

        self.btn_rotate_left = make_btn(
            "rotate_left", "左旋", on_rotate_left, min_w=44, tooltip="向左旋转"
        )
        self.btn_rotate_right = make_btn(
            "rotate_right", "右旋", on_rotate_right, min_w=44, tooltip="向右旋转"
        )

        self.btn_download = make_btn(
            "download", "下载", on_download, min_w=44, tooltip="下载原件"
        )
        self.btn_print = make_btn(
            "print", "打印", on_print, min_w=44, tooltip="打印原件"
        )
        self.btn_fullscreen = make_btn(
            "focus_mode", "全屏", on_fullscreen, min_w=44, tooltip="全屏预览 (双击原件)"
        )

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


__all__ = ["PreviewToolbar"]
