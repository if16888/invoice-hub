# -*- coding: utf-8 -*-
"""Shared controller and embedded surface for mobile upload sessions."""

from io import BytesIO
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from ..config import RUNTIME_DIR
from .ui_components import make_badge, make_button


class MobileUploadSessionController(QObject):
    starting = Signal()
    started = Signal(object)
    stats_changed = Signal(dict)
    upload_received = Signal(dict)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, db_path: Path, parent=None, runtime_dir: Path = RUNTIME_DIR):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.runtime_dir = Path(runtime_dir)
        self.server = None
        self.session = None
        self.host_options = []
        self._last_total = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh_status)

    def enumerate_hosts(self):
        from ..mobile_upload import enumerate_upload_hosts
        self.host_options = enumerate_upload_hosts()
        return self.host_options

    def start(self, host: str | None = None):
        if self.server is not None:
            return self.session
        self.starting.emit()
        try:
            from ..mobile_upload import MobileUploadServer
            options = self.enumerate_hosts()
            selected = host or (options[0].host if options else None)
            self.server = MobileUploadServer(
                runtime_dir=self.runtime_dir, db_path=self.db_path, host=selected,
                port=0, import_on_upload=True,
            )
            self.session = self.server.start()
            self._last_total = 0
            self.timer.start()
            self.started.emit(self.session)
            return self.session
        except Exception as exc:
            self.server = None
            self.session = None
            self.failed.emit(str(exc))
            return None

    def set_public_host(self, host: str):
        if self.server is None:
            return None
        try:
            self.session = self.server.set_public_host(host)
            self.started.emit(self.session)
            return self.session
        except Exception as exc:
            self.failed.emit(str(exc))
            return None

    def refresh_status(self):
        if self.server is None:
            return
        status = dict(self.server.status())
        self.stats_changed.emit(status)
        total = sum(int(status.get(k, 0) or 0) for k in ("accepted", "duplicate", "failed", "imported"))
        if total and total != self._last_total:
            self._last_total = total
            self.upload_received.emit(status)

    def stop(self):
        if self.server is not None:
            self.server.stop()
        self.server = None
        self.session = None
        self.timer.stop()
        self.stopped.emit()

    @staticmethod
    def qr_png(url: str) -> bytes:
        import qrcode
        image = qrcode.make(url)
        buf = BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()


