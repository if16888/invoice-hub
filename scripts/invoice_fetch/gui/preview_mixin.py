# -*- coding: utf-8 -*-
"""Preview panel behavior mixed into the Invoice Hub main window."""

import json
import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut, QTransform
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from ..config import RUNTIME_DIR

_log = logging.getLogger("invoice_fetch.gui.app")

HAS_QT_PDF = None
_QPDF_CLASSES = None


def _runtime_dir_compat():
    app_module = sys.modules.get(f"{__package__}.app")
    return getattr(app_module, "RUNTIME_DIR", RUNTIME_DIR)

def check_has_qt_pdf() -> bool:
    global HAS_QT_PDF
    if HAS_QT_PDF is None:
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        HAS_QT_PDF = QPdfDocument is not None and QPdfView is not None
    return HAS_QT_PDF


def get_qt_pdf_classes():
    global _QPDF_CLASSES
    if _QPDF_CLASSES is not None:
        return _QPDF_CLASSES
    try:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
        _QPDF_CLASSES = (QPdfDocument, QPdfView)
    except ImportError:
        _QPDF_CLASSES = (None, None)
    return _QPDF_CLASSES

from ..config import RUNTIME_DIR

_log = logging.getLogger("invoice_fetch.gui.app")

HAS_QT_PDF = None
_QPDF_CLASSES = None


def _runtime_dir_compat():
    app_module = sys.modules.get(f"{__package__}.app")
    return getattr(app_module, "RUNTIME_DIR", RUNTIME_DIR)

def check_has_qt_pdf() -> bool:
    global HAS_QT_PDF
    if HAS_QT_PDF is None:
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        HAS_QT_PDF = QPdfDocument is not None and QPdfView is not None
    return HAS_QT_PDF


def get_qt_pdf_classes():
    global _QPDF_CLASSES
    if _QPDF_CLASSES is not None:
        return _QPDF_CLASSES
    try:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
        _QPDF_CLASSES = (QPdfDocument, QPdfView)
    except ImportError:
        _QPDF_CLASSES = (None, None)
    return _QPDF_CLASSES


