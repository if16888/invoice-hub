# -*- coding: utf-8 -*-
"""Preview panel behavior mixed into the Invoice Hub main window."""

import json
import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QComboBox, QDoubleSpinBox, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QTextEdit, QVBoxLayout, QWidget,
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


class PreviewMixin:
    def _init_preview_panel(self):
        self.preview_panel = QGroupBox("原件预览")
        self.preview_panel.setFocusPolicy(Qt.StrongFocus)
        preview_layout = QVBoxLayout(self.preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(0)

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
        self.preview_container = QWidget()
        preview_layout.addWidget(self.preview_container, 1)

        # Install event filter to track mouse entry and exit on preview container
        self.preview_container.installEventFilter(self)

        # Enable Context Menu on preview area
        self.preview_container.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preview_container.customContextMenuRequested.connect(self._show_preview_context_menu)

        container_layout = QVBoxLayout(self.preview_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self.preview_stack = QStackedWidget()
        self.preview_stack.setFrameShape(QFrame.StyledPanel)
        self.preview_stack.installEventFilter(self)

        self.lbl_preview_status = QLabel("请选择一张发票查看原件")
        self.lbl_preview_status.setAlignment(Qt.AlignCenter)
        self.lbl_preview_status.setWordWrap(True)
        self.lbl_preview_status.setStyleSheet("color: #6B7280; font-size: 13px; background-color: #F9FAFB;")
        self.preview_stack.addWidget(self.lbl_preview_status)
        self._preview_empty_message = "请选择一张发票查看原件"

        self.pdf_document = None
        self.pdf_view = None
        self.lbl_pdf_fallback = None

        self.image_scroll_area = QScrollArea()
        self.image_scroll_area.setWidgetResizable(True)
        self.image_scroll_area.setAlignment(Qt.AlignCenter)
        self.image_scroll_area.installEventFilter(self)
        # Dynamic Resizing scaling for image in FitToWidth / FitInView modes
        self.image_scroll_area.resizeEvent = lambda event: (
            QScrollArea.resizeEvent(self.image_scroll_area, event),
            self._schedule_image_display_update()
        )

        self.lbl_image_preview = QLabel()
        self.lbl_image_preview.setAlignment(Qt.AlignCenter)
        self.lbl_image_preview.setStyleSheet("background-color: #FFFFFF;")
        self.image_scroll_area.setWidget(self.lbl_image_preview)

        self.preview_stack.addWidget(self.image_scroll_area)
        container_layout.addWidget(self.preview_stack)

        # Create Floating Overlay Toolbar (weaker visual, smaller height, semi-transparent)
        self.overlay_toolbar = QWidget(self.preview_container)
        self.overlay_toolbar.setObjectName("OverlayToolbar")
        self.overlay_toolbar.setFixedHeight(28)
        self.overlay_toolbar.setStyleSheet("""
            QWidget#OverlayToolbar {
                background-color: rgba(255, 255, 255, 195);
                border: 1px solid #D1D5DB;
                border-radius: 8px;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                padding: 1px 4px;
                font-size: 11px;
                color: #374151;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: rgba(243, 244, 246, 200);
                border-radius: 4px;
                color: #111827;
            }
            QPushButton:disabled {
                color: #9CA3AF;
                background-color: transparent;
            }
        """)

        # Install event filter to prevent hide when inside toolbar itself
        self.overlay_toolbar.installEventFilter(self)

        tb_layout = QHBoxLayout(self.overlay_toolbar)
        tb_layout.setContentsMargins(4, 0, 4, 0)
        tb_layout.setSpacing(3)

        # Left / Prev Doc button (file-level)
        self.btn_prev = QPushButton("←")
        self.btn_prev.clicked.connect(self._prev_preview_doc)
        self.btn_prev.setFixedWidth(18)
        self.btn_prev.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.btn_prev.setToolTip("上一文件")
        tb_layout.addWidget(self.btn_prev)

        # File index/name display (minimal format e.g. 文件 1/2｜主发票｜PDF 1/7)
        self.lbl_file_info = QLabel("0 / 0 无文件")
        self.lbl_file_info.setAlignment(Qt.AlignCenter)
        self.lbl_file_info.setStyleSheet("font-weight: bold; color: #374151; font-size: 11px; padding: 0 2px; background: transparent; border: none;")
        tb_layout.addWidget(self.lbl_file_info)

        # Right / Next Doc button (file-level)
        self.btn_next = QPushButton("→")
        self.btn_next.clicked.connect(self._next_preview_doc)
        self.btn_next.setFixedWidth(18)
        self.btn_next.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.btn_next.setToolTip("下一文件")
        tb_layout.addWidget(self.btn_next)

        # Divider Frame helper
        def add_divider():
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFrameShadow(QFrame.Plain)
            sep.setStyleSheet("color: #E5E7EB; max-height: 14px; background: transparent; border: none; border-left: 1px solid #E5E7EB;")
            tb_layout.addWidget(sep)

        add_divider()

        # ── PDF page-level navigation ──
        self.btn_prev_page = QPushButton("◀ 上一页")
        self.btn_prev_page.clicked.connect(self._prev_pdf_page)
        self.btn_prev_page.setToolTip("PDF 上一页")
        self.btn_prev_page.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.btn_prev_page.setEnabled(False)
        tb_layout.addWidget(self.btn_prev_page)

        self.btn_next_page = QPushButton("下一页 ▶")
        self.btn_next_page.clicked.connect(self._next_pdf_page)
        self.btn_next_page.setToolTip("PDF 下一页")
        self.btn_next_page.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.btn_next_page.setEnabled(False)
        tb_layout.addWidget(self.btn_next_page)

        add_divider()

        # Fit Width Button
        self.btn_fit_width = QPushButton("适宽")
        self.btn_fit_width.clicked.connect(self._zoom_fit_width)
        tb_layout.addWidget(self.btn_fit_width)

        # Fit Page Button
        self.btn_fit_page = QPushButton("整页")
        self.btn_fit_page.clicked.connect(self._zoom_fit_page)
        tb_layout.addWidget(self.btn_fit_page)

        # Zoom 100% Button
        self.btn_zoom_100 = QPushButton("100%")
        self.btn_zoom_100.clicked.connect(self._zoom_100)
        tb_layout.addWidget(self.btn_zoom_100)

        # Zoom Out Button
        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        self.btn_zoom_out.setFixedWidth(14)
        self.btn_zoom_out.setStyleSheet("font-weight: bold; font-size: 11px;")
        tb_layout.addWidget(self.btn_zoom_out)

        # Zoom In Button
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        self.btn_zoom_in.setFixedWidth(14)
        self.btn_zoom_in.setStyleSheet("font-weight: bold; font-size: 11px;")
        tb_layout.addWidget(self.btn_zoom_in)

        add_divider()

        # Open External Button
        self.btn_open_ext = QPushButton("外部打开")
        self.btn_open_ext.clicked.connect(self._open_current_preview_ext)
        tb_layout.addWidget(self.btn_open_ext)

        # Divider and Link Evidence Button
        add_divider()
        self.btn_link_evidence = QPushButton("关联到当前发票")
        self.btn_link_evidence.clicked.connect(self._link_current_evidence_to_invoice)
        self.btn_link_evidence.setStyleSheet("font-weight: bold; color: #059669; padding: 0 4px;")
        self.btn_link_evidence.setVisible(False)
        self.btn_link_evidence.setEnabled(False)
        tb_layout.addWidget(self.btn_link_evidence)

        # Bind container resizing to overlay position alignment (Y-offset smaller = 4px)
        def resize_container(event):
            QWidget.resizeEvent(self.preview_container, event)
            self._reposition_overlay_toolbar()

        self.preview_container.resizeEvent = resize_container

        # Hide overlay initially
        self.overlay_toolbar.setVisible(False)
        self._set_zoom_buttons_enabled(False)

        # Register Ctrl+Left/Ctrl+Right shortcuts for file-level navigation
        self._register_navigation_shortcuts()

    def _reposition_overlay_toolbar(self):
        if self.overlay_toolbar.isVisible() and hasattr(self, "preview_container") and self.preview_container.width() > 0:
            tb_size = self.overlay_toolbar.sizeHint()
            w = min(tb_size.width(), self.preview_container.width() - 20)
            h = 28
            x = (self.preview_container.width() - w) // 2
            y = 4  # Minimal Y offset to not block document content
            self.overlay_toolbar.setGeometry(x, y, w, h)

    def _show_overlay_toolbar(self):
        self.overlay_hide_timer.stop()
        if hasattr(self, "current_preview_docs") and self.current_preview_docs:
            idx = self.current_preview_index
            if 0 <= idx < len(self.current_preview_docs):
                doc = self.current_preview_docs[idx]
                if doc["path"].exists():
                    self.overlay_toolbar.setVisible(True)
                    self.overlay_toolbar.adjustSize()
                    self._reposition_overlay_toolbar()

    def _hide_overlay_toolbar(self):
        self.overlay_toolbar.setVisible(False)

    def _start_hide_overlay_timer(self):
        self.overlay_hide_timer.start(1500)  # Hide after 1.5 seconds

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
            getattr(self, "overlay_toolbar", None),
        }
        if watched in preview_widgets and watched is not None:
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

    def _show_preview_status(self, text):
        if text == "当前发票没有可预览的原件":
            text = "当前发票没有可预览的原件\n可点击“查看文件”或“定位文件”确认原件位置"
        elif text == "文件不存在":
            text = "原件文件不存在\n可点击“定位文件”确认路径，或重新导入/重新下载"
        elif text == "暂不支持内嵌预览，请点击打开外部文件":
            text = "当前格式暂不支持内嵌预览\n请点击外部打开查看原件"
        elif text == "图片加载失败，暂不支持预览":
            text = "图片加载失败\n请点击外部打开，或重新导入该材料"
        self.lbl_preview_status.setText(text)
        self.preview_stack.setCurrentWidget(self.lbl_preview_status)
        self.overlay_toolbar.setVisible(False)
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

        if self.image_zoom_mode == "fit_width":
            width = self.image_scroll_area.width() - 24
            if width <= 0:
                width = 400
            scaled = self.current_image_pixmap.scaledToWidth(width, Qt.SmoothTransformation)
            self.lbl_image_preview.setPixmap(scaled)
        elif self.image_zoom_mode == "fit_page":
            width = self.image_scroll_area.width() - 24
            height = self.image_scroll_area.height() - 24
            if width <= 0:
                width = 400
            if height <= 0:
                height = 300
            scaled = self.current_image_pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_image_preview.setPixmap(scaled)
        elif self.image_zoom_mode == "custom":
            width = int(self.current_image_pixmap.width() * self.image_zoom_factor)
            if width <= 0:
                width = 100
            scaled = self.current_image_pixmap.scaledToWidth(width, Qt.SmoothTransformation)
            self.lbl_image_preview.setPixmap(scaled)

    def _update_document_preview(self):
        if not hasattr(self, "current_preview_docs") or not self.current_preview_docs:
            self._show_preview_status(getattr(self, "_preview_empty_message", "请选择一张发票查看原件"))
            self.lbl_file_info.setText("0 / 0 无文件")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.btn_open_ext.setEnabled(False)
            if hasattr(self, "btn_link_evidence"):
                self.btn_link_evidence.setVisible(False)
                self.btn_link_evidence.setEnabled(False)
            self.overlay_toolbar.setVisible(False)
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
        title = doc["title"]
        basename = doc["basename"]

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
            self.overlay_toolbar.setVisible(False)
            self._set_zoom_buttons_enabled(False)
            return

        # Keep default state as hidden, show toolbar when mouse enters
        self.overlay_toolbar.setVisible(False)
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
                    self.pdf_document = QPdfDocument(self)
                    self.pdf_view = QPdfView(self)
                    self.pdf_view.setDocument(self.pdf_document)
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

                self.pdf_document.load(str(file_path))
                # Re-apply MultiPage preference on every load
                if hasattr(QPdfView.PageMode, "MultiPage"):
                    self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
                else:
                    self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
                self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
                self.preview_stack.setCurrentWidget(self.pdf_view)
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
                self.overlay_toolbar.setVisible(False)
                self._set_zoom_buttons_enabled(False)
        elif suffix in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".heic"):
            pixmap = QPixmap(str(file_path))
            if pixmap.isNull():
                used_fallback = True
                if suffix == ".heic":
                    self._show_preview_status("该图片格式暂不支持内嵌预览，请点击外部打开")
                else:
                    self._show_preview_status("图片加载失败，暂不支持预览")
                self.overlay_toolbar.setVisible(False)
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
            self.overlay_toolbar.setVisible(False)
            self._set_zoom_buttons_enabled(False)

        load_elapsed_ms = int((time.perf_counter() - preview_start) * 1000)
        fallback_text = " fallback=1" if used_fallback else ""
        self.write_log(
            f"[性能] 原件预览: type={suffix or '<none>'} "
            f"size={file_size_mb:.1f}MB load={load_elapsed_ms}ms{fallback_text}"
        )

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