class MobileUploadSessionPanel(QFrame):
    upload_finished = Signal()

    def __init__(self, controller: MobileUploadSessionController, parent=None):
        super().__init__(parent)
        self.setObjectName("MobileUploadSessionPanel")
        self.controller = controller
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        self.stack = QStackedWidget(self)
        root.addWidget(self.stack, 0, Qt.AlignTop)
        self.idle_page = self._build_idle()
        self.active_page = self._build_active()
        self.stack.addWidget(self.idle_page)
        self.stack.addWidget(self.active_page)
        controller.starting.connect(lambda: self.btn_start.setEnabled(False))
        controller.started.connect(self._show_active)
        controller.stats_changed.connect(self._set_stats)
        controller.upload_received.connect(lambda _stats: self.upload_finished.emit())
        controller.failed.connect(self._show_error)
        controller.stopped.connect(self.show_idle)

    def _build_idle(self):
        page = QWidget(self)
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
        title = QLabel("手机扫码上传"); title.setProperty("class", "SectionTitle")
        desc = QLabel("从手机上传发票原件、行程单或证明材料。\n手机和电脑需要连接同一局域网。")
        desc.setWordWrap(True); desc.setProperty("class", "SectionHint")
        self.lbl_idle_network = QLabel("网络：局域网 · 自动检测\n支持：PDF / OFD / XML / 图片\n上传后：自动进入审核队列")
        self.lbl_idle_network.setWordWrap(True)
        self.btn_start = make_button("启动手机上传", variant="primary")
        self.btn_start.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.btn_start.clicked.connect(self.controller.start)
        layout.addWidget(title); layout.addWidget(desc); layout.addWidget(self.lbl_idle_network)
        layout.addWidget(self.btn_start, 0, Qt.AlignLeft); layout.addStretch(1)
        return page

    def _build_active(self):
        page = QWidget(self)
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(10)
        header = QHBoxLayout(); title = QLabel("手机扫码上传"); title.setProperty("class", "SectionTitle")
        self.status_badge = make_badge("运行中", "success")
        header.addWidget(title); header.addWidget(self.status_badge); header.addStretch(1)
        body = QHBoxLayout(); body.setSpacing(16)
        self.lbl_qr = QLabel(); self.lbl_qr.setObjectName("MobileUploadQr")
        self.lbl_qr.setAlignment(Qt.AlignCenter); self.lbl_qr.setFixedSize(240, 240)
        details = QWidget(); form = QFormLayout(details); form.setContentsMargins(0, 0, 0, 0)
        self.txt_url = QLineEdit(); self.txt_url.setReadOnly(True)
        self.combo_upload_host = QComboBox(); self.combo_upload_host.currentIndexChanged.connect(self._host_changed)
        self.lbl_service_address = QLabel("—"); self.lbl_stats = QLabel("成功 0 · 重复 0 · 失败 0 · 入库 0")
        form.addRow("操作", QLabel("手机扫描二维码，在浏览器中选择文件上传。"))
        form.addRow("上传 URL", self.txt_url); form.addRow("网络接口", self.combo_upload_host)
        form.addRow("服务地址", self.lbl_service_address); form.addRow("本次上传", self.lbl_stats)
        body.addWidget(self.lbl_qr); body.addWidget(details, 1)
        footer = QHBoxLayout()
        self.btn_copy_url = make_button("复制链接", variant="secondary"); self.btn_copy_url.clicked.connect(self._copy_url)
        self.btn_change_network = make_button("更换网络", variant="ghost"); self.btn_change_network.clicked.connect(self.combo_upload_host.showPopup)
        self.btn_stop = make_button("停止服务", variant="secondary"); self.btn_stop.setProperty("danger", True); self.btn_stop.clicked.connect(self.controller.stop)
        footer.addWidget(self.btn_copy_url); footer.addWidget(self.btn_change_network); footer.addStretch(1); footer.addWidget(self.btn_stop)
        self.lbl_error = QLabel(); self.lbl_error.setWordWrap(True); self.lbl_error.hide()
        layout.addLayout(header); layout.addLayout(body); layout.addWidget(self.lbl_error); layout.addLayout(footer)
        return page

    def show_idle(self):
        self.btn_start.setEnabled(True)
        self.stack.setCurrentWidget(self.idle_page)

    def _show_active(self, session):
        self.combo_upload_host.blockSignals(True); self.combo_upload_host.clear()
        for option in self.controller.host_options:
            self.combo_upload_host.addItem(option.label, option.host)
        self.combo_upload_host.blockSignals(False)
        self.txt_url.setText(session.upload_url); self.lbl_service_address.setText(f"{session.host}:{session.port}")
        try:
            pixmap = QPixmap(); pixmap.loadFromData(self.controller.qr_png(session.upload_url), "PNG")
            self.lbl_qr.setPixmap(pixmap.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            self.lbl_qr.setText("二维码不可用\n请复制上传链接")
        self.lbl_error.hide(); self.stack.setCurrentWidget(self.active_page)

    def _set_stats(self, stats):
        self.lbl_stats.setText("成功 {accepted} · 重复 {duplicate} · 失败 {failed} · 入库 {imported}".format(
            accepted=stats.get("accepted", 0), duplicate=stats.get("duplicate", 0),
            failed=stats.get("failed", 0), imported=stats.get("imported", 0)))

    def _show_error(self, message):
        self.btn_start.setEnabled(True); self.lbl_error.setText(f"上传服务启动失败：{message}"); self.lbl_error.show()

    def _copy_url(self):
        QApplication.clipboard().setText(self.txt_url.text())

    def _host_changed(self):
        host = self.combo_upload_host.currentData()
        if host: self.controller.set_public_host(str(host))