class PreviewMixin:
    def _make_toolbar_button(self, text: str, handler, *, width: int | None = None, tooltip: str = "") -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(handler)
        button.setFixedHeight(32)
        button.setProperty("class", "PreviewToolBtn")
        if width is not None:
            button.setFixedWidth(width)
        if tooltip:
            button.setToolTip(tooltip)
        return button

    def _init_overlay_toolbar(self):
        from .ui.components.preview_toolbar import PreviewToolbar
        self.overlay_toolbar = PreviewToolbar(
            on_zoom_out=self._zoom_out,
            on_zoom_100=self._zoom_100,
            on_zoom_in=self._zoom_in,
            on_fit_width=self._zoom_fit_width,
            on_fit_page=self._zoom_fit_page,
            on_rotate_left=lambda: self._rotate_preview(-90),
            on_rotate_right=lambda: self._rotate_preview(90),
            on_download=self._download_current_preview,
            on_print=self._print_current_preview,
            on_fullscreen=self._toggle_preview_focus_mode,
            parent=getattr(self, "preview_container", None),
        )
        self.overlay_toolbar.installEventFilter(self)
        self.btn_zoom_out = self.overlay_toolbar.btn_zoom_out
        self.btn_zoom_100 = self.overlay_toolbar.btn_zoom_100
        self.btn_zoom_in = self.overlay_toolbar.btn_zoom_in
        self.btn_fit_width = self.overlay_toolbar.btn_fit_width
        self.btn_fit_page = self.overlay_toolbar.btn_fit_page
        self.btn_rotate_left = self.overlay_toolbar.btn_rotate_left
        self.btn_rotate_right = self.overlay_toolbar.btn_rotate_right
        self.btn_download_preview = self.overlay_toolbar.btn_download
        self.btn_print_preview = self.overlay_toolbar.btn_print
        self.btn_preview_focus = self.overlay_toolbar.btn_fullscreen
        self.lbl_file_info = QLabel("0 / 0 无文件", self.overlay_toolbar)
        self.btn_prev = QToolButton(self.overlay_toolbar)
        self.btn_next = QToolButton(self.overlay_toolbar)
        self.btn_open_ext = QToolButton(self.overlay_toolbar)

        for w in (self.lbl_file_info, self.btn_prev, self.btn_next, self.btn_open_ext):
            w.setGeometry(0, 0, 0, 0)
            w.hide()

        self.preview_actions = {
            "zoom_out": self.overlay_toolbar.btn_zoom_out,
            "zoom_100": self.overlay_toolbar.btn_zoom_100,
            "zoom_in": self.overlay_toolbar.btn_zoom_in,
            "fit_width": self.overlay_toolbar.btn_fit_width,
            "fit_page": self.overlay_toolbar.btn_fit_page,
            "rotate_left": self.overlay_toolbar.btn_rotate_left,
            "rotate_right": self.overlay_toolbar.btn_rotate_right,
            "download": self.overlay_toolbar.btn_download,
            "print": self.overlay_toolbar.btn_print,
            "focus_mode": self.overlay_toolbar.btn_fullscreen,
        }
        return
        self.old_tb = QWidget(self.preview_workbench)
        self.overlay_toolbar.setObjectName("OverlayToolbar")
        self.overlay_toolbar.setFixedHeight(40)
        self.overlay_toolbar.setStyleSheet("""
            QWidget#OverlayToolbar {
                background-color: #FFFFFF;
                border-bottom: 1px solid #E5EAF2;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }
            QPushButton, QToolButton {
                background-color: #F8FAFC;
                border: 1px solid #E5EAF2;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                color: #334155;
                font-weight: 500;
            }
            QPushButton:hover, QToolButton:hover {
                background-color: #EFF6FF;
                border-color: #BFDBFE;
                color: #1D4ED8;
            }
            QPushButton:disabled, QToolButton:disabled {
                color: #94A3B8;
                background-color: #F8FAFC;
                border-color: #E2E8F0;
            }
            QLabel.ToolbarSep {
                color: #CBD5E1;
                font-size: 14px;
                padding: 0 4px;
            }
        """)
        self.overlay_toolbar.installEventFilter(self)

        tb_layout = QHBoxLayout(self.overlay_toolbar)
        tb_layout.setContentsMargins(10, 4, 10, 4)
        tb_layout.setSpacing(8)

        def make_sep():
            sep = QLabel("|")
            sep.setProperty("class", "ToolbarSep")
            return sep

        self.btn_zoom_out = self._make_toolbar_button("-", self._zoom_out, width=28)
        self.btn_zoom_100 = self._make_toolbar_button("100%", self._zoom_100, width=54)
        self.btn_zoom_in = self._make_toolbar_button("+", self._zoom_in, width=28)
        self.btn_fit_width = self._make_toolbar_button("适应宽度", self._zoom_fit_width)
        self.btn_fit_page = self._make_toolbar_button("适应页面", self._zoom_fit_page)
        self.btn_rotate_left = self._make_toolbar_button("左旋", lambda: self._rotate_preview(-90))
        self.btn_rotate_right = self._make_toolbar_button("右旋", lambda: self._rotate_preview(90))
        self.btn_download_preview = self._make_toolbar_button("下载", self._download_current_preview)
        self.btn_print_preview = self._make_toolbar_button("打印", self._print_current_preview)
        self.btn_preview_focus = self._make_toolbar_button("全屏", self._toggle_preview_focus_mode)
        self.btn_preview_more = QToolButton(self.overlay_toolbar)
        self.btn_preview_more.setText("更多")
        self.btn_preview_more.setFixedHeight(30)
        self.btn_preview_more.setPopupMode(QToolButton.InstantPopup)

        preview_more_menu = QMenu(self.btn_preview_more)
        for label, button in (
            ("适应页面", self.btn_fit_page),
            ("左旋", self.btn_rotate_left),
            ("右旋", self.btn_rotate_right),
            ("下载", self.btn_download_preview),
            ("打印", self.btn_print_preview),
        ):
            action = preview_more_menu.addAction(label)
            action.triggered.connect(button.click)
        self.btn_preview_more.setMenu(preview_more_menu)

        self.preview_actions = {
            "zoom_out": self.btn_zoom_out,
            "zoom_100": self.btn_zoom_100,
            "zoom_in": self.btn_zoom_in,
            "fit_width": self.btn_fit_width,
            "fit_page": self.btn_fit_page,
            "rotate_left": self.btn_rotate_left,
            "rotate_right": self.btn_rotate_right,
            "download": self.btn_download_preview,
            "print": self.btn_print_preview,
            "focus_mode": self.btn_preview_focus,
        }
        for key, button in self.preview_actions.items():
            button.setObjectName(f"PreviewAction_{key}")

        tb_layout.addWidget(self.btn_zoom_out)
        tb_layout.addWidget(self.btn_zoom_100)
        tb_layout.addWidget(self.btn_zoom_in)
        tb_layout.addWidget(make_sep())
        tb_layout.addWidget(self.btn_fit_width)
        tb_layout.addWidget(self.btn_fit_page)
        tb_layout.addWidget(make_sep())
        tb_layout.addWidget(self.btn_rotate_left)
        tb_layout.addWidget(self.btn_rotate_right)
        tb_layout.addWidget(make_sep())
        tb_layout.addWidget(self.btn_download_preview)
        tb_layout.addWidget(self.btn_print_preview)
        tb_layout.addWidget(self.btn_preview_focus)
        tb_layout.addStretch(1)

        for button in (
            self.btn_zoom_out, self.btn_zoom_100, self.btn_zoom_in,
            self.btn_fit_width, self.btn_fit_page,
            self.btn_rotate_left, self.btn_rotate_right,
            self.btn_download_preview, self.btn_print_preview, self.btn_preview_focus
        ):
            button.setParent(self.overlay_toolbar)
            button.show()

        self.overlay_toolbar.show()
        self._init_legacy_preview_controls()

    def _init_legacy_preview_controls(self):
        """Keep old preview control attributes available without visible orphan widgets."""
        self._legacy_preview_controls = QWidget(self.overlay_toolbar)
        self._legacy_preview_controls.hide()

        self.btn_prev = self._make_toolbar_button("←", self._prev_preview_doc, width=18, tooltip="上一文件")
        self.lbl_file_info = QLabel("0 / 0 无文件")
        self.lbl_file_info.setAlignment(Qt.AlignCenter)
        self.btn_next = self._make_toolbar_button("→", self._next_preview_doc, width=18, tooltip="下一文件")
        self.btn_prev_page = self._make_toolbar_button("◀ 上一页", self._prev_pdf_page, tooltip="PDF 上一页")
        self.btn_next_page = self._make_toolbar_button("下一页 ▶", self._next_pdf_page, tooltip="PDF 下一页")
        self.btn_open_ext = self._make_toolbar_button("外部打开", self._open_current_preview_ext)
        self.btn_link_evidence = self._make_toolbar_button("关联到当前发票", self._link_current_evidence_to_invoice)

        for widget in (
            self.btn_prev,
            self.lbl_file_info,
            self.btn_next,
            self.btn_prev_page,
            self.btn_next_page,
            self.btn_open_ext,
            self.btn_link_evidence,
        ):
            widget.setParent(self._legacy_preview_controls)
            widget.setGeometry(0, 0, 0, 0)
            widget.hide()

    def _init_preview_panel(self):
        self.preview_panel = QGroupBox("原件预览")
        self.preview_panel.setFocusPolicy(Qt.StrongFocus)
        preview_layout = QVBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(0)

        self.preview_workbench = QWidget(self.preview_panel)
        self.preview_workbench.setObjectName("PreviewWorkbench")
        self.preview_workbench_layout = QVBoxLayout(self.preview_workbench)
        self.preview_workbench_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_workbench_layout.setSpacing(6)
        preview_layout.addWidget(self.preview_workbench, 1)

        self.preview_body = QWidget(self.preview_workbench)
        self.preview_body_layout = QHBoxLayout(self.preview_body)
        self.preview_body_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_body_layout.setSpacing(8)

        self.thumbnail_rail = QScrollArea(self.preview_body)
        self.thumbnail_rail.setObjectName("PreviewThumbnailRail")
        self.thumbnail_rail.setFixedWidth(68)
        self.thumbnail_rail.setWidgetResizable(True)
        self.thumbnail_rail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumbnail_content = QWidget()
        self.thumbnail_layout = QVBoxLayout(self.thumbnail_content)
        self.thumbnail_layout.setContentsMargins(6, 6, 6, 6)
        self.thumbnail_layout.setSpacing(6)
        self.thumbnail_layout.setAlignment(Qt.AlignTop)
        self.thumbnail_rail.setWidget(self.thumbnail_content)
        self.thumbnail_buttons = []
        self.thumbnail_rail.setVisible(False)
        self.preview_body_layout.addWidget(self.thumbnail_rail)

        # Initialize Zoom State Variables
        self.image_zoom_mode = "fit_width"
        self.image_zoom_factor = 1.0
        self.current_image_pixmap = None
        self.image_resize_timer = QTimer(self)
        self.image_resize_timer.setSingleShot(True)
        self.image_resize_timer.setInterval(80)
        self.image_resize_timer.timeout.connect(self._update_image_display)

        # Setup Hover Hide Timer
        self.overlay_hide_timer = QTimer(self)
        self.overlay_hide_timer.setSingleShot(True)
        self.overlay_hide_timer.timeout.connect(self._hide_overlay_toolbar)

        # Container widget to hold preview stack and floating overlay toolbar
        self.preview_container = QWidget(self.preview_body)
        self.preview_body_layout.addWidget(self.preview_container, 1)
        self.preview_workbench_layout.addWidget(self.preview_body, 1)

        # Install event filter to track mouse entry and exit on preview container
        self.preview_container.installEventFilter(self)

        # Enable Context Menu on preview area
        self.preview_container.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preview_container.customContextMenuRequested.connect(self._show_preview_context_menu)

        container_layout = QVBoxLayout(self.preview_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self.preview_stack = QStackedWidget()
        self.preview_stack.setObjectName("PreviewSurface")
        self.preview_stack.setFrameShape(QFrame.StyledPanel)
        self.preview_stack.installEventFilter(self)

        self.lbl_preview_status = QLabel("请选择一张发票查看原件")
        self.lbl_preview_status.setAlignment(Qt.AlignCenter)
        self.lbl_preview_status.setWordWrap(True)
        self.lbl_preview_status.setProperty("class", "PreviewEmptyState")
        self.lbl_preview_status.setMaximumWidth(520)
        self.preview_stack.addWidget(self.lbl_preview_status)
        self._preview_empty_message = "请选择一张发票查看原件"

        self.pdf_document = None
        self.pdf_view = None
        self.lbl_pdf_fallback = None

        self.image_scroll_area = QScrollArea()
        self.image_scroll_area.setWidgetResizable(True)
        self.image_scroll_area.setAlignment(Qt.AlignCenter)
        self.image_scroll_area.installEventFilter(self)
        self.image_scroll_area.viewport().installEventFilter(self)
        # Dynamic Resizing scaling for image in FitToWidth / FitInView modes
        self.image_scroll_area.resizeEvent = lambda event: (
            QScrollArea.resizeEvent(self.image_scroll_area, event),
            self._schedule_image_display_update()
        )

        self.lbl_image_preview = QLabel()
        self.lbl_image_preview.setAlignment(Qt.AlignCenter)
        self.lbl_image_preview.setStyleSheet("background-color: #F1F5F9;")
        self.image_scroll_area.setStyleSheet("background-color: #F1F5F9; border: none;")
        self.lbl_image_preview.installEventFilter(self)
        self.image_scroll_area.setWidget(self.lbl_image_preview)

        self.preview_stack.addWidget(self.image_scroll_area)
        container_layout.addWidget(self.preview_stack)

        self._init_overlay_toolbar()
        # overlay_toolbar floats on preview_container directly
        self._reposition_overlay_toolbar()

        # Bind container resizing to overlay position alignment (Y-offset smaller = 4px)
        def resize_container(event):
            QWidget.resizeEvent(self.preview_container, event)
            self._reposition_overlay_toolbar()

        self.preview_container.resizeEvent = resize_container

        self.preview_rotation = 0
        self.preview_focus_dialog = None
        self.overlay_toolbar.hide()
        self.thumbnail_rail.setVisible(False)
        self._set_zoom_buttons_enabled(False)


    def _reposition_overlay_toolbar(self):
        if not hasattr(self, "overlay_toolbar") or not hasattr(self, "preview_container"):
            return
        tb = self.overlay_toolbar
        container = self.preview_container
        tb.adjustSize()
        w = tb.width()
        c_w = container.width()
        # Top-right alignment with 16px right padding and 10px top padding (never blocks center title)
        x = max(8, c_w - w - 16)
        y = 10
        tb.move(x, y)
        tb.raise_()

    def _show_overlay_toolbar(self):
        if hasattr(self, "overlay_hide_timer"):
            self.overlay_hide_timer.stop()
        if hasattr(self, "overlay_toolbar"):
            self._reposition_overlay_toolbar()
            self.overlay_toolbar.show()
            self.overlay_toolbar.raise_()
        self._start_hide_overlay_timer(1200)

    def _hide_overlay_toolbar(self):
        if not hasattr(self, "overlay_toolbar"):
            return
        # Do not hide if mouse is hovered over toolbar or focus is inside toolbar
        if self.overlay_toolbar.underMouse() or self.overlay_toolbar.hasFocus():
            return
        self.overlay_toolbar.hide()

    def _start_hide_overlay_timer(self, delay_ms: int = 1200):
        if hasattr(self, "overlay_hide_timer"):
            self.overlay_hide_timer.start(delay_ms)

    def _show_preview_context_menu(self, pos):
        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            return
        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return
        doc = self.current_preview_docs[idx]
        if not doc["path"].exists():
            return

        menu = QMenu(self)
        if len(self.current_preview_docs) > 1:
            action_prev = menu.addAction("◀ 上一文件")
            action_prev.triggered.connect(self._prev_preview_doc)
            action_next = menu.addAction("下一文件 ▶")
            action_next.triggered.connect(self._next_preview_doc)
            menu.addSeparator()

        # PDF page navigation
        _, page_count = self._get_pdf_page_info()
        if page_count is not None and page_count > 1:
            action_prev_page = menu.addAction("◀ 上一页")
            action_prev_page.triggered.connect(self._prev_pdf_page)
            action_next_page = menu.addAction("下一页 ▶")
            action_next_page.triggered.connect(self._next_pdf_page)
            menu.addSeparator()

        action_fit_width = menu.addAction("适宽")
        action_fit_width.triggered.connect(self._zoom_fit_width)

        action_fit_page = menu.addAction("整页")
        action_fit_page.triggered.connect(self._zoom_fit_page)

        action_zoom_100 = menu.addAction("100% 原始比例")
        action_zoom_100.triggered.connect(self._zoom_100)

        action_zoom_in = menu.addAction("🔍 放大")
        action_zoom_in.triggered.connect(self._zoom_in)

        action_zoom_out = menu.addAction("🔍 缩小")
        action_zoom_out.triggered.connect(self._zoom_out)

        menu.addSeparator()
        action_open_ext = menu.addAction("📂 外部打开")
        action_open_ext.triggered.connect(self._open_current_preview_ext)

        menu.exec(self.preview_container.mapToGlobal(pos))

    def _focus_is_editing_widget(self) -> bool:
        """Return True if the currently focused widget should receive raw keyboard input."""
        focused = QApplication.focusWidget()
        if focused is None:
            return False
        from PySide6.QtWidgets import (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox,
                                        QAbstractSpinBox, QSpinBox, QDoubleSpinBox)
        if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox,
                                QAbstractSpinBox, QSpinBox, QDoubleSpinBox)):
            return True
        return False

    def eventFilter(self, watched, event) -> bool:
        double_click_targets = (
            getattr(self, "preview_container", None),
            getattr(self, "lbl_image_preview", None),
            getattr(getattr(self, "image_scroll_area", None), "viewport", lambda: None)(),
        )
        if watched in double_click_targets and watched is not None:
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self._toggle_preview_focus_mode()
                return True

        if watched is getattr(self, "preview_container", None):
            if event.type() == QEvent.Type.Enter:
                self._show_overlay_toolbar()
            elif event.type() == QEvent.Type.Leave:
                self._start_hide_overlay_timer()
        elif watched is getattr(self, "overlay_toolbar", None):
            if event.type() == QEvent.Type.Enter:
                self.overlay_hide_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                self._start_hide_overlay_timer()

        # ── Capture Left/Right keys for preview navigation with focus protection ──
        preview_widgets = {
            getattr(self, "preview_container", None),
            getattr(self, "preview_stack", None),
            getattr(self, "pdf_view", None),
            getattr(self, "image_scroll_area", None),
            getattr(getattr(self, "image_scroll_area", None), "viewport", lambda: None)(),
            getattr(self, "lbl_image_preview", None),
            getattr(self, "overlay_toolbar", None),
        }
        if watched in preview_widgets and watched is not None:
            if (
                event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.ControlModifier
            ):
                if event.angleDelta().y() > 0:
                    self._zoom_in()
                elif event.angleDelta().y() < 0:
                    self._zoom_out()
                return True
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key_Left, Qt.Key_Right):
                    # Only grab focus when active focus is inside preview related area (or no focus)
                    focused = QApplication.focusWidget()
                    is_preview_focused = False
                    if focused:
                        for w in preview_widgets:
                            if w and (focused is w or w.isAncestorOf(focused)):
                                is_preview_focused = True
                                break
                    else:
                        is_preview_focused = True

                    if is_preview_focused:
                        is_pdf_mode = (
                            getattr(self, "pdf_view", None) is not None
                            and self.preview_stack.currentWidget() is self.pdf_view
                        )
                        if event.key() == Qt.Key_Left:
                            if is_pdf_mode:
                                if not self._navigate_pdf_page(-1):
                                    self._prev_preview_doc()
                            else:
                                self._prev_preview_doc()
                            return True
                        elif event.key() == Qt.Key_Right:
                            if is_pdf_mode:
                                if not self._navigate_pdf_page(1):
                                    self._next_preview_doc()
                            else:
                                self._next_preview_doc()
                            return True

        try:
            return super().eventFilter(watched, event)
        except RuntimeError:
            return False

    def _set_zoom_buttons_enabled(self, enabled: bool):
        self.btn_fit_width.setEnabled(enabled)
        self.btn_fit_page.setEnabled(enabled)
        self.btn_zoom_100.setEnabled(enabled)
        self.btn_zoom_in.setEnabled(enabled)
        self.btn_zoom_out.setEnabled(enabled)
        for name in ("rotate_left", "rotate_right", "download", "print", "focus_mode"):
            action = getattr(self, "preview_actions", {}).get(name)
            if action is not None:
                action.setEnabled(enabled)

    def _set_preview_action_availability(self, file_path):
        """Apply capability-specific states and explain every disabled action."""
        exists = bool(file_path and file_path.exists())
        suffix = file_path.suffix.lower() if file_path else ""
        image_suffixes = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".heic")
        previewable = suffix == ".pdf" or suffix in image_suffixes
        missing_reason = "原文件不存在，无法执行此操作"
        unsupported_reason = "当前文件格式不支持内嵌预览"

        for name in ("zoom_out", "zoom_100", "zoom_in", "fit_width", "fit_page"):
            action = self.preview_actions[name]
            action.setEnabled(exists and previewable)
            action.setToolTip("" if action.isEnabled() else (missing_reason if not exists else unsupported_reason))

        rotate_enabled = exists and suffix in image_suffixes
        rotate_reason = missing_reason if not exists else "PDF 及当前文件格式请使用外部查看器旋转"
        for name in ("rotate_left", "rotate_right"):
            action = self.preview_actions[name]
            action.setEnabled(rotate_enabled)
            action.setToolTip("" if rotate_enabled else rotate_reason)

        for name in ("download", "print", "focus_mode"):
            action = self.preview_actions[name]
            action.setEnabled(exists)
            action.setToolTip("" if exists else missing_reason)

    def _show_preview_status(self, text):
        if text == "\u5f53\u524d\u53d1\u7968\u6ca1\u6709\u53ef\u9884\u89c8\u7684\u539f\u4ef6":
            text = (
                "\u5f53\u524d\u53d1\u7968\u6ca1\u6709\u53ef\u9884\u89c8\u7684\u539f\u4ef6\n"
                "\u53ef\u70b9\u51fb\u53f3\u4fa7\u6750\u6599\u533a\u7684 \u5b9a\u4f4d / \u8865\u5145\uff0c\u6216\u91cd\u65b0\u4e0b\u8f7d\u3002"
            )
        elif text == "\u6587\u4ef6\u4e0d\u5b58\u5728":
            text = (
                "\u539f\u4ef6\u6587\u4ef6\u4e0d\u5b58\u5728\n"
                "\u8def\u5f84\u53ef\u80fd\u5df2\u79fb\u52a8\u3001\u5220\u9664\uff0c\u6216\u4e0b\u8f7d\u672a\u5b8c\u6210\u3002\n"
                "\u53ef\u70b9\u51fb\u53f3\u4fa7\u6750\u6599\u533a\u7684 \u5b9a\u4f4d / \u66ff\u6362\uff0c\u6216\u91cd\u65b0\u5bfc\u5165/\u91cd\u65b0\u4e0b\u8f7d\u3002"
            )
        elif text == "\u6682\u4e0d\u652f\u6301\u5185\u5d4c\u9884\u89c8\uff0c\u8bf7\u70b9\u51fb\u6253\u5f00\u5916\u90e8\u6587\u4ef6":
            text = "\u5f53\u524d\u683c\u5f0f\u6682\u4e0d\u652f\u6301\u5185\u5d4c\u9884\u89c8\n\u8bf7\u70b9\u51fb\u5916\u90e8\u6253\u5f00\u67e5\u770b\u539f\u4ef6"
        elif text == "\u56fe\u7247\u52a0\u8f7d\u5931\u8d25\uff0c\u6682\u4e0d\u652f\u6301\u9884\u89c8":
            text = "\u56fe\u7247\u52a0\u8f7d\u5931\u8d25\n\u8bf7\u70b9\u51fb\u5916\u90e8\u6253\u5f00\uff0c\u6216\u91cd\u65b0\u5bfc\u5165\u8be5\u6750\u6599"
        self.lbl_preview_status.setText(text)
        self.preview_stack.setCurrentWidget(self.lbl_preview_status)
        self.overlay_toolbar.hide()
        self._set_zoom_buttons_enabled(False)

    def _zoom_fit_width(self):
        self.image_zoom_mode = "fit_width"
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self._update_image_display()

    def _zoom_fit_page(self):
        self.image_zoom_mode = "fit_page"
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self._update_image_display()

    def _zoom_100(self):
        self.image_zoom_mode = "custom"
        self.image_zoom_factor = 1.0
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(1.0)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self._update_image_display()

    def _zoom_in(self):
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() * 1.2)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self.image_zoom_mode = "custom"
            self.image_zoom_factor *= 1.2
            self._update_image_display()

    def _zoom_out(self):
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfView is not None and self.pdf_view is not None and self.preview_stack.currentWidget() == self.pdf_view:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() * 0.8)
        elif self.preview_stack.currentWidget() == self.image_scroll_area:
            self.image_zoom_mode = "custom"
            self.image_zoom_factor *= 0.8
            self._update_image_display()

    def _schedule_image_display_update(self):
        if hasattr(self, "image_resize_timer"):
            self.image_resize_timer.start()
        else:
            self._update_image_display()

    def _update_image_display(self):
        if self.current_image_pixmap is None or self.current_image_pixmap.isNull():
            return

        pixmap = self.current_image_pixmap
        if self.preview_rotation:
            pixmap = pixmap.transformed(
                QTransform().rotate(self.preview_rotation),
                Qt.SmoothTransformation,
            )

        if self.image_zoom_mode == "fit_width":
            width = self.image_scroll_area.width() - 24
            if width <= 0:
                width = 400
            scaled = pixmap.scaledToWidth(width, Qt.SmoothTransformation)
            self.lbl_image_preview.setPixmap(scaled)
        elif self.image_zoom_mode == "fit_page":
            width = self.image_scroll_area.width() - 24
            height = self.image_scroll_area.height() - 24
            if width <= 0:
                width = 400
            if height <= 0:
                height = 300
            scaled = pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_image_preview.setPixmap(scaled)
        elif self.image_zoom_mode == "custom":
            width = int(pixmap.width() * self.image_zoom_factor)
            if width <= 0:
                width = 100
            scaled = pixmap.scaledToWidth(width, Qt.SmoothTransformation)
            self.lbl_image_preview.setPixmap(scaled)

    def _update_document_preview(self):
        self._refresh_preview_thumbnails()
        # Thumbnail rail stays collapsed by default unless user toggles attachment list
        # self.thumbnail_rail.setVisible(False)
        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            self._show_preview_status(getattr(self, "_preview_empty_message", "请选择一张发票查看原件"))
            self.lbl_file_info.setText("0 / 0 无文件")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.btn_open_ext.setEnabled(False)
            if hasattr(self, "btn_link_evidence"):
                self.btn_link_evidence.setVisible(False)
                self.btn_link_evidence.setEnabled(False)
            self.overlay_toolbar.hide()
            self._set_zoom_buttons_enabled(False)
            return

        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return

        # Synchronize combo box selection
        if hasattr(self, "combo_supporting_docs") and getattr(self, "supporting_doc_items", None):
            current_doc = self.current_preview_docs[idx]
            doc_path = current_doc.get("path")
            if doc_path:
                doc_path_abs = str(doc_path.resolve()).lower()
                for i, item in enumerate(self.supporting_doc_items):
                    if item.get("path") and str(item["path"].resolve()).lower() == doc_path_abs:
                        self.combo_supporting_docs.blockSignals(True)
                        self.combo_supporting_docs.setCurrentIndex(i)
                        status_text = "已关联" if item["status"] == "linked" else "待关联"
                        self.combo_supporting_docs.setToolTip(f"[{status_text}] {item['path']}")
                        self.combo_supporting_docs.blockSignals(False)
                        break

        doc = self.current_preview_docs[idx]
        file_path = doc["path"]
        title = doc.get("title") or doc.get("label") or "附件"
        basename = doc.get("basename") or file_path.name

        # ── Format file info with PDF page distinction ──
        pdf_page, pdf_page_count = self._get_pdf_page_info()
        file_info_text = self._format_preview_file_info(doc, idx, len(self.current_preview_docs), pdf_page, pdf_page_count)
        self.lbl_file_info.setText(file_info_text)
        self.lbl_file_info.setToolTip(f"{title}: {basename}\n路径: {file_path.resolve()}")

        self.btn_prev.setEnabled(len(self.current_preview_docs) > 1)
        self.btn_next.setEnabled(len(self.current_preview_docs) > 1)
        self.btn_open_ext.setEnabled(True)
        # Disable PDF page buttons initially (will be refreshed after PDF load)
        if hasattr(self, "btn_prev_page"):
            self.btn_prev_page.setEnabled(False)
        if hasattr(self, "btn_next_page"):
            self.btn_next_page.setEnabled(False)

        is_pending = (doc.get("type") == "pending_evidence" and doc.get("evidence_id") is not None)
        if hasattr(self, "btn_link_evidence"):
            self.btn_link_evidence.setVisible(is_pending)
            self.btn_link_evidence.setEnabled(is_pending)

        if not file_path.exists():
            self._show_preview_status("文件不存在")
            self.overlay_toolbar.hide()
            self._set_preview_action_availability(file_path)
            return

        # Keep default state as hidden, show toolbar when mouse enters
        self.overlay_toolbar.hide()
        self._set_zoom_buttons_enabled(True)

        suffix = file_path.suffix.lower()
        file_size_mb = 0.0
        preview_start = time.perf_counter()
        used_fallback = False
        try:
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
        except OSError:
            file_size_mb = 0.0

        if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".heic") and file_size_mb > 8:
            self.write_log(f"[性能] 大图预览可能较慢: {file_size_mb:.1f}MB")

        if suffix == ".pdf":
            QPdfDocument, QPdfView = get_qt_pdf_classes()
            if QPdfDocument is not None and QPdfView is not None:
                if self.pdf_view is None:
                    self.pdf_view = QPdfView(self)
                    # ── PDF MultiPage: prefer MultiPage, fallback to SinglePage ──
                    if hasattr(QPdfView.PageMode, "MultiPage"):
                        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
                    else:
                        self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
                        _log.info("当前 Qt PDF 组件不支持 MultiPage，已降级为单页预览")
                    self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
                    self.preview_stack.addWidget(self.pdf_view)
                    # Install event filter to capture key events that QPdfView may consume
                    self.pdf_view.installEventFilter(self)

                old_document = getattr(self, "pdf_document", None)
                if old_document is not None:
                    try:
                        self.pdf_view.setDocument(None)
                    except Exception:
                        pass
                    try:
                        old_document.close()
                    except Exception:
                        pass
                    try:
                        old_document.deleteLater()
                    except Exception:
                        pass

                self.pdf_document = QPdfDocument(self)
                self.pdf_view.setDocument(self.pdf_document)
                self.pdf_document.load(str(file_path))
                # Re-apply MultiPage preference on every load
                if hasattr(QPdfView.PageMode, "MultiPage"):
                    self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
                else:
                    self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
                self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
                self.preview_stack.setCurrentWidget(self.pdf_view)
                self.pdf_view.update()
                # ── Refresh PDF-page-aware file info after loading ──
                self._refresh_preview_file_info()
                self._update_pdf_page_buttons()
                # ── Connect pageNavigator signal if available ──
                self._connect_pdf_page_navigator()
            else:
                used_fallback = True
                if self.lbl_pdf_fallback is None:
                    self.lbl_pdf_fallback = QLabel("暂不支持内嵌 PDF 预览，请点击【外部打开】")
                    self.lbl_pdf_fallback.setAlignment(Qt.AlignCenter)
                    self.lbl_pdf_fallback.setStyleSheet("color: #D97706; background-color: #FEF3C7; font-weight: bold; padding: 20px;")
                    self.preview_stack.addWidget(self.lbl_pdf_fallback)
                self.preview_stack.setCurrentWidget(self.lbl_pdf_fallback)
                self.overlay_toolbar.hide()
                self._set_zoom_buttons_enabled(False)
        elif suffix in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".heic"):
            pixmap = QPixmap(str(file_path))
            if pixmap.isNull():
                used_fallback = True
                if suffix == ".heic":
                    self._show_preview_status("该图片格式暂不支持内嵌预览，请点击外部打开")
                else:
                    self._show_preview_status("图片加载失败，暂不支持预览")
                self.overlay_toolbar.hide()
                self._set_zoom_buttons_enabled(False)
            else:
                self.current_image_pixmap = pixmap
                self.image_zoom_mode = "fit_width"
                self.image_zoom_factor = 1.0
                self._update_image_display()
                self.preview_stack.setCurrentWidget(self.image_scroll_area)
        else:
            used_fallback = True
            self._show_preview_status("暂不支持内嵌预览，请点击打开外部文件")
            self.overlay_toolbar.hide()
            self._set_zoom_buttons_enabled(False)

        load_elapsed_ms = int((time.perf_counter() - preview_start) * 1000)
        fallback_text = " fallback=1" if used_fallback else ""
        self.write_log(
            f"[性能] 原件预览: type={suffix or '<none>'} "
            f"size={file_size_mb:.1f}MB load={load_elapsed_ms}ms{fallback_text}"
        )
        self._set_preview_action_availability(file_path)

    def _prev_preview_doc(self):
        if hasattr(self, "current_preview_docs") and self.current_preview_docs:
            self.current_preview_index = (self.current_preview_index - 1) % len(self.current_preview_docs)
            self._update_document_preview()
            self._refresh_preview_file_info()
            self._update_pdf_page_buttons()

    def _next_preview_doc(self):
        if hasattr(self, "current_preview_docs") and self.current_preview_docs:
            self.current_preview_index = (self.current_preview_index + 1) % len(self.current_preview_docs)
            self._update_document_preview()
            self._refresh_preview_file_info()
            self._update_pdf_page_buttons()

    def _format_preview_file_info(self, doc: dict, file_index: int, file_count: int,
                                   pdf_page: int | None = None, pdf_page_count: int | None = None) -> str:
        """Build display string distinguishing file-level from PDF page-level navigation.

        Non-PDF:  "文件 1/2｜主发票"
        PDF:      "文件 1/2｜主发票｜PDF 1/7"  or  "文件 1/2｜主发票｜PDF 共 7 页"
        """
        title = doc.get("title", "文件")
        base = f"文件 {file_index + 1}/{file_count}｜{title}"

        suffix = file_path = doc.get("path")
        if suffix is not None and hasattr(suffix, "suffix"):
            suffix = suffix.suffix.lower()
        elif suffix is not None and hasattr(suffix, "lower"):
            suffix = suffix.lower()
        else:
            suffix = ""

        if suffix != ".pdf" or pdf_page_count is None:
            return base

        if pdf_page is not None:
            return f"{base}｜PDF {pdf_page}/{pdf_page_count}"
        return f"{base}｜PDF 共 {pdf_page_count} 页"

    def _get_pdf_page_info(self) -> tuple[int | None, int | None]:
        """Return (current_page 1-based, total_pages) or (None, None) if not a PDF."""
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfDocument is None:
            return None, None
        pdf_view = getattr(self, "pdf_view", None)
        pdf_doc = getattr(self, "pdf_document", None)
        if pdf_view is None or pdf_doc is None:
            return None, None
        if self.preview_stack.currentWidget() != pdf_view:
            return None, None
        try:
            page_count = pdf_doc.pageCount()
        except Exception:
            return None, None
        if page_count <= 0:
            return None, None

        current_page = None
        # Try to read current page from pageNavigator (PySide6 >= 6.5)
        try:
            nav = pdf_doc.pageNavigator()
            if nav is not None:
                cp = nav.currentPage()
                if cp is not None and isinstance(cp, int):
                    current_page = cp + 1  # 0-based → 1-based
        except Exception:
            pass
        return current_page, page_count

    def _refresh_preview_file_info(self):
        """Recompute overlay toolbar file-info label in-place without reloading the preview."""
        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            return
        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return
        doc = self.current_preview_docs[idx]
        pdf_page, pdf_page_count = self._get_pdf_page_info()
        text = self._format_preview_file_info(doc, idx, len(self.current_preview_docs), pdf_page, pdf_page_count)
        if hasattr(self, "lbl_file_info"):
            self.lbl_file_info.setText(text)

    def _connect_pdf_page_navigator(self):
        """Try to connect to QPdfDocument's pageNavigator currentPageChanged signal."""
        pdf_doc = getattr(self, "pdf_document", None)
        if pdf_doc is None:
            return
        try:
            nav = pdf_doc.pageNavigator()
            if nav is not None and hasattr(nav, "currentPageChanged"):
                try:
                    nav.currentPageChanged.disconnect(self._on_pdf_page_changed)
                except Exception:
                    pass
                nav.currentPageChanged.connect(self._on_pdf_page_changed)
        except Exception:
            pass

    def _on_pdf_page_changed(self, _page: int):
        """Slot for pageNavigator.currentPageChanged – keep toolbar in sync."""
        self._refresh_preview_file_info()
        self._update_pdf_page_buttons()

    def _prev_pdf_page(self):
        self._navigate_pdf_page(-1)

    def _next_pdf_page(self):
        self._navigate_pdf_page(1)

    def _navigate_pdf_page(self, delta: int) -> bool:
        """Navigate within PDF pages. Returns True if navigation succeeded."""
        QPdfDocument, QPdfView = get_qt_pdf_classes()
        if QPdfDocument is None:
            return False
        pdf_view = getattr(self, "pdf_view", None)
        pdf_doc = getattr(self, "pdf_document", None)
        if pdf_view is None or pdf_doc is None:
            return False
        if self.preview_stack.currentWidget() != pdf_view:
            return False
        try:
            page_count = pdf_doc.pageCount()
            nav = pdf_doc.pageNavigator()
            if nav is None:
                return False
            current = nav.currentPage()  # 0-based
            new_page = current + delta
            if new_page < 0 or new_page >= page_count:
                return False
            nav.jump(new_page, 0.0, 0.0)
            self._refresh_preview_file_info()
            self._update_pdf_page_buttons()
            return True
        except Exception:
            return False

    def _update_pdf_page_buttons(self):
        """Enable/disable PDF page-nav buttons based on current state."""
        btn_prev_page = getattr(self, "btn_prev_page", None)
        btn_next_page = getattr(self, "btn_next_page", None)
        if btn_prev_page is None or btn_next_page is None:
            return

        _, page_count = self._get_pdf_page_info()
        if page_count is None or page_count <= 1:
            btn_prev_page.setEnabled(False)
            btn_next_page.setEnabled(False)
            return

        nav = None
        pdf_doc = getattr(self, "pdf_document", None)
        if pdf_doc is not None:
            try:
                nav = pdf_doc.pageNavigator()
            except Exception:
                pass
        if nav is None:
            btn_prev_page.setEnabled(False)
            btn_next_page.setEnabled(False)
            return

        try:
            current = nav.currentPage()  # 0-based
        except Exception:
            btn_prev_page.setEnabled(False)
            btn_next_page.setEnabled(False)
            return

        btn_prev_page.setEnabled(current > 0)
        btn_next_page.setEnabled(current < page_count - 1)

    def _prev_preview_file(self):
        """Alias for _prev_preview_doc – file-level navigation."""
        self._prev_preview_doc()

    def _next_preview_file(self):
        """Alias for _next_preview_doc – file-level navigation."""
        self._next_preview_doc()

    def _open_current_preview_ext(self):
        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            return
        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return
        doc = self.current_preview_docs[idx]
        file_path = doc["path"]
        if file_path and file_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path.resolve())))

    def _on_supporting_docs_combo_changed(self, index):
        """Called when combo box item is selected. Updates tooltip and synchronizes preview window."""
        if index < 0 or not getattr(self, "supporting_doc_items", None):
            self.combo_supporting_docs.setToolTip("")
            return

        if index < len(self.supporting_doc_items):
            item = self.supporting_doc_items[index]
            status_text = "已关联" if item["status"] == "linked" else "待关联"
            path_str = str(item["path"]) if item["path"] else "未知路径"
            self.combo_supporting_docs.setToolTip(f"[{status_text}] {path_str}")

            # Sync preview index if the file path is present in current_preview_docs
            if hasattr(self, "current_preview_docs") and self.current_preview_docs:
                resolved_path = item["path"]
                if resolved_path:
                    resolved_abs = str(resolved_path.resolve()).lower()
                    for i, doc in enumerate(self.current_preview_docs):
                        if doc.get("path") and str(doc["path"].resolve()).lower() == resolved_abs:
                            if self.current_preview_index != i:
                                self.current_preview_index = i
                                self._update_document_preview()
                            break

    def _format_supporting_doc_label(self, status_text: str, path: Path, max_len: int = 42) -> str:
        """Format supporting document label with middle elision if file name is too long."""
        prefix = f"[{status_text}] "
        filename = path.name if hasattr(path, "name") else Path(str(path)).name

        max_filename_len = max_len - len(prefix)
        if max_filename_len < 10:
            max_filename_len = 10

        if len(filename) > max_filename_len:
            half = max_filename_len // 2 - 2
            if half < 3:
                half = 3
            filename = filename[:half] + "..." + filename[-half:]

        return f"{prefix}{filename}"

    def _update_supporting_docs_selector(self, inv, selected_path=None):
        """Update the supporting documents combo box selector."""
        self.combo_supporting_docs.blockSignals(True)
        self.combo_supporting_docs.clear()
        self.supporting_doc_items = []

        if not inv:
            self.combo_supporting_docs.addItem("暂无证明材料")
            self.combo_supporting_docs.setEnabled(False)
            self.btn_open_extra_files.setEnabled(False)
            self.combo_supporting_docs.setToolTip("酒店水单、行程记录、支付截图等证明材料会显示在这里。")
            self.combo_supporting_docs.blockSignals(False)
            return

        # 1. Gather linked extra docs
        extra_paths_raw = inv.get("extra_paths") or []
        if isinstance(extra_paths_raw, str):
            try:
                extra_paths_raw = json.loads(extra_paths_raw)
            except json.JSONDecodeError:
                extra_paths_raw = [extra_paths_raw]

        seen_paths = set()

        if isinstance(extra_paths_raw, list):
            for p in extra_paths_raw:
                p_str = str(p).strip()
                if not p_str:
                    continue
                resolved = self._resolve_attachment_path(p_str)
                if resolved:
                    abs_path_lower = str(resolved.resolve()).lower()
                    if abs_path_lower not in seen_paths:
                        seen_paths.add(abs_path_lower)
                        self.supporting_doc_items.append({
                            "label": self._format_supporting_doc_label("已关联", resolved),
                            "path": resolved,
                            "status": "linked",
                            "type": "supporting"
                        })

        # 2. Gather pending evidence docs
        mailbox_key = inv.get("mailbox_key")
        mail_uid = inv.get("mail_uid")
        if mailbox_key and mail_uid is not None:
            try:
                rows = self.db.list_pending_evidence_for_mail(mailbox_key, mail_uid)
                for row in rows:
                    att_p = row.get("attachment_path")
                    if att_p:
                        resolved = self._resolve_attachment_path(str(att_p))
                        if resolved:
                            abs_path_lower = str(resolved.resolve()).lower()
                            if abs_path_lower not in seen_paths:
                                seen_paths.add(abs_path_lower)
                                self.supporting_doc_items.append({
                                    "label": self._format_supporting_doc_label("待关联", resolved),
                                    "path": resolved,
                                    "status": "pending",
                                    "type": "pending_evidence"
                                })
            except Exception as e:
                print(f"Error querying unassociated evidence: {e}")

        # 3. Populate QComboBox
        if self.supporting_doc_items:
            for item in self.supporting_doc_items:
                self.combo_supporting_docs.addItem(item["label"])
            self.combo_supporting_docs.setEnabled(True)
            self.btn_open_extra_files.setEnabled(True)

            # Determine selected index
            matched_index = 0
            if selected_path is not None:
                selected_path_str = str(Path(selected_path).resolve()).lower()
                for i, item in enumerate(self.supporting_doc_items):
                    if item.get("path") and str(item["path"].resolve()).lower() == selected_path_str:
                        matched_index = i
                        break

            self.combo_supporting_docs.setCurrentIndex(matched_index)

            # Set tooltip for selected item
            sel_item = self.supporting_doc_items[matched_index]
            status_text = "已关联" if sel_item["status"] == "linked" else "待关联"
            self.combo_supporting_docs.setToolTip(f"[{status_text}] {sel_item['path']}")
        else:
            self.combo_supporting_docs.addItem("暂无证明材料")
            self.combo_supporting_docs.setEnabled(False)
            self.btn_open_extra_files.setEnabled(False)
            self.combo_supporting_docs.setToolTip("酒店水单、行程记录、支付截图等证明材料会显示在这里。")

        self.combo_supporting_docs.blockSignals(False)

    def _link_current_evidence_to_invoice(self):
        """Link the currently previewed evidence document to the current invoice."""
        if not self.current_invoice:
            return

        invoice_id = self.current_invoice.get("id")
        if not invoice_id:
            return

        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            return

        idx = self.current_preview_index
        if idx < 0 or idx >= len(self.current_preview_docs):
            return

        doc = self.current_preview_docs[idx]
        if doc.get("type") != "pending_evidence" or doc.get("evidence_id") is None:
            return

        evidence_id = doc["evidence_id"]
        evidence_name = doc["basename"]
        invoice_num = self.current_invoice.get("invoice_number") or "（无发票号）"
        current_file_path = doc["path"]

        # Prompt confirmation
        reply = QMessageBox.question(
            self,
            "确认关联",
            f"确认将该证明材料关联到当前发票吗？\n\n发票号码: {invoice_num}\n证明材料文件名: {evidence_name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            success = self.db.link_evidence_to_invoice(invoice_id, evidence_id)
            if success:
                # Refresh invoice data
                updated_inv = self.db.get_invoice(invoice_id)
                if updated_inv:
                    self.current_invoice = updated_inv
                    for i, item in enumerate(self.invoices_list):
                        if item.get("id") == invoice_id:
                            self.invoices_list[i] = updated_inv
                            break

                # Re-resolve preview docs
                from .helpers import resolve_invoice_documents_with_evidence
                self.current_preview_docs = resolve_invoice_documents_with_evidence(
                    self.current_invoice,
                    self.db,
                    _runtime_dir_compat(),
                )

                # Update selector first with the path to keep it selected
                self._update_supporting_docs_selector(self.current_invoice, selected_path=current_file_path)

                # Locate the newly linked document in its new position (type=supporting)
                new_idx = 0
                if current_file_path:
                    current_file_path_abs = str(current_file_path.resolve()).lower()
                    for i, doc_item in enumerate(self.current_preview_docs):
                        if doc_item.get("path") and str(doc_item["path"].resolve()).lower() == current_file_path_abs:
                            new_idx = i
                            break
                self.current_preview_index = new_idx

                # Update preview last which handles synchronization
                self._update_document_preview()
                self.statusBar().showMessage("已成功将证明材料关联到当前发票", 3000)
            else:
                QMessageBox.warning(self, "关联失败", "无法将证明材料关联到当前发票，请重试。")

    def _refresh_preview_thumbnails(self):
        while self.thumbnail_layout.count():
            item = self.thumbnail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.thumbnail_buttons = []

        for index, doc in enumerate(getattr(self, "current_preview_docs", []) or []):
            path = doc.get("path")
            label = doc.get("title") or doc.get("label") or (path.name if path else f"附件 {index + 1}")
            button = QPushButton(label)
            button.setObjectName("PreviewThumbnail")
            button.setProperty("selected", index == self.current_preview_index)
            button.setCheckable(True)
            button.setChecked(index == self.current_preview_index)
            button.setToolTip(str(path) if path else label)
            button.clicked.connect(lambda _checked=False, value=index: self._select_preview_doc(value))
            self.thumbnail_layout.addWidget(button)
            self.thumbnail_buttons.append(button)

        add_button = QPushButton("＋\n添加附件")
        add_button.setObjectName("PreviewAddAttachment")
        add_button.clicked.connect(self._add_attachment_manually)
        self.thumbnail_layout.addWidget(add_button)
        self.thumbnail_layout.addStretch(1)

    def _select_preview_doc(self, index: int):
        docs = getattr(self, "current_preview_docs", []) or []
        if index < 0 or index >= len(docs):
            return False
        self.current_preview_index = index
        self.preview_rotation = 0
        self._refresh_preview_thumbnails()
        self._update_document_preview()
        return True

    def _rotate_preview(self, degrees: int):
        if degrees not in (-90, 90):
            raise ValueError("Preview rotation must be -90 or 90 degrees")
        docs = getattr(self, "current_preview_docs", []) or []
        if not docs:
            return False
        path = docs[self.current_preview_index].get("path")
        if path is None or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".heic"):
            self.statusBar().showMessage("PDF 旋转请使用外部查看器", 3000)
            return False
        self.preview_rotation = (self.preview_rotation + degrees) % 360
        self._update_image_display()
        return True

    def _download_current_preview(self):
        docs = getattr(self, "current_preview_docs", []) or []
        if not docs:
            return False
        source = docs[self.current_preview_index].get("path")
        if source is None or not source.exists():
            return False
        destination, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "下载原件",
            source.name,
            f"文件 (*{source.suffix})",
        )
        if not destination:
            return False
        import shutil

        shutil.copy2(source, destination)
        self.statusBar().showMessage("原件已下载", 3000)
        return True

    def _print_current_preview(self):
        docs = getattr(self, "current_preview_docs", []) or []
        if not docs:
            return False
        self.statusBar().showMessage("已在外部查看器打开，请使用系统打印功能", 4000)
        self._open_current_preview_ext()
        return True

    def _toggle_preview_focus_mode(self):
        if self.preview_focus_dialog is None:
            self._enter_preview_focus_mode()
        else:
            self._exit_preview_focus_mode()

    def _enter_preview_focus_mode(self):
        if self.preview_focus_dialog is not None:
            return
        self._preview_original_parent = self.preview_workbench.parentWidget()
        self._preview_original_layout = self._preview_original_parent.layout()
        self._preview_original_index = self._preview_original_layout.indexOf(self.preview_workbench)

        owner = self

        class PreviewFocusDialog(QDialog):
            def keyPressEvent(dialog_self, event):
                if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    if hasattr(owner, "_invoke_workbench_action"):
                        owner._invoke_workbench_action(lambda: owner._set_selected_status("approved"))
                    event.accept()
                    return
                if event.key() == Qt.Key_Delete:
                    if hasattr(owner, "_invoke_workbench_action"):
                        owner._invoke_workbench_action(lambda: owner._set_selected_status("ignored"))
                    event.accept()
                    return
                if event.key() == Qt.Key_E and event.modifiers() & Qt.ControlModifier:
                    if hasattr(owner, "_invoke_workbench_action"):
                        owner._invoke_workbench_action(lambda: owner._set_selected_status("error"))
                    event.accept()
                    return
                if event.key() == Qt.Key_Escape:
                    owner._exit_preview_focus_mode()
                    event.accept()
                    return
                super().keyPressEvent(event)

        dialog = PreviewFocusDialog(self)
        dialog.setWindowTitle("发票预览")
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(8, 8, 8, 8)
        self.preview_workbench.setParent(dialog)
        dialog_layout.addWidget(self.preview_workbench)
        self.preview_focus_dialog = dialog
        if hasattr(self, "_bind_review_shortcuts"):
            self.preview_focus_shortcuts = self._bind_review_shortcuts(dialog)
            self.preview_focus_workbench_shortcuts = self._bind_review_shortcuts(self.preview_workbench)
        self._preview_escape_shortcut = QShortcut(QKeySequence("Esc"), dialog)
        self._preview_escape_shortcut.activated.connect(self._exit_preview_focus_mode)
        dialog.finished.connect(self._preview_focus_finished)
        self.btn_preview_focus.setText("退出全屏")
        dialog.showMaximized()
        dialog.setFocusPolicy(Qt.StrongFocus)
        dialog.activateWindow()
        dialog.raise_()
        dialog.setFocus(Qt.ActiveWindowFocusReason)

    def _preview_focus_finished(self, _result):
        if self.preview_focus_dialog is not None:
            self._exit_preview_focus_mode(close_dialog=False)

    def _handle_preview_focus_keypress(self, event) -> bool:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._set_selected_status("approved")
            event.accept()
            return True
        if event.key() == Qt.Key_Delete:
            self._set_selected_status("ignored")
            event.accept()
            return True
        if event.key() == Qt.Key_E and event.modifiers() & Qt.ControlModifier:
            self._set_selected_status("error")
            event.accept()
            return True
        if event.key() == Qt.Key_Escape:
            self._exit_preview_focus_mode()
            event.accept()
            return True
        return False

    def _exit_preview_focus_mode(self, close_dialog=True):
        dialog = self.preview_focus_dialog
        if dialog is None:
            return
        self.preview_focus_dialog = None
        self.preview_focus_shortcuts = {}
        self.preview_focus_workbench_shortcuts = {}
        self.preview_workbench.setParent(self._preview_original_parent)
        self._preview_original_layout.insertWidget(
            max(0, self._preview_original_index),
            self.preview_workbench,
            1,
        )
        self.btn_preview_focus.setText("全屏")
        if close_dialog:
            dialog.close()
        dialog.deleteLater()

    def keyPressEvent(self, event):
        # Toggle overlay toolbar visible state temporarily on Alt or Ctrl keypress
        if event.key() in (Qt.Key_Alt, Qt.Key_Control):
            self._show_overlay_toolbar()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() in (Qt.Key_Alt, Qt.Key_Control):
            self._start_hide_overlay_timer()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _register_navigation_shortcuts(self):
        """Register Ctrl+Left / Ctrl+Right for file-level navigation via QShortcut."""
        # ── Ctrl+Left: previous file ──
        self.shortcut_prev_file = QShortcut(Qt.CTRL | Qt.Key_Left, self)
        self.shortcut_prev_file.setContext(Qt.WindowShortcut)
        self.shortcut_prev_file.activated.connect(self._on_ctrl_left)

        # ── Ctrl+Right: next file ──
        self.shortcut_next_file = QShortcut(Qt.CTRL | Qt.Key_Right, self)
        self.shortcut_next_file.setContext(Qt.WindowShortcut)
        self.shortcut_next_file.activated.connect(self._on_ctrl_right)

    def _on_ctrl_left(self):
        if not self._focus_is_editing_widget():
            self._prev_preview_doc()

    def _on_ctrl_right(self):
        if not self._focus_is_editing_widget():
            self._next_preview_doc()
